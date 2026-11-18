"""Color/depth frame matcher (ROS-free, testable). Replaces message_filters.ApproximateTimeSynchronizer because that
one never fires when the depth stream is missing or dead; here the color frame is still processed (depth=None -> PROXY)
after `wait_s` of waiting, which is the intended behaviour when the structured-light depth is invalid (spec 6.2).

Only the newest processable color frame is returned; older ones are dropped (latest-only, spec 4.3)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, List, Optional


@dataclass
class Matched:
    color_stamp: float
    color: Any
    depth: Any = None           # payload or None
    depth_stamp: float = 0.0
    dt: Optional[float] = None  # depth_stamp - color_stamp when matched


class FrameMatcher:
    def __init__(self, slop_s: float, wait_s: float, max_color: int = 5, max_depth: int = 10, use_depth: bool = True):
        self.slop_s, self.wait_s, self.use_depth = float(slop_s), float(wait_s), bool(use_depth)
        self._colors: Deque[tuple] = deque(maxlen=max_color)   # (stamp, payload, arrival)
        self._depths: Deque[tuple] = deque(maxlen=max_depth)   # (stamp, payload)
        self.dropped = 0

    def push_color(self, stamp: float, payload: Any, arrival: float) -> None:
        if len(self._colors) == self._colors.maxlen:
            self.dropped += 1
        self._colors.append((stamp, payload, arrival))

    def push_depth(self, stamp: float, payload: Any) -> None:
        self._depths.append((stamp, payload))

    def _best_depth(self, stamp: float):
        best = None
        for ds, dp in self._depths:
            dt = ds - stamp
            if abs(dt) <= self.slop_s and (best is None or abs(dt) < abs(best[0])):
                best = (dt, ds, dp)
        return best

    def pop_ready(self, now: float) -> Optional[Matched]:
        if not self._colors:
            return None
        items: List[tuple] = list(self._colors)
        pick = None
        if self.use_depth:
            for i in range(len(items) - 1, -1, -1):          # newest first
                b = self._best_depth(items[i][0])
                if b is not None:
                    pick = (i, b)
                    break
        if pick is not None:
            i, (dt, ds, dp) = pick
            m = Matched(items[i][0], items[i][1], dp, ds, dt)
        else:
            i = len(items) - 1
            if self.use_depth and (now - items[i][2]) < self.wait_s:
                return None                                  # newest frame still waiting for its depth partner
            m = Matched(items[i][0], items[i][1])
        self.dropped += i                                    # older frames are skipped
        for _ in range(i + 1):
            self._colors.popleft()
        return m
