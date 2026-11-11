"""Dev-only (P02, reviewed labels) per-person binary precision/recall at several cigarette thresholds, per model.

  python prototype/sweep_dev_thresholds.py --models models/cig_roi.onnx models/cig_roi_v3exp.onnx models/cig_roi_v3.onnx
Runs each model once at the lowest threshold, stores the per-person best cigarette box conf, then sweeps (raw per-frame
state, same unit as eval_images.py; no temporal stabilisation). Refuses hold-out/protected paths. Output:
_workspace/eval_out/sweep_dev_thresholds.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import list_images, refuse_holdout  # noqa: E402
from eval_images import iou, dist_bin  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.distance import proxy_position  # noqa: E402
from ash_e_core.pipeline import PerceptionPipeline  # noqa: E402
from ash_e_core.types import CameraIntrinsics  # noqa: E402

THR = [0.25, 0.35, 0.45, 0.55, 0.65]


def collect(model, img_dir, pose_m):
    cfg = PerceptionConfig(cig_conf_thresh=min(THR))
    cig_m = load_model(model, "onnxruntime", cfg.num_threads)
    rows = []
    for ip in list_images(img_dir):
        jp = ip.with_suffix(".json")
        if not jp.is_file():
            continue
        img = cv2.imread(str(ip))
        gts = json.loads(jp.read_text(encoding="utf-8"))
        pipe = PerceptionPipeline(cfg, pose_model=pose_m, cig_model=cig_m)
        pipe.process(img, 0.0)
        H, W = img.shape[:2]
        intr = CameraIntrinsics.from_hfov(W, H, cfg.hfov_deg)
        pers, used = pipe.last.persons, set()
        for g in gts:
            if not g.get("reviewed", True):
                continue
            best, bi = 0.0, -1
            for i, pd in enumerate(pers):
                v = iou(g["bbox_xyxy"], pd.pose.bbox_xyxy) if i not in used else 0
                if v > best:
                    best, bi = v, i
            conf, dist = 0.0, None
            if bi >= 0 and best >= 0.3:
                used.add(bi)
                pd = pers[bi]
                if pd.checked and pd.raw.box is not None and pd.raw.state != 0:
                    conf = float(pd.raw.box.conf)
                dist = proxy_position(pd.pose, intr, cfg, H)[1]
            rows.append(dict(pos=g["label"] in ("smoking", "holding", "positive"), cat=g.get("category", "plain"),
                             conf=conf, bin=dist_bin(dist) if dist is not None else None))
    return rows


def metrics(rows, t, sel=lambda r: True):
    tp = sum(1 for r in rows if sel(r) and r["pos"] and r["conf"] >= t)
    fn = sum(1 for r in rows if sel(r) and r["pos"] and r["conf"] < t)
    fp = sum(1 for r in rows if sel(r) and not r["pos"] and r["conf"] >= t)
    return dict(P=tp / max(1, tp + fp), R=tp / max(1, tp + fn), tp=tp, fp=fp, fn=fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--images", default=str(ROOT / "data/eval/dev/images"))
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    a = ap.parse_args()
    d = Path(a.images)
    refuse_holdout(d)
    if "holdout" in d.as_posix().lower():
        sys.exit("REFUSED: hold-out")
    pose_m = load_model(a.pose, "onnxruntime", 4)
    out = {}
    for m in a.models:
        rows = collect(m, d, pose_m)
        out[Path(m).stem] = {"n": len(rows), "by_thr": {str(t): dict(
            all=metrics(rows, t),
            fp_by_cat={c: sum(1 for r in rows if not r["pos"] and r["cat"] == c and r["conf"] >= t)
                       for c in sorted({r["cat"] for r in rows if not r["pos"]})}) for t in THR}}
        print(Path(m).stem, "n=%d" % len(rows))
        for t in THR:
            x = out[Path(m).stem]["by_thr"][str(t)]
            print("  thr %.2f P %.3f R %.3f fp %s" % (t, x["all"]["P"], x["all"]["R"], x["fp_by_cat"]))
    (ROOT / "_workspace/eval_out/sweep_dev_thresholds.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
