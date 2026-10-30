"""Participant-level split of labeled self-captured frames (spec 9A.5). Deterministic, leak-checked.

  python training/make_splits.py --holdout P05,P06 --val P04 --approve-holdout
Groups: holdout (>=2 people recommended) / val (>=1) / train (everyone else). One person -> one group only.
Writes data/splits/{train,val,holdout}.txt (absolute image paths) and participants.json.
Aborts when: a participant appears in two groups, or any pHash near-duplicate (hamming <= 6) crosses
train/val vs holdout (own frames AND the public CigDet images).
Holdout assignment needs the USER's approval: pass --approve-holdout only after the user confirmed the IDs.
After this, run training/lock_acceptance.py to hash + read-only-lock the holdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT, hamming, list_images, phash  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", default=str(ROOT / "data/labeled"))
    ap.add_argument("--holdout", required=True, help="comma-separated participant IDs")
    ap.add_argument("--val", required=True, help="comma-separated participant IDs")
    ap.add_argument("--approve-holdout", action="store_true", help="user approved the holdout IDs")
    ap.add_argument("--phash-dist", type=int, default=6)
    a = ap.parse_args()
    if not a.approve_holdout:
        sys.exit("Holdout participants need the user's approval. Re-run with --approve-holdout after confirmation.")

    ho, va = set(a.holdout.split(",")), set(a.val.split(","))
    if ho & va:
        sys.exit("a participant is in both holdout and val: %s" % (ho & va))
    by_p = defaultdict(list)
    for p in list_images(Path(a.labeled)):
        rel = p.relative_to(a.labeled)
        by_p[rel.parts[0]].append(p)
    allp = set(by_p)
    for g, name in ((ho, "holdout"), (va, "val")):
        miss = g - allp
        if miss:
            sys.exit("%s IDs have no labeled frames: %s" % (name, miss))
    groups = {"holdout": sorted(ho), "val": sorted(va), "train": sorted(allp - ho - va)}
    if len(ho) < 2:
        print("WARNING: holdout has < 2 participants; results are low-confidence (spec 9A.3).")
    if not groups["train"]:
        sys.exit("no train participants")
    files = {g: [p for pid in ids for p in by_p[pid]] for g, ids in groups.items()}

    # leak check: pHash near duplicates between holdout and (train, val, public)
    print("hashing ...")
    hh = [phash(cv2.imread(str(p))) for p in files["holdout"]]
    others = [("own-" + g, p) for g in ("train", "val") for p in files[g]]
    pub = ROOT / "data/public/cigdet/raw/CigDet_dataset"
    if pub.is_dir():
        others += [("public", p) for p in list_images(pub)]
    bad = []
    for tag, p in others:
        h = phash(cv2.imread(str(p)))
        if any(hamming(h, x) <= a.phash_dist for x in hh):
            bad.append((tag, str(p)))
    if bad:
        sys.exit("LEAK: %d near-duplicates between holdout and others, e.g. %s" % (len(bad), bad[:3]))

    out = ROOT / "data/splits"
    out.mkdir(parents=True, exist_ok=True)
    for g, fl in files.items():
        (out / (g + ".txt")).write_text("\n".join(str(p) for p in fl) + "\n")
    (out / "participants.json").write_text(json.dumps(groups, indent=2))
    print({g: (len(ids), len(files[g])) for g, ids in groups.items()}, "(participants, frames)")


if __name__ == "__main__":
    main()
