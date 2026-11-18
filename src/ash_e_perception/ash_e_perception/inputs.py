"""ROS-free input helpers for the perception wrapper: unit conversion, CameraInfo -> intrinsics, path lookup,
Image message decoding without cv_bridge (tools). Everything takes plain numpy / duck-typed objects so that it can be
tested on Windows."""
from __future__ import annotations

import math
import os
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np

from ash_e_core.types import CameraIntrinsics


# ---------------------------------------------------------------- time
def stamp_to_sec(sec: int, nanosec: int) -> float:
    return float(sec) + float(nanosec) * 1e-9


def sec_to_stamp(t: float) -> Tuple[int, int]:
    """float seconds -> (sec, nanosec) with carry handling (nanosec always in [0, 1e9))."""
    sec = int(math.floor(t))
    ns = int(round((t - sec) * 1e9))
    if ns >= 1_000_000_000:
        sec, ns = sec + 1, ns - 1_000_000_000
    return sec, ns


# ---------------------------------------------------------------- depth
def depth_to_meters(arr: np.ndarray, encoding: str) -> np.ndarray:
    """16UC1 (mm) -> float32 m ; 32FC1 (m) -> float32 m. Zero / NaN stay invalid markers (core drops them)."""
    enc = (encoding or "").upper()
    if enc in ("16UC1", "MONO16"):
        return arr.astype(np.float32) * np.float32(0.001)
    if enc == "32FC1":
        return arr.astype(np.float32, copy=False)
    raise ValueError(f"unsupported depth encoding: {encoding!r} (expected 16UC1 or 32FC1)")


def valid_depth_ratio(depth_m: np.ndarray, dmin: float, dmax: float) -> float:
    if depth_m.size == 0:
        return 0.0
    ok = np.isfinite(depth_m) & (depth_m >= dmin) & (depth_m <= dmax)
    return float(ok.sum()) / float(depth_m.size)


# ---------------------------------------------------------------- intrinsics
def intrinsics_from_camera_info(K: Sequence[float], info_w: int, info_h: int,
                                img_w: int, img_h: int) -> Optional[Tuple[CameraIntrinsics, bool]]:
    """CameraInfo.k -> CameraIntrinsics for an image of size (img_w, img_h).
    Returns (intrinsics, was_scaled) or None when K is unusable (all zeros = uncalibrated driver).
    If the CameraInfo size differs from the image, K is scaled by the size ratio (was_scaled=True)."""
    k = [float(v) for v in K]
    if len(k) != 9 or k[0] <= 0 or k[4] <= 0:
        return None
    fx, fy, cx, cy = k[0], k[4], k[2], k[5]
    scaled = False
    if info_w and info_h and (int(info_w) != int(img_w) or int(info_h) != int(img_h)):
        sx, sy = img_w / float(info_w), img_h / float(info_h)
        fx, cx, fy, cy = fx * sx, cx * sx, fy * sy, cy * sy
        scaled = True
    return CameraIntrinsics(fx, fy, cx, cy, int(img_w), int(img_h)), scaled


def hfov_from_intrinsics(intr: CameraIntrinsics) -> float:
    """hfov_deg = 2 atan(W / (2 fx)) (spec 6.2). For priority.yaml after calibration."""
    return math.degrees(2.0 * math.atan(intr.width / (2.0 * intr.fx)))


def camera_info_dict(width: int, height: int, hfov_deg: float) -> dict:
    """Plain-dict CameraInfo fields for a pinhole camera built from hfov_deg (same formula as
    CameraIntrinsics.from_hfov), used by video_to_bag so that bag replay equals the prototype's intrinsics."""
    i = CameraIntrinsics.from_hfov(width, height, hfov_deg)
    k = [i.fx, 0.0, i.cx, 0.0, i.fy, i.cy, 0.0, 0.0, 1.0]
    p = [i.fx, 0.0, i.cx, 0.0, 0.0, i.fy, i.cy, 0.0, 0.0, 0.0, 1.0, 0.0]
    return {"width": int(width), "height": int(height), "distortion_model": "plumb_bob", "d": [0.0] * 5,
            "k": k, "r": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], "p": p}


# ---------------------------------------------------------------- paths
def resolve_path(path: str, search_dirs: Iterable[str]) -> str:
    """Absolute path or an existing relative path is returned unchanged; otherwise the first existing
    <dir>/<path> (or <dir>/<basename>) is returned; if nothing exists the original string is returned."""
    if not path:
        return path
    if os.path.isabs(path) or os.path.exists(path):
        return path
    for d in search_dirs:
        if not d:
            continue
        cand = os.path.join(d, path)
        if os.path.exists(cand):
            return cand
        cand = os.path.join(d, os.path.basename(path))
        if os.path.exists(cand):
            return cand
    return path


# ---------------------------------------------------------------- Image message -> numpy (no cv_bridge)
_DTYPES = {"8UC1": (np.uint8, 1), "8UC3": (np.uint8, 3), "mono8": (np.uint8, 1), "bgr8": (np.uint8, 3),
           "rgb8": (np.uint8, 3), "16UC1": (np.uint16, 1), "mono16": (np.uint16, 1), "32FC1": (np.float32, 1),
           "bgra8": (np.uint8, 4), "rgba8": (np.uint8, 4)}


def image_msg_to_numpy(msg, want_bgr: bool = False) -> np.ndarray:
    """sensor_msgs/Image (or any object with height,width,encoding,step,data,is_bigendian) -> ndarray.
    want_bgr converts rgb8/rgba8/bgra8/mono8 to BGR uint8 (color images)."""
    enc = msg.encoding
    if enc not in _DTYPES:
        raise ValueError(f"unsupported encoding {enc!r}")
    base, ch = _DTYPES[enc]
    dt = np.dtype(base).newbyteorder(">" if getattr(msg, "is_bigendian", 0) else "<")
    h, w = int(msg.height), int(msg.width)
    raw = np.frombuffer(bytes(msg.data), np.uint8).reshape(h, int(msg.step))
    row = raw[:, : w * ch * dt.itemsize]
    arr = np.ascontiguousarray(row).view(dt).reshape(h, w, ch) if ch > 1 else np.ascontiguousarray(row).view(dt).reshape(h, w)
    arr = arr.astype(np.dtype(base), copy=False)
    if want_bgr:
        if enc == "rgb8":
            arr = arr[:, :, ::-1]
        elif enc == "rgba8":
            arr = arr[:, :, 2::-1]
        elif enc == "bgra8":
            arr = arr[:, :, :3]
        elif enc in ("mono8", "8UC1"):
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        arr = np.ascontiguousarray(arr)
    return arr
