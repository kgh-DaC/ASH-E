"""Fake ROS message classes generated from the real .msg files (so the tests also check the .msg field names).
Assigning an attribute that the .msg does not define raises AttributeError (__slots__)."""
import os
import re

MSG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "ash_e_msgs", "msg")

_BUILTIN = {"bool": False, "uint8": 0, "uint16": 0, "uint32": 0, "int32": 0, "int64": 0, "uint64": 0,
            "float32": 0.0, "float64": 0.0, "string": ""}


class Time:
    __slots__ = ("sec", "nanosec")

    def __init__(self):
        self.sec, self.nanosec = 0, 0


class Header:
    __slots__ = ("stamp", "frame_id")

    def __init__(self):
        self.stamp, self.frame_id = Time(), ""


class Point:
    __slots__ = ("x", "y", "z")

    def __init__(self):
        self.x = self.y = self.z = 0.0


_CLASSES = {"std_msgs/Header": Header, "geometry_msgs/Point": Point}


def parse_msg(path):
    """-> (constants {name: int}, fields [(type, is_array, name)])"""
    consts, fields = {}, []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(\S+)\s+([A-Z][A-Z0-9_]*)\s*=\s*(\S+)$", line)
        if m:
            consts[m.group(2)] = int(m.group(3))
            continue
        t, n = line.split()[:2]
        arr = t.endswith("[]")
        fields.append((t[:-2] if arr else t, arr, n))
    return consts, fields


def get_class(name):
    """name e.g. 'SmokerDetection' or 'std_msgs/Header'."""
    if name in _CLASSES:
        return _CLASSES[name]
    consts, fields = parse_msg(os.path.join(MSG_DIR, name + ".msg"))
    names = [f[2] for f in fields]

    def init(self):
        for t, arr, n in fields:
            if arr:
                v = []
            elif t in _BUILTIN:
                v = _BUILTIN[t]
            else:
                v = get_class(t)()
            setattr(self, n, v)

    cls = type(name, (), {"__slots__": tuple(names), "__init__": init})
    _CLASSES[name] = cls
    return cls
