"""Priority selector tests = spec 12.2 scenarios 1-13 (numbers in test names)."""
import logging
import math

import pytest

from ash_e_core.config import PriorityConfig
from ash_e_core.priority import PrioritySelector
from ash_e_core.types import (Detection, DetectionArray, DistanceSource, FeedbackResult, Ineligible, Point3,
                              PriorityMode, SmokerState, TargetEvent, TargetFeedback)

S, H, N = SmokerState.SMOKING, SmokerState.HOLDING, SmokerState.NONE


def det(tid, state=S, dist=2.0, conf=0.9, bearing=0.0, stay=0.0, src=DistanceSource.PROXY):
    x = -math.sin(bearing) * dist if dist >= 0 else 0.0
    z = math.cos(bearing) * dist if dist >= 0 else 0.0
    return Detection(track_id=tid, state=int(state), state_confidence=conf, position=Point3(x, 0.0, z),
                     distance_m=dist, distance_source=int(src if dist >= 0 else DistanceSource.NONE),
                     bearing_rad=bearing, stationary_s=stay)


def arr(t, *dets):
    return DetectionArray(stamp=t, frame_id="cam", detections=list(dets))


def run(sel, t0, t1, dt, make):
    """Feed make(t) -> list[Detection] from t0 to t1; returns list of statuses."""
    out, t = [], t0
    while t <= t1 + 1e-9:
        out.append(sel.update(arr(t, *make(t))))
        t = round(t + dt, 6)
    return out


def test_01_three_smokers_best_and_ranking_order():
    sel = PrioritySelector()
    st = sel.update(arr(0.0, det(1, dist=4.0), det(2, dist=1.0), det(3, H, dist=1.0)))
    assert st.last_event == TargetEvent.ACQUIRED and st.target_id == 2
    scores = [c.score for c in st.ranking]
    assert scores == sorted(scores, reverse=True)
    assert [c.track_id for c in st.ranking] == [2, 3, 1]


def test_01_tie_break_distance_then_id():
    sel = PrioritySelector(PriorityConfig(w_state=1, w_dist=0, w_conf=0, w_center=0, w_stay=0))
    st = sel.update(arr(0.0, det(5, dist=3.0), det(4, dist=3.0), det(3, dist=2.0)))
    assert [c.track_id for c in st.ranking] == [3, 4, 5]
    assert st.target_id == 3


def test_02_near_holding_beats_far_smoking():
    sel = PrioritySelector()
    near_h = sel.score(det(1, H, dist=1.5, conf=0.8))
    far_s = sel.score(det(2, S, dist=4.5, conf=0.8))
    # near holding: .35*.7 + .30*1 + .10*.8 + .10*1 = 0.725 ; far smoking: .35 + .30*(0.5/3.5) + .08 + .10 = 0.5729
    assert near_h.score == pytest.approx(0.725, abs=1e-6)
    assert far_s.score == pytest.approx(0.35 + 0.30 * (0.5 / 3.5) + 0.08 + 0.10, abs=1e-6)
    assert near_h.score > far_s.score
    # same distance: smoking wins by w_state * (1 - 0.7)
    assert sel.score(det(3, S, 2.0)).score - sel.score(det(4, H, 2.0)).score == pytest.approx(0.35 * 0.3)


def test_03_close_scores_no_switch_for_30s():
    sel = PrioritySelector()
    sts = run(sel, 0.0, 30.0, 0.1, lambda t: [det(1, dist=2.0), det(2, dist=2.0 - 0.3 * (int(t) % 2))])
    first = sts[0].target_id
    assert all(s.target_id == first for s in sts)
    assert not any(s.last_event == TargetEvent.SWITCHED_BETTER for s in sts)


def test_04_margin_short_no_switch_then_switch_after_confirm_and_hold():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, H, dist=4.0)))  # target 1, low score
    assert sel.target_id == 1
    # better candidate appears for 0.9 s only (after min_hold)
    sts = run(sel, 3.0, 3.9, 0.1, lambda t: [det(1, H, dist=4.0), det(2, S, dist=1.0)])
    sts += run(sel, 4.0, 4.5, 0.1, lambda t: [det(1, H, dist=4.0)])
    assert not any(s.last_event == TargetEvent.SWITCHED_BETTER for s in sts)
    # now it stays >= 1 s
    sts = run(sel, 5.0, 6.2, 0.1, lambda t: [det(1, H, dist=4.0), det(2, S, dist=1.0)])
    sw = [s for s in sts if s.last_event == TargetEvent.SWITCHED_BETTER]
    assert len(sw) == 1 and sw[0].target_id == 2 and sw[0].previous_target_id == 1
    assert sw[0].stamp == pytest.approx(6.0)


