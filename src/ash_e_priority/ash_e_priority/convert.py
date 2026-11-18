"""ROS msg <-> ash_e_core type conversion (spec section 3). Pure Python: no rclpy / ash_e_msgs import.

Messages are duck-typed (attribute access), so the Windows pytest can use fake message objects. Functions that must
create messages take a `factory` object with callables `Point`, `PointStamped`, `SmokerDetection`,
`SmokerDetectionArray`, `TargetCandidate`, `TargetStatus` (the node passes the real classes).
Field copying is driven by the core dataclass fields, so a renamed/added core field is picked up (and a missing msg
field fails loudly in the round-trip test instead of being silently dropped).
"""
from __future__ import annotations

import math
from dataclasses import MISSING, fields
from typing import Iterable, List, Optional, Tuple

from ash_e_core.types import (Detection, DetectionArray, Point3, TargetCandidate, TargetFeedback, TargetStatus)

_HEADER_ONLY = {"stamp", "frame_id"}


# ------------------------------------------------------------------ time
def stamp_to_sec(stamp) -> float:
    """builtin_interfaces/Time -> float seconds."""
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


def sec_to_stamp_parts(t: float) -> Tuple[int, int]:
    sec = int(math.floor(t))
    ns = int(round((t - sec) * 1e9))
    if ns >= 1_000_000_000:
        sec, ns = sec + 1, ns - 1_000_000_000
    return sec, ns


def set_header(header, stamp_s: float, frame_id: str) -> None:
    header.stamp.sec, header.stamp.nanosec = sec_to_stamp_parts(float(stamp_s))
    header.frame_id = str(frame_id)


def watchdog_now(last_stamp: float, recv_clock_s: float, clock_now_s: float) -> float:
    """`now` for PrioritySelector.tick in the *stamp* time domain: last input stamp + node-clock time elapsed since it
    arrived. Keeps tick consistent with update(now=stamp) whatever clock the camera driver stamps with (and with
    use_sim_time). A clock that jumped backwards counts as zero elapsed."""
    return float(last_stamp) + max(0.0, float(clock_now_s) - float(recv_clock_s))


# ------------------------------------------------------------------ generic scalar copy
def _cast(default, value):
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):  # IntEnum defaults too
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def _default_of(f):
    if f.default is not MISSING:
        return f.default
    return f.default_factory()


def _read_scalars(obj, cls, skip: Iterable[str]):
    """Return {name: cast value} for the plain fields of dataclass `cls` read from msg `obj`."""
    out = {}
    for f in fields(cls):
        if f.name in skip:
            continue
        out[f.name] = _cast(_default_of(f), getattr(obj, f.name))
    return out


def _write_scalars(msg, obj, skip: Iterable[str]) -> None:
    for f in fields(type(obj)):
        if f.name in skip:
            continue
        setattr(msg, f.name, _cast(_default_of(f), getattr(obj, f.name)))


# ------------------------------------------------------------------ msg -> core
def point_from_msg(p) -> Point3:
    return Point3(float(p.x), float(p.y), float(p.z))


def set_point(msg_point, p: Point3) -> None:
    msg_point.x, msg_point.y, msg_point.z = float(p.x), float(p.y), float(p.z)


def detection_from_msg(m) -> Detection:
    d = Detection(**_read_scalars(m, Detection, {"position"}))
    d.position = point_from_msg(m.position)
    return d


def detections_from_msg(msg) -> DetectionArray:
    """SmokerDetectionArray -> core DetectionArray (stamp in seconds)."""
    arr = DetectionArray(**_read_scalars(msg, DetectionArray, _HEADER_ONLY | {"detections"}))
    arr.stamp = stamp_to_sec(msg.header.stamp)
    arr.frame_id = str(msg.header.frame_id)
    arr.detections = [detection_from_msg(m) for m in msg.detections]
    return arr


def feedback_from_msg(msg) -> TargetFeedback:
    fb = TargetFeedback(**_read_scalars(msg, TargetFeedback, _HEADER_ONLY))
    fb.stamp = stamp_to_sec(msg.header.stamp)
    fb.frame_id = str(msg.header.frame_id)
    return fb


# ------------------------------------------------------------------ core -> msg
def detection_to_msg(d: Detection, factory):
    m = factory.SmokerDetection()
    _write_scalars(m, d, {"position"})
    set_point(m.position, d.position)
    return m


def detections_to_msg(arr: DetectionArray, factory):
    msg = factory.SmokerDetectionArray()
    set_header(msg.header, arr.stamp, arr.frame_id)
    _write_scalars(msg, arr, _HEADER_ONLY | {"detections"})
    msg.detections = [detection_to_msg(d, factory) for d in arr.detections]
    return msg


def candidate_to_msg(c: TargetCandidate, factory):
    m = factory.TargetCandidate()
    _write_scalars(m, c, set())
    return m


def target_status_to_msg(st: TargetStatus, factory):
    msg = factory.TargetStatus()
    set_header(msg.header, st.stamp, st.frame_id)
    _write_scalars(msg, st, _HEADER_ONLY | {"target_position", "ranking"})
    set_point(msg.target_position, st.target_position)
    msg.ranking = [candidate_to_msg(c, factory) for c in st.ranking]
    return msg


def target_point_to_msg(st: TargetStatus, factory):
    """PointStamped for /ash_e/target_point, or None when there is no target."""
    if not st.has_target:
        return None
    msg = factory.PointStamped()
    set_header(msg.header, st.stamp, st.frame_id)
    set_point(msg.point, st.target_position)
    return msg


# ------------------------------------------------------------------ debug helpers
def bearing_distance_to_xyz(distance_m: float, bearing_rad: float) -> Optional[Tuple[float, float, float]]:
    """Optical-frame (x right, y down, z forward) point from distance and REP-103 bearing (left +): x = -sin(b)*d."""
    if distance_m is None or distance_m < 0.0:
        return None
    return (-math.sin(bearing_rad) * distance_m, 0.0, math.cos(bearing_rad) * distance_m)
