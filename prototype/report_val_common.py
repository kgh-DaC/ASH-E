"""Evaluate every cigarette-ROI model version on ONE common validation set with the ultralytics validator.

Why: each version's own val split differs (v1 = public only, v3+ = public + P01 val blocks), so the val mAP in each
results.csv cannot be compared across versions. Here all versions are scored on the v6 val split
(data/roi_ds_v6.yaml: roi_ds_v2 val 506 ROI + P01 val 1,330 ROI). P01 val frames are the same 5th-of-every-20-frame
blocks in every version, so they were never in any version's train split. No P02/P03 data is read.

  python prototype/report_val_common.py               # all versions -> _workspace/eval_out/val_common/<ver>.json
  python prototype/report_val_common.py --only v6     # one version (+ plots: confusion matrix, PR/P/R/F1 curves)

Per version it also scores the two halves separately (public val / P01 val) so the robot-view part is visible.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import refuse_holdout  # noqa: E402

WEIGHTS = {
    "v1": "training/runs/cig_roi_v2/weights/best.pt",
    "v3exp": "training/runs/cig_roi_v3exp/weights/best.pt",
    "v3": "training/runs/cig_roi_v3/weights/best.pt",
    "v4": "training/runs/cig_roi_v4/weights/best.pt",
    "v5": "training/runs/cig_roi_v5/weights/best.pt",
    "v6": "training/runs/cig_roi_v6/weights/best.pt",
}
OUT = ROOT / "_workspace/eval_out/val_common"
VAL_PUBLIC = ROOT / "data/roi_ds_v2/images/val"
VAL_OWN = ROOT / "data/roi_own_p01_reviewed_v6/images/val"


def write_yaml(name, dirs):
    p = OUT / f"{name}.yaml"
    body = "train:\n" + "".join(f"  - {d.as_posix()}\n" for d in dirs) + "val:\n" + \
        "".join(f"  - {d.as_posix()}\n" for d in dirs) + "names:\n  0: cigarette\n"
    p.write_text(body, encoding="utf-8")
    return p


def run(ver, plots):
    from ultralytics import YOLO
    w = ROOT / WEIGHTS[ver]
    if not w.is_file():
        print("skip", ver, "(no weights)", w)
        return
    res = {"weights": WEIGHTS[ver]}
    for part, dirs in (("all", [VAL_PUBLIC, VAL_OWN]), ("public", [VAL_PUBLIC]), ("p01", [VAL_OWN])):
        for d in dirs:
            refuse_holdout(d)
        y = write_yaml(f"val_{part}", dirs)
        name = f"{ver}_{part}"
        m = YOLO(str(w)).val(data=str(y), imgsz=192, batch=64, device="cpu", conf=0.001, iou=0.7, workers=0,
                             plots=plots and part == "all", project=str(OUT / "runs"), name=name, exist_ok=True,
                             verbose=False)
        b = m.box
        res[part] = dict(P=float(b.mp), R=float(b.mr), mAP50=float(b.map50), mAP50_95=float(b.map),
                         images=int(m.seen) if hasattr(m, "seen") else None,
                         speed_ms=dict(m.speed) if hasattr(m, "speed") else None)
        try:
            cm = m.confusion_matrix.matrix.tolist()
            res[part]["confusion_matrix"] = cm  # rows = predicted [cigarette, background], cols = true
        except Exception:  # noqa: BLE001
            pass
        print(ver, part, res[part]["P"], res[part]["R"], res[part]["mAP50"], res[part]["mAP50_95"])
    (OUT / f"{ver}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--plots", action="store_true", help="save ultralytics plots (confusion matrix, PR, F1 curves)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for v in (a.only or list(WEIGHTS)):
        run(v, a.plots)


if __name__ == "__main__":
    main()
