"""Per-track temporal voting with hysteresis and smoking latch (spec 5.4-6). All times are frame stamps."""
from __future__ import annotations

from collections import deque
from typing import Deque, Tuple

from .types import SmokerState


class Stabilizer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.obs: Deque[Tuple[float, int, float]] = deque()  # (stamp, raw_state, raw_conf); checked frames only
        self.state = int(SmokerState.NONE)
        self._below_since = None
        self._latch_until = -1e18
        self.state_conf = 0.0

    def update(self, stamp: float, checked: bool, raw_state: int, raw_conf: float) -> Tuple[int, float]:
        c = self.cfg
        if checked:
            self.obs.append((stamp, int(raw_state), float(raw_conf)))
        while self.obs and stamp - self.obs[0][0] > c.stab_window_s:
            self.obs.popleft()
        n = len(self.obs)
        pos = [o for o in self.obs if o[1] != SmokerState.NONE]
        ratio = len(pos) / n if n else 0.0
        n_smoke = sum(1 for o in self.obs if o[1] == SmokerState.SMOKING)

        if self.state == SmokerState.NONE:
            if n >= c.stab_min_obs and ratio >= c.confirm_ratio:
                self.state = int(SmokerState.HOLDING)
                self._below_since = None
        elif n > 0 and ratio < c.release_ratio:
            if self._below_since is None:
                self._below_since = stamp
            elif stamp - self._below_since >= c.release_hold_s:
                self.state = int(SmokerState.NONE)
                self._latch_until = -1e18
                self._below_since = None
        else:
            self._below_since = None

        if self.state != SmokerState.NONE:
            if n_smoke >= c.smoking_min_obs:
                self._latch_until = stamp + c.smoking_latch_s
            self.state = int(SmokerState.SMOKING if stamp < self._latch_until else SmokerState.HOLDING)
        self.state_conf = (sum(o[2] for o in pos) / len(pos)) if (pos and self.state != SmokerState.NONE) else 0.0
        return self.state, float(self.state_conf)
