"""ROS-parameter helpers and the shipped yaml (no ROS)."""
import dataclasses
from pathlib import Path

import pytest
import yaml

from ash_e_core.config import PriorityConfig, load_priority_config
from ash_e_priority import params

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parents[1]


def _yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["/**"]["ros__parameters"]


def test_shipped_yaml_has_every_core_key_with_default_value():
    raw = _yaml(PKG / "config" / "priority.yaml")
    core = {f.name: getattr(PriorityConfig(), f.name) for f in dataclasses.fields(PriorityConfig)}
    assert set(core) <= set(raw), set(core) - set(raw)
    assert set(raw) - set(core) == set(params.WRAPPER_DEFAULTS)
    for k, v in core.items():
        assert raw[k] == v, k
    for k, v in params.WRAPPER_DEFAULTS.items():
        assert raw[k] == v


def test_package_yaml_equals_prototype_yaml_values():
    proto = yaml.safe_load((ROOT / "prototype" / "config" / "priority.yaml").read_text(encoding="utf-8"))
    raw = _yaml(PKG / "config" / "priority.yaml")
    assert {k: raw[k] for k in proto} == proto


def test_core_loader_reads_ros_style_yaml():
    assert load_priority_config(str(PKG / "config" / "priority.yaml")) == PriorityConfig()


def test_coercion_int_for_float_and_strings():
    cfg = params.config_from_values({"w_state": 1, "switch_margin": "0.3", "spatial_cooldown_enable": "false",
                                     "unknown_key": 5})
    assert isinstance(cfg.w_state, float) and cfg.switch_margin == 0.3 and cfg.spatial_cooldown_enable is False


@pytest.mark.parametrize("bad", [{"near_m": 6.0}, {"release_range_m": 4.0}, {"input_timeout_s": 0.0},
                                 {"holding_value": 1.5}, {"min_hold_s": -1}, {"hfov_deg": 0},
                                 {"w_state": 0, "w_dist": 0, "w_conf": 0, "w_center": 0, "w_stay": 0},
                                 {"far_m": "abc"}])
def test_invalid_values_rejected(bad):
    with pytest.raises(ValueError):
        params.config_from_values(bad)


def test_weights_not_summing_to_one_are_allowed():
    assert params.config_from_values({"w_state": 0.7}).w_state == 0.7  # core normalises (+warning)
