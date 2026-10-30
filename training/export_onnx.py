"""Export trained cigarette ROI detector to ONNX (opset 17). Default: static batch 1 (what core runs)."""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--weights", default=str(ROOT / "training/runs/cig_roi/weights/best.pt"))
ap.add_argument("--out", default=str(ROOT / "models/cig_roi.onnx"))
ap.add_argument("--imgsz", type=int, default=192)
ap.add_argument("--dynamic", action="store_true", help="dynamic batch (batched ROI inference)")
a = ap.parse_args()

from ultralytics import YOLO  # noqa: E402

p = YOLO(a.weights).export(format="onnx", imgsz=a.imgsz, opset=17, simplify=False, dynamic=a.dynamic, batch=1)
shutil.copy(p, a.out)
print("exported ->", a.out)
