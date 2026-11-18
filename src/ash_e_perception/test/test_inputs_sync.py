import dataclasses
import os
import types

import numpy as np
import pytest

from ash_e_perception import inputs
from ash_e_perception.sync import FrameMatcher

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_depth_units():
    mm = np.array([[0, 1000, 2500]], np.uint16)
    out = inputs.depth_to_meters(mm, "16UC1")
    assert out.dtype == np.float32 and out.tolist() == [[0.0, 1.0, 2.5]]
    f = np.array([[np.nan, 1.5]], np.float32)
    assert inputs.depth_to_meters(f, "32FC1")[0, 1] == 1.5
    with pytest.raises(ValueError):
        inputs.depth_to_meters(f, "rgb8")


def test_valid_ratio():
    d = np.array([[0.0, 1.0], [np.nan, 7.0]], np.float32)
    assert inputs.valid_depth_ratio(d, 0.6, 6.0) == 0.25


def test_intrinsics_from_info():
    K = [500, 0, 320, 0, 510, 240, 0, 0, 1]
    i, scaled = inputs.intrinsics_from_camera_info(K, 640, 480, 640, 480)
    assert (i.fx, i.fy, i.cx, i.cy) == (500, 510, 320, 240) and not scaled
    i2, scaled2 = inputs.intrinsics_from_camera_info(K, 640, 480, 1280, 960)
    assert scaled2 and i2.fx == 1000 and i2.cy == 480 and i2.width == 1280
    assert inputs.intrinsics_from_camera_info([0] * 9, 640, 480, 640, 480) is None


def test_hfov_roundtrip_and_camera_info_dict():
    from ash_e_core.types import CameraIntrinsics
    i = CameraIntrinsics.from_hfov(1280, 720, 70.0)
    assert inputs.hfov_from_intrinsics(i) == pytest.approx(70.0)
    d = inputs.camera_info_dict(1280, 720, 70.0)
    assert d["k"][0] == pytest.approx(i.fx) and d["k"][2] == 640 and len(d["p"]) == 12


def test_resolve_path(tmp_path):
    (tmp_path / "zz_pose.onnx").write_bytes(b"x")
    assert inputs.resolve_path("models/zz_pose.onnx", [str(tmp_path)]) == str(tmp_path / "zz_pose.onnx")
    assert inputs.resolve_path("models/none.onnx", [str(tmp_path)]) == "models/none.onnx"
    assert inputs.resolve_path("", [str(tmp_path)]) == ""


def test_stamp():
    assert inputs.sec_to_stamp(1.5) == (1, 500_000_000)
    assert inputs.stamp_to_sec(2, 250_000_000) == 2.25


def _img(enc, arr):
    h, w = arr.shape[:2]
    return types.SimpleNamespace(height=h, width=w, encoding=enc, is_bigendian=0, step=arr.strides[0],
                                 data=arr.tobytes())


def test_image_decode_variants():
    bgr = np.random.default_rng(0).integers(0, 255, (4, 6, 3), dtype=np.uint8)
    assert np.array_equal(inputs.image_msg_to_numpy(_img("bgr8", bgr)), bgr)
    assert np.array_equal(inputs.image_msg_to_numpy(_img("rgb8", bgr[:, :, ::-1].copy()), want_bgr=True), bgr)
    d16 = np.arange(24, dtype=np.uint16).reshape(4, 6) * 100
    assert np.array_equal(inputs.image_msg_to_numpy(_img("16UC1", d16)), d16)
    padded = np.zeros((4, 8), np.uint16)
    padded[:, :6] = d16
    got = inputs.image_msg_to_numpy(types.SimpleNamespace(height=4, width=6, encoding="16UC1", is_bigendian=0,
                                                          step=16, data=padded.tobytes()))
    assert np.array_equal(got, d16)


