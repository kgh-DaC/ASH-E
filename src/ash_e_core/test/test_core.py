"""Unit tests for ash_e_core stage A (no model files needed)."""
import json
import types as pytypes

import numpy as np
import pytest

from ash_e_core.config import PerceptionConfig, load_perception_config
from ash_e_core.detector import PoseModel, CigaretteRoiModel, letterbox, nms
from ash_e_core.distance import depth_median_position, proxy_position
from ash_e_core.pipeline import PerceptionPipeline
from ash_e_core.roi import compute_rois, head_size, person_anchors
from ash_e_core.serialize import detections_from_dict, frame_to_jsonl, to_dict
from ash_e_core.stabilizer import Stabilizer
from ash_e_core.state import Anchors, assign_states
from ash_e_core.tracker import Tracker
from ash_e_core.types import CameraIntrinsics, CigBox, DetectionArray, DistanceSource, PersonPose, SmokerState

CFG = PerceptionConfig()


def make_pose(cx=320, top=100, h=400, w=140, kp=None):
    bbox = np.array([cx - w / 2, top, cx + w / 2, top + h], np.float32)
    k = np.zeros((17, 3), np.float32)
    if kp == "full":
        k[0] = [cx, top + 30, 0.9]; k[1] = [cx - 10, top + 22, 0.9]; k[2] = [cx + 10, top + 22, 0.9]
        k[3] = [cx - 25, top + 25, 0.9]; k[4] = [cx + 25, top + 25, 0.9]
        k[5] = [cx - 40, top + 80, 0.9]; k[6] = [cx + 40, top + 80, 0.9]
        k[7] = [cx - 50, top + 150, 0.9]; k[8] = [cx + 50, top + 150, 0.9]
        k[9] = [cx - 55, top + 210, 0.9]; k[10] = [cx + 55, top + 210, 0.9]
        k[11] = [cx - 25, top + 200, 0.9]; k[12] = [cx + 25, top + 200, 0.9]
    elif kp == "nose":
        k[0] = [cx, top + 30, 0.9]
    return PersonPose(bbox, 0.9, k)


# ---------------- roi ----------------
def test_roi_full_keypoints():
    p = make_pose(kp="full")
    assert head_size(p, 0.3) == pytest.approx(50.0)  # ear-ear
    rois = compute_rois(p, CFG, 640, 720)
    kinds = sorted(r.kind for r in rois)
    assert kinds == ["hand_l", "hand_r", "mouth"]
    mouth = [r for r in rois if r.kind == "mouth"][0]
    assert mouth.side == pytest.approx(1.6 * 50)
    # mouth is below the nose (image y grows downward)
    assert mouth.center[1] > 130


def test_roi_nose_only_has_mouth_only():
    p = make_pose(kp="nose")
    rois = compute_rois(p, CFG, 640, 720)
    assert [r.kind for r in rois] == ["mouth"]


def test_roi_no_face_no_mouth():
    p = make_pose(kp="full")
    p.keypoints[0:5, 2] = 0.0  # back view: no face
    rois = compute_rois(p, CFG, 640, 720)
    assert "mouth" not in [r.kind for r in rois]
    assert len(rois) == 2


def test_roi_fallback_all_invalid():
    p = make_pose(kp=None)
    rois = compute_rois(p, CFG, 640, 720)
    assert sorted(r.kind for r in rois) == ["hand_l", "hand_r", "mouth"]


def test_roi_clipped_to_frame():
    p = make_pose(cx=10, kp="full")
    for r in compute_rois(p, CFG, 640, 720):
        x1, y1, x2, y2 = r.xyxy
        assert x1 >= 0 and y1 >= 0 and x2 <= 640 and y2 <= 720


def test_roi_min_size_skip():
    p = make_pose(h=100, w=35, kp="full")
    # shrink head: ears 4px apart -> side = 6.4 px < 24
    p.keypoints[3, 0], p.keypoints[4, 0] = 318, 322
    assert compute_rois(p, CFG, 640, 720) == []


# ---------------- state ----------------
def cb(x, y, conf=0.8, s=10):
    return CigBox(np.array([x - s, y - 3, x + s, y + 3], np.float32), conf)


