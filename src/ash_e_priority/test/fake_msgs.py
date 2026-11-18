"""Fake ROS message classes written from spec 3.2-3.6 (field names/order), independent of ash_e_core, plus a loader that
compares them with src/ash_e_msgs/msg/*.msg when that package exists."""
from pathlib import Path
from types import SimpleNamespace

Z = lambda: 0


class Stamp:
    def __init__(self):
        self.sec, self.nanosec = 0, 0


class Header:
    def __init__(self):
        self.stamp, self.frame_id = Stamp(), ""


class Point:
    def __init__(self):
        self.x = self.y = self.z = 0.0


class PointStamped:
    def __init__(self):
        self.header, self.point = Header(), Point()


def _cls(name, scalars, nested=(), header=False, lists=()):
    def init(self):
        if header:
            self.header = Header()
        for k, v in scalars:
            setattr(self, k, v)
        for k, c in nested:
            setattr(self, k, c())
        for k in lists:
            setattr(self, k, [])
    return type(name, (), {"__init__": init, "_scalars": [k for k, _ in scalars]})


# spec 3.2
DET_SCALARS = [("track_id", 0), ("state", 0), ("state_confidence", 0.0), ("raw_state", 0), ("raw_confidence", 0.0),
               ("cigarette_checked", False), ("person_confidence", 0.0), ("bbox_x", 0), ("bbox_y", 0), ("bbox_w", 0),
               ("bbox_h", 0), ("has_cigarette_box", False), ("cig_x", 0), ("cig_y", 0), ("cig_w", 0), ("cig_h", 0),
               ("distance_m", -1.0), ("distance_source", 0), ("bearing_rad", 0.0), ("stationary_s", 0.0),
               ("frames_observed", 0)]
SmokerDetection = _cls("SmokerDetection", DET_SCALARS, nested=[("position", Point)])
# spec 3.3
SmokerDetectionArray = _cls("SmokerDetectionArray", [("frame_seq", 0), ("image_width", 0), ("image_height", 0),
                                                     ("inference_ms", 0.0)], header=True, lists=["detections"])
# spec 3.4
CAND_SCALARS = [("track_id", 0), ("state", 0), ("score", 0.0), ("s_state", 0.0), ("s_dist", 0.0), ("s_conf", 0.0),
                ("s_center", 0.0), ("s_stay", 0.0), ("distance_m", 0.0), ("bearing_rad", 0.0), ("eligible", False),
                ("ineligible_reason", 0), ("cooldown_remaining_s", 0.0)]
TargetCandidate = _cls("TargetCandidate", CAND_SCALARS)
# spec 3.5
STATUS_SCALARS = [("mode", 0), ("has_target", False), ("target_id", 0), ("target_visible", False), ("target_state", 0),
                  ("target_score", 0.0), ("target_distance_m", 0.0), ("target_bearing_rad", 0.0),
                  ("distance_source", 0), ("tracking_duration_s", 0.0), ("locked", False), ("last_event", 0),
                  ("previous_target_id", 0)]
TargetStatus = _cls("TargetStatus", STATUS_SCALARS, nested=[("target_position", Point)], header=True, lists=["ranking"])
# spec 3.6
TargetFeedback = _cls("TargetFeedback", [("track_id", 0), ("result", 0)], header=True)

FACTORY = SimpleNamespace(Point=Point, PointStamped=PointStamped, SmokerDetection=SmokerDetection,
                          SmokerDetectionArray=SmokerDetectionArray, TargetCandidate=TargetCandidate,
                          TargetStatus=TargetStatus)

MSG_DIR = Path(__file__).resolve().parents[2] / "ash_e_msgs" / "msg"


def parse_msg_fields(path):
    """[(type, name)] of a .msg file, constants skipped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or "=" in line:
            continue
        t, n = line.split()[:2]
        out.append((t, n))
    return out
