"""depth_align tests with synthetic data (spec 12.1)."""
import numpy as np
import pytest

from ash_e_core.depth_align import (DepthAligner, DepthCalibration, DepthExtrinsics, load_extrinsics,
                                    rotation_to_quaternion, save_extrinsics)
from ash_e_core.types import CameraIntrinsics

K_D = CameraIntrinsics(500.0, 500.0, 320.0, 240.0, 640, 480)


def plane(z, h=480, w=640):
    return np.full((h, w), z, np.float32)


def test_identity_returns_input():
    al = DepthAligner(K_D, K_D, DepthExtrinsics(), decimate=1)
    d = plane(2.0)
    d[100:200, 100:200] = 1.2
    out = al.align(d)
    assert out.shape == d.shape and out.dtype == np.float32
    np.testing.assert_allclose(out, d, atol=1e-5)


def test_output_size_equals_color_size():
    color = CameraIntrinsics(900.0, 900.0, 640.0, 360.0, 1280, 720)
    out = DepthAligner(K_D, color, DepthExtrinsics(), decimate=2).align(plane(2.0))
    assert out.shape == (720, 1280)


def test_translation_shifts_pixels():
    # p_c = p_d + [0.025,0,0]: a point on a z=2 plane moves by fx*0.025/2 = 6.25 px to the right
    al = DepthAligner(K_D, K_D, DepthExtrinsics(np.eye(3), np.array([0.025, 0.0, 0.0])), decimate=1, fill_radius=0)
    d = np.zeros((480, 640), np.float32)
    d[:, 300:340] = 2.0                       # vertical stripe
    out = al.align(d)
    cols = np.where((out > 0).any(axis=0))[0]
    assert cols.min() in (306, 307) and cols.max() in (345, 346)
    np.testing.assert_allclose(out[out > 0], 2.0, atol=1e-5)


def test_zbuffer_nearest_wins_independent_of_order():
    # color focal length is half the depth focal length -> depth pixels 320 and 321 land on the same color pixel
    col = CameraIntrinsics(250.0, 250.0, 160.0, 120.0, 320, 240)
    al = DepthAligner(K_D, col, DepthExtrinsics(), decimate=1, fill_radius=0)
    a = np.zeros((480, 640), np.float32)
    a[240, 320], a[240, 321] = 5.0, 1.5
    b = np.zeros((480, 640), np.float32)
    b[240, 320], b[240, 321] = 1.5, 5.0
    assert al.align(a)[120, 160] == pytest.approx(1.5)
    assert al.align(b)[120, 160] == pytest.approx(1.5)


def test_zero_and_nan_ignored():
    d = np.full((480, 640), np.nan, np.float32)
    d[10:20, 10:20] = 0.0
    out = DepthAligner(K_D, K_D, DepthExtrinsics(), decimate=1).align(d)
    assert (out == 0).all()


def test_decimate_fills_holes_inside_plane():
    color = CameraIntrinsics(1000.0, 1000.0, 640.0, 360.0, 1280, 720)   # 2x upscale
    out = DepthAligner(K_D, color, DepthExtrinsics(), decimate=2).align(plane(2.0))
    inner = out[200:520, 300:980]
    assert (inner > 0).all()
    np.testing.assert_allclose(inner, 2.0, atol=1e-5)


def test_fill_keeps_invalid_where_no_neighbours():
    d = np.zeros((480, 640), np.float32)
    d[240, 320] = 2.0
    out = DepthAligner(K_D, K_D, DepthExtrinsics(), decimate=1, fill_radius=2).align(d)
    assert out[240, 320] == pytest.approx(2.0)
    assert out[240, 323] == 0 and out[100, 100] == 0     # outside radius stays invalid
    assert out[240, 322] == pytest.approx(2.0)           # inside radius is filled


def test_points_behind_camera_dropped():
    al = DepthAligner(K_D, K_D, DepthExtrinsics(np.eye(3), np.array([0, 0, -5.0])), decimate=1)
    assert (al.align(plane(2.0)) == 0).all()


def test_pixel_offset_shifts_projection():
    d = np.zeros((480, 640), np.float32)
    d[240, 320] = 2.0
    out = DepthAligner(K_D, K_D, DepthExtrinsics(), decimate=1, fill_radius=0, pixel_offset_uv=(3.0, 0.0)).align(d)
    assert out[240, 323] == pytest.approx(2.0)


def test_deterministic_and_wrong_shape():
    rng = np.random.default_rng(0)
    d = rng.uniform(0.5, 5.0, (480, 640)).astype(np.float32)
    al = DepthAligner(K_D, K_D, DepthExtrinsics(np.eye(3), np.array([0.03, 0.01, 0.0])), decimate=2)
    np.testing.assert_array_equal(al.align(d), al.align(d))
    with pytest.raises(ValueError):
        al.align(np.zeros((100, 100), np.float32))


def test_calibration_yaml_roundtrip(tmp_path):
    R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)
    cal = DepthCalibration(DepthExtrinsics(R, np.array([0.03, 0.0, 0.01])), K_D,
                           CameraIntrinsics(900, 905, 640, 360, 1280, 720), rms_px=0.4, date="2026-11-19",
                           note="x", depth_pixel_offset_uv=(1.0, -2.0))
    p = str(tmp_path / "e.yaml")
    save_extrinsics(p, cal)
    got = load_extrinsics(p)
    np.testing.assert_allclose(got.extr.R, R)
    np.testing.assert_allclose(got.extr.t, [0.03, 0.0, 0.01])
    assert got.intr_color.width == 1280 and got.intr_color.fy == 905
    assert got.depth_pixel_offset_uv == (1.0, -2.0) and got.rms_px == pytest.approx(0.4)


def test_load_missing_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("R: [1,0,0,0,1,0,0,0,1]\n")
    with pytest.raises(ValueError):
        load_extrinsics(str(p))


def test_rotation_to_quaternion():
    assert rotation_to_quaternion(np.eye(3)) == pytest.approx((0, 0, 0, 1))
    Rz90 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)
    x, y, z, w = rotation_to_quaternion(Rz90)
    assert (x, y) == pytest.approx((0, 0)) and z == pytest.approx(np.sqrt(0.5)) and w == pytest.approx(np.sqrt(0.5))
    assert abs(rotation_to_quaternion(np.diag([1.0, -1, -1]))[0]) == pytest.approx(1.0)
