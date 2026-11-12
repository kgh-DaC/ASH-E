"""Pre-label self-captured frames with the current cigarette ROI model so a human only has to FIX boxes.

  python prototype/prelabel.py --src data/raw/P01 [--model models/cig_roi.onnx] [--conf 0.25]

Reads frames (+ meta.jsonl) written by capture.py, copies them to data/labeled/<PID>/<SESSION>/<scenario>/
and writes YOLO txt next to each image (class 0 = cigarette) plus classes.txt for the labeling tool.
 * holding / mouth scenarios: model boxes are written as the DRAFT label (you must verify every frame).
 * none / similar / gesture / ecig_* scenarios: a cigarette is NOT expected -> label file is EMPTY (hard negative).
   Model detections there are only counted as false positives in the report (a free measure of look-alike confusion).
Outputs review_queue.csv: what to look at first (missed-looking frames, then lowest confidence).
Nothing is uploaded anywhere. Human review is mandatory (spec 9A.5); this script never marks a frame "reviewed".
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import bystanders_consented, own_subject, list_images, write_yolo  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import CigaretteRoiModel, PoseModel, global_nms  # noqa: E402
from ash_e_core.roi import compute_rois  # noqa: E402

POSITIVE_SCENARIOS = {"holding", "mouth"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="participant or session dir under data/raw")
    ap.add_argument("--out", default=str(ROOT / "data/labeled"))
    ap.add_argument("--model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--conf", type=float, default=0.25, help="draft-label threshold (low on purpose: easier to delete than to add)")
    a = ap.parse_args()

    src, out = Path(a.src).resolve(), Path(a.out)
    raw_root = (ROOT / "data/raw").resolve()
    cfg = PerceptionConfig(person_conf_thresh=0.30)
    pose = PoseModel(load_model(a.pose, "onnxruntime", 4), cfg)
    cig = CigaretteRoiModel(load_model(a.model, "onnxruntime", 4), cfg)
    if pose.is_stub:
        sys.exit("pose model missing: %s" % a.pose)
    if cig.is_stub:
        print("WARNING: cigarette model missing (%s). Writing EMPTY drafts; label everything by hand.\n"
              "         Train one first: _workspace/02a_perception_notes.md" % a.model)

    stats = defaultdict(lambda: {"frames": 0, "frames_with_pred": 0, "no_person": 0, "excluded_multi_person": 0})
    queue, excluded = [], []
    for img_path in list_images(src):
        try:
            rel = img_path.resolve().relative_to(raw_root)  # <PID>/<SESSION>/<scenario>/<file>
        except ValueError:
            sys.exit("--src must be inside data/raw")
        scenario = rel.parts[-2]
        dst_dir = out / Path(*rel.parts[:-1])
        dst_dir.mkdir(parents=True, exist_ok=True)
        img = cv2.imread(str(img_path))
        H, W = img.shape[:2]
        detected = pose.detect(img)
        persons = own_subject(detected, W, bystanders_consented(img_path))  # third party in frame (capture QC 2026-11-10)
        if detected and not persons:
            excluded.append(rel.as_posix())  # 2+ fully visible people: subject ambiguous -> not copied, not labelled
            stats[scenario]["excluded_multi_person"] += 1
            continue
        boxes = []
        if not cig.is_stub:
            for p in persons:
                for lst in cig.detect_crops(img, [r.xyxy for r in compute_rois(p, cfg, W, H)], a.conf):
                    boxes.extend(lst)
            boxes = global_nms(boxes, 0.5)
        st = stats[scenario]
        st["frames"] += 1
        st["frames_with_pred"] += int(bool(boxes))
        st["no_person"] += int(not persons)
        shutil.copy(img_path, dst_dir / img_path.name)
        txt = dst_dir / (img_path.stem + ".txt")
        if scenario in POSITIVE_SCENARIOS:
            write_yolo(txt, [b.xyxy for b in boxes], W, H)
            top = max([b.conf for b in boxes], default=0.0)
            flag = "NO_PERSON" if not persons else ("NO_BOX_CHECK_MISSED" if not boxes else "verify")
            queue.append((0 if not boxes else 1, top, str(dst_dir / img_path.name), flag))
        else:
            write_yolo(txt, [], W, H)  # hard negative: empty label
    for d in {p.parent for p in out.rglob("*.txt")}:
        (d / "classes.txt").write_text("cigarette\n")
    queue.sort(key=lambda q: (q[0], q[1]))
    with open(out / ("review_queue_%s.csv" % src.name), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["priority", "max_conf", "image", "flag"])
        w.writerows(queue)
    (out / ("excluded_multi_person_%s.txt" % src.name)).write_text("\n".join(excluded) + "\n", encoding="utf-8")
    rep = {k: dict(v) for k, v in stats.items()}
    (out / ("prelabel_report_%s.json" % src.name)).write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))
    print("negative-scenario frames with a model detection = false positives (see report); review queue:",
          out / ("review_queue_%s.csv" % src.name))


if __name__ == "__main__":
    main()
