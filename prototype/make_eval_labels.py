"""Turn captured frames (capture.py) into an evaluation image set for eval_images.py (spec 9.2, image mode).

  python prototype/make_eval_labels.py --participants P01,P02 --split dev [--every 2] [--review]
  python prototype/make_eval_labels.py --participants P05,P06 --split holdout --review   # then lock_acceptance.py --create

For every Nth captured frame it runs the pose model, takes the LARGEST person as the labeled person and writes
data/eval/<split>/images/<name>.jpg + .json with the label implied by the capture scenario
(holding->holding, mouth->smoking, none/similar/gesture/ecig_* -> none). That implied label is only a DRAFT:
in the 'mouth' scenario the hand is down half of the time (-> really holding). --review shows each frame and lets you fix
it: s = smoking, h = holding, n = none, d = drop frame, SPACE/Enter = keep, q = stop (the rest stays unreviewed and is
marked "reviewed": false -- eval_images.py counts only reviewed frames when (unreviewed frames are only drafts)).
Frames show faces: everything stays under data/ (local, never uploaded). Hold-out participants must be the ones chosen
in make_splits.py; the hold-out folder is written once and must be locked right after (lock_acceptance.py --create).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402

IMPLIED = {"holding": "holding", "mouth": "smoking"}
KEYS = {ord("s"): "smoking", ord("h"): "holding", ord("n"): "none"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--participants", required=True, help="comma-separated IDs, e.g. P01,P02")
    ap.add_argument("--split", choices=["dev", "holdout"], required=True)
    ap.add_argument("--raw", default=str(ROOT / "data/raw"))
    ap.add_argument("--every", type=int, default=2, help="take every Nth captured frame")
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--review", action="store_true")
    a = ap.parse_args()

    out = ROOT / "data/eval" / a.split / "images"
    if a.split == "holdout" and (ROOT / "acceptance/holdout_manifest.sha256").is_file():
        sys.exit("REFUSED: hold-out is already locked (manifest exists). Changing it needs user approval.")
    out.mkdir(parents=True, exist_ok=True)
    pose = PoseModel(load_model(a.pose, "onnxruntime", 4), PerceptionConfig(person_conf_thresh=0.3))
    if pose.is_stub:
        sys.exit("pose model missing: %s" % a.pose)

    n = k = 0
    for pid in [p.strip() for p in a.participants.split(",") if p.strip()]:
        for meta in sorted(Path(a.raw).glob("%s/*/meta.jsonl" % pid)):
            for i, line in enumerate(meta.read_text(encoding="utf-8").splitlines()):
                if i % a.every:
                    continue
                m = json.loads(line)
                src = meta.parent / m["file"]
                img = cv2.imread(str(src))
                if img is None:
                    continue
                persons = pose.detect(img)
                if not persons:
                    continue
                p = persons[0]  # detector sorts big (near) first
                label = IMPLIED.get(m["scenario"], "none")
                cat = m.get("category", "plain")
                if a.review:
                    vis = img.copy()
                    x1, y1, x2, y2 = [int(v) for v in p.bbox_xyxy]
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(vis, "%s [%s] s=smoking h=holding n=none d=drop SPACE=keep q=stop" % (label, m["scenario"]),
                                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    cv2.imshow("review (local)", vis)
                    key = cv2.waitKey(0) & 0xFF
                    if key == ord("q"):
                        cv2.destroyAllWindows()
                        print("stopped; %d frames written" % k)
                        return
                    if key == ord("d"):
                        continue
                    label = KEYS.get(key, label)
                name = "%s_%s_%s" % (a.split, m["participant"], Path(m["file"]).name)
                shutil.copy(src, out / name)
                (out / name).with_suffix(".json").write_text(json.dumps([{
                    "bbox_xyxy": [float(v) for v in p.bbox_xyxy], "label": label, "category": cat,
                    "scenario": m["scenario"], "distance_tag": m.get("distance_tag"), "reviewed": bool(a.review)}]))
                k += 1
                n += 1
    cv2.destroyAllWindows()
    print("%d frames -> %s (reviewed=%s)" % (k, out, a.review))
    if a.split == "holdout":
        print("NEXT: python training/lock_acceptance.py --create   (locks hold-out; never edit afterwards)")


if __name__ == "__main__":
    main()
