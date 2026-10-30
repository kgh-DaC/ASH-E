"""JSONL serialization (spec 3.8)."""
from __future__ import annotations

import dataclasses
import json
from enum import IntEnum
from typing import Optional

from .types import Detection, DetectionArray, Point3, TargetStatus


def _conv(o):
    if dataclasses.is_dataclass(o):
        return {f.name: _conv(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, IntEnum):
        return int(o)
    if isinstance(o, (list, tuple)):
        return [_conv(x) for x in o]
    if isinstance(o, bool):
        return o
    if isinstance(o, float):
        return round(o, 4)
    if hasattr(o, "item"):  # numpy scalar
        return _conv(o.item())
    return o


def to_dict(obj) -> dict:
    return _conv(obj)


def detections_from_dict(d: dict) -> DetectionArray:
    dets = []
    for x in d.get("detections", []):
        x = dict(x)
        x["position"] = Point3(**x["position"])
        dets.append(Detection(**x))
    d = dict(d)
    d["detections"] = dets
    return DetectionArray(**d)


def frame_to_jsonl(frame_seq: int, stamp: float, dets: DetectionArray,
                   target: Optional[TargetStatus] = None) -> str:
    rec = {"frame_seq": int(frame_seq), "stamp": round(float(stamp), 4),
           "detections": to_dict(dets), "target": to_dict(target) if target is not None else None}
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
