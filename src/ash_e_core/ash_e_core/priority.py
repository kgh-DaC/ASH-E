"""Target priority selection (spec section 7). Pure Python, ROS-free, deterministic (time comes from the caller).

  sel = PrioritySelector(PriorityConfig())
  status = sel.update(det_array, now=det_array.stamp)   # every perception output
  status = sel.tick(now)                                # periodic; returns a status only on INPUT_TIMEOUT
  status = sel.on_feedback(TargetFeedback(...), now)    # hook for the (out-of-scope) nudge node
  sel.set_lock(True / False)

One evaluation -> at most one event (TargetStatus.last_event). After a release the next best eligible candidate is chosen
in the same evaluation; the new target is visible as a target_id change (no separate ACQUIRED event).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from .config import PriorityConfig
from .types import (Detection, DetectionArray, DistanceSource, FeedbackResult, Ineligible, Point3, PriorityMode,
                    SmokerState, TargetCandidate, TargetEvent, TargetFeedback, TargetStatus)

log = logging.getLogger(__name__)

WEIGHTS = ("w_state", "w_dist", "w_conf", "w_center", "w_stay")


def normalized_config(cfg: PriorityConfig) -> PriorityConfig:
    """Copy of cfg with weights summing to 1 (spec 7.2: normalise + warn)."""
    s = sum(getattr(cfg, w) for w in WEIGHTS)
    if s <= 0:
        raise ValueError("priority weights must sum to > 0")
    if abs(s - 1.0) > 1e-6:
        log.warning("priority weights sum to %.4f, normalising to 1.0", s)
        cfg = replace(cfg, **{w: getattr(cfg, w) / s for w in WEIGHTS})
    return cfg


def has_distance(d: Detection) -> bool:
    return d.distance_source != DistanceSource.NONE and d.distance_m >= 0.0


@dataclass
class _SpatialCooldown:
    position: Optional[Point3]  # None when the released target had no distance
    bearing_rad: float
    until: float


class PrioritySelector:
    def __init__(self, config: Optional[PriorityConfig] = None):
        self.cfg = normalized_config(config or PriorityConfig())
        self.mode = PriorityMode.IDLE
        self.target_id = 0
        self.locked = False
        self.previous_target_id = 0
        self._since = 0.0              # target acquired at
        self._last_seen = 0.0
        self._snap: Optional[Detection] = None  # last observation of the target
        self._snap_score = 0.0
        self._oor_since: Optional[float] = None
        self._none_since: Optional[float] = None
        self._challenger: Optional[Tuple[int, float]] = None  # (track_id, first time it beat the margin)
        self._cooldown: Dict[int, float] = {}
        self._spatial: List[_SpatialCooldown] = []
        self._last_input: Optional[float] = None
        self._last_dets: Optional[DetectionArray] = None

    # ------------------------------------------------------------------ scoring
    def score(self, d: Detection) -> TargetCandidate:
        c = self.cfg
        s_state = 1.0 if d.state == SmokerState.SMOKING else (c.holding_value if d.state == SmokerState.HOLDING else 0.0)
        if has_distance(d):
            if d.distance_m <= c.near_m:
                s_dist = 1.0
            elif d.distance_m >= c.far_m:
                s_dist = 0.0
            else:
                s_dist = 1.0 - (d.distance_m - c.near_m) / (c.far_m - c.near_m)
        else:
            s_dist = 0.0
        s_conf = min(max(float(d.state_confidence), 0.0), 1.0)
        half = math.radians(c.hfov_deg) / 2.0
        s_center = min(max(1.0 - abs(d.bearing_rad) / half, 0.0), 1.0)
        s_stay = min(max(d.stationary_s, 0.0) / c.stay_full_s, 1.0) if c.stay_full_s > 0 else 1.0
        total = c.w_state * s_state + c.w_dist * s_dist + c.w_conf * s_conf + c.w_center * s_center + c.w_stay * s_stay
        return TargetCandidate(track_id=d.track_id, state=int(d.state), score=float(total), s_state=s_state,
                               s_dist=s_dist, s_conf=s_conf, s_center=s_center, s_stay=s_stay,
                               distance_m=float(d.distance_m), bearing_rad=float(d.bearing_rad))

    def _cooldown_left(self, d: Detection, now: float) -> float:
        left = max(0.0, self._cooldown.get(d.track_id, 0.0) - now)
        if self.cfg.spatial_cooldown_enable:
            for sc in self._spatial:
                if sc.until <= now:
                    continue
                if sc.position is not None and has_distance(d):
                    near = math.hypot(d.position.x - sc.position.x, d.position.z - sc.position.z) \
                        <= self.cfg.spatial_cooldown_radius_m
                else:
                    near = abs(d.bearing_rad - sc.bearing_rad) <= math.radians(self.cfg.spatial_cooldown_bearing_deg)
                if near:
                    left = max(left, sc.until - now)
        return left

    def _rank(self, dets: List[Detection], now: float) -> List[TargetCandidate]:
        out = []
        for d in dets:
            cand = self.score(d)
            cd = self._cooldown_left(d, now)
            cand.cooldown_remaining_s = float(cd)
            if d.state == SmokerState.NONE:
                reason = Ineligible.NOT_CONFIRMED
            elif d.state_confidence < self.cfg.min_state_conf:
                reason = Ineligible.LOW_CONFIDENCE
            elif has_distance(d) and d.distance_m > self.cfg.acquire_range_m:
                reason = Ineligible.OUT_OF_RANGE
            elif cd > 0:
                reason = Ineligible.COOLDOWN
            else:
                reason = Ineligible.OK
            cand.eligible = reason == Ineligible.OK
            cand.ineligible_reason = int(reason)
            out.append(cand)
        out.sort(key=lambda c: (-c.score, c.distance_m if c.distance_m >= 0 else math.inf, c.track_id))
        return out

    # ------------------------------------------------------------------ state changes
    def _release(self, reason: TargetEvent, now: float, cooldown_s: float, spatial: bool) -> None:
        if cooldown_s > 0:
            self._cooldown[self.target_id] = max(self._cooldown.get(self.target_id, 0.0), now + cooldown_s)
            if spatial and self._snap is not None:
                pos = Point3(self._snap.position.x, self._snap.position.y, self._snap.position.z) \
                    if has_distance(self._snap) else None
                self._spatial.append(_SpatialCooldown(pos, self._snap.bearing_rad, now + cooldown_s))
        self.previous_target_id = self.target_id
        self.mode, self.target_id, self.locked = PriorityMode.IDLE, 0, False
        self._snap, self._snap_score = None, 0.0
        self._oor_since = self._none_since = None
        self._challenger = None

    def _acquire(self, d: Detection, cand: TargetCandidate, now: float) -> None:
        self.mode, self.target_id = PriorityMode.TRACKING, d.track_id
        self._since = self._last_seen = now
        self._snap, self._snap_score = d, cand.score
        self._oor_since = self._none_since = None
        self._challenger = None

    def _select(self, by_id: Dict[int, Detection], ranking: List[TargetCandidate], now: float) -> bool:
        for c in ranking:
            if c.eligible:
                self._acquire(by_id[c.track_id], c, now)
                return True
        return False

    def _feedback_cooldown(self, result: int) -> Tuple[float, bool]:
        c = self.cfg
        if result == FeedbackResult.DONE:
            return c.cooldown_done_s, True
        if result == FeedbackResult.REFUSED:
            return c.cooldown_refused_s, True
        return c.cooldown_aborted_s, False

    def _gc(self, now: float) -> None:
        self._cooldown = {k: v for k, v in self._cooldown.items() if v > now}
        self._spatial = [s for s in self._spatial if s.until > now]

    # ------------------------------------------------------------------ API
    def update(self, dets: DetectionArray, now: Optional[float] = None) -> TargetStatus:
        now = dets.stamp if now is None else now
        self._last_input, self._last_dets = now, dets
        self._gc(now)
        by_id = {d.track_id: d for d in dets.detections}
        event = TargetEvent.NONE
        c = self.cfg

        if self.mode == PriorityMode.TRACKING:
            d = by_id.get(self.target_id)
            if d is None:
                if now - self._last_seen >= c.lost_timeout_s:
                    event = TargetEvent.LOST_TIMEOUT
                    self._release(event, now, c.cooldown_lost_s, False)
            else:
                self._last_seen, self._snap, self._snap_score = now, d, self.score(d).score
                if has_distance(d) and d.distance_m > c.release_range_m:
                    self._oor_since = now if self._oor_since is None else self._oor_since
                else:
                    self._oor_since = None
                self._none_since = (now if self._none_since is None else self._none_since) \
                    if d.state == SmokerState.NONE else None
                if self._oor_since is not None and now - self._oor_since >= c.out_of_range_hold_s:
                    event = TargetEvent.OUT_OF_RANGE
                    self._release(event, now, c.cooldown_out_of_range_s, False)
                elif self._none_since is not None and now - self._none_since >= c.state_cleared_s:
                    event = TargetEvent.STATE_CLEARED
                    self._release(event, now, c.cooldown_state_cleared_s, False)

        ranking = self._rank(dets.detections, now)

        if self.mode == PriorityMode.IDLE:
            if self._select(by_id, ranking, now) and event == TargetEvent.NONE:
                event = TargetEvent.ACQUIRED
        elif self.target_id in by_id and not self.locked:
            cur = next(x.score for x in ranking if x.track_id == self.target_id)
            best = next((x for x in ranking if x.eligible and x.track_id != self.target_id), None)
            if best is not None and best.score >= cur + c.switch_margin:
                if self._challenger is None or self._challenger[0] != best.track_id:
                    self._challenger = (best.track_id, now)
                if now - self._challenger[1] >= c.switch_confirm_s and now - self._since >= c.min_hold_s:
                    self.previous_target_id = self.target_id
                    self._acquire(by_id[best.track_id], best, now)
                    event = TargetEvent.SWITCHED_BETTER
            else:
                self._challenger = None
        return self._status(now, dets.frame_id, event, ranking, visible=self.target_id in by_id)

    def tick(self, now: float) -> Optional[TargetStatus]:
        """Input watchdog. Returns a status only when it changes something (INPUT_TIMEOUT, no cooldown)."""
        if self._last_input is None or now - self._last_input < self.cfg.input_timeout_s:
            return None
        if self.mode != PriorityMode.TRACKING:
            return None
        self._release(TargetEvent.INPUT_TIMEOUT, now, 0.0, False)
        fid = self._last_dets.frame_id if self._last_dets else ""
        return self._status(now, fid, TargetEvent.INPUT_TIMEOUT, [], visible=False)

    def on_feedback(self, fb: TargetFeedback, now: float) -> Optional[TargetStatus]:
        """Nudge result for a track. Releases the target (FEEDBACK_RELEASED) and re-selects from the last input if it is
        still fresh. Feedback for another track only registers its cooldown."""
        cd, spatial = self._feedback_cooldown(fb.result)
        if self.mode != PriorityMode.TRACKING or fb.track_id != self.target_id:
            self._cooldown[fb.track_id] = max(self._cooldown.get(fb.track_id, 0.0), now + cd)
            return None
        self._release(TargetEvent.FEEDBACK_RELEASED, now, cd, spatial)
        ranking: List[TargetCandidate] = []
        fid = ""
        if self._last_dets is not None:
            fid = self._last_dets.frame_id
            if now - self._last_input < self.cfg.input_timeout_s:
                ranking = self._rank(self._last_dets.detections, now)
                self._select({d.track_id: d for d in self._last_dets.detections}, ranking, now)
        return self._status(now, fid, TargetEvent.FEEDBACK_RELEASED, ranking,
                            visible=self.mode == PriorityMode.TRACKING)

    def set_lock(self, locked: bool) -> None:
        """Nudge in progress: no switching to a better candidate. Releases (lost, out of range, ...) still happen and
        clear the lock."""
        self.locked = bool(locked) and self.mode == PriorityMode.TRACKING

    # ------------------------------------------------------------------ output
    def _status(self, now, frame_id, event, ranking, visible) -> TargetStatus:
        st = TargetStatus(stamp=now, frame_id=frame_id, mode=int(self.mode), locked=self.locked,
                          last_event=int(event), previous_target_id=self.previous_target_id, ranking=ranking)
        if self.mode == PriorityMode.TRACKING and self._snap is not None:
            s = self._snap
            st.has_target, st.target_id, st.target_visible = True, self.target_id, bool(visible)
            st.target_state, st.target_score = int(s.state), float(self._snap_score)
            st.target_position = Point3(s.position.x, s.position.y, s.position.z)
            st.target_distance_m, st.target_bearing_rad = float(s.distance_m), float(s.bearing_rad)
            st.distance_source = int(s.distance_source)
            st.tracking_duration_s = float(now - self._since)
        return st
