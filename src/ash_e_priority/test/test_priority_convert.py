"""msg <-> core conversion with fake message objects (no ROS). Spec section 3."""
import dataclasses
import sys
from pathlib import Path

import pytest

import fake_msgs as fm
from ash_e_core.config import PriorityConfig
from ash_e_core.priority import PrioritySelector
from ash_e_core.types import (Detection, DetectionArray, DistanceSource, FeedbackResult, Point3, SmokerState,
                              TargetCandidate, TargetEvent, TargetFeedback, TargetStatus)
from ash_e_priority import convert
from ash_e_priority.markers import marker_specs

ROOT = Path(__file__).resolve().parents[3]


def sample_array(stamp=1731900000.123456):
    d1 = Detection(track_id=7, state=SmokerState.SMOKING, state_confidence=0.875, raw_state=SmokerState.SMOKING,
                   raw_confidence=0.5, cigarette_checked=True, person_confidence=0.75, bbox_x=10, bbox_y=20, bbox_w=30,
                   bbox_h=40, has_cigarette_box=True, cig_x=1, cig_y=2, cig_w=3, cig_h=4, position=Point3(0.25, -0.5, 2.0),
                   distance_m=2.0, distance_source=DistanceSource.DEPTH, bearing_rad=-0.125, stationary_s=4.5,
                   frames_observed=99)
    d2 = Detection(track_id=8, state=SmokerState.HOLDING)
    return DetectionArray(stamp=stamp, frame_id="cam_optical", frame_seq=12, image_width=1280, image_height=720,
                          inference_ms=33.5, detections=[d1, d2])


def test_stamp_parts_roundtrip():
    for t in (0.0, 1.5, 1731900000.123456, 12.999999999):
        sec, ns = convert.sec_to_stamp_parts(t)
        assert 0 <= ns < 10 ** 9
        s = fm.Stamp()
        s.sec, s.nanosec = sec, ns
        assert convert.stamp_to_sec(s) == pytest.approx(t, abs=1e-6)


def test_detections_roundtrip_core_msg_core():
    arr = sample_array()
    msg = convert.detections_to_msg(arr, fm.FACTORY)
    assert msg.header.frame_id == "cam_optical" and len(msg.detections) == 2
    back = convert.detections_from_msg(msg)
    assert back.stamp == pytest.approx(arr.stamp, abs=1e-6)
    back.stamp = arr.stamp
    assert back == arr
    # plain python types in the msg (rclpy setters assert them)
    d = msg.detections[0]
    assert type(d.state) is int and type(d.distance_m) is float and type(d.cigarette_checked) is bool
    assert type(d.distance_source) is int


def test_empty_array_roundtrip():
    arr = DetectionArray(stamp=3.0, frame_id="f")
    assert convert.detections_from_msg(convert.detections_to_msg(arr, fm.FACTORY)) == arr


def test_fake_msg_fields_match_core_dataclasses():
    """fake .msg (written from spec 3.2-3.6) vs core dataclass: names and order."""
    def names(cls, skip=()):
        return [f.name for f in dataclasses.fields(cls) if f.name not in skip]
    assert [k for k, _ in fm.DET_SCALARS] == names(Detection, {"position"})
    assert [k for k, _ in fm.CAND_SCALARS] == names(TargetCandidate)
    assert [k for k, _ in fm.STATUS_SCALARS] == names(TargetStatus, {"stamp", "frame_id", "target_position", "ranking"})
    assert ["track_id", "result"] == names(TargetFeedback, {"stamp", "frame_id"})
    assert ["frame_seq", "image_width", "image_height", "inference_ms"] == names(
        DetectionArray, {"stamp", "frame_id", "detections"})


@pytest.mark.skipif(not fm.MSG_DIR.is_dir(), reason="src/ash_e_msgs not present yet")
def test_real_msg_files_match_core():
    def scalar_names(fn, skip=()):
        return [n for t, n in fm.parse_msg_fields(fm.MSG_DIR / fn) if n not in skip and t != "std_msgs/Header"]
    assert scalar_names("SmokerDetection.msg", {"position"}) == [f.name for f in dataclasses.fields(Detection)
                                                                  if f.name != "position"]
    assert scalar_names("TargetCandidate.msg") == [f.name for f in dataclasses.fields(TargetCandidate)]
    assert scalar_names("TargetStatus.msg", {"target_position", "ranking"}) == [
        f.name for f in dataclasses.fields(TargetStatus) if f.name not in ("stamp", "frame_id", "target_position", "ranking")]
    assert scalar_names("TargetFeedback.msg") == ["track_id", "result"]
    assert scalar_names("SmokerDetectionArray.msg", {"detections"}) == [
        "frame_seq", "image_width", "image_height", "inference_ms"]


