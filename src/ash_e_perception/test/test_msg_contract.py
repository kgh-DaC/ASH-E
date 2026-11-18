"""ash_e_msgs/*.msg vs ash_e_core types (spec 3): field names, order, base types, constant values."""
import dataclasses
import os

import pytest

from ash_e_core import types as T
from perc_fake_msgs import MSG_DIR, parse_msg

PAIRS = [("SmokerDetection", T.Detection), ("TargetCandidate", T.TargetCandidate),
         ("SmokerDetectionArray", T.DetectionArray), ("TargetStatus", T.TargetStatus),
         ("TargetFeedback", T.TargetFeedback)]
HEADER_FIELDS = {"stamp", "frame_id"}


def msg(name):
    return parse_msg(os.path.join(MSG_DIR, name + ".msg"))


@pytest.mark.parametrize("name,cls", PAIRS)
def test_field_names_and_order(name, cls):
    _, fields = msg(name)
    msg_names = [n for _, _, n in fields]
    core = [f.name for f in dataclasses.fields(cls)]
    if msg_names[0] == "header":
        core = [n for n in core if n not in HEADER_FIELDS]     # core splits the header into stamp + frame_id
        msg_names = msg_names[1:]
        assert [f.name for f in dataclasses.fields(cls)][:2] == ["stamp", "frame_id"]
    assert msg_names == core


def test_base_types():
    _, f = msg("SmokerDetection")
    types = {n: t for t, _, n in f}
    assert types["track_id"] == "uint32" and types["bbox_x"] == "int32" and types["position"] == "geometry_msgs/Point"
    assert types["distance_m"] == "float32" and types["cigarette_checked"] == "bool"
    assert types["frames_observed"] == "uint32" and types["state"] == "uint8"
    _, a = msg("SmokerDetectionArray")
    assert [(t, arr) for t, arr, n in a if n == "detections"] == [("SmokerDetection", True)]
    _, s = msg("TargetStatus")
    assert [(t, arr) for t, arr, n in s if n == "ranking"] == [("TargetCandidate", True)]


def test_enum_constants_match_core():
    c, _ = msg("SmokerDetection")
    for e in T.SmokerState:
        assert c["STATE_" + e.name] == int(e)
    for e in T.DistanceSource:
        assert c["DIST_SRC_" + e.name] == int(e)
    s, _ = msg("TargetStatus")
    for e in T.PriorityMode:
        assert s["MODE_" + e.name] == int(e)
    for e in T.TargetEvent:
        assert s["EVENT_" + e.name] == int(e)
    fb, _ = msg("TargetFeedback")
    for e in T.FeedbackResult:
        assert fb["RESULT_" + e.name] == int(e)


def test_msg_files_registered_in_cmake():
    cm = open(os.path.join(os.path.dirname(MSG_DIR), "CMakeLists.txt"), encoding="utf-8").read()
    for n, _ in PAIRS:
        assert '"msg/%s.msg"' % n in cm
