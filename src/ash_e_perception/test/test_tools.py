import json

import cv2
import numpy as np
import pytest

from ash_e_core.serialize import frame_to_jsonl
from ash_e_core.types import Detection, DetectionArray, TargetStatus
from ash_e_perception.tools import calib_astra_extrinsics as calib
from ash_e_perception.tools import depth_check
from ash_e_perception.tools.dump_jsonl import JsonlPairer
from ash_e_perception.tools.video_to_bag import build_camera_info_fields, frame_stamp_ns, stamp_fields


def test_frame_stamps_exact():
    assert frame_stamp_ns(0, 30.0) == 0
    assert frame_stamp_ns(30, 30.0) == 1_000_000_000
    assert frame_stamp_ns(1, 15.0) == 66_666_667
    assert stamp_fields(1_500_000_000) == (1, 500_000_000)
    assert frame_stamp_ns(10 ** 6, 29.97) / 1e9 == pytest.approx(10 ** 6 / 29.97, abs=1e-6)


def test_camera_info_matches_core_intrinsics():
    from ash_e_core.types import CameraIntrinsics
    i = CameraIntrinsics.from_hfov(1280, 720, 70.0)
    f = build_camera_info_fields(1280, 720, 70.0)
    assert f["k"][0] == i.fx and f["k"][4] == i.fy and f["k"][2] == i.cx and f["k"][5] == i.cy


def _arr(seq, stamp):
    return DetectionArray(stamp=stamp, frame_id="f", frame_seq=seq, detections=[Detection(track_id=1)])


def test_pairer_matches_by_stamp_and_flushes():
    p = JsonlPairer()
    assert p.add_detections(_arr(1, 1.0)) == []
    out = p.add_target(TargetStatus(stamp=1.0, frame_id="f", has_target=True))
    rec = json.loads(out[0])
    assert rec["frame_seq"] == 1 and rec["target"]["has_target"] is True
    # frames that never get a target are written with target null once too many are pending
    lines = []
    for i in range(2, 8):
        lines += p.add_detections(_arr(i, float(i)))
    lines += p.flush()
    recs = [json.loads(l) for l in lines]
    assert [r["frame_seq"] for r in recs] == [2, 3, 4, 5, 6, 7] and all(r["target"] is None for r in recs)


def test_pairer_target_first_and_no_target_mode():
    p = JsonlPairer()
    assert p.add_target(TargetStatus(stamp=2.0)) == []
    assert json.loads(p.add_detections(_arr(5, 2.0))[0])["target"] is not None
    q = JsonlPairer(with_target=False)
    assert q.add_detections(_arr(1, 1.0)) == [frame_to_jsonl(1, 1.0, _arr(1, 1.0), None)]


def test_pair_nearest():
    r = depth_check.pair_nearest([1.0, 2.0, 3.0], [1.01, 2.2], 0.05)
    assert r[0][1] == 0 and r[0][2] == pytest.approx(0.01) and r[1][1] is None and r[2][1] is None
    assert depth_check.pair_nearest([1.0], [], 0.05) == [(0, None, None)]


def test_summarize_table():
    rows = [{"proxy_m": 2.4, "depth_m": 2.0}, {"proxy_m": 3.3, "depth_m": 3.0}, {"proxy_m": 2.0, "depth_m": None}]
    txt = depth_check.summarize(rows, ref_m=2.0, dts=[0.01, -0.02, 0.03], valid_ratios=[0.5, 0.7], deterministic=True)
    assert "with DEPTH distance | 2" in txt and "fell back to PROXY (depth invalid) | 1" in txt
    assert "deterministic" in txt and "median / p95" in txt and "error vs ref" in txt
    assert depth_check.summarize([]).count("| 0 |") >= 1


def test_depth_check_runs_with_stub_models(tmp_path):
    from ash_e_core.config import PerceptionConfig
    from ash_e_core.depth_align import DepthCalibration, DepthExtrinsics
    from ash_e_core.types import CameraIntrinsics
    cal = DepthCalibration(DepthExtrinsics(), CameraIntrinsics(500, 500, 320, 240, 640, 480),
                           CameraIntrinsics(500, 500, 320, 240, 640, 480))
    cfg = PerceptionConfig(pose_model_path="none.onnx", cig_model_path="none.onnx")
    d = tmp_path / "rec"
    d.mkdir()
    for i in range(2):
        cv2.imwrite(str(d / ("color_%06d.png" % i)), np.zeros((480, 640, 3), np.uint8))
        cv2.imwrite(str(d / ("depth_%06d.png" % i)), np.full((480, 640), 2000, np.uint16))
    rows, valid, dts, det_ok = depth_check.run(depth_check.iter_dir(str(d), 15.0), cal, cfg)
    assert rows == [] and len(valid) == 2 and valid[0] == pytest.approx(1.0) and det_ok is True


def test_calibrate_extrinsics_recovers_known_transform():
    cols, rows, sq = 9, 6, 0.025
    objp = calib.board_points(cols, rows, sq)
    Kd = np.array([[570.0, 0, 320], [0, 570, 240], [0, 0, 1]])
    Kc = np.array([[900.0, 0, 640], [0, 900, 360], [0, 0, 1]])
    R_true = cv2.Rodrigues(np.array([0.01, -0.02, 0.005]))[0]
    t_true = np.array([0.03, -0.004, 0.002])
    rng = np.random.default_rng(1)
    pd, pc = [], []
    for _ in range(18):
        rv = rng.uniform(-0.45, 0.45, 3)
        tv = np.array([rng.uniform(-0.1, 0.0), rng.uniform(-0.06, 0.0), rng.uniform(0.6, 1.4)])
        # board pose in the depth(IR) camera; color camera sees p_c = R p_d + t
        Rb = cv2.Rodrigues(rv)[0]
        a, _ = cv2.projectPoints(objp, cv2.Rodrigues(Rb)[0], tv, Kd, None)
        Rc, tc = R_true @ Rb, R_true @ tv + t_true
        b, _ = cv2.projectPoints(objp, cv2.Rodrigues(Rc)[0], tc, Kc, None)
        pd.append((a + rng.normal(0, 0.1, a.shape)).astype(np.float32))
        pc.append((b + rng.normal(0, 0.1, b.shape)).astype(np.float32))
    cal = calib.calibrate_extrinsics(objp, pd, pc, (640, 480), (1280, 720))
    assert cal.rms_px < 0.5
    np.testing.assert_allclose(cal.extr.t, t_true, atol=0.005)
    assert np.abs(cal.extr.R - R_true).max() < 0.01
    assert cal.intr_color.width == 1280 and cal.intr_depth.fx == pytest.approx(570.0, rel=0.03)


def test_find_corners_on_rendered_board():
    cols, rows, sq = 9, 6, 40
    img = np.full((60 + (rows + 1) * sq, 60 + (cols + 1) * sq), 255, np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                img[30 + r * sq:30 + (r + 1) * sq, 30 + c * sq:30 + (c + 1) * sq] = 0
    got = calib.find_corners(img, cols, rows)
    assert got is not None and got.shape == (cols * rows, 1, 2)
    assert calib.find_corners(np.full((100, 100), 128, np.uint8), cols, rows) is None
