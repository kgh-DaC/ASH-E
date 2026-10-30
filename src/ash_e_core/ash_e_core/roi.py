"""Mouth / hand ROIs from COCO keypoints (spec 5.4-3)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .types import PersonPose

NOSE, LEYE, REYE, LEAR, REAR, LSH, RSH, LELB, RELB, LWR, RWR = range(11)


@dataclass
class Roi:
    kind: str                     # "mouth" | "hand_l" | "hand_r"
    center: Tuple[float, float]   # anchor position (frame coords)
    side: float                   # un-clipped square side [px]
    xyxy: Tuple[int, int, int, int]  # clipped to frame


def _ok(kp: np.ndarray, i: int, t: float) -> bool:
    return bool(kp[i, 2] >= t)


def head_size(pose: PersonPose, kp_thresh: float) -> float:
    kp = pose.keypoints
    bh = float(pose.bbox_xyxy[3] - pose.bbox_xyxy[1])
    if _ok(kp, LEAR, kp_thresh) and _ok(kp, REAR, kp_thresh):
        return float(np.linalg.norm(kp[LEAR, :2] - kp[REAR, :2]))
    if _ok(kp, LEYE, kp_thresh) and _ok(kp, REYE, kp_thresh):
        return 2.0 * float(np.linalg.norm(kp[LEYE, :2] - kp[REYE, :2]))
    if _ok(kp, LSH, kp_thresh) and _ok(kp, RSH, kp_thresh):
        return 0.6 * float(np.linalg.norm(kp[LSH, :2] - kp[RSH, :2]))
    return 0.12 * bh


def mouth_position(pose: PersonPose, h: float, kp_thresh: float) -> Optional[Tuple[float, float]]:
    kp = pose.keypoints
    if not _ok(kp, NOSE, kp_thresh):
        return None
    if _ok(kp, LEYE, kp_thresh) and _ok(kp, REYE, kp_thresh):
        mid = (kp[LEYE, :2] + kp[REYE, :2]) / 2.0
        m = kp[NOSE, :2] + 0.6 * (kp[NOSE, :2] - mid)
        return float(m[0]), float(m[1])
    return float(kp[NOSE, 0]), float(kp[NOSE, 1] + 0.25 * h)


def hand_positions(pose: PersonPose, kp_thresh: float) -> List[Tuple[str, Tuple[float, float]]]:
    kp = pose.keypoints
    out = []
    for kind, wr, el in (("hand_l", LWR, LELB), ("hand_r", RWR, RELB)):
        if not _ok(kp, wr, kp_thresh):
            continue
        p = kp[wr, :2].copy()
        if _ok(kp, el, kp_thresh):
            p = p + 0.3 * (kp[wr, :2] - kp[el, :2])
        out.append((kind, (float(p[0]), float(p[1]))))
    return out


def _square(cx: float, cy: float, side: float, W: int, H: int) -> Tuple[int, int, int, int]:
    x1, y1 = int(round(max(0.0, cx - side / 2))), int(round(max(0.0, cy - side / 2)))
    x2, y2 = int(round(min(float(W), cx + side / 2))), int(round(min(float(H), cy + side / 2)))
    return x1, y1, x2, y2


def person_anchors(pose: PersonPose, cfg) -> Tuple[Optional[Tuple[float, float]], List[Tuple[float, float]], float]:
    """(mouth, hands, head size h). Falls back to bbox ratios when no upper-body keypoint is valid."""
    kp, t = pose.keypoints, cfg.kp_conf_thresh
    if any(_ok(kp, i, t) for i in range(11)):
        h = head_size(pose, t)
        return mouth_position(pose, h, t), [p for _, p in hand_positions(pose, t)], h
    x1, y1, x2, y2 = [float(v) for v in pose.bbox_xyxy]
    bw, bh = x2 - x1, y2 - y1
    return ((x1 + x2) / 2, y1 + 0.125 * bh), [(x1 + bw * 0.25, y1 + 0.55 * bh), (x1 + bw * 0.75, y1 + 0.55 * bh)], 0.12 * bh


def compute_rois(pose: PersonPose, cfg, W: int, H: int) -> List[Roi]:
    """Mouth/hand ROIs. ROIs whose un-clipped side < min_roi_px are skipped (person too far)."""
    kp, t = pose.keypoints, cfg.kp_conf_thresh
    cand = []
    if any(_ok(kp, i, t) for i in range(11)):
        h = head_size(pose, t)
        m = mouth_position(pose, h, t)
        if m is not None:
            cand.append(("mouth", m, cfg.mouth_roi_scale * h))
        for kind, pos in hand_positions(pose, t):
            cand.append((kind, pos, cfg.hand_roi_scale * h))
    else:  # bbox-ratio fallback
        x1, y1, x2, y2 = [float(v) for v in pose.bbox_xyxy]
        bw, bh = x2 - x1, y2 - y1
        cand = [("mouth", ((x1 + x2) / 2, y1 + 0.125 * bh), 0.25 * bh),
                ("hand_l", (x1 + bw * 0.25, y1 + 0.55 * bh), 0.4 * bh),
                ("hand_r", (x1 + bw * 0.75, y1 + 0.55 * bh), 0.4 * bh)]
    rois: List[Roi] = []
    for kind, (cx, cy), side in cand:
        if side < cfg.min_roi_px:
            continue
        box = _square(cx, cy, side, W, H)
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            continue
        rois.append(Roi(kind, (cx, cy), float(side), box))
    return rois