def test_state_mouth_smoking_hand_holding_far_ignored():
    a = Anchors((100, 100), [(100, 300)], 50.0)
    r = assign_states([a], [cb(105, 105)], 0.7, 0.9)
    assert r[0].state == SmokerState.SMOKING
    r = assign_states([a], [cb(100, 310)], 0.7, 0.9)
    assert r[0].state == SmokerState.HOLDING
    r = assign_states([a], [cb(500, 500)], 0.7, 0.9)
    assert r[0].state == SmokerState.NONE and r[0].box is None


def test_state_smoking_outranks_holding_and_conf():
    a = Anchors((100, 100), [(100, 300)], 50.0)
    r = assign_states([a], [cb(100, 300, 0.9), cb(100, 100, 0.5)], 0.7, 0.9)
    assert r[0].state == SmokerState.SMOKING and r[0].conf == 0.5


def test_state_overlapping_people_nearest_gets_it():
    a = Anchors((100, 100), [], 50.0)
    b = Anchors((150, 100), [], 50.0)
    r = assign_states([a, b], [cb(140, 100)], 0.7, 0.9)
    assert r[0].state == SmokerState.NONE and r[1].state == SmokerState.SMOKING


# ---------------- stabilizer ----------------
def run_stab(rate, seq_fn, dur, cfg=CFG):
    st = Stabilizer(cfg)
    out = []
    n = int(dur * rate)
    for i in range(n):
        t = i / rate
        s, conf = seq_fn(t)
        out.append((t, st.update(t, True, s, conf)[0]))
    return out


def test_stab_single_false_positive_not_confirmed():
    res = run_stab(8, lambda t: (SmokerState.HOLDING, 0.9) if abs(t - 1.0) < 1e-6 else (0, 0.0), 3)
    assert all(s == SmokerState.NONE for _, s in res)


def test_stab_confirm_release_and_latch():
    def seq(t):
        if 1.0 <= t < 4.0:
            return (SmokerState.SMOKING, 0.8) if 1.0 <= t < 1.5 else (SmokerState.HOLDING, 0.8)
        return (0, 0.0)
    res = run_stab(8, seq, 40)
    states = dict(res)
    assert states[0.5] == SmokerState.NONE
    first = next(t for t, s in res if s != SmokerState.NONE)
    assert 1.0 < first <= 2.5
    # latch: smoking held although only HOLDING obs after t=1.5, until release or 20 s
    assert states[3.0] == SmokerState.SMOKING
    # observations stop being positive at 4.0: released after window decay + 1 s hold
    assert states[9.0] == SmokerState.NONE


def test_stab_latch_duration_with_continuous_holding():
    # smoking only at the beginning, then holding forever: smoking for ~20 s then holding
    def seq(t):
        return (SmokerState.SMOKING, 0.8) if t < 0.5 else (SmokerState.HOLDING, 0.8)
    res = dict(run_stab(8, seq, 40))
    assert res[10.0] == SmokerState.SMOKING
    assert res[30.0] == SmokerState.HOLDING


def test_stab_unchecked_frames_excluded():
    st = Stabilizer(CFG)
    for i in range(40):
        st.update(i / 8, False, SmokerState.HOLDING, 0.9)  # not checked -> ignored
    assert st.state == SmokerState.NONE and len(st.obs) == 0


def test_stab_release_hysteresis_short_gap_keeps_state():
    def seq(t):
        return (0, 0.0) if 3.0 <= t < 3.6 else (SmokerState.HOLDING, 0.8)
    res = run_stab(8, seq, 8)
    assert all(s != SmokerState.NONE for t, s in res if t >= 1.5)


@pytest.mark.parametrize("rate", [4, 8, 15])
def test_stab_rate_independent(rate):
    def seq(t):
        return (SmokerState.HOLDING, 0.8) if 1.0 <= t < 5.0 else (0, 0.0)
    res = run_stab(rate, seq, 10)
    first = next(t for t, s in res if s != SmokerState.NONE)
    last = max(t for t, s in res if s != SmokerState.NONE)
    assert first <= 2.6 and 5.0 <= last <= 7.5


# ---------------- tracker ----------------
def box(cx, top=100, w=100, h=300):
    return np.array([cx - w / 2, top, cx + w / 2, top + h], np.float32)


