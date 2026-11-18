"""Software depth -> color alignment (spec 5.8). Pure numpy (+ yaml for the calibration file), no ROS imports.

A structured-light depth camera (Astra Pro) and its UVC color module are separate devices, so the driver cannot be
trusted to deliver an aligned depth image. DepthAligner projects the depth pixels into the color image with the
extrinsics found by tools/calib_astra_extrinsics.py:  p_c = R @ p_d + t  (depth optical frame -> color optical frame).

Output: float32 [m], same size as the color image, 0 = invalid. Z-buffer: the nearest surface wins. Deterministic.
Lens distortion is ignored (spec 5.8).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from .types import CameraIntrinsics


@dataclass
class DepthExtrinsics:
    R: np.ndarray = field(default_factory=lambda: np.eye(3))      # (3,3)
    t: np.ndarray = field(default_factory=lambda: np.zeros(3))    # (3,) [m]

    def __post_init__(self):
        self.R = np.asarray(self.R, np.float64).reshape(3, 3)
        self.t = np.asarray(self.t, np.float64).reshape(3)


@dataclass
class DepthCalibration:
    """Contents of astra_pro_extrinsics.yaml (spec 5.8)."""
    extr: DepthExtrinsics
    intr_depth: CameraIntrinsics
    intr_color: CameraIntrinsics
    rms_px: float = -1.0
    date: str = ""
    note: str = ""
    depth_pixel_offset_uv: Tuple[float, float] = (0.0, 0.0)


def intrinsics_from_k(K, width: int, height: int) -> CameraIntrinsics:
    k = [float(v) for v in K]
    if len(k) != 9:
        raise ValueError("K must have 9 elements")
    return CameraIntrinsics(k[0], k[4], k[2], k[5], int(width), int(height))


def load_extrinsics(path: str) -> DepthCalibration:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    for key in ("depth_K", "depth_size", "color_K", "color_size", "R", "t"):
        if key not in d:
            raise ValueError(f"{path}: missing key '{key}'")
    off = d.get("depth_pixel_offset_uv", [0.0, 0.0]) or [0.0, 0.0]
    return DepthCalibration(
        extr=DepthExtrinsics(np.array(d["R"], np.float64).reshape(3, 3), np.array(d["t"], np.float64).reshape(3)),
        intr_depth=intrinsics_from_k(d["depth_K"], d["depth_size"][0], d["depth_size"][1]),
        intr_color=intrinsics_from_k(d["color_K"], d["color_size"][0], d["color_size"][1]),
        rms_px=float(d.get("rms_px", -1.0)), date=str(d.get("date", "")), note=str(d.get("note", "")),
        depth_pixel_offset_uv=(float(off[0]), float(off[1])))


def save_extrinsics(path: str, cal: DepthCalibration) -> None:
    import yaml

    def k(i: CameraIntrinsics):
        return [float(i.fx), 0.0, float(i.cx), 0.0, float(i.fy), float(i.cy), 0.0, 0.0, 1.0]

    d = {"depth_K": k(cal.intr_depth), "depth_size": [int(cal.intr_depth.width), int(cal.intr_depth.height)],
         "color_K": k(cal.intr_color), "color_size": [int(cal.intr_color.width), int(cal.intr_color.height)],
         "R": [float(v) for v in cal.extr.R.reshape(-1)], "t": [float(v) for v in cal.extr.t],
         "rms_px": float(cal.rms_px), "date": cal.date, "note": cal.note,
         "depth_pixel_offset_uv": [float(cal.depth_pixel_offset_uv[0]), float(cal.depth_pixel_offset_uv[1])]}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(d, f, sort_keys=False, allow_unicode=True)


def _min_filter_1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Sliding minimum over a window of 2r+1 along axis (outside the array counts as +inf)."""
    out = a.copy()
    n = a.shape[axis]
    for s in range(1, r + 1):
        if s >= n:
            break
        lo = [slice(None)] * a.ndim
        hi = [slice(None)] * a.ndim
        lo[axis], hi[axis] = slice(0, n - s), slice(s, n)
        lo, hi = tuple(lo), tuple(hi)
        np.minimum(out[lo], a[hi], out=out[lo])   # neighbour at +s
        np.minimum(out[hi], a[lo], out=out[hi])   # neighbour at -s
    return out