def test_04_no_switch_before_min_hold():
    sel = PrioritySelector()
    sts = run(sel, 0.0, 2.9, 0.1, lambda t: [det(1, H, dist=4.0)] + ([det(2, S, dist=1.0)] if t >= 0.1 else []))
    assert all(s.target_id == 1 for s in sts)
    st = sel.update(arr(3.0, det(1, H, dist=4.0), det(2, S, dist=1.0)))
    assert st.last_event == TargetEvent.SWITCHED_BETTER


def test_05_out_of_range_release_next_and_cooldown():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, dist=1.0), det(2, dist=3.0)))
    assert sel.target_id == 1
    sts = run(sel, 0.1, 1.2, 0.1, lambda t: [det(1, dist=6.0), det(2, dist=3.0)])
    ev = [s for s in sts if s.last_event == TargetEvent.OUT_OF_RANGE]
    assert len(ev) == 1 and ev[0].stamp == pytest.approx(1.1)
    assert ev[0].target_id == 2 and ev[0].previous_target_id == 1  # re-selected in the same evaluation
    c1 = next(c for c in ev[0].ranking if c.track_id == 1)
    assert not c1.eligible
    # back in range at 20 s: still cooling down (30 s), at 31.2 s eligible again
    st = sel.update(arr(20.0, det(1, dist=1.0), det(2, dist=3.0)))
    c1 = next(c for c in st.ranking if c.track_id == 1)
    assert c1.ineligible_reason == Ineligible.COOLDOWN and c1.cooldown_remaining_s == pytest.approx(11.1)
    st = sel.update(arr(31.2, det(1, dist=1.0), det(2, dist=3.0)))
    assert next(c for c in st.ranking if c.track_id == 1).eligible


def test_06_lost_timeout_and_reappear_before():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1), det(2, dist=4.0)))
    st = sel.update(arr(1.9, det(2, dist=4.0)))
    assert st.target_id == 1 and not st.target_visible and st.last_event == TargetEvent.NONE
    st = sel.update(arr(2.0, det(1), det(2, dist=4.0)))  # reappears: kept
    assert st.target_id == 1 and st.target_visible
    st = sel.update(arr(3.0, det(2, dist=4.0)))  # last seen 2.0
    st = sel.update(arr(3.9, det(2, dist=4.0)))
    assert st.target_id == 1
    st = sel.update(arr(4.0, det(2, dist=4.0)))
    assert st.last_event == TargetEvent.LOST_TIMEOUT and st.previous_target_id == 1 and st.target_id == 2


def test_06_no_switch_while_target_hidden():
    sel = PrioritySelector()
    run(sel, 0.0, 3.0, 0.1, lambda t: [det(1, H, dist=4.0)])
    sts = run(sel, 3.1, 4.9, 0.1, lambda t: [det(2, S, dist=1.0)])  # target hidden, better candidate visible
    assert all(s.target_id == 1 and not s.target_visible for s in sts)


def test_07_nobody_idle():
    sel = PrioritySelector()
    st = sel.update(arr(0.0))
    assert st.mode == PriorityMode.IDLE and not st.has_target and st.target_id == 0
    st = sel.update(arr(0.1, det(1, N)))
    assert not st.has_target and st.ranking[0].ineligible_reason == Ineligible.NOT_CONFIRMED


def test_08_input_timeout():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1)))
    assert sel.tick(0.9) is None
    st = sel.tick(1.0)
    assert st is not None and st.last_event == TargetEvent.INPUT_TIMEOUT and st.mode == PriorityMode.IDLE
    assert sel.tick(1.5) is None  # nothing changes any more
    st = sel.update(arr(2.0, det(1)))  # no cooldown after INPUT_TIMEOUT
    assert st.target_id == 1 and st.last_event == TargetEvent.ACQUIRED