def test_tracker_id_kept_and_hits():
    tr = Tracker(CFG)
    ids = []
    for i in range(5):
        m = tr.update([box(100 + 5 * i)], i / 8)
        ids.append(m[0].track_id)
    assert set(ids) == {1} and m[0].hits == 5


def test_tracker_crossing_keeps_ids():
    tr = Tracker(CFG)
    ida = idb = None
    for i in range(30):
        ax, bx = 100 + 20 * i, 700 - 20 * i  # cross around i=15
        m = tr.update([box(ax), box(bx, w=70, h=240)], i / 8)
        if i == 0:
            ida, idb = m[0].track_id, m[1].track_id
    # different box sizes: after crossing, large box (index 0) must still be ida
    assert m[0].track_id == ida and m[1].track_id == idb


def test_tracker_expire_and_new_id():
    tr = Tracker(CFG)
    tr.update([box(100)], 0.0)
    m = tr.update([box(100)], 2.5)  # older than track_max_age_s=1.0
    assert m[0].track_id == 2


def test_tracker_stationary_accumulates_and_resets():
    tr = Tracker(CFG)
    for i in range(17):
        m = tr.update([box(100)], i / 8)
    assert m[0].stationary_s == pytest.approx(2.0, abs=0.01)
    m = tr.update([box(300)], 17 / 8)  # big jump
    assert m[0].stationary_s == 0.0


# ---------------- distance ----------------
INTR = CameraIntrinsics.from_hfov(1280, 720, 70)


def test_proxy_full_body_and_bearing_sign():
    p = make_pose(cx=300, top=100, h=360, w=120, kp="full")  # left of center (640)
    pt, dist, src, bearing = proxy_position(p, INTR, CFG, 720)
    assert src == DistanceSource.PROXY
    assert pt.z == pytest.approx(INTR.fy * 1.65 / 360)
    assert pt.x < 0 and bearing > 0  # left => positive (REP-103)
    p2 = make_pose(cx=900, top=100, h=360, w=120, kp="full")
    assert proxy_position(p2, INTR, CFG, 720)[3] < 0


def test_proxy_cropped_uses_shoulders_then_head():
    p = make_pose(top=-5, h=800, kp="full")  # touches the top/bottom edge
    z_sh = INTR.fx * 0.40 / 80.0
    assert proxy_position(p, INTR, CFG, 720)[0].z == pytest.approx(z_sh)
    p.keypoints[5:7, 2] = 0
    z_head = INTR.fx * 0.15 / 50.0
    assert proxy_position(p, INTR, CFG, 720)[0].z == pytest.approx(z_head)


def test_depth_median_filters_invalid_and_fallback():
    p = make_pose(cx=320, top=100, h=400, w=140, kp="full")
    d = np.full((720, 1280), 2.5, np.float32)
    d[190:230, 290:330] = 0.0  # a hole
    d[200:210, 300:310] = np.nan
    d[300:305, 300:305] = 20.0  # out of range
    r = depth_median_position(p, d, INTR, CFG)
    assert r is not None and r[0].z == pytest.approx(2.5) and r[2] == DistanceSource.DEPTH
    dz = np.zeros((720, 1280), np.float32)
    assert depth_median_position(p, dz, INTR, CFG) is None


# ---------------- detector helpers ----------------
def test_letterbox_and_nms():
    img = np.zeros((100, 200, 3), np.uint8)
    x, s, px, py = letterbox(img, 320)
    assert x.shape == (1, 3, 320, 320) and s == pytest.approx(1.6) and px == 0 and py == 80
    b = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], np.float32)
    assert nms(b, np.array([0.9, 0.8, 0.7]), 0.5) == [0, 2]


class FakeModel:
    is_stub = False

    def __init__(self, out, size=320):
        self.out, self.input_size = out, size

    def run(self, x):
        return self.out


def test_pose_decode_synthetic():
    out = np.zeros((1, 56, 3), np.float32)
    out[0, :5, 0] = [160, 160, 80, 200, 0.9]       # cx,cy,w,h,conf in letterbox coords (320)
    out[0, 5:56, 0] = np.tile([160, 100, 0.9], 17)
    pm = PoseModel(FakeModel(out), CFG)
    res = pm.decode(out, 0.5, 0.0, 0.0, 1280, 720)
    assert len(res) == 1
    assert res[0].bbox_xyxy[1] == pytest.approx(120.0)  # (160-100)/0.5
    assert res[0].keypoints.shape == (17, 3)


