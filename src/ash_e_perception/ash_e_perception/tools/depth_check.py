"""Proxy vs Astra Pro depth check (spec 10.5). Runs the core twice per frame: depth=None (PROXY) and depth=aligned depth.
No ROS needed for --dir; --bag needs rosbag2_py (on the RPi5).

Input A (--dir): folder with color_000000.png (BGR) and depth_000000.png (16-bit PNG, millimetres), optional
    stamps.csv ("index,stamp_s"); without it stamp = index / --fps.
Input B (--bag): rosbag2 with --color-topic and --depth-topic (16UC1 mm or 32FC1 m); frames are paired by nearest
    stamp within --slop-s. The pair stamp differences are reported (10.5-6).
Calibration: --extrinsics astra_pro_extrinsics.yaml (intrinsics of both cameras come from it).

  depth_check --dir rec_2m --extrinsics astra_pro_extrinsics.yaml --ref-m 2.0 --csv rec_2m.csv
Prints a markdown summary: counts, PROXY vs DEPTH distance (mean ratio, std, sign), error vs --ref-m (tape measure),
valid depth ratio, alignment determinism (10.5-7), color/depth stamp difference median / p95 (10.5-6).
Paste the tables into _workspace/02b_perception_notes.md.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import statistics
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from ash_e_core.types import DistanceSource


# ----------------------------------------------------------------- pure helpers (tested)
def pair_nearest(color_stamps: Sequence[float], depth_stamps: Sequence[float], slop_s: float) -> List[Tuple[int, Optional[int], Optional[float]]]:
    """For every color index the nearest depth index within slop (None if none). Returns (ci, di, depth-color dt)."""
    out = []
    ds = np.asarray(depth_stamps, float)
    for ci, cs in enumerate(color_stamps):
        if ds.size == 0:
            out.append((ci, None, None))
            continue
        j = int(np.argmin(np.abs(ds - cs)))
        dt = float(ds[j] - cs)
        out.append((ci, j, dt) if abs(dt) <= slop_s else (ci, None, None))
    return out


def _pct(vals: Sequence[float], q: float) -> float:
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))] if s else 0.0


def summarize(rows: List[dict], ref_m: Optional[float] = None, dts: Sequence[float] = (),
              valid_ratios: Sequence[float] = (), deterministic: Optional[bool] = None) -> str:
    """rows: dicts with proxy_m, depth_m (None if the DEPTH source was not used), depth_src. Markdown text."""
    both = [r for r in rows if r.get("depth_m") is not None and r.get("proxy_m") is not None]
    L = ["| item | value |", "| --- | --- |", "| detections (frames x tracks) | %d |" % len(rows),
         "| with DEPTH distance | %d |" % len(both),
         "| fell back to PROXY (depth invalid) | %d |" % (len(rows) - len(both))]
    if both:
        ratio = [r["proxy_m"] / r["depth_m"] for r in both]
        diff = [r["proxy_m"] - r["depth_m"] for r in both]
        L += ["| proxy / depth ratio mean (>1 = proxy overestimates) | %.3f |" % statistics.mean(ratio),
              "| proxy / depth ratio std | %.3f |" % (statistics.pstdev(ratio)),
              "| proxy - depth mean / std [m] | %.3f / %.3f |" % (statistics.mean(diff), statistics.pstdev(diff)),
              "| depth distance mean [m] | %.3f |" % statistics.mean(r["depth_m"] for r in both)]
    if ref_m:
        for name in ("depth_m", "proxy_m"):
            v = [r[name] for r in rows if r.get(name) is not None]
            if v:
                err = [(x - ref_m) / ref_m * 100.0 for x in v]
                L.append("| %s error vs ref %.2f m: mean %.1f %% , worst |.| %.1f %% (n=%d) |" % (
                    name, ref_m, statistics.mean(err), max(abs(e) for e in err), len(v)))
    if valid_ratios:
        L.append("| aligned depth valid ratio mean | %.3f |" % statistics.mean(valid_ratios))
    if dts:
        a = [abs(x) * 1000.0 for x in dts]
        L.append("| color-depth stamp |dt| median / p95 [ms] | %.0f / %.0f |" % (statistics.median(a), _pct(a, 0.95)))
    if deterministic is not None:
        L.append("| alignment deterministic (same input twice) | %s |" % ("yes" if deterministic else "NO"))
    return "\n".join(L)


# ----------------------------------------------------------------- input readers
def iter_dir(d: str, fps: float):
    import cv2
    colors = sorted(glob.glob(os.path.join(d, "color_*.png")))
    stamps = {}
    sp = os.path.join(d, "stamps.csv")
    if os.path.isfile(sp):
        with open(sp, newline="") as f:
            for r in csv.reader(f):
                try:
                    stamps[int(r[0])] = float(r[1])
                except (ValueError, IndexError):
                    pass
    for i, cp in enumerate(colors):
        idx = int(os.path.basename(cp)[6:-4])
        dp = os.path.join(d, "depth_%s.png" % os.path.basename(cp)[6:-4])
        if not os.path.isfile(dp):
            continue
        col = cv2.imread(cp, cv2.IMREAD_COLOR)
        dep = cv2.imread(dp, cv2.IMREAD_UNCHANGED)
        if col is None or dep is None:
            continue
        yield stamps.get(idx, idx / fps), col, dep.astype(np.float32) * 0.001, None


def iter_bag(path: str, color_topic: str, depth_topic: str, slop_s: float):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import Image
    from ..inputs import depth_to_meters, image_msg_to_numpy, stamp_to_sec

    r = rosbag2_py.SequentialReader()
    r.open(rosbag2_py.StorageOptions(uri=path, storage_id="sqlite3"), rosbag2_py.ConverterOptions("", ""))
    colors, depths = [], []
    while r.has_next():
        topic, data, _ = r.read_next()
        if topic == color_topic:
            m = deserialize_message(data, Image)
            colors.append((stamp_to_sec(m.header.stamp.sec, m.header.stamp.nanosec), image_msg_to_numpy(m, want_bgr=True)))
        elif topic == depth_topic:
            m = deserialize_message(data, Image)
            depths.append((stamp_to_sec(m.header.stamp.sec, m.header.stamp.nanosec),
                           depth_to_meters(image_msg_to_numpy(m), m.encoding)))
    for ci, di, dt in pair_nearest([c[0] for c in colors], [d[0] for d in depths], slop_s):
        yield colors[ci][0], colors[ci][1], (depths[di][1] if di is not None else None), dt


# ----------------------------------------------------------------- main
def run(frames: Iterable, cal, cfg, frame_id: str = "color_optical"):
    from ash_e_core.backends import load_model
    from ash_e_core.depth_align import DepthAligner
    from ash_e_core.pipeline import PerceptionPipeline
    from .. import inputs

    pose_m = load_model(cfg.pose_model_path, cfg.backend, cfg.num_threads)
    cig_m = load_model(cfg.cig_model_path, cfg.backend, cfg.num_threads)
    p_proxy = PerceptionPipeline(cfg, pose_m, cig_m)
    p_depth = PerceptionPipeline(cfg, pose_m, cig_m)
    aligner = DepthAligner(cal.intr_depth, cal.intr_color, cal.extr, cfg.depth_align_decimate,
                           pixel_offset_uv=cal.depth_pixel_offset_uv)
    rows, valid, dts, det_ok = [], [], [], None
    for stamp, color, depth, dt in frames:
        if dt is not None:
            dts.append(dt)
        h, w = color.shape[:2]
        if (w, h) != (cal.intr_color.width, cal.intr_color.height):
            raise SystemExit("color size %dx%d != calibration color_size %dx%d" % (
                w, h, cal.intr_color.width, cal.intr_color.height))
        intr = cal.intr_color
        a = p_proxy.process(color, stamp, frame_id, None, intr)
        if depth is None:
            continue
        aligned = aligner.align(depth)
        if det_ok is None:
            det_ok = bool(np.array_equal(aligned, aligner.align(depth)))
        valid.append(inputs.valid_depth_ratio(aligned, cfg.depth_min_m, cfg.depth_max_m))
        b = p_depth.process(color, stamp, frame_id, aligned, intr)
        proxy_by_id = {d.track_id: d for d in a.detections}
        for d in b.detections:
            pd_ = proxy_by_id.get(d.track_id)
            rows.append({"stamp": stamp, "track_id": d.track_id,
                         "proxy_m": pd_.position.z if pd_ is not None else None,
                         "depth_m": d.position.z if d.distance_source == DistanceSource.DEPTH else None,
                         "depth_src": int(d.distance_source), "state": int(d.state)})
    return rows, valid, dts, det_ok


def main(argv=None):
    from ash_e_core.config import load_perception_config
    from ash_e_core.depth_align import load_extrinsics

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir")
    g.add_argument("--bag")
    ap.add_argument("--extrinsics", required=True)
    ap.add_argument("--color-topic")
    ap.add_argument("--depth-topic")
    ap.add_argument("--slop-s", type=float, default=0.05)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--config", default=None, help="perception yaml (default: core defaults)")
    ap.add_argument("--ref-m", type=float, default=None, help="tape-measured distance of the person (z, metres)")
    ap.add_argument("--csv", default=None)
    a = ap.parse_args(argv)
    if a.bag and not (a.color_topic and a.depth_topic):
        ap.error("--bag needs --color-topic and --depth-topic")
    cfg = load_perception_config(a.config)
    cal = load_extrinsics(a.extrinsics)
    frames = iter_dir(a.dir, a.fps) if a.dir else iter_bag(a.bag, a.color_topic, a.depth_topic, a.slop_s)
    rows, valid, dts, det_ok = run(frames, cal, cfg)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["stamp", "track_id", "proxy_m", "depth_m", "depth_src", "state"])
            w.writeheader()
            w.writerows(rows)
    print(summarize(rows, a.ref_m, dts, valid, det_ok))
    if not rows:
        print("\nno detections: models missing (models/pose.onnx) or nobody in view.")


if __name__ == "__main__":
    main(sys.argv[1:])
