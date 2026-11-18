"""ROS-parameter <-> PriorityConfig helpers (pure Python). Parameter names are exactly the PriorityConfig fields."""
from __future__ import annotations

from dataclasses import fields
from typing import Dict, List

from ash_e_core.config import PriorityConfig

WEIGHTS = ("w_state", "w_dist", "w_conf", "w_center", "w_stay")

# wrapper-only parameters (not in PriorityConfig): name -> default
WRAPPER_DEFAULTS = {
    "tick_rate_hz": 10.0,           # watchdog timer (input timeout only)
    "time_jump_reset_s": 1.0,       # input stamp earlier than the previous one by more than this -> selector reset
    "marker_max_candidates": 5,     # ranking rows drawn in RViz
    "marker_lifetime_s": 1.0,
    "publish_markers": True,
}


def config_field_defaults() -> Dict[str, object]:
    return {f.name: getattr(PriorityConfig(), f.name) for f in fields(PriorityConfig)}


def coerce(name: str, value):
    """Coerce a parameter value to the PriorityConfig field type (yaml `1` for a float field etc.)."""
    cur = config_field_defaults()[name]
    if isinstance(cur, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    return type(cur)(value)


def config_from_values(values: Dict[str, object]) -> PriorityConfig:
    """Build a PriorityConfig from {name: value}; unknown names are ignored, bad values raise ValueError."""
    cfg = PriorityConfig()
    names = config_field_defaults()
    for k, v in values.items():
        if k in names:
            try:
                setattr(cfg, k, coerce(k, v))
            except (TypeError, ValueError) as e:
                raise ValueError("parameter %s=%r: %s" % (k, v, e))
    problems = validate(cfg)
    if problems:
        raise ValueError("; ".join(problems))
    return cfg


def validate(cfg: PriorityConfig) -> List[str]:
    """Reject values that would make the selector misbehave. Weights are NOT checked for sum 1 (core normalises)."""
    p: List[str] = []
    if sum(getattr(cfg, w) for w in WEIGHTS) <= 0 or any(getattr(cfg, w) < 0 for w in WEIGHTS):
        p.append("weights must be >= 0 with a positive sum")
    if not cfg.near_m < cfg.far_m:
        p.append("near_m must be < far_m")
    if cfg.release_range_m < cfg.acquire_range_m:
        p.append("release_range_m must be >= acquire_range_m (distance hysteresis)")
    if not 0.0 <= cfg.holding_value <= 1.0:
        p.append("holding_value must be in 0..1")
    if cfg.hfov_deg <= 0.0 or cfg.hfov_deg >= 180.0:
        p.append("hfov_deg must be in (0, 180)")
    if cfg.switch_margin < 0.0:
        p.append("switch_margin must be >= 0")
    for n in ("out_of_range_hold_s", "min_hold_s", "switch_confirm_s", "lost_timeout_s", "state_cleared_s",
              "input_timeout_s", "cooldown_lost_s", "cooldown_out_of_range_s", "cooldown_state_cleared_s",
              "cooldown_done_s", "cooldown_refused_s", "cooldown_aborted_s", "spatial_cooldown_radius_m",
              "spatial_cooldown_bearing_deg"):
        if getattr(cfg, n) < 0.0:
            p.append("%s must be >= 0" % n)
    if cfg.input_timeout_s <= 0.0:
        p.append("input_timeout_s must be > 0")
    if cfg.stay_full_s < 0.0:
        p.append("stay_full_s must be >= 0")
    return p
