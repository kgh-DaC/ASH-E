"""Own-capture ROIs from HUMAN-REVIEWED labels (spec 9A.5) -> data/roi_own_p01_reviewed + data/roi_ds_v3.yaml.

  python training/build_roi_own_reviewed.py --pid P01 --clean
  -> writes data/roi_ds_v3.yaml = roi_ds_v2 train/val + this dataset's train/val

Frame selection (select_frames, unit-tested):
 * holding / mouth: only frames whose review_state is "ok" AND that have a label box. Unreviewed, "ignore", boxless: dropped.
 * none / similar / gesture / ecig_*: every frame not in ignore.txt (no cigarette in the scene) -> negative ROIs.
 * subject only (own_subject); third-party frames/ROIs are never used. Never reads data/eval or holdout (refuse_holdout).
 * split: per scenario, consecutive blocks of --block frames; every 5th block -> val (no jitter).
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
from dataset_utils import ROOT, bystanders_consented, own_subject, read_yolo, refuse_holdout  # noqa: E402

POSITIVE = {"holding", "mouth"}


def select_frames(frames, review_state, ignored, has_box):
    """frames: [(rel_key 'P01/S1/holding/x.jpg', abs_posix_path, scene)]. Returns ([(key, path, scene)], Counter of drops).
    has_box(path)->bool tells whether the label file has a cigarette box."""
    keep, drop = [], Counter()
    for key, path, scene in frames:
        if path in ignored:
            drop["ignored"] += 1
        elif scene in POSITIVE:
            st = review_state.get(key)
            if st != "ok":
                drop["unreviewed" if st is None else "state_" + st] += 1
            elif not has_box(path):
                drop["ok_but_boxless"] += 1
            else:
                keep.append((key, path, scene))
        else:
            keep.append((key, path, scene))
    return keep, drop


def main():
    from ash_e_core.backends import load_model
    from ash_e_core.config import PerceptionConfig
    from ash_e_core.detector import PoseModel

    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="P01")
    ap.add_argument("--out", default=str(ROOT / "data/roi_own_p01_reviewed"))
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--jitter", type=int, default=2)
    ap.add_argument("--block", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--yaml", default=str(ROOT / "data/roi_ds_v3.yaml"))
    a = ap.parse_args()

    out = Path(a.out).resolve()
    if out.name in ("roi_ds", "roi_ds_v2"):
        sys.exit("REFUSED: preserved dataset")
    if a.clean and out.exists():
        shutil.rmtree(out)
    for s in ("train", "val"):
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)

    lab = ROOT / "data/labeled"
    state = json.loads((lab / ("review_state_%s.json" % a.pid)).read_text(encoding="utf-8"))
    ign_f = lab / "ignore.txt"
    ignored = {Path(x.strip()).as_posix() for x in ign_f.read_text().splitlines() if x.strip()} if ign_f.is_file() else set()

    cfg = PerceptionConfig(person_conf_thresh=0.25, min_person_h_px=40)
    pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", 4), cfg)
    if pose.is_stub:
        sys.exit("pose model missing")
    rng = np.random.default_rng(a.seed)
    stats = {s: Counter() for s in ("train", "val")}
    drops = Counter()

    def has_box(p):
        t = Path(p).with_suffix(".txt")
        return t.is_file() and t.stat().st_size > 0

    for sc_dir in sorted(p for s in (lab / a.pid).iterdir() if s.is_dir() for p in s.iterdir() if p.is_dir()):
        sc = sc_dir.name
        files = sorted(sc_dir.glob("*.jpg"))
        frames = [(f.relative_to(lab).as_posix(), f.as_posix(), sc) for f in files]
        keep, d = select_frames(frames, state, ignored, has_box)
        drops.update({"%s:%s" % (sc, k): v for k, v in d.items()})
        for k, (key, path, _) in enumerate(keep):
            f = Path(path)
            refuse_holdout(f)
            split = "val" if (k // a.block) % 5 == 4 else "train"
            st = stats[split]
            img = cv2.imread(str(f))
            if img is None:
                continue
            H, W = img.shape[:2]
            boxes = [b for c, b in read_yolo(f.with_suffix(".txt"), W, H) if c == 0] if sc in POSITIVE else []
            samples = process_image(img, boxes, pose, cfg, rng, a.jitter, False, split == "train", primary_only=True,
                                    bystanders_ok=bystanders_consented(f))
            if not samples:
                st["frame_no_subject_or_all_skipped"] += 1
                continue
            for suf, crop, kb, status in samples:
                save_sample(out, split, "own_%s_%s" % (f.stem, suf), crop, kb)
                st["%s_%s" % (status, "scene_pos" if sc in POSITIVE else "scene_neg")] += 1
                st[status] += 1
            st["frames_used"] += 1
        print(sc, {s: dict(stats[s]) for s in stats}, flush=True)

    v2 = ROOT / "data/roi_ds_v2"
    Path(a.yaml).write_text(
        "# roi_ds_v2 + %s human-reviewed own ROIs\ntrain:\n  - %s\n  - %s\nval:\n  - %s\n  - %s\nnames:\n  0: cigarette\n" % (
            a.pid, (v2 / "images/train").as_posix(), (out / "images/train").as_posix(),
            (v2 / "images/val").as_posix(), (out / "images/val").as_posix()), encoding="utf-8")
    rep = {"pid": a.pid, "reviewed": True, "frame_drops": dict(drops), "stats": {s: dict(stats[s]) for s in stats}}
    (out / "build_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
