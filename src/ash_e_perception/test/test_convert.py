import dataclasses

import numpy as np
import pytest

from ash_e_core.serialize import to_dict
from ash_e_core.types import (Detection, DetectionArray, DistanceSource, Point3, SmokerState, TargetCandidate,
                              TargetStatus)
from ash_e_perception import convert
from perc_fake_msgs import get_class

Det = get_class("SmokerDetection")
Arr = get_class("SmokerDetectionArray")
TS = get_class("TargetStatus")
TC = get_class("TargetCandidate")


def sample():
    d1 = Detection(track_id=3, state=SmokerState.SMOKING, state_confidence=0.75, raw_state=SmokerState.HOLDING,
                   raw_confidence=0.5, cigarette_checked=True, person_confidence=0.875, bbox_x=10, bbox_y=20,
                   bbox_w=100, bbox_h=300, has_cigarette_box=True, cig_x=40, cig_y=50, cig_w=20, cig_h=5,
                   position=Point3(0.5, -0.25, 2.0), distance_m=2.0615, distance_source=DistanceSource.DEPTH,
                   bearing_rad=-0.245, stationary_s=3.5, frames_observed=77)
    d2 = Detection(track_id=4)
    return DetectionArray(stamp=1234.5678, frame_id="color_optical", frame_seq=9, image_width=1280,
                          image_height=720, inference_ms=88.25, detections=[d1, d2])


def test_array_roundtrip():
    arr = sample()
    m = convert.array_to_msg(arr, Arr, Det)
    assert m.header.frame_id == "color_optical" and m.header.stamp.sec == 1234
    assert 0 <= m.header.stamp.nanosec < 1_000_000_000
    assert isinstance(m.detections[0].state, int) and not isinstance(m.detections[0].state, SmokerState)
    back = convert.array_from_msg(m)
    assert back.stamp == pytest.approx(arr.stamp, abs=1e-6)
    a, b = to_dict(arr), to_dict(back)
    a.pop("stamp"), b.pop("stamp")
    assert a == b


def test_empty_array_and_numpy_scalars():
    arr = DetectionArray(stamp=0.0, frame_id="x")
    m = convert.array_to_msg(arr, Arr, Det)
    assert list(m.detections) == [] and m.header.stamp.sec == 0
    d = Detection(track_id=np.int64(2), bbox_x=np.int32(5), person_confidence=np.float32(0.5),
                  cigarette_checked=np.bool_(True))
    md = convert.detection_to_msg(d, Det)
    assert md.track_id == 2 and md.cigarette_checked is True and isinstance(md.bbox_x, int)


def test_every_core_field_is_copied():
    d = sample().detections[0]
    m = convert.detection_to_msg(d, Det)
    for f in dataclasses.fields(Detection):
        if f.name != "position":
            assert getattr(m, f.name) == getattr(d, f.name), f.name
    assert (m.position.x, m.position.y, m.position.z) == (0.5, -0.25, 2.0)


def test_stamp_carry():
    h = get_class("std_msgs/Header")()
    convert.set_header(h, 0.9999999999, "f")
    assert h.stamp.nanosec < 1_000_000_000
    assert h.stamp.sec + h.stamp.nanosec * 1e-9 == pytest.approx(1.0, abs=1e-8)


def test_target_status_from_msg():
    m = TS()
    m.header.stamp.sec, m.header.stamp.nanosec, m.header.frame_id = 5, 500_000_000, "f"
    m.mode, m.has_target, m.target_id, m.target_visible = 1, True, 3, True
    m.target_position.x, m.target_position.z = 0.25, 2.5
    m.last_event = 2
    c = TC()
    c.track_id, c.score, c.eligible, c.ineligible_reason = 3, 0.75, True, 0
    m.ranking = [c]
    st = convert.target_status_from_msg(m)
    assert isinstance(st, TargetStatus) and st.stamp == pytest.approx(5.5) and st.target_id == 3
    assert st.target_position == Point3(0.25, 0.0, 2.5) and st.ranking[0].score == 0.75
    assert isinstance(st.ranking[0], TargetCandidate) and st.last_event == 2
    to_dict(st)


def test_fake_msg_rejects_unknown_field():
    m = Det()
    with pytest.raises(AttributeError):
        m.not_a_field = 1