class DepthAligner:
    """align(depth_m) -> float32 aligned depth in the color image grid. Build once per (intrinsics, extrinsics)."""

    def __init__(self, intr_depth: CameraIntrinsics, intr_color: CameraIntrinsics, extr: DepthExtrinsics,
                 decimate: int = 2, fill_radius: Optional[int] = None,
                 pixel_offset_uv: Tuple[float, float] = (0.0, 0.0)):
        self.intr_depth, self.intr_color, self.extr = intr_depth, intr_color, extr
        self.decimate = max(1, int(decimate))
        d, c = intr_depth, intr_color
        # sparse projection leaves holes whose spacing is decimate * (color px per depth px)
        scale = max(1.0, c.fx / d.fx, c.fy / d.fy)
        self.fill_radius = (int(fill_radius) if fill_radius is not None
                            else max(1, int(math.ceil(self.decimate * scale * 0.75))))
        us = np.arange(0, d.width, self.decimate)
        vs = np.arange(0, d.height, self.decimate)
        uu, vv = np.meshgrid(us, vs)
        self._rx = ((uu.astype(np.float64) + pixel_offset_uv[0] - d.cx) / d.fx).reshape(-1)
        self._ry = ((vv.astype(np.float64) + pixel_offset_uv[1] - d.cy) / d.fy).reshape(-1)
        self._R = extr.R
        self._t = extr.t

    def align(self, depth_m: np.ndarray) -> np.ndarray:
        d, c = self.intr_depth, self.intr_color
        if depth_m.shape[:2] != (d.height, d.width):
            raise ValueError(f"depth shape {depth_m.shape[:2]} != expected {(d.height, d.width)}")
        z = depth_m[::self.decimate, ::self.decimate].astype(np.float64).reshape(-1)
        ok = np.isfinite(z) & (z > 0)
        z = z[ok]
        rx, ry = self._rx[ok], self._ry[ok]
        R, t = self._R, self._t
        xd, yd = rx * z, ry * z
        xc = R[0, 0] * xd + R[0, 1] * yd + R[0, 2] * z + t[0]
        yc = R[1, 0] * xd + R[1, 1] * yd + R[1, 2] * z + t[1]
        zc = R[2, 0] * xd + R[2, 1] * yd + R[2, 2] * z + t[2]
        front = zc > 1e-6
        xc, yc, zc = xc[front], yc[front], zc[front]
        u = np.rint(c.fx * xc / zc + c.cx).astype(np.int64)
        v = np.rint(c.fy * yc / zc + c.cy).astype(np.int64)
        inb = (u >= 0) & (u < c.width) & (v >= 0) & (v < c.height)
        u, v, zc = u[inb], v[inb], zc[inb]
        out = np.zeros(c.height * c.width, np.float32)
        if zc.size:
            idx = v * c.width + u
            order = np.argsort(-zc, kind="stable")       # far first: with repeated indices the last write (nearest) wins
            out[idx[order]] = zc[order].astype(np.float32)
        return self._fill(out.reshape(c.height, c.width))

    def _fill(self, out: np.ndarray) -> np.ndarray:
        r = self.fill_radius
        if r <= 0:
            return out
        big = np.where(out > 0, out, np.float32(np.inf)).astype(np.float32)
        m = _min_filter_1d(_min_filter_1d(big, r, 1), r, 0)
        m = np.where(np.isinf(m), np.float32(0), m)
        return np.where(out > 0, out, m).astype(np.float32)


def rotation_to_quaternion(R) -> Tuple[float, float, float, float]:
    """3x3 rotation -> (x, y, z, w). Used for the optional static TF in the ROS wrapper."""
    R = np.asarray(R, np.float64)
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    return float(x), float(y), float(z), float(w)
