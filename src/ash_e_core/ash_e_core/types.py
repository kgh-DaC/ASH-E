"""Contract types (spec section 3). Field names/order/units mirror the ROS .msg files.
Header is split into stamp (float seconds) and frame_id (str)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List

import numpy as np


class SmokerState(IntEnum):
    NONE = 0
    HOLDING = 1
    SMOKING = 2


class DistanceSource(IntEnum):
    NONE = 0
    PROXY = 1
    DEPTH = 2


class PriorityMode(IntEnum):
    IDLE = 0
    TRACKING = 1


class TargetEvent(IntEnum):
    NONE = 0
    ACQUIRED = 1
    SWITCHED_BETTER = 2
    LOST_TIMEOUT = 3
    OUT_OF_RANGE = 4
    STATE_CLEARED = 5
    INPUT_TIMEOUT = 6
    FEEDBACK_RELEASED = 7


class Ineligible(IntEnum):
    OK = 0
    NOT_CONFIRMED = 1
    LOW_CONFIDENCE = 2
    OUT_OF_RANGE = 3
    COOLDOWN = 4


class FeedbackResult(IntEnum):
    DONE = 1
    REFUSED = 2
    ABORTED = 3
    UNREACHABLE = 4


@dataclass
class Point3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class Detection:
    track_id: int = 0
    state: int = SmokerState.NONE
    state_confidence: float = 0.0
    raw_state: int = SmokerState.NONE
    raw_confidence: float = 0.0
    cigarette_checked: bool = False
    person_confidence: float = 0.0
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_w: int = 0
    bbox_h: int = 0
    has_cigarette_box: bool = False
    cig_x: int = 0
    cig_y: int = 0
    cig_w: int = 0
    cig_h: int = 0
    position: Point3 = field(default_factory=Point3)
    distance_m: float = -1.0
    distance_source: int = DistanceSource.NONE
    bearing_rad: float = 0.0
    stationary_s: float = 0.0
    frames_observed: int = 0


@dataclass
class DetectionArray:
    stamp: float = 0.0
    frame_id: str = ""
    frame_seq: int = 0
    image_width: int = 0
    image_height: int = 0
    inference_ms: float = 0.0
    detections: List[Detection] = field(default_factory=list)


@dataclass
class TargetCandidate:
    track_id: int = 0
    state: int = 0
    score: float = 0.0
    s_state: float = 0.0
    s_dist: float = 0.0
    s_conf: float = 0.0
    s_center: float = 0.0
    s_stay: float = 0.0
    distance_m: float = -1.0
    bearing_rad: float = 0.0
    eligible: bool = False
    ineligible_reason: int = Ineligible.OK
    cooldown_remaining_s: float = 0.0


@dataclass
class TargetStatus:
    stamp: float = 0.0
    frame_id: str = ""
    mode: int = PriorityMode.IDLE
    has_target: bool = False
    target_id: int = 0
    target_visible: bool = False
    target_state: int = 0
    target_score: float = 0.0
    target_position: Point3 = field(default_factory=Point3)
    target_distance_m: float = -1.0
    target_bearing_rad: float = 0.0
    distance_source: int = DistanceSource.NONE
    tracking_duration_s: float = 0.0
    locked: bool = False
    last_event: int = TargetEvent.NONE
    previous_target_id: int = 0
    ranking: List[TargetCandidate] = field(default_factory=list)


@dataclass
class TargetFeedback:
    stamp: float = 0.0
    frame_id: str = ""
    track_id: int = 0
    result: int = FeedbackResult.DONE


# ---- core-internal types (no message) ----
@dataclass
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @staticmethod
    def from_hfov(width: int, height: int, hfov_deg: float) -> "CameraIntrinsics":
        f = (width / 2.0) / float(np.tan(np.radians(hfov_deg) / 2.0))
        return CameraIntrinsics(f, f, width / 2.0, height / 2.0, width, height)


@dataclass
class PersonPose:
    bbox_xyxy: np.ndarray  # (4,) float
    conf: float
    keypoints: np.ndarray  # (17,3) x,y,conf


@dataclass
class CigBox:
    xyxy: np.ndarray  # (4,) original image coords
    conf: float