# ---------------- FrameMatcher
def test_matcher_pairs_within_slop():
    m = FrameMatcher(0.05, 0.12)
    m.push_color(1.00, "c1", arrival=10.0)
    assert m.pop_ready(10.0) is None                       # waiting for depth
    m.push_depth(1.03, "d1")
    r = m.pop_ready(10.01)
    assert r.color == "c1" and r.depth == "d1" and r.dt == pytest.approx(0.03)
    assert m.pop_ready(10.02) is None


def test_matcher_timeout_gives_proxy_frame():
    m = FrameMatcher(0.05, 0.12)
    m.push_color(1.0, "c1", arrival=10.0)
    m.push_depth(5.0, "far")                               # outside slop
    assert m.pop_ready(10.05) is None
    r = m.pop_ready(10.13)
    assert r.color == "c1" and r.depth is None


def test_matcher_latest_only_and_nearest():
    m = FrameMatcher(0.05, 0.12)
    for i, s in enumerate((1.0, 1.1, 1.2)):
        m.push_color(s, "c%d" % i, arrival=10.0 + i * 0.1)
    m.push_depth(1.0, "dA")
    m.push_depth(1.21, "dB")
    r = m.pop_ready(10.25)
    assert r.color == "c2" and r.depth == "dB"             # newest colour with a partner
    assert m.dropped == 2 and m.pop_ready(11.0) is None


def test_matcher_no_depth_mode():
    m = FrameMatcher(0.05, 0.12, use_depth=False)
    m.push_color(1.0, "c", arrival=0.0)
    assert m.pop_ready(0.0).depth is None


# ---------------- static checks
def test_no_camera_topic_hardcoding_outside_params():
    bad = []
    for root, _, files in os.walk(os.path.join(SRC, "ash_e_perception")):
        for f in files:
            if f.endswith(".py") and f != "params.py":
                for n, line in enumerate(open(os.path.join(root, f), encoding="utf-8"), 1):
                    if "/camera/" in line.split("#", 1)[0]:
                        bad.append("%s:%d" % (f, n))
    assert not bad, bad
    assert "/camera/" not in open(os.path.join(SRC, "launch", "perception.launch.py"), encoding="utf-8").read()


def test_core_has_no_ros_imports():
    core = os.path.join(os.path.dirname(SRC), "ash_e_core", "ash_e_core")
    banned = ("rclpy", "rospy", "sensor_msgs", "cv_bridge", "openni", "ultralytics", "win32", "msvcrt")
    for f in os.listdir(core):
        if f.endswith(".py"):
            for line in open(os.path.join(core, f), encoding="utf-8"):
                s = line.strip()
                if s.startswith(("import ", "from ")):
                    assert not any(b in s for b in banned), (f, s)


def test_wrapper_keys_do_not_collide_with_core_keys():
    from ash_e_core.config import PerceptionConfig
    from ash_e_perception.params import WRAPPER_DEFAULTS
    assert not set(WRAPPER_DEFAULTS) & {f.name for f in dataclasses.fields(PerceptionConfig)}


def test_perception_yaml_keys():
    import yaml
    from ash_e_core.config import PerceptionConfig, load_perception_config
    from ash_e_perception.params import WRAPPER_DEFAULTS
    p = os.path.join(SRC, "config", "perception.yaml")
    y = yaml.safe_load(open(p, encoding="utf-8"))["/**"]["ros__parameters"]
    core = {f.name for f in dataclasses.fields(PerceptionConfig)}
    assert core <= set(y) and set(y) - core <= set(WRAPPER_DEFAULTS)
    assert load_perception_config(p) == PerceptionConfig()


def test_camera_yaml_keys_are_wrapper_keys():
    import yaml
    from ash_e_perception.params import WRAPPER_DEFAULTS
    p = os.path.join(SRC, "config", "camera_astra_pro.yaml")
    y = yaml.safe_load(open(p, encoding="utf-8"))["/**"]["ros__parameters"]
    assert set(y) <= set(WRAPPER_DEFAULTS)
