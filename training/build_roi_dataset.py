"""Build the ROI cigarette detection dataset (YOLO format, 1 class) from full images + YOLO labels.

For each source image the pose model finds people; mouth/hand ROIs are cropped with the SAME rule as
inference (ash_e_core.roi), cigarette boxes are mapped into ROI coordinates, ROIs without a cigarette become
negative samples. Train ROIs are also jittered (shift/scale) to tolerate pose errors.

  python training/build_roi_dataset.py --source public            # CigDet: train->train, test->val
  python training/build_roi_dataset.py --source own               # data/splits/{train,val}.txt (never holdout)
  python training/build_roi_dataset.py --source public --limit 40 --out data/roi_ds_smoke --clean   # smoke
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT, hamming, list_images, phash, read_yolo, refuse_holdout  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402
from ash_e_core.roi import compute_rois  # noqa: E402

MIN_VISIBLE = 0.7     # cigarette box kept in a crop only if >=70% of its area is inside
AMBIGUOUS_BELOW = 0.05  # overlap smaller than this counts as "not in the crop" (negative)


def crop_labels(crop_xyxy, boxes):
    """Returns (kept boxes in crop px, status) where status in {'pos','neg','skip'}."""
    cx1, cy1, cx2, cy2 = crop_xyxy
    kept, ambiguous = [], False
    for b in boxes:
        ix1, iy1, ix2, iy2 = max(b[0], cx1), max(b[1], cy1), min(b[2], cx2), min(b[3], cy2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        f = inter / area
        if f >= MIN_VISIBLE:
            kept.append(np.array([ix1 - cx1, iy1 - cy1, ix2 - cx1, iy2 - cy1], np.float32))
        elif f > AMBIGUOUS_BELOW:
            ambiguous = True
    if ambiguous:
        return [], "skip"
    return kept, ("pos" if kept else "neg")


def jitter_square(cx, cy, side, W, H, rng):
    s = side * rng.uniform(0.85, 1.25)
    cx += rng.uniform(-0.25, 0.25) * side
    cy += rng.uniform(-0.25, 0.25) * side
    return (int(max(0, cx - s / 2)), int(max(0, cy - s / 2)), int(min(W, cx + s / 2)), int(min(H, cy + s / 2)))


def save_sample(out_dir: Path, split: str, name: str, crop, boxes):
    h, w = crop.shape[:2]
    cv2.imwrite(str(out_dir / "images" / split / (name + ".jpg")), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
    lines = ["0 %.6f %.6f %.6f %.6f" % ((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h, (b[2] - b[0]) / w, (b[3] - b[1]) / h)
             for b in boxes]
    (out_dir / "labels" / split / (name + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))


def process_image(img, boxes, pose: PoseModel, cfg, rng, jitter, include_full, train):
    """Yields (suffix, crop, boxes_in_crop, status)."""
    H, W = img.shape[:2]
    out = []
    if include_full:
        out.append(("full", img, [b.copy() for b in boxes], "pos" if boxes else "neg"))
    for pi, p in enumerate(pose.detect(img)):
        for r in compute_rois(p, cfg, W, H):
            variants = [r.xyxy]
            if train:
                variants += [jitter_square(r.center[0], r.center[1], r.side, W, H, rng) for _ in range(jitter)]
            for vi, v in enumerate(variants):
                if v[2] - v[0] < 24 or v[3] - v[1] < 24:
                    continue
                kept, status = crop_labels(v, boxes)
                if status == "skip":
                    continue
                out.append(("p%d_%s_v%d" % (pi, r.kind, vi), img[v[1]:v[3], v[0]:v[2]].copy(), kept, status))
    return out


def gather(args):
    """Returns {split: [(img_path, group)]}. group is the participant/dataset tag used for names."""
    if args.source == "public":
        base = ROOT / "data/public/cigdet/raw/CigDet_dataset"
        return {"train": [(p, "cigdet") for p in list_images(base / "train")],
                "val": [(p, "cigdet") for p in list_images(base / "test")]}
    res = {}
    for split in ("train", "val"):
        f = ROOT / "data/splits" / (split + ".txt")
        if not f.is_file():
            raise SystemExit("missing %s (run training/make_splits.py first)" % f)
        paths = [Path(x.strip()) for x in f.read_text().splitlines() if x.strip()]
        for p in paths:
            refuse_holdout(p)
        ign = ROOT / "data/labeled/ignore.txt"
        ignored = {Path(x.strip()).as_posix() for x in ign.read_text().splitlines()} if ign.is_file() else set()
        res[split] = [(p, p.parts[-4] if len(p.parts) >= 4 else "own") for p in paths if p.as_posix() not in ignored]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["public", "own"], required=True)
    ap.add_argument("--out", default=str(ROOT / "data/roi_ds"))
    ap.add_argument("--limit", type=int, default=0, help="max images per split (smoke test)")
    ap.add_argument("--jitter", type=int, default=2, help="extra jittered crops per ROI (train only)")
    ap.add_argument("--no-full", action="store_true", help="do not add the whole image as a sample")
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--clean", action="store_true", help="delete --out first")
    ap.add_argument("--phash-dist", type=int, default=6)
    args = ap.parse_args()

    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    for s in ("train", "val"):
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)

    cfg = PerceptionConfig(person_conf_thresh=0.25, min_person_h_px=40)
    pose = PoseModel(load_model(args.pose, "onnxruntime", 4), cfg)
    if pose.is_stub:
        raise SystemExit("pose model missing: %s" % args.pose)
    rng = np.random.default_rng(args.seed)
    data = gather(args)

    # dedup (pHash, hamming <= phash_dist): within train, then val vs train
    hashes_train = []
    stats = {}
    for split in ("train", "val"):
        items = data[split][: args.limit] if args.limit else data[split]
        kept_items, dropped = [], 0
        hs_split = []
        for p, grp in items:
            img = cv2.imread(str(p))
            if img is None:
                continue
            h = phash(img)
            ref = hashes_train + hs_split if split == "val" else hs_split
            if any(hamming(h, o) <= args.phash_dist for o in ref):
                dropped += 1
                continue
            hs_split.append(h)
            kept_items.append((p, grp, img))
        if split == "train":
            hashes_train = hs_split
        st = {"images_in": len(items), "dedup_dropped": dropped, "pos": 0, "neg": 0, "skipped_imgs_no_sample": 0}
        for p, grp, img in kept_items:
            H, W = img.shape[:2]
            boxes = [b for c, b in read_yolo(p.with_suffix(".txt"), W, H) if c == 0]
            samples = process_image(img, boxes, pose, cfg, rng, args.jitter, not args.no_full, split == "train")
            if not samples:
                st["skipped_imgs_no_sample"] += 1
            for suf, crop, kb, status in samples:
                save_sample(out, split, "%s_%s_%s" % (args.source, p.stem, suf), crop, kb)
                st[status] += 1
        stats[split] = st
    (out / "data.yaml").write_text("path: %s\ntrain: images/train\nval: images/val\nnames:\n  0: cigarette\n"
                                   % out.resolve().as_posix())
    print("built", out)
    for s, st in stats.items():
        print(s, st)


if __name__ == "__main__":
    main()