def test_cig_decode_maps_to_frame():
    out = np.zeros((1, 5, 2), np.float32)
    out[0, :, 0] = [96, 96, 20, 10, 0.9]
    cm = CigaretteRoiModel(FakeModel(out, 192), CFG)
    frame = np.zeros((400, 400, 3), np.uint8)
    res = cm.detect_crops(frame, [(100, 100, 292, 292)])[0]  # 192x192 crop -> scale 1
    assert len(res) == 1
    assert res[0].xyxy[0] == pytest.approx(100 + 86) and res[0].conf == pytest.approx(0.9)


# ---------------- pipeline / serialize ----------------
def test_pipeline_stub_models_boot_and_empty_result():
    pl = PerceptionPipeline(PerceptionConfig(pose_model_path="nope.onnx", cig_model_path="nope2.onnx"))
    assert pl.models_ready == {"pose": False, "cigarette": False}
    arr = pl.process(np.zeros((480, 640, 3), np.uint8), 0.0, "cam")
    assert arr.detections == [] and arr.image_width == 640 and arr.frame_id == "cam"
    assert arr.frame_seq == 1


def _fake_pipeline(cig_out):
    pose_out = np.zeros((1, 56, 2), np.float32)
    pose_out[0, :5, 0] = [160, 160, 100, 280, 0.9]
    kp = np.zeros((17, 3), np.float32)
    kp[0] = [160, 60, .9]; kp[1] = [150, 52, .9]; kp[2] = [170, 52, .9]
    kp[3] = [135, 55, .9]; kp[4] = [185, 55, .9]
    kp[9] = [120, 200, .9]; kp[7] = [125, 150, .9]
    pose_out[0, 5:56, 0] = kp.reshape(-1)
    cfg = PerceptionConfig(min_person_h_px=60)
    return PerceptionPipeline(cfg, FakeModel(pose_out), FakeModel(cig_out, 192))


def test_pipeline_end_to_end_with_fake_models_and_determinism():
    cig = np.zeros((1, 5, 1), np.float32)
    cig[0, :, 0] = [96, 96, 40, 20, 0.9]  # always a cigarette in the center of every ROI
    frame = np.full((320, 320, 3), 100, np.uint8)
    runs = []
    for _ in range(2):
        pl = _fake_pipeline(cig)
        seq = [pl.process(frame, i / 8, "f") for i in range(12)]
        runs.append([json.dumps(to_dict(a), sort_keys=True) for a in seq if True])
    # timing field differs between runs; compare without inference_ms
    strip = lambda s: {k: v for k, v in json.loads(s).items() if k != "inference_ms"}
    assert [strip(s) for s in runs[0]] == [strip(s) for s in runs[1]]
    last = json.loads(runs[0][-1])
    assert len(last["detections"]) == 1
    d = last["detections"][0]
    assert d["track_id"] == 1 and d["cigarette_checked"] is True and d["state"] in (1, 2)
    # first frame: hits < 2 so not published
    assert json.loads(runs[0][0])["detections"] == []


def test_serialize_roundtrip():
    pl = PerceptionPipeline(PerceptionConfig(pose_model_path="x", cig_model_path="y"))
    arr = DetectionArray(stamp=1.5, frame_id="f", frame_seq=3, image_width=10, image_height=5)
    line = frame_to_jsonl(3, 1.5, arr)
    rec = json.loads(line)
    back = detections_from_dict(rec["detections"])
    assert back == arr


def test_config_loader_flat_and_ros(tmp_path):
    f = tmp_path / "a.yaml"
    f.write_text("cig_conf_thresh: 0.5\nstab_min_obs: 6\n")
    c = load_perception_config(str(f))
    assert c.cig_conf_thresh == 0.5 and c.stab_min_obs == 6 and isinstance(c.stab_min_obs, int)
    g = tmp_path / "b.yaml"
    g.write_text("ash_e_perception:\n  ros__parameters:\n    smoking_radius: 0.5\n")
    assert load_perception_config(str(g)).smoking_radius == 0.5
