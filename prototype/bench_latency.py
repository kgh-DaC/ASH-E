"""Latency / throughput benchmark for the paper report (stage-wise breakdown). CPU only, onnxruntime.

  python prototype/bench_latency.py                       # synthetic 1280x720 frames, 3 synthetic persons
  python prototype/bench_latency.py --clip data/eval/dev/<clip>/clip.mp4   # real frames for the end-to-end loop
  python prototype/bench_latency.py --n 300 --warmup 30 --persons 3 --out _workspace/paper/latency.json

Stages (each timed per iteration, `total` = per-iteration sum, so its p95 is a real p95 and not a sum of p95s):
  pose  PoseModel.detect() on the frame (letterbox + ONNX + decode)           [real frame / synthetic frame]
  roi   compute_rois() for N synthetic persons (pure numpy)
  cig   CigaretteRoiModel.detect_crops() on the ROIs of those N persons (ONNX per ROI)
  stab  Stabilizer.update() for N tracks
`end_to_end` = PerceptionPipeline.process() on the same frames (with a synthetic frame no person is found, so it only
shows the pose cost; give --clip for a meaningful end-to-end number).

THIS IS A WINDOWS PC NUMBER, NOT RPi5. The RPi5 >= 5 Hz criterion is measured in stage B. Never reads data/eval/holdout
(a --clip under protected folders is refused). No acceptance/ access.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
from dataset_utils import refuse_holdout  # noqa: E402

STAGES = ("pose", "roi", "cig", "stab")


def cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(errors="ignore").splitlines():
                if line.lower().startswith(("model name", "hardware", "model")) and ":" in line:
                    return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or "unknown"


def model_info(path: str) -> dict:
    """File size and parameter count (sum of ONNX initializer elements). Missing file -> present False."""
    p = Path(path)
    if not p.is_file():
        return dict(path=str(path), present=False)
    d = dict(path=str(path), present=True, onnx_bytes=p.stat().st_size, params=None)
    try:
        import onnx
        m = onnx.load(str(p), load_external_data=False)
        d["params"] = int(sum(int(np.prod(t.dims)) for t in m.graph.initializer))
    except Exception as e:  # noqa: BLE001
        d["params_error"] = str(e)
    return d


def stats(x) -> dict:
    a = np.asarray(x, float)
    if a.size == 0:
        return dict(n=0, mean=None, median=None, p95=None, min=None, max=None)
    return dict(n=int(a.size), mean=float(a.mean()), median=float(np.median(a)), p95=float(np.percentile(a, 95)),
                min=float(a.min()), max=float(a.max()))


def synthetic_frame(w=1280, h=720, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.linspace(40, 200, w, dtype=np.uint8)[None, :, None].repeat(h, 0).repeat(3, 2)
    return (base + rng.integers(0, 20, base.shape, dtype=np.uint8)).astype(np.uint8)


def synthetic_person(frame_w, frame_h, k, n):
    """Standing person with plausible keypoints (COCO order) so compute_rois yields a mouth and two hand ROIs."""
    from ash_e_core.types import PersonPose
    bh = 0.7 * frame_h
    bw = 0.25 * bh
    cx = frame_w * (k + 1) / (n + 1)
    y1 = 0.15 * frame_h
    box = np.array([cx - bw / 2, y1, cx + bw / 2, y1 + bh], np.float32)
    kp = np.zeros((17, 3), np.float32)
    kp[:, 2] = 0.9
    head = 0.12 * bh
    kp[0] = (cx, y1 + 0.5 * head, 0.9)                       # nose
    kp[1] = (cx - 0.2 * head, y1 + 0.4 * head, 0.9)
    kp[2] = (cx + 0.2 * head, y1 + 0.4 * head, 0.9)
    kp[3] = (cx - 0.45 * head, y1 + 0.5 * head, 0.9)
    kp[4] = (cx + 0.45 * head, y1 + 0.5 * head, 0.9)
    kp[5] = (cx - 0.5 * bw, y1 + 0.2 * bh, 0.9)             # shoulders
    kp[6] = (cx + 0.5 * bw, y1 + 0.2 * bh, 0.9)
    kp[9] = (cx - 0.4 * bw, y1 + 0.45 * bh, 0.9)            # wrists
    kp[10] = (cx + 0.4 * bw, y1 + 0.45 * bh, 0.9)
    return PersonPose(box, 0.9, kp)


def frame_source(clip: str | None, n_needed: int):
    """Yield frames. Synthetic when no clip; clip frames loop."""
    if not clip:
        f = synthetic_frame()
        while True:
            yield f
    import cv2
    cap = cv2.VideoCapture(clip)
    frames = []
    while len(frames) < min(n_needed, 300):
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    cap.release()
    if not frames:
        sys.exit("no frames could be read from %s" % clip)
    i = 0
    while True:
        yield frames[i % len(frames)]
        i += 1


def run(args) -> dict:
    from ash_e_core.backends import load_model
    from ash_e_core.config import config_to_dict, load_perception_config
    from ash_e_core.pipeline import PerceptionPipeline
    from ash_e_core.roi import compute_rois
    from ash_e_core.stabilizer import Stabilizer
    import onnxruntime as ort

    cfg = load_perception_config(args.config)
    if args.threads:
        cfg.num_threads = args.threads
    pose = load_model(args.pose, "onnxruntime", cfg.num_threads)
    cig = load_model(args.cig_model, "onnxruntime", cfg.num_threads)
    if getattr(pose, "is_stub", False):
        sys.exit("pose model missing: %s" % args.pose)
    cig_stub = getattr(cig, "is_stub", False)
    if cig_stub:
        print("WARNING: cigarette model missing (%s): cig stage not timed (null), models list marks it absent" % args.cig_model)
    pipe = PerceptionPipeline(cfg, pose_model=pose, cig_model=cig)
    src = frame_source(args.clip, args.n + args.warmup)
    first = next(src)
    H, W = first.shape[:2]
    persons = [synthetic_person(W, H, k, args.persons) for k in range(args.persons)]
    stabs = [Stabilizer(cfg) for _ in persons]
    rois_flat = [r.xyxy for p in persons for r in compute_rois(p, cfg, W, H)]
    per = {s: [] for s in STAGES}
    tot, e2e = [], []
    pc = time.perf_counter
    for i in range(args.warmup + args.n):
        fr = next(src)
        t0 = pc()
        pipe.pose.detect(fr)
        t1 = pc()
        rois = [compute_rois(p, cfg, W, H) for p in persons]
        t2 = pc()
        if not cig_stub:
            pipe.cig.detect_crops(fr, rois_flat)
        t3 = pc()
        for j, s in enumerate(stabs):
            s.update(i / 8.0, True, 0, 0.0)
        t4 = pc()
        t5 = pc()
        pipe.process(fr, i / 8.0)
        t6 = pc()
        if i < args.warmup:
            continue
        ms = [(t1 - t0) * 1e3, (t2 - t1) * 1e3, (t3 - t2) * 1e3, (t4 - t3) * 1e3]
        for s, v in zip(STAGES, ms):
            per[s].append(v)
        tot.append(sum(ms))
        e2e.append((t6 - t5) * 1e3)
    fps = [1000.0 / v for v in tot if v > 0]
    out = dict(
        schema="bench_latency/1", synthetic_input=not bool(args.clip), platform_note="Windows PC measurement, NOT RPi5",
        when=datetime.now().isoformat(timespec="seconds"), command=" ".join(sys.argv),
        env=dict(cpu=cpu_name(), logical_cpus=os.cpu_count(), ort_threads=int(cfg.num_threads), onnxruntime=ort.__version__,
                 numpy=np.__version__, python=platform.python_version(), os=platform.platform()),
        params=dict(n=args.n, warmup=args.warmup, persons=args.persons, frame=[W, H], rois_per_frame=len(rois_flat),
                    clip=args.clip),
        stages_ms={s: (stats(per[s]) if not (s == "cig" and cig_stub) else None) for s in STAGES},
        total_ms=stats(tot), end_to_end_ms=stats(e2e), fps=stats(fps), fps_samples=[round(v, 2) for v in fps],
        models=dict(pose=model_info(args.pose), cig=model_info(args.cig_model)),
        config=config_to_dict(cfg))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--cig-model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--clip", default=None, help="optional dev clip mp4 (frames loop); default synthetic frames")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--persons", type=int, default=3)
    ap.add_argument("--threads", type=int, default=0, help="override cfg.num_threads")
    ap.add_argument("--out", default=str(ROOT / "_workspace/paper/latency.json"))
    a = ap.parse_args(argv)
    if a.clip:
        refuse_holdout(Path(a.clip))
    res = run(a)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    t = res["total_ms"]
    print("cpu=%s threads=%d ort=%s | total median %.1f ms p95 %.1f ms | fps median %.1f | stages(median ms) %s | end-to-end median %s ms"
          % (res["env"]["cpu"], res["env"]["ort_threads"], res["env"]["onnxruntime"], t["median"], t["p95"], res["fps"]["median"],
             {k: (round(v["median"], 2) if v else None) for k, v in res["stages_ms"].items()},
             "%.1f" % res["end_to_end_ms"]["median"]))
    print("Windows PC number, NOT RPi5. ->", out)
    return res


if __name__ == "__main__":
    main()
