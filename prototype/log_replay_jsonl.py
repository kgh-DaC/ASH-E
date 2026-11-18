"""Equivalence-check reference log (spec 10.2 step 2): run a video through the prototype path (core PerceptionPipeline
with the default config + PrioritySelector) and write one JSONL line per frame with ash_e_core.serialize.frame_to_jsonl,
the same function the ROS dump_jsonl tool uses.

  .venv\\Scripts\\python prototype\\log_replay_jsonl.py clip.mp4 proto.jsonl [--max-frames N]

Rules that match video_to_bag + perception_node(equivalence_mode) + priority_node:
  * stamp of frame idx = round(idx * 1e9 / fps) / 1e9 s (frame 0 -> 0.0), every frame is processed (no throttle),
  * frame_id = "webcam_optical" (video_to_bag default), intrinsics from hfov_deg (core default 70, same as bag CameraInfo),
  * priority: selector.update(arr, arr.stamp) per frame, no extra tick (the ROS node also ticks at 10 Hz).
Never point this at the hold-out set (data/eval/holdout, P03): the script refuses such paths.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
from ash_e_core.config import load_perception_config, load_priority_config  # noqa: E402
from ash_e_core.pipeline import PerceptionPipeline  # noqa: E402
from ash_e_core.priority import PrioritySelector  # noqa: E402
from ash_e_core.serialize import frame_to_jsonl  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--config", default=None, help="perception yaml (default: PerceptionConfig defaults = v6)")
    ap.add_argument("--priority-config", default=None)
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--cig-model", default=str(ROOT / "models/cig_roi_v6.onnx"))
    ap.add_argument("--frame-id", default="webcam_optical")
    ap.add_argument("--fps", type=float, default=0.0, help="override the file's fps")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--no-priority", action="store_true")
    a = ap.parse_args(argv)
    low = str(Path(a.video).resolve()).lower().replace("\\", "/")
    if "holdout" in low or "/p03/" in low:
        sys.exit("refusing to read hold-out / P03 data")

    cfg = load_perception_config(a.config)
    cfg.pose_model_path, cfg.cig_model_path = a.pose, a.cig_model
    cfg.process_rate_hz, cfg.roi_every_n = 0.0, 1            # same as equivalence_mode
    pipe = PerceptionPipeline(cfg)
    if not all(pipe.models_ready.values()):
        print("WARNING: model missing %s -> results are stub output" % pipe.models_ready)
    sel = None if a.no_priority else PrioritySelector(load_priority_config(a.priority_config))
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        sys.exit("cannot open video: %s" % a.video)
    fps = a.fps or cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        sys.exit("video fps unknown; pass --fps")
    n = 0
    with open(a.out, "w", encoding="utf-8") as f:
        while True:
            ok, frame = cap.read()
            if not ok or (a.max_frames and n >= a.max_frames):
                break
            stamp = int(round(n * 1e9 / float(fps))) / 1e9        # same ns rounding as video_to_bag.frame_stamp_ns
            arr = pipe.process(frame, stamp, a.frame_id)
            st = sel.update(arr, arr.stamp) if sel is not None else None
            f.write(frame_to_jsonl(arr.frame_seq, arr.stamp, arr, st) + "\n")
            n += 1
    cap.release()
    print("wrote %d lines to %s (fps %.3f)" % (n, a.out, fps))


if __name__ == "__main__":
    main()
