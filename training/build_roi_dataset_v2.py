"""Build data/roi_ds_v2 = CigDet positives + COCO none/similar hard negatives + synthetic copy-paste (train only).

Reuses build_roi_dataset.process_image/save_sample (same ROI rule as inference). Does NOT touch data/roi_ds and refuses to
write there. Public/synthetic data goes to train/val only (never holdout; own data via data/splits is optional and
already excludes holdout).

  python training/build_roi_dataset_v2.py --out data/roi_ds_v2 --clean
  python training/build_roi_dataset_v2.py --out data/roi_ds_v2_smoke --clean --limit 40     # smoke
Name prefixes: public_*  coco_none_*  coco_similar_*  synth_*  (own_* if --include-own)
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
from build_roi_dataset import gather, process_image, save_sample  # noqa: E402
from dataset_utils import ROOT, coco_split, hamming, phash, read_yolo, refuse_holdout  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402

EVAL_OUT = ROOT / "_workspace/eval_out"


def montage(crops, path, cols=8, size=160):
    if not crops:
        return
    tiles = [cv2.resize(c, (size, size)) for c in crops]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    EVAL_OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/roi_ds_v2"))
    ap.add_argument("--clean", action="store_true", help="delete --out first (refused for data/roi_ds)")
    ap.add_argument("--limit", type=int, default=0, help="max images per source/split (smoke)")
    ap.add_argument("--jitter", type=int, default=2)
    ap.add_argument("--coco-neg-per-img", type=int, default=3, help="max ROIs kept per COCO image (random)")
    ap.add_argument("--coco-jitter", type=int, default=1)
    ap.add_argument("--screen-model", default=str(ROOT / "training/runs/calib/weights/best.pt"))
    ap.add_argument("--screen-conf", type=float, default=0.5, help="drop COCO negatives where the cigarette model fires")
    ap.add_argument("--no-synth", action="store_true")
    ap.add_argument("--include-own", action="store_true", help="also add data/splits train/val own frames")
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--phash-dist", type=int, default=6)
    a = ap.parse_args()

    out = Path(a.out).resolve()
    if out == (ROOT / "data/roi_ds").resolve():
        raise SystemExit("REFUSED: data/roi_ds is the preserved v1 dataset; use another --out")
    if a.clean and out.exists():
        shutil.rmtree(out)
    for s in ("train", "val"):
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)

    cfg = PerceptionConfig(person_conf_thresh=0.25, min_person_h_px=40)
    pose = PoseModel(load_model(a.pose, "onnxruntime", 4), cfg)
    if pose.is_stub:
        raise SystemExit("pose model missing")
    rng = np.random.default_rng(a.seed)
    screen = None
    if Path(a.screen_model).is_file():
        from ultralytics import YOLO
        screen = YOLO(a.screen_model)
    else:
        print("WARNING: screen model missing, COCO negatives are NOT auto-screened")

    stats = {s: Counter() for s in ("train", "val")}
    hashes = {"train": [], "val": []}
    flagged, neg_sample = [], []

    def dup(img_h, split):
        ref = hashes["train"] + (hashes["val"] if split == "val" else [])
        return any(hamming(img_h, o) <= a.phash_dist for o in ref)

    # 1) public CigDet positives (+ their own ROI negatives): same as v1
    pub = gather(argparse.Namespace(source="public"))
    for split in ("train", "val"):
        items = pub[split][: a.limit] if a.limit else pub[split]
        for p, _ in items:
            img = cv2.imread(str(p))
            if img is None:
                continue
            h = phash(img)
            if dup(h, split):
                stats[split]["dedup_dropped"] += 1
                continue
            hashes[split].append(h)
            H, W = img.shape[:2]
            boxes = [b for c, b in read_yolo(p.with_suffix(".txt"), W, H) if c == 0]
            for suf, crop, kb, st in process_image(img, boxes, pose, cfg, rng, a.jitter, True, split == "train"):
                save_sample(out, split, "public_%s_%s" % (p.stem, suf), crop, kb)
                stats[split]["public_" + st] += 1

    # 2) COCO none / similar (negatives, empty labels)
    man_f = ROOT / "data/public/coco/subset/manifest.json"
    man = json.loads(man_f.read_text()) if man_f.is_file() else []
    for split in ("train", "val"):
        items = [m for m in man if coco_split(m["id"]) == split]
        if a.limit:
            idx = np.random.default_rng(1).permutation(len(items))[: a.limit]
            items = [items[i] for i in idx]
        for m in items:
            p = ROOT / m["file"]
            refuse_holdout(p)
            img = cv2.imread(str(p))
            if img is None:
                continue
            h = phash(img)
            if dup(h, split):
                stats[split]["dedup_dropped"] += 1
                continue
            hashes[split].append(h)
            samples = process_image(img, [], pose, cfg, rng, a.coco_jitter, False, split == "train")
            if not samples:
                continue
            rng.shuffle(samples)
            samples = samples[: a.coco_neg_per_img]
            if screen is not None:
                res = screen.predict([s[1] for s in samples], imgsz=192, conf=a.screen_conf, verbose=False, device="cpu")
                keep = []
                for s, r in zip(samples, res):
                    if len(r.boxes):
                        flagged.append(s[1])
                        stats[split]["coco_flagged_dropped"] += 1
                    else:
                        keep.append(s)
                samples = keep
            for suf, crop, kb, st in samples:
                tag = "coco_%s" % m["category"]
                save_sample(out, split, "%s_%s_%s" % (tag, p.stem, suf), crop, kb)
                stats[split][tag] += 1
                if len(neg_sample) < 64 and rng.random() < 0.1:
                    neg_sample.append(crop)

    # 3) synthetic copy-paste: train only, ratio-capped at generation time (synth_copy_paste.py)
    synth = ROOT / "data/synth"
    if not a.no_synth and (synth / "images").is_dir():
        imgs = sorted((synth / "images").glob("synth_*.jpg"))
        if a.limit:
            imgs = imgs[: a.limit]
        for p in imgs:
            img = cv2.imread(str(p))
            H, W = img.shape[:2]
            boxes = [b for c, b in read_yolo(synth / "labels" / (p.stem + ".txt"), W, H) if c == 0]
            for suf, crop, kb, st in process_image(img, boxes, pose, cfg, rng, 0, False, True):
                if st != "pos":  # other ROIs of the source image are plain COCO negatives; not re-added here
                    continue
                save_sample(out, "train", "%s_%s" % (p.stem, suf), crop, kb)
                stats["train"]["synth_" + st] += 1

    if a.include_own and (ROOT / "data/splits/train.txt").is_file():
        own = gather(argparse.Namespace(source="own"))
        for split in ("train", "val"):
            for p, _ in (own[split][: a.limit] if a.limit else own[split]):
                img = cv2.imread(str(p))
                if img is None:
                    continue
                H, W = img.shape[:2]
                boxes = [b for c, b in read_yolo(p.with_suffix(".txt"), W, H) if c == 0]
                for suf, crop, kb, st in process_image(img, boxes, pose, cfg, rng, a.jitter, True, split == "train",
                                                       primary_only=True):
                    save_sample(out, split, "own_%s_%s" % (p.stem, suf), crop, kb)
                    stats[split]["own_" + st] += 1

    (out / "data.yaml").write_text("path: %s\ntrain: images/train\nval: images/val\nnames:\n  0: cigarette\n" % out.as_posix())
    montage(flagged[:48], EVAL_OUT / "coco_neg_flagged_by_screen.jpg")
    montage(neg_sample[:48], EVAL_OUT / "coco_neg_random_sample.jpg")

    # balance report: positives = label file non-empty
    rep = {}
    for s in ("train", "val"):
        names = sorted((out / "labels" / s).glob("*.txt"))
        c = Counter()
        for f in names:
            grp = "synth" if f.name.startswith("synth_") else "coco_similar" if f.name.startswith("coco_similar") else \
                "coco_none" if f.name.startswith("coco_none") else "own" if f.name.startswith("own_") else "public"
            c[grp + ("_pos" if f.stat().st_size > 0 else "_neg")] += 1
        pos = sum(v for k, v in c.items() if k.endswith("_pos"))
        neg = sum(v for k, v in c.items() if k.endswith("_neg"))
        rep[s] = {"counts": dict(c), "pos": pos, "neg": neg, "neg_per_pos": round(neg / max(1, pos), 2),
                  "build_stats": dict(stats[s])}
    (out / "build_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
