"""Config dataclasses; field names == yaml keys (flat)."""
from __future__ import annotations

from dataclasses import dataclass, fields, asdict
from typing import Optional

import yaml


@dataclass
class PerceptionConfig:
    pose_model_path: str = "models/pose.onnx"
    cig_model_path: str = "models/cig_roi_v3.onnx"
    backend: str = "onnxruntime"
    num_threads: int = 4
    pose_input: int = 320
    roi_input: int = 192
    person_conf_thresh: float = 0.40
    min_person_h_px: int = 60
    max_persons: int = 8
    max_roi_persons: int = 4
    roi_every_n: int = 1
    kp_conf_thresh: float = 0.30
    mouth_roi_scale: float = 1.6
    hand_roi_scale: float = 1.4
    min_roi_px: int = 24
    cig_conf_thresh: float = 0.35
    smoking_radius: float = 0.7
    holding_radius: float = 0.9
    track_iou_thresh: float = 0.3
    track_max_age_s: float = 1.0
    stationary_speed_thresh: float = 0.25
    stab_window_s: float = 1.5
    stab_min_obs: int = 4
    confirm_ratio: float = 0.6
    release_ratio: float = 0.25
    release_hold_s: float = 1.0
    smoking_min_obs: int = 2
    smoking_latch_s: float = 20.0
    person_height_m: float = 1.65
    shoulder_width_m: float = 0.40
    head_width_m: float = 0.15
    edge_margin_px: int = 8
    hfov_deg: float = 70.0
    depth_min_m: float = 0.6
    depth_max_m: float = 6.0
    depth_min_valid_px: int = 30
    depth_min_valid_ratio: float = 0.15
    depth_roi_shrink: float = 0.1
    depth_align_decimate: int = 2
    process_rate_hz: float = 8.0
    frame_id: str = "webcam_optical"


@dataclass
class PriorityConfig:
    """Field list per spec section 8. Logic lives in priority.py (priority-dev, not in this scope)."""
    w_state: float = 0.35
    w_dist: float = 0.30
    w_conf: float = 0.10
    w_center: float = 0.10
    w_stay: float = 0.15
    holding_value: float = 0.7
    near_m: float = 1.5
    far_m: float = 5.0
    acquire_range_m: float = 5.0
    release_range_m: float = 5.8
    out_of_range_hold_s: float = 1.0
    min_state_conf: float = 0.40
    hfov_deg: float = 70.0
    stay_full_s: float = 10.0
    switch_margin: float = 0.15
    min_hold_s: float = 3.0
    switch_confirm_s: float = 1.0
    lost_timeout_s: float = 2.0
    state_cleared_s: float = 5.0
    input_timeout_s: float = 1.0
    cooldown_lost_s: float = 10.0
    cooldown_out_of_range_s: float = 30.0
    cooldown_state_cleared_s: float = 30.0
    cooldown_done_s: float = 600.0
    cooldown_refused_s: float = 300.0
    cooldown_aborted_s: float = 60.0
    spatial_cooldown_enable: bool = True
    spatial_cooldown_radius_m: float = 1.0
    spatial_cooldown_bearing_deg: float = 5.0


def _load(cls, path: Optional[str]):
    cfg = cls()
    if path:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for v in list(raw.values()):  # tolerate ROS-style nesting
            if isinstance(v, dict) and "ros__parameters" in v:
                raw = v["ros__parameters"]
                break
        names = {f.name for f in fields(cls)}
        for k, v in raw.items():
            if k in names:
                cur = getattr(cfg, k)
                setattr(cfg, k, bool(v) if isinstance(cur, bool) else type(cur)(v))
    return cfg


def load_perception_config(path: Optional[str] = None) -> PerceptionConfig:
    return _load(PerceptionConfig, path)


def load_priority_config(path: Optional[str] = None) -> PriorityConfig:
    return _load(PriorityConfig, path)


def config_to_dict(cfg) -> dict:
    return asdict(cfg)
