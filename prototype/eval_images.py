"""Accuracy evaluation on labeled images / clips (spec 9.3). CPU only, ONNX Runtime.

  python prototype/eval_images.py                       # dev images: data/eval/dev/images (+ .json per image)
  python prototype/eval_images.py --images DIR          # any non-protected folder of images + same-name .json
  python prototype/eval_images.py --clips               # dev clips: data/eval/dev/clips/*.mp4 + labels/<id>.json
  python prototype/eval_images.py --final               # HOLD-OUT (images + clips). Verifies the SHA-256 manifest first.
  python prototype/eval_images.py --make-demo-cigdet 40 # build a functional-test set from public CigDet (NOT an accuracy test)

Image label file (same name as the image, .json):  [{"bbox_xyxy":[x1,y1,x2,y2], "label":"smoking|holding|none|positive",
  "category":"cigarette|similar_object|gesture|ecig_liquid|ecig_heated|plain", "occluded":false}]
  "positive" = smoking or holding, not distinguished (used by the public-data demo). Detected persons that match no label
  entry are NOT put in the confusion matrix; they are listed as "unlabeled detections" (a positive one is a possible FP).
Clip label file (spec 9.2): data/eval/<split>/labels/<clip_id>.json with persons[].segments[] and persons[].anchor.

Protection (spec 9A.5): never writes to acceptance/ or data/eval/holdout/. Hold-out paths are refused unless --final;
--final verifies acceptance/holdout_manifest.sha256 and appends a line to acceptance/holdout_runs.log (the only
permitted write there). acceptance.yaml's own hash (acceptance/acceptance.sha256) is checked in every mode.
Error crops saved to _workspace/eval_out are ROI crops only (no whole-body images).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
from dataset_utils import is_under, list_images  # noqa: E402
import lock_acceptance  # noqa: E402

import yaml  # noqa: E402
from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.distance import proxy_position  # noqa: E402
from ash_e_core.pipeline import PerceptionPipeline  # noqa: E402
from ash_e_core.types import CameraIntrinsics  # noqa: E402

HOLDOUT = ROOT / "data/eval/holdout"
ACCEPT = ROOT / "acceptance"
OUT = ROOT / "_workspace/eval_out"
LABELS = ["none", "holding", "smoking"]
L2I = {"none": 0, "holding": 1, "smoking": 2}
NAMES = {0: "none", 1: "holding", 2: "smoking"}


# ------------------------------------------------------------------ protection
def guard(final: bool):
    """Hash checks. Returns the thresholds dict."""
    ah = ACCEPT / "acceptance.sha256"
    if ah.is_file():
        h, r = ah.read_text().strip().split("  ", 1)
        if not (ROOT / r).is_file() or lock_acceptance.sha(ROOT / r) != h:
            sys.exit("REFUSED: acceptance/acceptance.yaml does not match acceptance/acceptance.sha256 (modified?). No result produced.")
        print("acceptance.yaml hash: OK")
    else:
        print("WARNING: acceptance/acceptance.sha256 missing (run: python training/lock_acceptance.py --lock-thresholds)")
    if final:
        if not lock_acceptance.verify():
            sys.exit("REFUSED: hold-out manifest missing or mismatching. No result produced.")
    return yaml.safe_load((ACCEPT / "acceptance.yaml").read_text(encoding="utf-8"))


def refuse_protected(path: Path, final: bool):
    if not final and is_under(path, HOLDOUT):
        sys.exit("REFUSED: %s is hold-out data. Use --final (hash-verified, logged)." % path)
    if is_under(path, ACCEPT):
        sys.exit("REFUSED: acceptance/ is protected.")


# ------------------------------------------------------------------ helpers
def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    return p, r, f


def fmt(v, pct=False):
    return "n/a" if v is None else ("%.3f" % v)


def dist_bin(d):
    return "<=2m" if d <= 2 else ("2-3m" if d <= 3 else ("3-4m" if d <= 4 else ("4-5m" if d <= 5 else ">5m")))


def make_pipeline(args, cfg):
    pose = load_model(args.pose, "onnxruntime", cfg.num_threads)
    cig = load_model(args.cig_model, "onnxruntime", cfg.num_threads)
    missing = [n for n, m in (("pose", pose), ("cigarette", cig)) if getattr(m, "is_stub", False)]
    return pose, cig, missing


def crop_roi(img, box, scale=1.0, min_side=48):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    s = max(max(x2 - x1, y2 - y1) * scale, min_side)
    a, b = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
    c, d = int(min(W, cx + s / 2)), int(min(H, cy + s / 2))
    return img[b:d, a:c]


# ------------------------------------------------------------------ image mode
def eval_images(args, img_dir: Path, cfg, pose_m, cig_m):
    imgs = list_images(img_dir)
    if not imgs:
        return None
    conf = np.zeros((3, 3), int)           # rows=GT, cols=pred (smoking/holding/none labels only)
    pos_gt = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    per_bin = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0, "tn": 0})
    per_cat_fp = defaultdict(int)
    sh_ok = sh_n = 0
    unl_pos = unl_total = n_unmatched_gt = 0
    fps_list, fns_list, times = [], [], []
    n_labeled = 0
    for ip in imgs:
        jp = ip.with_suffix(".json")
        if not jp.is_file():
            continue
        gts = json.loads(jp.read_text(encoding="utf-8"))
        img = cv2.imread(str(ip))
        if img is None:
            continue
        pipe = PerceptionPipeline(cfg, pose_model=pose_m, cig_model=cig_m)   # fresh tracker per image
        t0 = time.perf_counter()
        pipe.process(img, 0.0)
        times.append((time.perf_counter() - t0) * 1000)
        H, W = img.shape[:2]
        intr = CameraIntrinsics.from_hfov(W, H, cfg.hfov_deg)
        pers = pipe.last.persons
        used = set()
        n_labeled += 1
        for g in gts:
            best, bi = 0.0, -1
            for i, pd in enumerate(pers):
                if i in used:
                    continue
                v = iou(g["bbox_xyxy"], pd.pose.bbox_xyxy)
                if v > best:
                    best, bi = v, i
            gl = g["label"]
            gpos = gl in ("smoking", "holding", "positive")
            if bi < 0 or best < 0.3:
                n_unmatched_gt += 1
                pred, dist, pd = 0, None, None        # person not found -> counts as predicted none
            else:
                used.add(bi)
                pd = pers[bi]
                pred = int(pd.raw.state) if pd.checked else 0
                dist = proxy_position(pd.pose, intr, cfg, H)[1]
            ppos = pred != 0
            key = ("tp" if ppos else "fn") if gpos else ("fp" if ppos else "tn")
            pos_gt[key] += 1
            if dist is not None:
                per_bin[dist_bin(dist)][key] += 1
            if gl in L2I:
                conf[L2I[gl], pred] += 1
            if gl in ("smoking", "holding") and ppos:
                sh_n += 1
                sh_ok += int(pred == L2I[gl])
            if key == "fp":
                per_cat_fp[g.get("category", "plain")] += 1
                conf_v = pd.raw.box.conf if (pd and pd.raw.box is not None) else 0.0
                fps_list.append((conf_v, ip, pd, img, g.get("category", "plain")))
            if key == "fn":
                fns_list.append((0.0, ip, pd, img, g.get("category", "cigarette")))
        for i, pd in enumerate(pers):
            if i not in used:
                unl_total += 1
                unl_pos += int(pd.checked and pd.raw.state != 0)
    if n_labeled == 0:
        return None
    return dict(conf=conf, pos=pos_gt, per_bin=dict(per_bin), per_cat_fp=dict(per_cat_fp), sh_ok=sh_ok, sh_n=sh_n,
                unl_pos=unl_pos, unl_total=unl_total, unmatched_gt=n_unmatched_gt, fps=fps_list, fns=fns_list,
                ms=times, n=n_labeled)


def save_cases(res, tag):
    d = OUT / tag
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.jpg"):
        old.unlink()
    for name, lst in (("FP", sorted(res["fps"], key=lambda t: -t[0])[:20]), ("FN", res["fns"][:20])):
        for k, (c, ip, pd, img, cat) in enumerate(lst):
            if pd is None:
                continue
            if pd.raw.box is not None:
                crop = crop_roi(img, pd.raw.box.xyxy, 3.0)
            elif pd.rois:
                xs = [r.xyxy for r in pd.rois]
                crop = crop_roi(img, (min(x[0] for x in xs), min(x[1] for x in xs), max(x[2] for x in xs), max(x[3] for x in xs)))
            else:
                x1, y1, x2, y2 = pd.pose.bbox_xyxy
                crop = crop_roi(img, (x1, y1, x2, y1 + 0.25 * (y2 - y1)))     # head area only
            if crop.size:
                cv2.imwrite(str(d / ("%s_%02d_%s_%.2f_%s.jpg" % (name, k, cat, c, ip.stem))), crop)


def report_images(res, th, mode):
    L = []
    L.append("## Frame-level (raw_state) -- %d labeled images, %s" % (res["n"], mode))
    c = res["conf"]
    L.append("Confusion (rows=GT, cols=pred; only smoking/holding/none labels):")
    L.append("| GT \\ pred | none | holding | smoking |")
    L.append("| --- | --- | --- | --- |")
    for g in range(3):
        L.append("| %s | %d | %d | %d |" % (NAMES[g], c[g, 0], c[g, 1], c[g, 2]))
    L.append("")
    L.append("| class | precision | recall | F1 |")
    L.append("| --- | --- | --- | --- |")
    for k in range(3):
        tp = c[k, k]
        p, r, f = prf(tp, c[:, k].sum() - tp, c[k, :].sum() - tp)
        L.append("| %s | %s | %s | %s |" % (NAMES[k], fmt(p), fmt(r), fmt(f)))
    p = res["pos"]
    bp, br, bf = prf(p["tp"], p["fp"], p["fn"])
    L.append("")
    L.append("Binary (smoking|holding|positive vs none): TP=%d FP=%d FN=%d TN=%d  precision=%s recall=%s F1=%s" % (
        p["tp"], p["fp"], p["fn"], p["tn"], fmt(bp), fmt(br), fmt(bf)))
    if p["fp"] + p["tn"] == 0:
        L.append("NOTE: no negative (none) persons in this set -> precision is meaningless (always 1.0 or n/a).")
    L.append("smoking/holding discrimination among true positives: %s (%d/%d)" % (
        fmt(res["sh_ok"] / res["sh_n"]) if res["sh_n"] else "n/a", res["sh_ok"], res["sh_n"]))
    L.append("GT persons with no matching detected person (counted as predicted none): %d" % res["unmatched_gt"])
    L.append("Unlabeled detections: %d, of which predicted positive (possible FP): %d" % (res["unl_total"], res["unl_pos"]))
    if res["per_cat_fp"]:
        L.append("FP by category: %s" % res["per_cat_fp"])
    L.append("")
    L.append("Recall / precision by PROXY distance bin (approximate distances):")
    L.append("| bin | TP | FN | FP | TN | recall | precision |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for b in ("<=2m", "2-3m", "3-4m", "4-5m", ">5m"):
        if b in res["per_bin"]:
            q = res["per_bin"][b]
            pp, rr, _ = prf(q["tp"], q["fp"], q["fn"])
            L.append("| %s | %d | %d | %d | %d | %s | %s |" % (b, q["tp"], q["fn"], q["fp"], q["tn"], fmt(rr), fmt(pp)))
    ms = np.array(res["ms"])
    L.append("")
    L.append("Inference (this PC, CPU): median %.0f ms, p95 %.0f ms per image (1 frame, includes ROI inference)" % (
        np.median(ms), np.percentile(ms, 95)))
    # acceptance comparison (frame-level approximation of the state-based thresholds)
    L.append("")
    L.append("Threshold comparison (%s; the official criteria are on STABILIZED state over hold-out clips, so this is only a guide):" % mode)
    pb = res["per_bin"]

    def agg(bins, k):
        return sum(pb.get(b, {}).get(k, 0) for b in bins)

    near = ("<=2m", "2-3m")
    mid = ("3-4m",)
    rows = [
        ("binary precision <=4m", th.get("binary_precision_max4m"), prf(agg(near + mid, "tp"), agg(near + mid, "fp"), 0)[0]),
        ("binary recall <=3m", th.get("binary_recall_max3m"), prf(agg(near, "tp"), 0, agg(near, "fn"))[1]),
        ("binary recall 3-5m", th.get("binary_recall_3to5m"), prf(agg(("3-4m", "4-5m"), "tp"), 0, agg(("3-4m", "4-5m"), "fn"))[1]),
        ("smoking/holding accuracy", th.get("smoking_holding_accuracy"), (res["sh_ok"] / res["sh_n"]) if res["sh_n"] else None),
    ]
    L.append("| criterion | required | measured | |")
    L.append("| --- | --- | --- | --- |")
    for n, req, m in rows:
        ok = "n/a" if m is None or req is None else ("meets" if m >= req else "below")
        L.append("| %s | >= %s | %s | %s |" % (n, req, fmt(m), ok))
    return "\n".join(L)


# ------------------------------------------------------------------ clip mode
def eval_clips(args, split_dir: Path, cfg, pose_m, cig_m):
    clips = sorted((split_dir / "clips").glob("*.mp4"))
    if not clips:
        return None
    conf_times, results, false_conf, neg_min = [], [], 0, 0.0
    pos_time = pos_conf_time = 0.0
    lines = []
    for cp in clips:
        lp = split_dir / "labels" / (cp.stem + ".json")
        if not lp.is_file():
            lines.append("- %s: label file missing, skipped" % cp.name)
            continue
        lab = json.loads(lp.read_text(encoding="utf-8"))
        cap = cv2.VideoCapture(str(cp))
        fps = cap.get(cv2.CAP_PROP_FPS) or lab.get("fps", 30.0)
        pipe = PerceptionPipeline(cfg, pose_model=pose_m, cig_model=cig_m)
        step = max(1, int(round(fps / cfg.process_rate_hz)))
        track = {}  # person_ref -> last bbox
        series = defaultdict(list)  # person_ref -> [(t, state)]
        k = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if k % step == 0:
                t = k / fps
                arr = pipe.process(fr, t)
                for p in lab["persons"]:
                    ref = p["person_ref"]
                    if t < p["anchor"]["t"] - 1e-6:
                        continue
                    ref_box = track.get(ref, p["anchor"]["bbox_xyxy"])
                    cand = [(iou(ref_box, [d.bbox_x, d.bbox_y, d.bbox_x + d.bbox_w, d.bbox_y + d.bbox_h]), d)
                            for d in arr.detections]
                    cand = [c for c in cand if c[0] >= 0.2]
                    if cand:
                        v, d = max(cand, key=lambda c: c[0])
                        track[ref] = [d.bbox_x, d.bbox_y, d.bbox_x + d.bbox_w, d.bbox_y + d.bbox_h]
                        series[ref].append((t, d.state))
                    else:
                        series[ref].append((t, 0))
            k += 1
        cap.release()
        dur = k / fps
        for p in lab["persons"]:
            ser = series[p["person_ref"]]
            for sg in p["segments"]:
                inside = [(t, s) for t, s in ser if sg["t0"] <= t < sg["t1"]]
                if not inside:
                    continue
                pos = sg["label"] in ("smoking", "holding")
                if pos:
                    first = next((t for t, s in inside if s != 0), None)
                    if first is not None:
                        conf_times.append(first - sg["t0"])
                    frac = sum(1 for _, s in inside if s != 0) / len(inside)
                    pos_time += sg["t1"] - sg["t0"]
                    pos_conf_time += frac * (sg["t1"] - sg["t0"])
                    lines.append("- %s %s %s [%.1f-%.1f s]: confirmed=%s, confirm_time=%s" % (
                        cp.name, p["person_ref"], sg["label"], sg["t0"], sg["t1"], first is not None,
                        "%.2f s" % (first - sg["t0"]) if first is not None else "never"))
                else:
                    # count rising edges none->positive as false confirmations
                    edges, prev = 0, 0
                    for _, s in inside:
                        edges += int(prev == 0 and s != 0)
                        prev = s
                    false_conf += edges
                    neg_min += (sg["t1"] - sg["t0"]) / 60.0
                    lines.append("- %s %s none(%s) [%.1f-%.1f s]: false confirmations=%d" % (
                        cp.name, p["person_ref"], sg.get("category", "plain"), sg["t0"], sg["t1"], edges))
    L = ["## Clip-level (stabilized state) -- %d clips" % len(clips)] + lines
    L.append("")
    if conf_times:
        L.append("Confirm time: median %.2f s, p95 %.2f s (n=%d)" % (np.median(conf_times), np.percentile(conf_times, 95), len(conf_times)))
    if pos_time:
        L.append("Positive time confirmed: %.1f%%" % (100 * pos_conf_time / pos_time))
    if neg_min:
        L.append("False confirmations on none segments: %d in %.1f min = %.2f per 10 min" % (false_conf, neg_min, 10 * false_conf / neg_min))
    return "\n".join(L)


# ------------------------------------------------------------------ demo set from public data
def make_demo(n, args, cfg, pose_m, cig_m):
    src = ROOT / "data/public/cigdet/raw/CigDet_dataset/test"
    dst = ROOT / "data/eval/demo_cigdet/images"
    dst.mkdir(parents=True, exist_ok=True)
    pipe = PerceptionPipeline(cfg, pose_model=pose_m, cig_model=cig_m)
    k = 0
    for ip in sorted(src.glob("*.jpg")):
        if k >= n:
            break
        img = cv2.imread(str(ip))
        H, W = img.shape[:2]
        pipe.tracker.tracks.clear() if hasattr(pipe.tracker, "tracks") else None
        persons = pipe.pose.detect(img)
        if not persons:
            continue
        p = persons[0]
        lines = ip.with_suffix(".txt").read_text().split()
        cx, cy = float(lines[1]) * W, float(lines[2]) * H
        x1, y1, x2, y2 = p.bbox_xyxy
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        cv2.imwrite(str(dst / ip.name), img)
        (dst / ip.with_suffix(".json").name).write_text(json.dumps(
            [{"bbox_xyxy": [float(v) for v in p.bbox_xyxy], "label": "positive", "category": "cigarette"}]))
        k += 1
    print("demo set: %d images -> %s  (labels = 'positive' because CigDet only tells there is a cigarette; "
          "person boxes come from the pose model; this checks that the tool runs, it is NOT an accuracy test)" % (k, dst.parent))


def write_metrics_json(res, tag, final):
    """Machine-readable copy of the frame-level result (read by prototype/paper_report.py). Additive: the report text
    is unchanged. Written under _workspace/eval_out only."""
    ms = np.array(res["ms"], float)
    d = dict(schema="eval_images_metrics/1", final=bool(final), tag=tag, n=int(res["n"]), labels=LABELS,
             confusion=np.asarray(res["conf"]).astype(int).tolist(), binary={k: int(v) for k, v in res["pos"].items()},
             per_bin={b: {k: int(v) for k, v in q.items()} for b, q in res["per_bin"].items()},
             per_cat_fp={k: int(v) for k, v in res["per_cat_fp"].items()}, sh_ok=int(res["sh_ok"]), sh_n=int(res["sh_n"]),
             unmatched_gt=int(res["unmatched_gt"]), unl_pos=int(res["unl_pos"]), unl_total=int(res["unl_total"]),
             infer_ms=dict(median=float(np.median(ms)) if len(ms) else None, p95=float(np.percentile(ms, 95)) if len(ms) else None),
             when=datetime.now().isoformat(timespec="seconds"))
    (OUT / ("metrics_%s.json" % tag)).write_text(json.dumps(d, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ main
def main():
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", default=None, help="folder of images + same-name .json (default data/eval/dev/images)")
    ap.add_argument("--clips", action="store_true", help="also/only evaluate clips under data/eval/<split>/clips")
    ap.add_argument("--final", action="store_true", help="hold-out evaluation (hash-verified, logged)")
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--cig-model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--config", default=None, help="perception yaml (thresholds, radii, ...)")
    ap.add_argument("--make-demo-cigdet", type=int, default=0, metavar="N")
    ap.add_argument("--clips-dir", default=None, help="folder with clips/ and labels/ (default data/eval/dev)")
    ap.add_argument("--tag", default=None, help="output sub folder name under _workspace/eval_out")
    a = ap.parse_args()

    from ash_e_core.config import load_perception_config
    cfg = load_perception_config(a.config)
    th = guard(a.final)
    pose_m, cig_m, missing = make_pipeline(a, cfg)
    if "pose" in missing:
        sys.exit("pose model missing: %s (see data/SOURCES.md / training/README)" % a.pose)
    if a.make_demo_cigdet:
        return make_demo(a.make_demo_cigdet, a, cfg, pose_m, cig_m)
    if "cigarette" in missing:
        print("WARNING: cigarette model missing (%s) -> every person is predicted 'none'. Train/export one first, or pass --cig-model." % a.cig_model)

    split = "holdout" if a.final else "dev"
    img_dir = Path(a.images) if a.images else (HOLDOUT if a.final else ROOT / "data/eval/dev") / "images"
    refuse_protected(img_dir, a.final)
    sec = []
    ran = False
    img_res = None
    if not a.clips or a.images:
        if list_images(img_dir):
            res = eval_images(a, img_dir, cfg, pose_m, cig_m)
            if res:
                ran = True
                img_res = res
                mode = "FINAL (hold-out)" if a.final else "DEV (not a judgment)"
                sec.append(report_images(res, th, mode))
                save_cases(res, a.tag or split)
        elif not a.clips:
            print("평가 데이터 없음, 촬영 필요: %s 에 이미지와 같은 이름의 .json 라벨이 없습니다." % img_dir)
            print("  1) prototype/capture.py 로 촬영  2) 라벨(.json) 작성  3) 이 스크립트를 다시 실행 (README: _workspace/02a_perception_notes.md '사용자 작업')")
    if a.clips:
        sd = HOLDOUT if a.final else (Path(a.clips_dir) if a.clips_dir else ROOT / "data/eval/dev")
        refuse_protected(sd, a.final)
        r = eval_clips(a, sd, cfg, pose_m, cig_m)
        if r:
            ran = True
            sec.append(r)
        else:
            print("평가 데이터 없음, 촬영 필요: %s/clips/*.mp4 와 labels/<id>.json 이 없습니다." % sd)
    if ran:
        head = "# eval_images report %s  (%s)\nmodels: pose=%s cig=%s%s\n" % (
            datetime.now().isoformat(timespec="seconds"), "FINAL" if a.final else "DEV", Path(a.pose).name,
            Path(a.cig_model).name, "  [cig STUB]" if "cigarette" in missing else "")
        text = head + "\n\n".join(sec)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / ("report_%s.md" % (a.tag or split))).write_text(text, encoding="utf-8")
        if img_res is not None:
            write_metrics_json(img_res, a.tag or split, a.final)
        print(text)
        print("\nreport + FP/FN ROI crops -> %s" % OUT)
        if a.final:
            nrun = 1
            lg = ACCEPT / "holdout_runs.log"
            if lg.is_file():
                nrun += len([x for x in lg.read_text().splitlines() if x.strip()])
            with open(lg, "a", encoding="utf-8") as f:
                f.write("%s run#%d cig=%s\n" % (datetime.now().isoformat(timespec="seconds"), nrun, Path(a.cig_model).name))
            print("hold-out run #%d logged to %s (report this count with the result)" % (nrun, lg))


if __name__ == "__main__":
    main()
