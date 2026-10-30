"""Distance / 3D position. Stage A uses only the box-size proxy. The depth-median helper is kept for stage B."""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

from .roi import head_size, LSH, RSH
from .types import CameraIntrinsics, DistanceSource, PersonPose, Point3


def _finish(x: float, y: float, z: float, src: int) -> Tuple[Point3, float, int, float]:
    return Point3(float(x), float(y), float(z)), float(math.hypot(x, z)), int(src), float(-math.atan2(x, z))


def proxy_position(pose: PersonPose, intr: CameraIntrinsics, cfg, img_h: int):
    """(Point3, distance_m, DistanceSource.PROXY, bearing_rad). Constants are approximate (spec 5.4-7)."""
    x1, y1, x2, y2 = [float(v) for v in pose.bbox_xyxy]
    bh = max(y2 - y1, 1.0)
    kp, t = pose.keypoints, cfg.kp_conf_thresh
    m = cfg.edge_margin_px
    if y1 >= m and y2 <= img_h - 1 - m:
        z = intr.fy * cfg.person_height_m / bh
    elif kp[LSH, 2] >= t and kp[RSH, 2] >= t and abs(float(kp[LSH, 0] - kp[RSH, 0])) > 1:
        z = intr.fx * cfg.shoulder_width_m / abs(float(kp[LSH, 0] - kp[RSH, 0]))
    else:
        z = intr.fx * cfg.head_width_m / max(head_size(pose, t), 1.0)
    uc, vc = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    return _finish((uc - intr.cx) * z / intr.fx, (vc - intr.cy) * z / intr.fy, z, DistanceSource.PROXY)


def depth_median_position(pose: PersonPose, depth: np.ndarray, intr: CameraIntrinsics, cfg):
    """Torso-ROI median depth; None when too few valid pixels (caller falls back to proxy)."""
    kp, t = pose.keypoints, cfg.kp_conf_thresh
    x1, y1, x2, y2 = [float(v) for v in pose.bbox_xyxy]
    pts = [i for i in (5, 6, 11, 12) if kp[i, 2] >= t]
    if len(pts) >= 3:
        rx1, rx2 = float(kp[pts, 0].min()), float(kp[pts, 0].max())
        ry1, ry2 = float(kp[pts, 1].min()), float(kp[pts, 1].max())
    else:
        w, h = x2 - x1, y2 - y1
        rx1, rx2, ry1, ry2 = x1 + 0.3 * w, x1 + 0.7 * w, y1 + 0.2 * h, y1 + 0.6 * h
    sw, sh = (rx2 - rx1) * cfg.depth_roi_shrink, (ry2 - ry1) * cfg.depth_roi_shrink
    H, W = depth.shape[:2]
    ix1, ix2 = int(max(0, rx1 + sw)), int(min(W, rx2 - sw))
    iy1, iy2 = int(max(0, ry1 + sh)), int(min(H, ry2 - sh))
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    roi = depth[iy1:iy2, ix1:ix2].astype(np.float32)
    valid = np.isfinite(roi) & (roi >= cfg.depth_min_m) & (roi <= cfg.depth_max_m)
    nv = int(valid.sum())
    if nv < cfg.depth_min_valid_px or nv / roi.size < cfg.depth_min_valid_ratio:
        return None
    z = float(np.median(roi[valid]))
    uc, vc = (rx1 + rx2) / 2.0, (ry1 + ry2) / 2.0
    return _finish((uc - intr.cx) * z / intr.fx, (vc - intr.cy) * z / intr.fy, z, DistanceSource.DEPTH)
