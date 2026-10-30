"""Clip recording / replay helpers for run_webcam.py (--record, --replay). No GUI code here.

Layout (one clip = one directory, participant ID in the path so splits can be done per person):
  data/raw_clips/<PID>/<SESSION>/<scenario>_<NNN>/
      clip.mp4        raw frames, NO overlay (mp4v, constant frame rate = --record-fps)
      events.jsonl    line 1 "header", then one "frame" line per video frame, "event" lines in between, last "footer"
      labels.json     empty template for the human ground-truth segments (spec 9.2 format); fill it in by hand

Timeline: video frame k has time t = k / fps. The live recorder writes a frame whenever its due time has passed and
repeats the camera frame ("dup": true) when the processing loop was slower than fps, so the video clock equals
the wall clock and a label time read in a player matches events.jsonl. The pipeline is fed stamp = k / fps and is
throttled by that same clock, so replaying clip.mp4 takes exactly the same decisions as the live run (only the
lossy mp4 re-decode can change a borderline detection; inference_ms always differs).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ash_e_core"))
from ash_e_core.config import config_to_dict  # noqa: E402
from ash_e_core.serialize import to_dict  # noqa: E402
from ash_e_core.tracker import Tracker  # noqa: E402

SCHEMA_VERSION = 1
CLIP_NAME = "clip.mp4"
EVENTS_NAME = "events.jsonl"
LABELS_NAME = "labels.json"
STATE_NAMES = {0: "none", 1: "holding", 2: "smoking"}


# ---------------------------------------------------------------- validation (same rules as capture.py)
def check_ids(participant: Optional[str], session: str, scenario: str, consent: bool) -> None:
    """Exit with a message when recording is not allowed."""
    if not participant or not re.fullmatch(r"P\d{2,3}", participant):
        sys.exit("participant must look like P01 (an ID, not a name)")
    if not consent:
        sys.exit("Refusing to record: pass --consent-confirmed after getting the participant's written consent.")
    if not re.fullmatch(r"S\d{1,2}", session):
        sys.exit("session must look like S1")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,31}", scenario or ""):
        sys.exit("scenario must be lowercase letters/digits/underscore, e.g. mouth, similar, s5_mixed")


def next_clip_dir(root: Path, participant: str, session: str, scenario: str) -> Path:
    base = Path(root) / participant / session
    n = 1
    while (base / ("%s_%03d" % (scenario, n))).exists():
        n += 1
    d = base / ("%s_%03d" % (scenario, n))
    d.mkdir(parents=True)
    return d


def write_labels_template(clip_dir: Path, participant: str, session: str, scenario: str, fps: float) -> None:
    """Spec 9.2 label file with empty values. Never overwrites an existing file (hand work)."""
    p = clip_dir / LABELS_NAME
    if p.exists():
        return
    tpl = {
        "_comment": "Fill by hand. Times are seconds on the clip.mp4 timeline (same t as events.jsonl). label: "
                    "smoking|holding|none; category: cigarette|similar_object|gesture|ecig_liquid|ecig_heated|plain. "
                    "anchor = one moment where you box this person (xyxy px) so the evaluator can match the track. "
                    "Add \"occluded\": true on segments where the cigarette is hidden. Do not add people from "
                    "another participant group (spec 9A.5).",
        "schema": 1,
        "clip": CLIP_NAME,
        "fps": round(float(fps), 4),
        "camera": "webcam",
        "participants": [participant],
        "participant": participant,
        "session": session,
        "scenario": scenario,
        "split": "",
        "lighting": "",
        "distance_tag": "",
        "angle_tag": "",
        "notes": "",
        "persons": [{"person_ref": "p1", "segments": [], "anchor": {"t": None, "bbox_xyxy": None}}],
        "segment_example": {"t0": None, "t1": None, "label": "", "category": ""},
    }
    p.write_text(json.dumps(tpl, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- pipeline helpers
def reset_pipeline(pipe) -> None:
    """Fresh tracker/stabilizers/frame counter so a clip starts from the same state as its replay."""
    pipe.tracker = Tracker(pipe.cfg)
    pipe.stabs = {}
    pipe.frame_seq = 0


def _sha16(path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return None


# ---------------------------------------------------------------- events.jsonl writer
class EventLog:
    """Writes header / frame / event / footer lines.

    frame line  : frame_idx, t, processed (pipeline ran on this frame; else tracks are carried over from the last
                  processed frame), dup, frame_seq, inference_ms, detections (serialize.to_dict of each Detection:
                  track_id, state, state_confidence, raw_state, raw_confidence, cigarette_checked, bbox_*,
                  distance_m, distance_source (1 = PROXY), ... + "confirmed" = state != none).
    event line  : type "event", event in {track_new, confirm, state_change, release, track_lost}, frame_idx, t,
                  track_id, from_state, to_state, state_confidence, distance_m. Built only from processed frames.
    """

    def __init__(self, path: Path, header: dict):
        self.path = Path(path)
        self.f = open(self.path, "w", encoding="utf-8")
        self.prev: Dict[int, int] = {}
        self.n_frames = self.n_processed = self.n_dup = 0
        self.inf_sum = 0.0
        self.events: List[dict] = []
        self.last_dets: List[dict] = []
        self._w(dict(type="header", schema=SCHEMA_VERSION, **header))

    def _w(self, rec: dict) -> None:
        self.f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")

    def add_frame(self, idx: int, t: float, arr, processed: bool, dup: bool) -> None:
        self.n_frames += 1
        self.n_dup += int(dup)
        t = round(float(t), 4)
        rec = {"type": "frame", "frame_idx": int(idx), "t": t, "processed": bool(processed), "dup": bool(dup)}
        if processed and arr is not None:
            self.n_processed += 1
            self.inf_sum += arr.inference_ms
            dets = []
            for d in arr.detections:
                dd = to_dict(d)
                dd["confirmed"] = int(d.state) != 0
                dets.append(dd)
            rec.update(frame_seq=arr.frame_seq, inference_ms=round(float(arr.inference_ms), 2), detections=dets)
            self._events(idx, t, arr)
            self.last_dets = dets
        else:
            rec.update(frame_seq=None, inference_ms=None, detections=self.last_dets)
        self._w(rec)
        if self.n_frames % 30 == 0:
            self.f.flush()

    def _events(self, idx: int, t: float, arr) -> None:
        cur = {d.track_id: d for d in arr.detections}
        for tid, d in sorted(cur.items()):
            old = self.prev.get(tid)
            new = int(d.state)
            if old is None:
                self._ev("track_new", idx, t, tid, None, new, d)
                old = 0
            if new != old:
                kind = "confirm" if old == 0 else ("release" if new == 0 else "state_change")
                self._ev(kind, idx, t, tid, old, new, d)
            self.prev[tid] = new
        for tid in [k for k in self.prev if k not in cur]:
            self._ev("track_lost", idx, t, tid, self.prev[tid], None, None)
            del self.prev[tid]

    def _ev(self, kind, idx, t, tid, old, new, d) -> None:
        rec = {"type": "event", "event": kind, "frame_idx": int(idx), "t": t, "track_id": int(tid),
               "from_state": old, "to_state": new,
               "state_confidence": round(float(d.state_confidence), 4) if d is not None else None,
               "distance_m": round(float(d.distance_m), 3) if d is not None else None}
        self.events.append(rec)
        self._w(rec)

    def close(self, fps: float) -> dict:
        footer = {"type": "footer", "n_frames": self.n_frames, "n_processed": self.n_processed,
                  "n_dup": self.n_dup, "duration_s": round(self.n_frames / fps, 4) if fps > 0 else None,
                  "mean_inference_ms": round(self.inf_sum / self.n_processed, 2) if self.n_processed else 0.0,
                  "n_events": len(self.events)}
        self._w(footer)
        self.f.close()
        return footer


def make_header(*, source: str, pipe, fps: float, width: int, height: int, rate_hz: float, throttle: bool,
                clip: str, participant=None, session=None, scenario=None, clip_dir=None, extra=None) -> dict:
    cfg = pipe.cfg
    h = {"source": source, "clip": clip, "created": datetime.now().isoformat(timespec="seconds"),
         "fps": round(float(fps), 4), "width": int(width), "height": int(height),
         "process_rate_hz": float(rate_hz), "throttle": bool(throttle),
         "participant": participant, "session": session, "scenario": scenario,
         "distance_source": "proxy (box height based, stage A)", "models_ready": pipe.models_ready,
         "models": {"pose": {"path": cfg.pose_model_path, "sha256_16": _sha16(cfg.pose_model_path)},
                    "cigarette": {"path": cfg.cig_model_path, "sha256_16": _sha16(cfg.cig_model_path)}},
         "config": config_to_dict(cfg)}
    if extra:
        h.update(extra)
    return h


# ---------------------------------------------------------------- shared per-frame step (live record AND replay)
class ClipRunner:
    """Feeds frames of one clip to the pipeline on the clip clock (t = idx / fps) and logs them."""

    def __init__(self, pipe, fps: float, rate_hz: float, throttle: bool, log: EventLog):
        self.pipe, self.fps, self.rate, self.throttle, self.log = pipe, float(fps), float(rate_hz), throttle, log
        self.last_proc = -1e9
        self.arr = None
        reset_pipeline(pipe)

    def step(self, frame, idx: int, dup: bool = False):
        """Returns (processed, latest DetectionArray or None)."""
        t = idx / self.fps
        processed = (not self.throttle) or (t - self.last_proc >= 1.0 / self.rate - 1e-9)
        if processed:
            self.last_proc = t
            self.arr = self.pipe.process(frame, t)
        self.log.add_frame(idx, t, self.arr if processed else None, processed, dup)
        return processed, self.arr

    def close(self) -> dict:
        return self.log.close(self.fps)


# ---------------------------------------------------------------- live recording of one clip
class ClipRecorder:
    """One clip: raw video writer + events log. Call feed(frame, now) for every camera frame while active."""

    def __init__(self, pipe, root: Path, participant: str, session: str, scenario: str, fps: float,
                 rate_hz: float, throttle: bool = True):
        self.pipe, self.fps = pipe, float(fps)
        self.dir = next_clip_dir(root, participant, session, scenario)
        self.ids = (participant, session, scenario)
        self.rate, self.throttle = rate_hz, throttle
        self.writer = None
        self.runner: Optional[ClipRunner] = None
        self.t0: Optional[float] = None
        self.written = 0
        self.size = None
        write_labels_template(self.dir, participant, session, scenario, fps)

    def _open(self, frame, now):
        h, w = frame.shape[:2]
        self.size = (w, h)
        self.writer = cv2.VideoWriter(str(self.dir / CLIP_NAME), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
        if not self.writer.isOpened():
            self.writer = None
            sys.exit("cannot open mp4 writer (mp4v) for %s" % (self.dir / CLIP_NAME))
        hdr = make_header(source="record", pipe=self.pipe, fps=self.fps, width=w, height=h, rate_hz=self.rate,
                          throttle=self.throttle, clip=CLIP_NAME, participant=self.ids[0], session=self.ids[1],
                          scenario=self.ids[2])
        self.runner = ClipRunner(self.pipe, self.fps, self.rate, self.throttle, EventLog(self.dir / EVENTS_NAME, hdr))
        self.t0 = now

    @property
    def elapsed(self) -> float:
        return 0.0 if self.t0 is None else self.written / self.fps

    def feed(self, frame, now: float):
        """Write the frame (repeated if we are late) and run the pipeline. Returns latest DetectionArray or None."""
        if self.writer is None:
            self._open(frame, now)
        if frame.shape[1::-1] != self.size:
            return self.runner.arr  # camera changed size mid-clip: skip rather than corrupt the clip
        n_due = int((now - self.t0) * self.fps) + 1 - self.written
        for k in range(max(n_due, 0)):
            self.writer.write(frame)
            self.runner.step(frame, self.written, dup=k > 0)
            self.written += 1
        return self.runner.arr

    def stop(self) -> Optional[dict]:
        """Finish the clip. A clip with zero frames is removed. Returns the footer (or None)."""
        if self.runner is None:
            _rm_empty(self.dir)
            return None
        self.writer.release()
        footer = self.runner.close()
        reset_pipeline(self.pipe)
        return footer


def _rm_empty(d: Path) -> None:
    for f in d.iterdir():
        f.unlink()
    d.rmdir()


# ---------------------------------------------------------------- replay
def replay_clip(clip: Path, pipe, out: Optional[Path] = None, rate_hz: float = 8.0, throttle: bool = True,
                fps_override: Optional[float] = None) -> dict:
    """Run the model again over a recorded clip and write events (default: next to the clip, never overwriting
    the live events.jsonl). Needs no camera. Returns the footer."""
    clip = Path(clip)
    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        sys.exit("cannot open clip: %s" % clip)
    fps = float(fps_override or cap.get(cv2.CAP_PROP_FPS) or 0)
    if not (1.0 <= fps <= 240.0):
        sys.exit("clip has no usable fps (got %r); pass --replay-fps" % fps)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if out is None:
        out = clip.with_name("events.replay.jsonl") if clip.name == CLIP_NAME else clip.with_suffix(".events.jsonl")
    ids = _ids_from_path(clip)
    hdr = make_header(source="replay", pipe=pipe, fps=fps, width=w, height=h, rate_hz=rate_hz, throttle=throttle,
                      clip=clip.name, participant=ids[0], session=ids[1], scenario=ids[2])
    runner = ClipRunner(pipe, fps, rate_hz, throttle, EventLog(Path(out), hdr))
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        runner.step(frame, idx)
        idx += 1
    cap.release()
    footer = runner.close()
    reset_pipeline(pipe)
    footer["events_path"] = str(out)
    return footer


def _ids_from_path(clip: Path):
    """participant/session/scenario from .../<PID>/<SESSION>/<scenario>_<NNN>/clip.mp4, else Nones."""
    try:
        d = clip.resolve().parent
        m = re.fullmatch(r"([a-z0-9_]+)_(\d{3})", d.name)
        if m and re.fullmatch(r"S\d{1,2}", d.parent.name) and re.fullmatch(r"P\d{2,3}", d.parent.parent.name):
            return d.parent.parent.name, d.parent.name, m.group(1)
    except OSError:
        pass
    return None, None, None


def load_events(path) -> List[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
