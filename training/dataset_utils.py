"""Shared helpers for dataset building: perceptual hash, YOLO label IO, path rules."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}


def phash(img_bgr: np.ndarray) -> int:
    """64-bit DCT perceptual hash (pHash)."""
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(g)[:8, :8].flatten()
    med = np.median(d[1:])
    bits = (d > med).astype(np.uint8)
    return int("".join(map(str, bits)), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def read_yolo(txt: Path, w: int, h: int) -> List[Tuple[int, np.ndarray]]:
    """Returns [(cls, xyxy_px)]."""
    out = []
    if not txt.is_file():
        return out
    for line in txt.read_text().splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        c, cx, cy, bw, bh = int(float(p[0])), *map(float, p[1:5])
        out.append((c, np.array([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h], np.float32)))
    return out


def write_yolo(txt: Path, boxes_xyxy, w: int, h: int, cls: int = 0) -> None:
    lines = []
    for b in boxes_xyxy:
        x1, y1, x2, y2 = [float(v) for v in b]
        lines.append("%d %.6f %.6f %.6f %.6f" % (cls, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h))
    txt.write_text("\n".join(lines) + ("\n" if lines else ""))


def list_images(d: Path) -> List[Path]:
    return sorted(p for p in d.rglob("*") if p.suffix.lower() in IMG_EXT)


def _norm(p) -> Path:
    """Absolute, symlink-resolved, case-normalised (Windows is case-insensitive) so '..' / case / junction tricks
    do not slip past the protection checks."""
    return Path(os.path.normcase(os.path.realpath(os.path.abspath(p))))


def is_under(path: Path, parent: Path) -> bool:
    try:
        _norm(path).relative_to(_norm(parent))
        return True
    except ValueError:
        return False


# Raw recorded clips mix training, dev and hold-out participants (run_webcam.py --record), and no training code
# reads them, so training/tuning code is refused there altogether (spec 9A.5, v2.1 gap fix).
PROTECTED_DIRS = ("data/eval/holdout", "acceptance", "data/raw_clips")


def holdout_participants() -> set:
    """Hold-out participant IDs from data/splits/participants.json. Missing file -> empty set; unreadable -> refuse."""
    f = ROOT / "data" / "splits" / "participants.json"
    if not f.is_file():
        return set()
    try:
        return set(json.loads(f.read_text(encoding="utf-8")).get("holdout", []))
    except (OSError, ValueError, AttributeError):
        raise SystemExit("REFUSED: %s is unreadable; cannot tell which participants are hold-out." % f)


def refuse_holdout(path: Path) -> None:
    """Training/tuning code must never read hold-out data or acceptance files (spec 9A.5).
    Refuses: protected dirs (and anything inside), any ancestor that contains one (e.g. data/ or data/eval), and any
    path under data/ that has a hold-out participant ID as a path component."""
    p = Path(path)
    for g in PROTECTED_DIRS:
        guarded = ROOT / g
        if is_under(p, guarded) or is_under(guarded, p):
            raise SystemExit("REFUSED: %s is protected (hold-out / raw clips / acceptance). Use eval_images.py / eval_clips.py --final." % path)
    if is_under(p, ROOT / "data"):
        bad = {x for x in holdout_participants() if x.lower() in {c.lower() for c in _norm(p).parts}}
        if bad:
            raise SystemExit("REFUSED: %s belongs to hold-out participant(s) %s." % (path, sorted(bad)))


def coco_split(image_id: int) -> str:
    """Deterministic train/val assignment for public COCO images (never holdout): 1 in 10 -> val."""
    return "val" if int(image_id) % 10 == 0 else "train"
