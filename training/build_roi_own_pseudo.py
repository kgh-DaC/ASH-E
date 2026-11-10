"""EXPERIMENT (user decision 2026-11-11): own-capture ROIs with UNREVIEWED pseudo labels from the pass-1 model.

Spec 9A.5 wants human-reviewed labels; this dataset is only for an experimental model, clearly named *_pseudo / *exp.

  python training/build_roi_own_pseudo.py --pid P01 --out data/roi_own_p01_pseudo --clean
  -> writes data/roi_ds_v3exp.yaml = roi_ds_v2 train/val + this dataset's train/val

Rules (to avoid teaching "missed cigarette = no cigarette"):
 * holding / mouth frames: boxes = pass-1 model on the subject's ROIs at conf >= --pos-conf (default 0.5).
   Only ROIs that CONTAIN such a box are kept (positives). ROIs without a box and frames without any box are dropped.
 * none / similar / gesture (and ecig_*) frames: every subject ROI is a negative (cigarette not in the scene).
 * subject only (own_subject): third-party ROIs and whole-frame samples are never used.
 * split: per scenario, consecutive blocks of --block frames (time order); every 5th block -> val (no jitter).
Never reads data/eval or holdout participants (refuse_holdout on every path).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_roi_dataset import process_image, save_sample  # noqa: E402
from dataset_utils import ROOT, own_subject, refuse_holdout  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import CigaretteRoiModel, PoseModel, global_nms  # noqa: E402
from ash_e_core.roi import compute_rois  # noqa: E402

POSITIVE = {"holding", "mouth"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="P01")
    ap.add_argument("--out", default=str(ROOT / "data/roi_own_p01_pseudo"))
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--pos-conf", type=float, default=0.5)
    ap.add_argument("--jitter", type=int, default=2)
    ap.add_argument("--block", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--yaml", default=str(ROOT / "data/roi_ds_v3exp.yaml"))
    a = ap.parse_args()

    out = Path(a.out).resolve()
    if out.name in ("roi_ds", "roi_ds_v2"):
        sys.exit("REFUSED: preserved dataset")
    if a.clean and out.exists():
        shutil.rmtree(out)
    for s in ("train", "val"):
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)

    cfg = PerceptionConfig(person_conf_thresh=0.25, min_person_h_px=40)  # same ROI rule as roi_ds_v2
    pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", 4), cfg)
    cig = CigaretteRoiModel(load_model(a.model, "onnxruntime", 4), cfg)
    if pose.is_stub or cig.is_stub:
        sys.exit("pose or cigarette model missing")
    rng = np.random.default_rng(a.seed)
    stats = {s: Counter() for s in ("train", "val")}

    raw = ROOT / "data/raw" / a.pid
    for sc_dir in sorted(p for s in raw.iterdir() if s.is_dir() for p in s.iterdir() if p.is_dir()):
        sc = sc_dir.name
        files = sorted(sc_dir.glob("*.jpg"))
        for k, f in enumerate(files):
            refuse_holdout(f)
            split = "val" if (k // a.block) % 5 == 4 else "train"
            st = stats[split]
            img = cv2.imread(str(f))
            if img is None:
                continue
            H, W = img.shape[:2]
            subj = own_subject(pose.detect(img), W)
            if not subj:
                st["frame_no_subject"] += 1
                continue
            boxes = []
            if sc in POSITIVE:
                for lst in cig.detect_crops(img, [r.xyxy for r in compute_rois(subj[0], cfg, W, H)], a.pos_conf):
                    boxes.extend(lst)
                boxes = [b.xyxy for b in global_nms(boxes, 0.5)]
                if not boxes:
                    st["pos_frame_no_box_dropped"] += 1
                    continue
            samples = process_image(img, boxes, pose, cfg, rng, a.jitter, False, split == "train", primary_only=True)
            for suf, crop, kb, status in samples:
                if sc in POSITIVE and status != "pos":
                    st["pos_scene_boxless_roi_dropped"] += 1
                    continue
                save_sample(out, split, "own_%s_%s" % (f.stem, suf), crop, kb)
                st["%s_%s" % (status, "scene_pos" if sc in POSITIVE else "scene_neg")] += 1
                st[status] += 1
            st["frames_used"] += 1
        print(sc, {s: dict(stats[s]) for s in stats}, flush=True)

    v2 = ROOT / "data/roi_ds_v2"
    Path(a.yaml).write_text(
        "# EXPERIMENT: roi_ds_v2 + %s pseudo-labelled own ROIs (unreviewed)\n"
        "train:\n  - %s\n  - %s\nval:\n  - %s\n  - %s\nnames:\n  0: cigarette\n" % (
            a.pid, (v2 / "images/train").as_posix(), (out / "images/train").as_posix(),
            (v2 / "images/val").as_posix(), (out / "images/val").as_posix()), encoding="utf-8")
    rep = {"pid": a.pid, "pos_conf": a.pos_conf, "reviewed": False, "stats": {s: dict(stats[s]) for s in stats}}
    (out / "build_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
