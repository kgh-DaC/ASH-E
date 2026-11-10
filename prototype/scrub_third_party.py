"""Remove non-consenting third parties from own capture frames (data/raw/<PID>/<SESSION>/<scenario>/*.jpg).

  python prototype/scrub_third_party.py --participants P01,P02,P03            # dry run: counts + preview montage
  python prototype/scrub_third_party.py --participants P01,P02,P03 --apply    # IRREVERSIBLE: overwrites raw frames

Per frame (pose model at a LOW threshold so a half-visible bystander is still found):
 * mask:      exactly one person fully inside the frame (= the subject) and every other person is cut off at the
              left/right border with few visible joints -> a full-height strip from that border to the edge
              person's inner side is filled with grey, except where it overlaps the subject's box.
 * ambiguous: two or more fully visible people, an edge person with many visible joints, or only edge people ->
              we cannot tell the subject from the third party. With --apply --delete-ambiguous these frames are deleted
              (and removed from meta.jsonl); without it they are left untouched and listed.
 * clean:     one person or nobody detected -> untouched.
 * After masking the frame is re-detected; people left over are masked too (up to ROUNDS times), still left -> ambiguous.
 * The kept subject's torso colours are compared with the participant's median; an outlier -> ambiguous.
No backup is kept (keeping one would defeat the purpose). The log lists file names only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import EDGE_FRAC, EDGE_VISIBLE_KPTS  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402

FILL = 114          # grey
MARGIN = 0.04       # box expansion (fraction of box size)
ROUNDS = 3          # re-detect after masking and extend the mask up to this many times
APPEAR_MAX = 0.8    # Bhattacharyya distance of the subject's torso colours to the participant median above this ->
                    # the "subject" is someone else (e.g. a third party walking past, P03) -> ambiguous


def classify(persons, W):
    m = EDGE_FRAC * W
    inner = [p for p in persons if p.bbox_xyxy[0] > m and p.bbox_xyxy[2] < W - m]
    edge = [p for p in persons if all(p is not q for q in inner)]
    if len(persons) <= 1 and len(inner) == len(persons):
        return "clean", inner, []
    big_edge = [p for p in edge if int((p.keypoints[:, 2] >= 0.5).sum()) >= EDGE_VISIBLE_KPTS]
    if len(inner) == 1 and not big_edge:
        return "mask", inner, edge
    return "ambiguous", inner, edge


def torso_hist(img, p):
    k = p.keypoints[[5, 6, 11, 12]]
    x1, y1, x2, y2 = p.bbox_xyxy
    v = k[k[:, 2] >= 0.4]
    if len(v) >= 3:
        a, b, c, d = v[:, 0].min(), v[:, 0].max(), v[:, 1].min(), v[:, 1].max()
    else:
        a, b, c, d = x1 + (x2 - x1) * .25, x2 - (x2 - x1) * .25, y1 + (y2 - y1) * .2, y1 + (y2 - y1) * .55
    H, W = img.shape[:2]
    a, b, c, d = int(max(0, a)), int(min(W, b)), int(max(0, c)), int(min(H, d))
    if b - a < 6 or d - c < 6:
        return None
    h = cv2.calcHist([cv2.cvtColor(img[c:d, a:b], cv2.COLOR_BGR2HSV)], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
    h = h.flatten()
    return (h / max(h.sum(), 1e-6)).astype(np.float32)


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / max(u, 1e-6)


def add_strips(m, subject_box, others, W):
    """Full-height strip from the border to each other person's inner side (on the side away from the subject):
    a seated bystander's legs/torso often fall outside the pose box (dry run 2026-11-10)."""
    scx = (subject_box[0] + subject_box[2]) / 2
    for p in others:
        x1, _, x2, _ = p.bbox_xyxy
        dx = (x2 - x1) * MARGIN + 8
        if (x1 + x2) / 2 > scx:
            m[:, int(max(0, x1 - dx)):] = True
        else:
            m[:, :int(min(W, x2 + dx))] = True