def test_09_feedback_done_cooldown_and_spatial():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, dist=2.0, bearing=0.1), det(2, H, dist=4.0)))
    st = sel.on_feedback(TargetFeedback(track_id=1, result=FeedbackResult.DONE), 0.5)
    assert st.last_event == TargetEvent.FEEDBACK_RELEASED and st.previous_target_id == 1 and st.target_id == 2
    # new track ID at the same spot (re-identified person) -> blocked by the spatial cooldown
    st = sel.update(arr(1.0, det(7, dist=2.1, bearing=0.1), det(2, H, dist=4.0)))
    c7 = next(c for c in st.ranking if c.track_id == 7)
    assert c7.ineligible_reason == Ineligible.COOLDOWN and c7.cooldown_remaining_s == pytest.approx(599.5)
    # a new person 2 m away is not blocked
    st = sel.update(arr(1.1, det(8, dist=2.0, bearing=-0.9), det(2, H, dist=4.0)))
    assert next(c for c in st.ranking if c.track_id == 8).eligible


def test_09_feedback_aborted_no_spatial():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, dist=2.0)))
    sel.on_feedback(TargetFeedback(track_id=1, result=FeedbackResult.ABORTED), 0.1)
    st = sel.update(arr(0.2, det(9, dist=2.0)))
    assert st.target_id == 9


def test_10_lock_blocks_switch_but_not_lost():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, H, dist=4.0)))
    sel.set_lock(True)
    sts = run(sel, 3.0, 6.0, 0.1, lambda t: [det(1, H, dist=4.0), det(2, S, dist=1.0)])
    assert all(s.target_id == 1 and s.locked for s in sts)
    st = sel.update(arr(8.0, det(2, S, dist=1.0)))  # target 1 unseen since 6.0
    assert st.last_event == TargetEvent.LOST_TIMEOUT and st.target_id == 2 and not st.locked


def test_11_weights_normalised_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        sel = PrioritySelector(PriorityConfig(w_state=0.7, w_dist=0.6, w_conf=0.2, w_center=0.2, w_stay=0.3))
    assert "normalising" in caplog.text
    c = sel.cfg
    assert c.w_state + c.w_dist + c.w_conf + c.w_center + c.w_stay == pytest.approx(1.0)
    assert c.w_state == pytest.approx(0.35)
    assert 0.0 <= sel.score(det(1, dist=0.5, stay=99)).score <= 1.0 + 1e-9


def test_12_boundary_5_to_5_8_no_flicker():
    sel = PrioritySelector()
    st = sel.update(arr(0.0, det(1, dist=5.4)))
    assert not st.has_target and st.ranking[0].ineligible_reason == Ineligible.OUT_OF_RANGE
    st = sel.update(arr(0.1, det(1, dist=4.9)))
    assert st.target_id == 1
    sts = run(sel, 0.2, 20.0, 0.1, lambda t: [det(1, dist=5.0 + 0.7 * ((int(t * 10) % 4) / 3))])  # 5.0 .. 5.7
    assert all(s.target_id == 1 for s in sts) and all(s.last_event == TargetEvent.NONE for s in sts)


def test_13_depth_proxy_jumps_no_release():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1, dist=4.8, src=DistanceSource.DEPTH)))

    def jumpy(t):
        proxy = int(t / 0.5) % 2 == 1
        return [det(1, dist=6.0 if proxy else 4.8, src=DistanceSource.PROXY if proxy else DistanceSource.DEPTH)]

    sts = run(sel, 0.1, 30.0, 0.1, jumpy)
    assert all(s.target_id == 1 for s in sts)
    assert not any(s.last_event == TargetEvent.OUT_OF_RANGE for s in sts)


def test_state_cleared_after_5s():
    sel = PrioritySelector()
    sel.update(arr(0.0, det(1)))
    sts = run(sel, 0.1, 5.2, 0.1, lambda t: [det(1, N, conf=0.0)])
    ev = [s for s in sts if s.last_event == TargetEvent.STATE_CLEARED]
    assert len(ev) == 1 and ev[0].stamp == pytest.approx(5.1)


def test_no_distance_passes_range_with_zero_s_dist():
    sel = PrioritySelector()
    st = sel.update(arr(0.0, det(1, dist=-1.0)))
    assert st.target_id == 1 and st.ranking[0].s_dist == 0.0


def test_deterministic_replay():
    def play():
        sel = PrioritySelector()
        return [(s.target_id, s.last_event, round(s.target_score, 9)) for s in
                run(sel, 0.0, 15.0, 0.1, lambda t: [det(1, H, dist=3.0 + math.sin(t)), det(2, S, dist=4.5 - t / 5)])]
    assert play() == play()
