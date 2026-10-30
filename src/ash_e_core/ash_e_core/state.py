"""Assign cigarette boxes to the nearest person's mouth/hand and derive per-person raw state (spec 5.4-5)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .types import CigBox, SmokerState


@dataclass
class Anchors:
    """Per-person anchors in frame coords. h = head size [px]."""
    mouth: Optional[Tuple[float, float]]
    hands: List[Tuple[float, float]]
    h: float


@dataclass
class RawResult:
    state: int = SmokerState.NONE
    conf: float = 0.0
    box: Optional[CigBox] = None


def _center(b: CigBox) -> np.ndarray:
    x1, y1, x2, y2 = b.xyxy
    return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])


def assign_states(anchors: Sequence[Anchors], cigs: Sequence[CigBox],
                  smoking_radius: float, holding_radius: float) -> List[RawResult]:
    """Each cigarette is given to the one person with the smallest normalized distance to any of their
    mouth/hand anchors (so overlapping people do not steal each other's cigarettes). Then:
    mouth distance <= smoking_radius -> SMOKING candidate; else hand distance <= holding_radius -> HOLDING;
    else ignored (cigarette lying on a table etc.)."""
    res = [RawResult() for _ in anchors]
    for cb in cigs:
        c = _center(cb)
        best = None  # (dist, person_idx)
        for i, a in enumerate(anchors):
            hs = max(a.h, 1.0)
            pts = ([a.mouth] if a.mouth is not None else []) + list(a.hands)
            for p in pts:
                d = float(np.linalg.norm(c - np.array(p))) / hs
                if best is None or d < best[0]:
                    best = (d, i)
        if best is None:
            continue
        i = best[1]
        a = anchors[i]
        hs = max(a.h, 1.0)
        dm = float(np.linalg.norm(c - np.array(a.mouth))) / hs if a.mouth is not None else 1e9
        dh = min([float(np.linalg.norm(c - np.array(p))) / hs for p in a.hands] or [1e9])
        if dm <= smoking_radius:
            st = SmokerState.SMOKING
        elif dh <= holding_radius:
            st = SmokerState.HOLDING
        else:
            continue
        r = res[i]
        if st > r.state or (st == r.state and cb.conf > r.conf):
            res[i] = RawResult(int(st), cb.conf, cb)
    return res
