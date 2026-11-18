"""Depth(IR) -> color extrinsics for the Astra Pro (spec 5.8, B0-4). OpenCV + numpy only (capture subcommand needs ROS).

Procedure (RPi5 or any PC):
 1. Print a checkerboard (default 9x6 inner corners, 25 mm squares) on a rigid flat board.
 2. Capture >= 20 pairs at different distances (0.6-2 m) and tilts, covering the image corners:
      calib_astra_extrinsics capture --color-topic <color image topic> --ir-topic <IR image topic> --out pairs_dir
    (Enter = save a pair, q + Enter = quit). The IR stream comes from the OpenNI2 driver. Cover or switch off the IR
    projector (structured-light dots break corner detection) and light the board with indirect light.
    Or save the pairs yourself as pairs_dir/ir_000.png + pairs_dir/color_000.png ... (same index = same moment).
 3. calib_astra_extrinsics calibrate pairs_dir --out astra_pro_extrinsics.yaml [--board 9x6 --square-m 0.025]
    Intrinsics of both cameras are estimated from the same images (cv2.calibrateCamera), then cv2.stereoCalibrate with
    fixed intrinsics gives R, t with p_color = R p_ir + t. depth_K/color_K/sizes are written into the yaml.
 4. Accept when rms_px <= 0.5 (spec). Then check silhouettes (depth_check) and set depth_pixel_offset_uv if needed.
The depth image is registered to the IR image on Astra sensors; if it is not, use depth_pixel_offset_uv.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import os
import sys
from typing import List, Optional, Tuple

import cv2
import numpy as np

from ash_e_core.depth_align import DepthCalibration, DepthExtrinsics, save_extrinsics
from ash_e_core.types import CameraIntrinsics


def board_points(cols: int, rows: int, square_m: float) -> np.ndarray:
    objp = np.zeros((cols * rows, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * square_m
    return objp


def to_gray8(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if img.dtype != np.uint8:
        img = cv2.normalize(img.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return img


def find_corners(img: np.ndarray, cols: int, rows: int) -> Optional[np.ndarray]:
    g = to_gray8(img)
    ok, c = cv2.findChessboardCorners(g, (cols, rows),
                                      cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
        return None
    return cv2.cornerSubPix(g, c, (5, 5), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))


def calibrate_extrinsics(objp: np.ndarray, pts_d: List[np.ndarray], pts_c: List[np.ndarray],
                         size_d: Tuple[int, int], size_c: Tuple[int, int]) -> DepthCalibration:
    """pts_*: lists of (N,1,2) float32 corner arrays (same board views). sizes are (width, height)."""
    obj = [objp] * len(pts_d)
    rms_d, Kd, Dd, _, _ = cv2.calibrateCamera(obj, pts_d, size_d, None, None)
    rms_c, Kc, Dc, _, _ = cv2.calibrateCamera(obj, pts_c, size_c, None, None)
    rms, Kd, Dd, Kc, Dc, R, T, _, _ = cv2.stereoCalibrate(
        obj, pts_d, pts_c, Kd, Dd, Kc, Dc, size_c, flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-7))

    def intr(K, size):
        return CameraIntrinsics(float(K[0, 0]), float(K[1, 1]), float(K[0, 2]), float(K[1, 2]), size[0], size[1])

    return DepthCalibration(
        extr=DepthExtrinsics(R, T.reshape(3)), intr_depth=intr(Kd, size_d), intr_color=intr(Kc, size_c),
        rms_px=float(rms), date=datetime.date.today().isoformat(),
        note="stereoCalibrate fixed intrinsics; single-camera rms depth/ir=%.3f color=%.3f px; %d views"
             % (rms_d, rms_c, len(pts_d)))


def _pair_files(d: str):
    irs = sorted(glob.glob(os.path.join(d, "ir_*.png")))
    out = []
    for p in irs:
        c = os.path.join(d, "color_" + os.path.basename(p)[3:])
        if os.path.isfile(c):
            out.append((p, c))
    return out


def run_calibrate(d: str, out: str, cols: int, rows: int, square_m: float) -> DepthCalibration:
    pairs = _pair_files(d)
    if len(pairs) < 10:
        raise SystemExit("need >= 10 pairs ir_NNN.png/color_NNN.png in %s (found %d); 20+ recommended" % (d, len(pairs)))
    pd, pc, used = [], [], 0
    size_d = size_c = None
    for ip, cp in pairs:
        ir = cv2.imread(ip, cv2.IMREAD_UNCHANGED)
        co = cv2.imread(cp, cv2.IMREAD_UNCHANGED)
        if ir is None or co is None:
            continue
        size_d, size_c = (ir.shape[1], ir.shape[0]), (co.shape[1], co.shape[0])
        a, b = find_corners(ir, cols, rows), find_corners(co, cols, rows)
        if a is None or b is None:
            print("skip (corners not found in %s): %s" % ("ir" if a is None else "color", os.path.basename(ip)))
            continue
        pd.append(a)
        pc.append(b)
        used += 1
    if used < 8:
        raise SystemExit("only %d usable pairs (need >= 8). IR projector dots? lighting? board size?" % used)
    cal = calibrate_extrinsics(board_points(cols, rows, square_m), pd, pc, size_d, size_c)
    save_extrinsics(out, cal)
    print("pairs used %d/%d | rms_px %.3f (%s <= 0.5 required) | t [m] = %s | written %s" % (
        used, len(pairs), cal.rms_px, "OK" if cal.rms_px <= 0.5 else "FAIL", np.round(cal.extr.t, 4).tolist(), out))
    return cal


def run_capture(out_dir: str, color_topic: str, ir_topic: str) -> None:
    import threading
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from ..inputs import image_msg_to_numpy

    os.makedirs(out_dir, exist_ok=True)
    rclpy.init()
    node = Node("ash_e_calib_capture")
    last = {"c": None, "i": None}
    node.create_subscription(Image, color_topic, lambda m: last.__setitem__("c", m), qos_profile_sensor_data)
    node.create_subscription(Image, ir_topic, lambda m: last.__setitem__("i", m), qos_profile_sensor_data)
    stop = threading.Event()
    threading.Thread(target=lambda: [rclpy.spin_once(node, timeout_sec=0.1) for _ in iter(stop.is_set, True)],
                     daemon=True).start()
    n = len(_pair_files(out_dir))
    print("Enter = save pair, q + Enter = quit. Saved so far: %d" % n)
    try:
        while True:
            s = input()
            if s.strip().lower() == "q":
                break
            c, i = last["c"], last["i"]
            if c is None or i is None:
                print("no color or IR image yet")
                continue
            cv2.imwrite(os.path.join(out_dir, "color_%03d.png" % n), image_msg_to_numpy(c, want_bgr=True))
            cv2.imwrite(os.path.join(out_dir, "ir_%03d.png" % n), to_gray8(image_msg_to_numpy(i)))
            n += 1
            print("saved pair %d" % (n - 1))
    finally:
        stop.set()
        node.destroy_node()
        rclpy.shutdown()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("pairs_dir")
    c.add_argument("--out", default="astra_pro_extrinsics.yaml")
    c.add_argument("--board", default="9x6", help="inner corners COLSxROWS")
    c.add_argument("--square-m", type=float, default=0.025)
    k = sub.add_parser("capture")
    k.add_argument("--out", required=True)
    k.add_argument("--color-topic", required=True)
    k.add_argument("--ir-topic", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "calibrate":
        cols, rows = [int(x) for x in a.board.lower().split("x")]
        run_calibrate(a.pairs_dir, a.out, cols, rows, a.square_m)
    else:
        run_capture(a.out, a.color_topic, a.ir_topic)


if __name__ == "__main__":
    main(sys.argv[1:])
