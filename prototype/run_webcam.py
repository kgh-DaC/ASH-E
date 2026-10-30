"""Live demo on the laptop webcam: person + keypoints + cigarette -> none / holding / smoking (stabilized), FPS.

  python prototype/run_webcam.py                          # camera 0, 1280x720 requested, q to quit
  python prototype/run_webcam.py --cig-model training/runs/smoke/weights/best.onnx
  python prototype/run_webcam.py --video clip.mp4         # file instead of camera
  python prototype/run_webcam.py --no-gui --max-seconds 8 # headless check (prints stats, saves nothing unless --save-last)
  python prototype/run_webcam.py --record --participant P01 --session S1 --scenario mouth --consent-confirmed
        # keys: r = start/stop one clip, q = quit (an open clip is finished). Raw frames (no overlay) + events.jsonl +
        # labels.json template go to data/raw_clips/<PID>/<SESSION>/<scenario>_<NNN>/ (see prototype/clip_io.py)
  python prototype/run_webcam.py --replay data/raw_clips/P01/S1/mouth_001/clip.mp4   # re-run the models, no camera

Models: models/pose.onnx (YOLO11n-pose, 320) and models/cig_roi.onnx (trained ROI detector). If a model is missing the
program still starts and shows "NO MODEL" on screen (Korean text cannot be drawn by cv2, so the banner is ASCII; the
console prints the Korean message). If models/pose.onnx is missing it is exported once from yolo11n-pose.pt through
ultralytics (auto-download of the .pt from the ultralytics release if needed) -- the download is logged to the console.
Nothing is recorded or sent anywhere; frames stay in memory unless --save-last or --record is given.
Distances are PROXY values (box height based), not measurements.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from collections import deque
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
from ash_e_core.config import load_perception_config  # noqa: E402
from ash_e_core.pipeline import PerceptionPipeline  # noqa: E402
from ash_e_core.viz import draw_detections, NAMES, COLORS  # noqa: E402
import clip_io  # noqa: E402  (prototype/clip_io.py: clip recording + replay)


def ensure_pose_onnx(path: Path):
    if path.is_file():
        return
    print("pose model missing -> exporting from yolo11n-pose (ultralytics may download the .pt now)")
    from ultralytics import YOLO  # lazy: only in this prototype
    pt = ROOT / "models/yolo11n-pose.pt"
    if not pt.is_file():
        print("DOWNLOAD: yolo11n-pose.pt via ultralytics auto-download (record this in data/SOURCES.md)")
    m = YOLO(str(pt) if pt.is_file() else "yolo11n-pose.pt")
    p = m.export(format="onnx", imgsz=320, opset=17, simplify=False, dynamic=False, batch=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(p, path)


def open_source(a):
    if a.video:
        cap = cv2.VideoCapture(a.video)
    else:
        cap = cv2.VideoCapture(a.camera, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(a.camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)    # explicit: default open may give 640x480
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
    return cap


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--video", default=None)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--config", default=None)
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--cig-model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--rate", type=float, default=None, help="processing rate Hz (default process_rate_hz=8, RPi5-like)")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=0.0, help="stop after N s (0 = until q)")
    ap.add_argument("--save-last", default=None, help="write the last annotated frame here (contains a face; keep local)")
    rec = ap.add_argument_group("clip recording / replay (spec 9.2, table B)")
    rec.add_argument("--record", action="store_true", help="record clips with key r (needs the options below)")
    rec.add_argument("--participant", default=None, help="e.g. P01 (ID only, never a name)")
    rec.add_argument("--session", default="S1")
    rec.add_argument("--scenario", default=None, help="e.g. mouth, holding, none, similar, gesture, s5_mixed")
    rec.add_argument("--consent-confirmed", action="store_true",
                     help="I confirm this adult participant gave written consent (spec 9A.3).")
    rec.add_argument("--record-fps", type=float, default=15.0, help="clip frame rate (spec: >= 15)")
    rec.add_argument("--record-out", default=str(ROOT / "data/raw_clips"))
    rec.add_argument("--record-auto", type=float, default=0.0,
                     help="start one clip at launch, stop and exit after N s (headless test, no key needed)")
    rec.add_argument("--replay", default=None, help="clip.mp4 to re-run through the models (no camera needed)")
    rec.add_argument("--replay-out", default=None, help="events file (default: events.replay.jsonl next to the clip)")
    rec.add_argument("--no-throttle", action="store_true", help="replay: process every frame instead of --rate Hz")
    a = ap.parse_args()

    if a.record and (a.video or a.replay):
        sys.exit("--record needs the live camera (not --video/--replay)")
    if a.record:  # same refusals as capture.py, before anything is opened
        clip_io.check_ids(a.participant, a.session, a.scenario, a.consent_confirmed)
        if a.no_gui and not a.record_auto:
            sys.exit("--record with --no-gui has no keys: add --record-auto SECONDS")
    elif a.record_auto:
        sys.exit("--record-auto needs --record")

    cfg = load_perception_config(a.config)
    cfg.pose_model_path, cfg.cig_model_path = a.pose, a.cig_model
    rate = a.rate or cfg.process_rate_hz
    try:
        ensure_pose_onnx(Path(a.pose))
    except Exception as e:  # noqa: BLE001
        print("could not prepare pose model:", e)
    pipe = PerceptionPipeline(cfg)
    ready = pipe.models_ready
    if not ready["pose"] or not ready["cigarette"]:
        print("모델 없음: pose=%s cigarette=%s  (cigarette: python training/train_cig_roi.py ... 후 export_onnx.py)" % (
            "OK" if ready["pose"] else "MISSING", "OK" if ready["cigarette"] else "MISSING"))

    if a.replay:
        footer = clip_io.replay_clip(Path(a.replay), pipe, Path(a.replay_out) if a.replay_out else None,
                                     rate_hz=rate, throttle=not a.no_throttle)
        print("REPLAY: %d frames, %d processed, %d events, mean inference %.1f ms -> %s" % (
            footer["n_frames"], footer["n_processed"], footer["n_events"], footer["mean_inference_ms"],
            footer["events_path"]))
        return

    cap = open_source(a)
    if not cap.isOpened():
        sys.exit("cannot open camera/video")
    got = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    print("source opened: %dx%d (requested %dx%d)" % (got[0], got[1], a.width, a.height))

    t_start = time.monotonic()
    last_proc, arr, dbg = -1e9, None, None
    disp_t, proc_t, inf_ms = deque(maxlen=30), deque(maxlen=30), deque(maxlen=30)
    n_frames = n_proc = 0
    last = None
    recorder, rec_fps, clips_done, auto_started = None, a.record_fps, 0, False

    def stop_clip():
        nonlocal recorder, clips_done, arr, dbg
        footer = recorder.stop()
        if footer:
            clips_done += 1
            print("clip saved: %s (%d frames, %.1f s, %d dup, %d events)" % (
                recorder.dir, footer["n_frames"], footer["duration_s"], footer["n_dup"], footer["n_events"]))
        else:
            print("clip discarded (no frames):", recorder.dir)
        recorder, arr, dbg = None, None, None

    while True:
        ok, frame = cap.read()
        if not ok:
            if a.video:
                break
            time.sleep(0.02)
            if time.monotonic() - t_start > 5 and n_frames == 0:
                sys.exit("camera gives no frames")
            continue
        now = time.monotonic()
        n_frames += 1
        disp_t.append(now)
        if a.record and a.record_auto and not auto_started:
            auto_started = True
            recorder = clip_io.ClipRecorder(pipe, Path(a.record_out), a.participant, a.session, a.scenario,
                                            rec_fps, rate)
        if recorder is not None:  # recording: the clip clock (frame idx / fps) drives the pipeline, not `now`
            new = recorder.feed(frame, now)  # writes the RAW frame first; overlay is drawn on a copy below
            if new is not None and (arr is None or new.frame_seq != arr.frame_seq):
                inf_ms.append(new.inference_ms)
            arr, dbg = new, pipe.last
        elif now - last_proc >= 1.0 / rate:
            last_proc = now
            arr = pipe.process(frame, now - t_start)
            dbg = pipe.last
            proc_t.append(now)
            inf_ms.append(arr.inference_ms)
            n_proc += 1
        out = frame.copy()
        if arr is not None:
            draw_detections(out, arr, dbg)
        fps_d = (len(disp_t) - 1) / (disp_t[-1] - disp_t[0]) if len(disp_t) > 1 and disp_t[-1] > disp_t[0] else 0.0
        fps_p = (len(proc_t) - 1) / (proc_t[-1] - proc_t[0]) if len(proc_t) > 1 and proc_t[-1] > proc_t[0] else 0.0
        ms = sum(inf_ms) / len(inf_ms) if inf_ms else 0.0
        cv2.putText(out, "cam %.0f fps | infer %.1f Hz (%.0f ms) | %dx%d | PROXY dist" % (fps_d, fps_p, ms, out.shape[1], out.shape[0]),
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        if not ready["pose"] or not ready["cigarette"]:
            msg = "NO MODEL: " + ", ".join(k for k, v in ready.items() if not v) + " (state stays none)"
            cv2.putText(out, msg, (8, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        y = out.shape[0] - 10
        for s in (0, 1, 2):
            cv2.putText(out, NAMES[s], (8 + 110 * s, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS[s], 2)
        cv2.putText(out, "r: rec | q: quit" if a.record else "q: quit", (out.shape[1] - (160 if a.record else 90), y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        if a.record:
            if recorder is not None:
                cv2.putText(out, "REC %s %s_%s  %.1f s  (r: stop)" % (a.participant, a.scenario, recorder.dir.name[-3:],
                            recorder.elapsed), (8, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                cv2.putText(out, "not recording (r: start clip, %d saved)" % clips_done, (8, 74),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        last = out
        if not a.no_gui:
            cv2.imshow("ASH-E webcam prototype", out)
            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("r") and a.record:
                if recorder is None:
                    recorder = clip_io.ClipRecorder(pipe, Path(a.record_out), a.participant, a.session, a.scenario,
                                                    rec_fps, rate)
                    arr = dbg = None
                else:
                    stop_clip()
        if a.record_auto and recorder is not None and recorder.elapsed >= a.record_auto:
            stop_clip()
            break
        if a.max_seconds and now - t_start >= a.max_seconds:
            break
    if recorder is not None:  # q / max-seconds while a clip is open: finish it properly
        stop_clip()
    cap.release()
    cv2.destroyAllWindows()
    dur = time.monotonic() - t_start
    print("RUN SUMMARY: %.1f s, %d frames read (%.1f fps), %d processed (%.1f Hz), mean inference %.1f ms, persons in last frame: %s" % (
        dur, n_frames, n_frames / dur, n_proc, n_proc / dur, (sum(inf_ms) / len(inf_ms)) if inf_ms else 0.0,
        len(arr.detections) if arr else 0))
    if a.save_last and last is not None:
        cv2.imwrite(a.save_last, last)
        print("saved last frame:", a.save_last)


if __name__ == "__main__":
    main()