def test_enum_constants_match_spec_msg_constants():
    assert (SmokerState.NONE, SmokerState.HOLDING, SmokerState.SMOKING) == (0, 1, 2)
    assert (DistanceSource.NONE, DistanceSource.PROXY, DistanceSource.DEPTH) == (0, 1, 2)
    assert [int(e) for e in TargetEvent] == list(range(8))
    assert [int(e) for e in FeedbackResult] == [1, 2, 3, 4]


def _status_with_target():
    sel = PrioritySelector(PriorityConfig())
    arr = sample_array(stamp=100.0)
    return sel.update(arr, now=arr.stamp), arr


def test_target_status_to_msg_fields():
    st, arr = _status_with_target()
    assert st.has_target and st.target_id == 7 and len(st.ranking) == 2
    msg = convert.target_status_to_msg(st, fm.FACTORY)
    assert convert.stamp_to_sec(msg.header.stamp) == pytest.approx(100.0)
    assert msg.header.frame_id == "cam_optical"
    for k, _ in fm.STATUS_SCALARS:
        assert getattr(msg, k) == pytest.approx(float(getattr(st, k))), k
        assert not isinstance(getattr(msg, k), (TargetEvent, DistanceSource))
    assert (msg.target_position.x, msg.target_position.y, msg.target_position.z) == (0.25, -0.5, 2.0)
    assert len(msg.ranking) == 2
    for c, mc in zip(st.ranking, msg.ranking):
        for k, _ in fm.CAND_SCALARS:
            assert getattr(mc, k) == pytest.approx(float(getattr(c, k))), k
    scores = [c.score for c in msg.ranking]
    assert scores == sorted(scores, reverse=True)


def test_target_point_only_with_target():
    st, _ = _status_with_target()
    p = convert.target_point_to_msg(st, fm.FACTORY)
    assert p.header.frame_id == "cam_optical" and (p.point.x, p.point.z) == (0.25, 2.0)
    assert convert.target_point_to_msg(TargetStatus(), fm.FACTORY) is None


def test_feedback_from_msg():
    m = fm.TargetFeedback()
    m.header.stamp.sec, m.header.stamp.nanosec = 50, 500_000_000
    m.header.frame_id, m.track_id, m.result = "x", 7, 2
    fb = convert.feedback_from_msg(m)
    assert fb == TargetFeedback(stamp=50.5, frame_id="x", track_id=7, result=2)
    assert isinstance(fb.result, int)


def test_watchdog_now_stamp_domain():
    assert convert.watchdog_now(100.0, 5000.0, 5000.4) == pytest.approx(100.4)
    assert convert.watchdog_now(100.0, 5000.0, 4990.0) == 100.0  # clock jumped back: zero elapsed


def test_watchdog_triggers_input_timeout_via_core():
    """Camera stamps in another clock domain than the node clock: tick still fires after input_timeout_s."""
    sel = PrioritySelector(PriorityConfig())
    arr = sample_array(stamp=12.0)
    assert sel.update(arr, now=arr.stamp).has_target
    recv = 98765.0  # node clock at receipt
    assert sel.tick(convert.watchdog_now(arr.stamp, recv, recv + 0.5)) is None
    st = sel.tick(convert.watchdog_now(arr.stamp, recv, recv + 1.1))
    assert st is not None and st.last_event == TargetEvent.INPUT_TIMEOUT and not st.has_target


def test_marker_specs():
    st, _ = _status_with_target()
    specs = marker_specs(st, max_candidates=5)
    assert specs[0]["kind"] == "delete_all"
    assert [s["kind"] for s in specs].count("sphere") == 1
    legend = [s for s in specs if s.get("ns") == "ranking"][0]["text"]
    assert legend.splitlines()[0].startswith("TARGET #7") and ">#7" in legend
    assert marker_specs(TargetStatus(), 5)[-1]["text"].startswith("IDLE")
    one = [x for x in marker_specs(st, max_candidates=1) if x.get("ns") == "ranking"][0]["text"]
    assert len(one.splitlines()) == 2 and len(legend.splitlines()) == 3  # head + rows


@pytest.mark.skipif(not (ROOT / "prototype" / "sim_priority.py").is_file(), reason="prototype not present")
@pytest.mark.parametrize("name", ["s5_mixed", "target_departs_oor", "target_dropout_reappear"])
def test_wrapper_path_equals_direct_selector(name):
    """core -> msg -> core (fake publisher -> node) must not change the selector's output."""
    sys.path.insert(0, str(ROOT / "prototype"))
    import sim_priority as sim
    sc = sim.load_scenarios()[name]
    direct, via = PrioritySelector(PriorityConfig()), PrioritySelector(PriorityConfig())
    n = 0
    for arr in sim.scenario_frames(sc):
        a = direct.update(arr, now=arr.stamp)
        arr2 = convert.detections_from_msg(convert.detections_to_msg(arr, fm.FACTORY))
        b = via.update(arr2, now=arr2.stamp)
        assert (a.has_target, a.target_id, a.last_event) == (b.has_target, b.target_id, b.last_event), (name, arr.stamp)
        n += 1
    assert n > 100
