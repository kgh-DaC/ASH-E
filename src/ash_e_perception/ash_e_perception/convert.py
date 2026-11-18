"""core dataclass <-> ash_e_msgs message conversion (spec 3). Pure Python: no rclpy import, so it can be tested on
Windows with fake message classes (see test/fake_msgs.py). Message classes are passed in by the caller.

Field copy is driven by the core dataclass field list, so a field added to core and to the .msg is picked up
automatically and the 1:1 contract test (test_msg_contract.py) catches a mismatch."""
from __future__ import annotations

import dataclasses
from enum import IntEnum
from typing import Any, Type

import numpy as np

from ash_e_core.types import (Detection, DetectionArray, Point3, TargetCandidate, TargetStatus)

from .inputs import sec_to_stamp, stamp_to_sec


def _cast(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (IntEnum, int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v)
    return v


def _set_point(msg_pt, p: Point3) -> None:
    msg_pt.x, msg_pt.y, msg_pt.z = float(p.x), float(p.y), float(p.z)


def _get_point(msg_pt) -> Point3:
    return Point3(float(msg_pt.x), float(msg_pt.y), float(msg_pt.z))


def set_header(msg_header, stamp: float, frame_id: str) -> None:
    sec, nsec = sec_to_stamp(stamp)
    msg_header.stamp.sec = sec
    msg_header.stamp.nanosec = nsec
    msg_header.frame_id = frame_id


def get_header(msg_header):
    return stamp_to_sec(msg_header.stamp.sec, msg_header.stamp.nanosec), str(msg_header.frame_id)


# ---------------------------------------------------------------- core -> msg
def detection_to_msg(det: Detection, msg_cls: Type) -> Any:
    m = msg_cls()
    for f in dataclasses.fields(Detection):
        v = getattr(det, f.name)
        if f.name == "position":
            _set_point(m.position, v)
        else:
            setattr(m, f.name, _cast(v))
    return m


def array_to_msg(arr: DetectionArray, array_cls: Type, det_cls: Type) -> Any:
    m = array_cls()
    set_header(m.header, arr.stamp, arr.frame_id)
    m.frame_seq = int(arr.frame_seq)
    m.image_width = int(arr.image_width)
    m.image_height = int(arr.image_height)
    m.inference_ms = float(arr.inference_ms)
    m.detections = [detection_to_msg(d, det_cls) for d in arr.detections]
    return m


# ---------------------------------------------------------------- msg -> core
def detection_from_msg(m) -> Detection:
    kw = {}
    for f in dataclasses.fields(Detection):
        v = getattr(m, f.name)
        kw[f.name] = _get_point(v) if f.name == "position" else _cast(v)
    return Detection(**kw)


def array_from_msg(m) -> DetectionArray:
    stamp, frame_id = get_header(m.header)
    return DetectionArray(stamp=stamp, frame_id=frame_id, frame_seq=int(m.frame_seq),
                          image_width=int(m.image_width), image_height=int(m.image_height),
                          inference_ms=float(m.inference_ms),
                          detections=[detection_from_msg(d) for d in m.detections])


def candidate_from_msg(m) -> TargetCandidate:
    return TargetCandidate(**{f.name: _cast(getattr(m, f.name)) for f in dataclasses.fields(TargetCandidate)})


def target_status_from_msg(m) -> TargetStatus:
    """Used by tools/dump_jsonl. (msg -> core only; the priority node owns core -> msg for TargetStatus.)"""
    stamp, frame_id = get_header(m.header)
    kw = {"stamp": stamp, "frame_id": frame_id}
    for f in dataclasses.fields(TargetStatus):
        if f.name in ("stamp", "frame_id"):
            continue
        v = getattr(m, f.name)
        if f.name == "target_position":
            kw[f.name] = _get_point(v)
        elif f.name == "ranking":
            kw[f.name] = [candidate_from_msg(c) for c in v]
        else:
            kw[f.name] = _cast(v)
    return TargetStatus(**kw)
