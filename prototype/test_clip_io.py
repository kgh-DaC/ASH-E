"""Tests for clip recording / replay (prototype/clip_io.py). Synthetic frames + fake models: no camera, no weights.

  .venv\\Scripts\\python -m pytest prototype\\test_clip_io.py -q
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clip_io  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.pipeline import PerceptionPipeline  # noqa: E402


class FakeModel:
    is_stub = False

    def __init__(self, out, size=320):
        self.out, self.input_size = out, size

    def run(self, x):
        return self.out


def make_pipe(cig_conf=0.9):
    pose_out = np.zeros((1, 56, 2), np.float32)
    pose_out[0, :5, 0] = [160, 160, 100, 280, 0.9]
    kp = np.zeros((17, 3), np.float32)
    kp[0] = [160, 60, .9]; kp[1] = [150, 52, .9]; kp[2] = [170, 52, .9]
    kp[3] = [135, 55, .9]; kp[4] = [185, 55, .9]
    kp[9] = [120, 200, .9]; kp[7] = [125, 150, .9]
    pose_out[0, 5:56, 0] = kp.reshape(-1)
    cig = np.zeros((1, 5, 1), np.float32)
    cig[0, :, 0] = [96, 96, 40, 20, cig_conf]
    return PerceptionPipeline(PerceptionConfig(min_person_h_px=60), FakeModel(pose_out), FakeModel(cig, 192))


FRAME = np.full((320, 320, 3), 100, np.uint8)


def record(tmp_path, pipe, n_wall=60, wall_dt=1 / 30, slow_at=None):
    """Drive ClipRecorder like the live loop: wall-clock `now`, optionally one slow iteration (-> dup frames)."""
    rec = clip_io.ClipRecorder(pipe, tmp_path, "P01", "S1", "mouth", fps=15.0, rate_hz=8.0)
    now = 1000.0
    for i in range(n_wall):
        now += wall_dt + (0.3 if slow_at == i else 0.0)
        rec.feed(FRAME, now)
    footer = rec.stop()
    return rec, footer


def strip(lines):
    return [{k: v for k, v in l.items() if k not in ("inference_ms", "created", "source", "clip", "models", "dup", "n_dup")}
            for l in lines if l["type"] != "footer"] + [
        {k: v for k, v in l.items() if k not in ("mean_inference_ms", "n_dup")} for l in lines if l["type"] == "footer"]


# ---------------------------------------------------------------- consent / ID rules (same as capture.py)
def test_check_ids_refuses_names_and_missing_consent():
    clip_io.check_ids("P01", "S1", "mouth", True)
    for bad in ("Alice", "p01", "P1", "", None, "P01_kim"):
        with pytest.raises(SystemExit):
            clip_io.check_ids(bad, "S1", "mouth", True)
    with pytest.raises(SystemExit):
        clip_io.check_ids("P01", "S1", "mouth", False)
    with pytest.raises(SystemExit):
        clip_io.check_ids("P01", "../x", "mouth", True)
    with pytest.raises(SystemExit):
        clip_io.check_ids("P01", "S1", "../evil", True)


# ---------------------------------------------------------------- record layout + events schema
def test_record_layout_and_events_schema(tmp_path):
    rec, footer = record(tmp_path, make_pipe(), slow_at=30)
    d = tmp_path / "P01" / "S1" / "mouth_001"
    assert rec.dir == d and sorted(p.name for p in d.iterdir()) == ["clip.mp4", "events.jsonl", "labels.json"]

    # raw video: no overlay, frame count == footer
    cap = cv2.VideoCapture(str(d / "clip.mp4"))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    assert len(frames) == footer["n_frames"] > 20
    assert frames[0].shape == FRAME.shape and abs(float(frames[5].mean()) - 100) < 8  # flat gray (mp4v shifts it a little), nothing drawn
    assert abs(cap.get(cv2.CAP_PROP_FPS) - 15.0) < 0.01

    ev = clip_io.load_events(d / "events.jsonl")
    hdr, frs, evs, ftr = ev[0], [e for e in ev if e["type"] == "frame"], [e for e in ev if e["type"] == "event"], ev[-1]
    assert hdr["type"] == "header" and hdr["schema"] == 1 and hdr["fps"] == 15.0 and hdr["participant"] == "P01"
    assert hdr["scenario"] == "mouth" and hdr["session"] == "S1" and hdr["process_rate_hz"] == 8.0
    assert "stab_window_s" in hdr["config"] and "confirm_ratio" in hdr["config"]
    assert ftr["type"] == "footer" and ftr["n_frames"] == len(frs) and ftr["duration_s"] == pytest.approx(len(frs) / 15.0, abs=1e-3)
    assert ftr["n_dup"] >= 3  # the 0.3 s stall repeats the camera frame to keep the clip clock real-time
    assert [f["frame_idx"] for f in frs] == list(range(len(frs)))
    assert all(f["t"] == pytest.approx(f["frame_idx"] / 15.0, abs=1e-4) for f in frs)
    assert sum(f["processed"] for f in frs) == ftr["n_processed"] < len(frs)  # throttled to ~8 Hz

    # fields needed by the evaluator (time-to-confirm, false confirms per 10 min, distance bins, raw-state metrics)
    proc = [f for f in frs if f["processed"] and f["detections"]]
    assert proc
    for key in ("track_id", "state", "state_confidence", "confirmed", "raw_state", "raw_confidence",
                "cigarette_checked", "person_confidence", "bbox_x", "bbox_y", "bbox_w", "bbox_h",
                "distance_m", "distance_source", "frames_observed"):
        assert key in proc[-1]["detections"][0], key
    assert proc[-1]["detections"][0]["distance_source"] == 1  # PROXY
    # a non-processed frame carries the previous tracks over and says so
    carried = [f for f in frs if not f["processed"] and f["detections"]]
    assert carried and carried[0]["inference_ms"] is None

    kinds = [e["event"] for e in evs]
    assert "track_new" in kinds and "confirm" in kinds
    c = next(e for e in evs if e["event"] == "confirm")
    assert c["from_state"] == 0 and c["to_state"] in (1, 2) and c["track_id"] == 1 and c["t"] > 0
    # time-to-confirm for a person who is positive from t = 0: first confirm event time
    assert c["t"] <= 2.0

    # labels template: empty values, spec 9.2 shape, human fills it in
    lab = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    assert lab["fps"] == 15.0 and lab["participants"] == ["P01"] and lab["persons"][0]["segments"] == []
    assert lab["persons"][0]["anchor"] == {"t": None, "bbox_xyxy": None} and lab["split"] == ""


def test_second_clip_gets_next_number_and_labels_not_overwritten(tmp_path):
    record(tmp_path, make_pipe(), n_wall=10)
    d1 = tmp_path / "P01" / "S1" / "mouth_001"
    (d1 / "labels.json").write_text('{"hand": "edited"}')
    clip_io.write_labels_template(d1, "P01", "S1", "mouth", 15.0)
    assert json.loads((d1 / "labels.json").read_text()) == {"hand": "edited"}
    rec2, _ = record(tmp_path, make_pipe(), n_wall=10)
    assert rec2.dir.name == "mouth_002"


def test_empty_clip_is_removed(tmp_path):
    rec = clip_io.ClipRecorder(make_pipe(), tmp_path, "P01", "S1", "none", 15.0, 8.0)
    assert rec.dir.exists()
    assert rec.stop() is None and not rec.dir.exists()


# ---------------------------------------------------------------- replay reproduces the live events
def test_replay_matches_live_events(tmp_path):
    rec, _ = record(tmp_path, make_pipe(), slow_at=20)
    live = clip_io.load_events(rec.dir / "events.jsonl")
    footer = clip_io.replay_clip(rec.dir / "clip.mp4", make_pipe(), rate_hz=8.0)
    out = rec.dir / "events.replay.jsonl"
    assert out.is_file() and footer["events_path"] == str(out)
    assert clip_io.load_events(rec.dir / "events.jsonl") == live  # live file untouched
    replay = clip_io.load_events(out)
    assert replay[0]["source"] == "replay" and replay[0]["participant"] == "P01" and replay[0]["scenario"] == "mouth"
    assert strip(replay) == strip(live)  # `dup` is live-only (replay cannot know), inference_ms differs


def test_replay_arbitrary_mp4_and_no_throttle(tmp_path):
    p = tmp_path / "some_video.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 320))
    for _ in range(25):
        w.write(FRAME)
    w.release()
    f = clip_io.replay_clip(p, make_pipe(), throttle=False)
    assert f["n_frames"] == f["n_processed"] == 25 and f["events_path"].endswith("some_video.events.jsonl")
    hdr = clip_io.load_events(f["events_path"])[0]
    assert hdr["participant"] is None and hdr["fps"] == 10.0 and hdr["throttle"] is False
    with pytest.raises(SystemExit):
        clip_io.replay_clip(tmp_path / "missing.mp4", make_pipe())


def test_none_clip_has_no_confirm_events(tmp_path):
    rec, footer = record(tmp_path, make_pipe(cig_conf=0.0), n_wall=90)
    evs = [e for e in clip_io.load_events(rec.dir / "events.jsonl") if e["type"] == "event"]
    assert not [e for e in evs if e["event"] == "confirm"]
    # false confirms per 10 min = confirm events / (duration_s / 600): computable from footer + events alone
    assert footer["duration_s"] > 0
