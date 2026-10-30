"""Detection overlay (BGR drawing with cv2; ASCII text only)."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .types import DetectionArray, SmokerState

COLORS = {SmokerState.NONE: (160, 160, 160), SmokerState.HOLDING: (0, 200, 255), SmokerState.SMOKING: (0, 0, 255)}
NAMES = {0: "none", 1: "holding", 2: "smoking"}


def draw_detections(img: np.ndarray, arr: DetectionArray, debug=None, show_rois: bool = True) -> np.ndarray:
    out = img
    if debug is not None:
        for pd in debug.persons:
            if show_rois:
                for r in pd.rois:
                    cv2.rectangle(out, r.xyxy[:2], r.xyxy[2:], (120, 120, 0), 1)
            kp = pd.pose.keypoints
            for i in range(11):
                if kp[i, 2] >= 0.3:
                    cv2.circle(out, (int(kp[i, 0]), int(kp[i, 1])), 3, (255, 200, 0), -1)
        for cb in debug.cig_boxes:
            x1, y1, x2, y2 = [int(v) for v in cb.xyxy]
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(out, "cig %.2f" % cb.conf, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    for d in arr.detections:
        col = COLORS.get(d.state, (255, 255, 255))
        p1, p2 = (d.bbox_x, d.bbox_y), (d.bbox_x + d.bbox_w, d.bbox_y + d.bbox_h)
        cv2.rectangle(out, p1, p2, col, 2)
        label = "#%d %s %.2f | raw:%s %.2f%s | %.1fm(%s)" % (
            d.track_id, NAMES.get(d.state, "?"), d.state_confidence, NAMES.get(d.raw_state, "?"), d.raw_confidence,
            "" if d.cigarette_checked else " (unchecked)", d.distance_m, "px" if d.distance_source == 1 else "d")
        cv2.putText(out, label, (p1[0], max(14, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
    return out
