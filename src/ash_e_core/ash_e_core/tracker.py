"""Greedy IoU tracker with center-distance second pass and stationary time (spec 5.4-2). Time = frame stamp."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence

import numpy as np

from .detector import iou_xyxy


@dataclass
class Track:
    track_id: int
    bbox: np.ndarray
    first_stamp: float
    last_stamp: float
    hits: int = 1
    stationary_s: float = 0.0
    speed_ema: float = -1.0
    frames_observed: int = 1
    last_checked_stamp: float = -1e9


class Tracker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tracks: Dict[int, Track] = {}
        self._next_id = 1

    def update(self, boxes: Sequence[np.ndarray], stamp: float) -> Dict[int, Track]:
        """Returns {detection_index: Track}. Unmatched detections start new tracks (ids from 1, monotonic)."""
        cfg = self.cfg
        for tid in [t for t, tr in self.tracks.items() if stamp - tr.last_stamp > cfg.track_max_age_s]:
            del self.tracks[tid]
        matched: Dict[int, Track] = {}
        used = set()
        pairs = []
        for di, b in enumerate(boxes):
            for tid, tr in self.tracks.items():
                v = iou_xyxy(b, tr.bbox)
                if v >= cfg.track_iou_thresh:
                    pairs.append((v, di, tid))
        for v, di, tid in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
            if di in matched or tid in used:
                continue
            matched[di] = self.tracks[tid]
            used.add(tid)
        for di, b in enumerate(boxes):  # second pass: center distance
            if di in matched:
                continue
            c = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
            best = None
            for tid, tr in self.tracks.items():
                if tid in used:
                    continue
                tc = np.array([(tr.bbox[0] + tr.bbox[2]) / 2, (tr.bbox[1] + tr.bbox[3]) / 2])
                d = float(np.linalg.norm(c - tc))
                if d <= 0.5 * float(tr.bbox[3] - tr.bbox[1]) and (best is None or d < best[0]):
                    best = (d, tid)
            if best is not None:
                matched[di] = self.tracks[best[1]]
                used.add(best[1])
        out: Dict[int, Track] = {}
        for di, b in enumerate(boxes):
            b = np.asarray(b, np.float32).copy()
            tr = matched.get(di)
            if tr is None:
                tr = Track(self._next_id, b, stamp, stamp)
                self._next_id += 1
                self.tracks[tr.track_id] = tr
            else:
                dt = max(stamp - tr.last_stamp, 1e-6)
                oc = np.array([(tr.bbox[0] + tr.bbox[2]) / 2, (tr.bbox[1] + tr.bbox[3]) / 2])
                nc = np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])
                v = float(np.linalg.norm(nc - oc)) / max(float(b[3] - b[1]), 1.0) / dt
                tr.speed_ema = v if tr.speed_ema < 0 else 0.5 * v + 0.5 * tr.speed_ema
                tr.stationary_s = tr.stationary_s + dt if tr.speed_ema < cfg.stationary_speed_thresh else 0.0
                tr.bbox = b
                tr.last_stamp = stamp
                tr.hits += 1
                tr.frames_observed += 1
            out[di] = tr
        return out
