"""Scene-level frame detection rates for comparing cigarette models on a DEV participant's captured frames.

  python prototype/frame_rates.py --pid P02 --models models/cig_roi.onnx,models/cig_roi_v3exp.onnx [--conf 0.35]

For every frame of data/raw/<PID>: subject (own_subject) -> mouth/hand ROIs -> cigarette model at --conf.
Reports, per scenario x distance tag, the share of frames with >= 1 box:
  holding / mouth  = "scene detection rate" (NOT recall: the cigarette is not visible in every frame)
  none / similar / gesture / ecig_* = frame false-positive rate
No stabiliser, no smoking/holding split: a quick model comparison only, not an acceptance metric (spec 9.4 uses clips).
Hold-out participants are refused (refuse_holdout). Writes _workspace/eval_out/frame_rates_<PID>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import own_subject, refuse_holdout  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import CigaretteRoiModel, PoseModel  # noqa: E402
from ash_e_core.roi import compute_rois  # noqa: E402

SCEN = ("holding", "mouth", "none", "similar", "gesture", "ecig_liquid", "ecig_heated")
DIST = ("1m", "2m", "3m", "4m", "5m", "unk")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", required=True)
    ap.add_argument("--models", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--conf", type=float, default=0.35)
    a = ap.parse_args()
    raw = ROOT / "data/raw" / a.pid
    refuse_holdout(raw)
    cfg = PerceptionConfig(person_conf_thresh=0.30)
    pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", 4), cfg)
    models = {Path(m).stem: CigaretteRoiModel(load_model(m, "onnxruntime", 4), cfg) for m in a.models.split(",")}
    if pose.is_stub or any(m.is_stub for m in models.values()):
        sys.exit("model missing")
    meta = {}
    for mf in raw.rglob("meta.jsonl"):
        for ln in mf.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                m = json.loads(ln)
                meta[Path(m["file"]).name] = m.get("distance_tag") or "unk"
    cnt = {k: defaultdict(lambda: [0, 0]) for k in models}
    for f in sorted(raw.rglob("*.jpg")):
        img = cv2.imread(str(f))
        if img is None:
            continue
        H, W = img.shape[:2]
        subj = own_subject(pose.detect(img), W)
        rois = [r.xyxy for p in subj for r in compute_rois(p, cfg, W, H)]
        key = (f.parent.name, meta.get(f.name, "unk"))
        for name, mdl in models.items():
            hit = any(bool(lst) for lst in mdl.detect_crops(img, rois, a.conf)) if rois else False
            cnt[name][key][0] += 1
            cnt[name][key][1] += int(hit)
    rep = {}
    for name in models:
        print("\n== %s  (conf %.2f, %s)" % (name, a.conf, a.pid))
        print("%-9s %-14s" % ("scenario", "all") + "".join("%-10s" % d for d in DIST))
        rep[name] = {}
        for sc in SCEN:
            cells = {d: cnt[name][(sc, d)] for d in DIST if cnt[name][(sc, d)][0]}
            if not cells:
                continue
            n, h = sum(v[0] for v in cells.values()), sum(v[1] for v in cells.values())
            rep[name][sc] = {"n": n, "hit": h, "rate": h / n, "by_dist": {d: v for d, v in cells.items()}}
            print("%-9s %-14s" % (sc, "%.2f (%d/%d)" % (h / n, h, n)) +
                  "".join("%-10s" % ("%d/%d" % (cells[d][1], cells[d][0]) if d in cells else "-") for d in DIST))
    out = ROOT / "_workspace/eval_out" / ("frame_rates_%s.json" % a.pid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"pid": a.pid, "conf": a.conf, "models": rep}, indent=1), encoding="utf-8")
    print("\nsaved", out)


if __name__ == "__main__":
    main()