def scrub(img, subject, edge, pose):
    """Returns (masked image, ok). ok=False when people other than the subject remain after ROUNDS."""
    H, W = img.shape[:2]
    sb = subject.bbox_xyxy
    keep = np.zeros((H, W), bool)
    keep[max(0, int(sb[1])):int(sb[3]), max(0, int(sb[0])):int(sb[2])] = True
    m = np.zeros((H, W), bool)
    others = edge
    for _ in range(ROUNDS + 1):
        add_strips(m, sb, others, W)
        out = img.copy()
        out[m & ~keep] = FILL
        others = [p for p in pose.detect(out) if iou(p.bbox_xyxy, sb) < 0.5]
        if not others:
            return out, True
    return out, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participants", default="P01,P02,P03")
    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--apply", action="store_true", help="overwrite raw frames (irreversible)")
    ap.add_argument("--delete-ambiguous", action="store_true", help="with --apply: delete ambiguous frames")
    ap.add_argument("--preview", default="", help="dry run: write a montage of masked / ambiguous samples here")
    ap.add_argument("--log", default=str(ROOT / "_workspace/scrub_third_party_log.json"))
    a = ap.parse_args()
    pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", 4), PerceptionConfig(person_conf_thresh=a.conf))
    if pose.is_stub:
        sys.exit("pose model missing")
    log, tiles = {}, []
    for pid in a.participants.split(","):
        # pass 1: classify + subject appearance
        items = []
        for f in sorted((ROOT / "data/raw" / pid).rglob("*.jpg")):
            img = cv2.imread(str(f))
            if img is None:
                continue
            kind, inner, edge = classify(pose.detect(img), img.shape[1])
            items.append([f, kind, inner, edge, torso_hist(img, inner[0]) if inner else None])
        hs = [it[4] for it in items if it[4] is not None]
        ref = np.median(np.array(hs), 0).astype(np.float32) if hs else None
        stats = {"clean": 0, "mask": 0, "ambiguous": 0, "appearance_outlier": 0, "residual_after_mask": 0}
        amb, masked = [], []
        for f, kind, inner, edge, h in items:
            rel = f.relative_to(ROOT / "data/raw").as_posix()
            if kind != "ambiguous" and h is not None and ref is not None and \
                    cv2.compareHist(ref, h, cv2.HISTCMP_BHATTACHARYYA) > APPEAR_MAX:
                kind = "ambiguous"
                stats["appearance_outlier"] += 1
            img = cv2.imread(str(f))
            if kind == "mask":
                out, ok = scrub(img, inner[0], edge, pose)
                if not ok:
                    kind = "ambiguous"
                    stats["residual_after_mask"] += 1
            stats[kind] += 1
            if kind == "mask":
                masked.append(rel)
                if a.apply:
                    cv2.imwrite(str(f), out, [cv2.IMWRITE_JPEG_QUALITY, 95])
                elif a.preview and stats["mask"] % 60 == 1:
                    tiles.append(cv2.resize(out, (256, 144)))
            elif kind == "ambiguous":
                amb.append(rel)
                if a.apply and a.delete_ambiguous:
                    f.unlink()
                elif a.preview and stats["ambiguous"] % 12 == 1:
                    t = cv2.resize(img, (256, 144))
                    cv2.rectangle(t, (0, 0), (255, 143), (0, 0, 255), 4)
                    tiles.append(t)
        if a.apply and a.delete_ambiguous and amb:
            gone = {Path(r).name for r in amb}
            for mf in (ROOT / "data/raw" / pid).rglob("meta.jsonl"):
                lines = [ln for ln in mf.read_text(encoding="utf-8").splitlines()
                         if ln.strip() and Path(json.loads(ln)["file"]).name not in gone]
                mf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log[pid] = {"stats": stats, "masked": masked, "ambiguous": amb,
                    "applied": a.apply, "ambiguous_deleted": bool(a.apply and a.delete_ambiguous)}
        print(pid, stats, flush=True)
    if a.preview and tiles:
        while len(tiles) % 6:
            tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(a.preview, np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))
    Path(a.log if a.apply else a.log.replace(".json", "_dryrun.json")).write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
