"""Train the 1-class ROI cigarette detector (YOLO11n, imgsz 192). CPU only on this PC.

  python training/train_cig_roi.py --smoke                     # pipeline check: tiny, ~1-2 min
  python training/train_cig_roi.py --epochs 80 --batch 32      # real run (LONG on CPU: see notes)
Ultralytics is imported here only (never in core / nodes).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT, refuse_holdout  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/roi_ds/data.yaml"))
    ap.add_argument("--weights", default=str(ROOT / "models/yolo11n.pt"))
    ap.add_argument("--imgsz", type=int, default=192)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--name", default="cig_roi")
    ap.add_argument("--smoke", action="store_true", help="tiny run on a 120-image subset, 1 epoch")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true",
                    help="continue an interrupted run from training/runs/<name>/weights/last.pt (settings come from the checkpoint)")
    args = ap.parse_args()
    refuse_holdout(Path(args.data))

    from ultralytics import YOLO

    if args.resume:
        last = ROOT / "training/runs" / args.name / "weights/last.pt"
        if not last.is_file():
            sys.exit("no checkpoint to resume: %s" % last)
        t0 = time.time()
        YOLO(str(last)).train(resume=True)
        print("TRAIN_WALL_SECONDS %.1f  (resumed)" % (time.time() - t0))
        best = last.with_name("best.pt")
        print("best weights:", best, best.is_file())
        return

    data = Path(args.data)
    fraction = 1.0
    if args.smoke:
        # build a tiny dataset view so the smoke run is short: copy 120 train / 40 val samples
        src = data.parent
        dst = ROOT / "data/roi_ds_smoke"
        if dst.exists():
            shutil.rmtree(dst)
        for split, n in (("train", 120), ("val", 40)):
            (dst / "images" / split).mkdir(parents=True)
            (dst / "labels" / split).mkdir(parents=True)
            for p in sorted((src / "images" / split).glob("*.jpg"))[::max(1, len(list((src / "images" / split).glob("*.jpg"))) // n)][:n]:
                shutil.copy(p, dst / "images" / split / p.name)
                shutil.copy(src / "labels" / split / (p.stem + ".txt"), dst / "labels" / split / (p.stem + ".txt"))
        (dst / "data.yaml").write_text("path: %s\ntrain: images/train\nval: images/val\nnames:\n  0: cigarette\n" % dst.as_posix())
        data, args.epochs, args.name = dst / "data.yaml", 1, "smoke"

    t0 = time.time()
    model = YOLO(args.weights)
    model.train(data=str(data), imgsz=args.imgsz, epochs=args.epochs, batch=args.batch, device="cpu",
                workers=0 if args.smoke else args.workers, patience=args.patience, project=str(ROOT / "training/runs"),
                name=args.name, exist_ok=True, plots=False, seed=args.seed, amp=False, verbose=False,
                degrees=15.0, fliplr=0.5, hsv_v=0.4, mosaic=1.0, close_mosaic=5, cache=False)
    dt = time.time() - t0
    print("TRAIN_WALL_SECONDS %.1f  epochs=%d" % (dt, args.epochs))
    best = ROOT / "training/runs" / args.name / "weights/best.pt"
    print("best weights:", best, best.is_file())


if __name__ == "__main__":
    main()
