"""ash_e_perception node: thin ROS2 wrapper around ash_e_core.PerceptionPipeline (spec 2.2, 4.2-4.4, 5.8).

color image (+ depth image) -> cv_bridge / unit conversion -> [DepthAligner] -> PerceptionPipeline.process ->
ash_e_msgs/SmokerDetectionArray.  All decisions use the color image stamp (determinism, spec 2.3).

Not runnable on Windows (needs rclpy, cv_bridge, ash_e_msgs). The ROS-free parts live in convert.py, inputs.py, sync.py
and ash_e_core/depth_align.py and are tested with pytest.
"""
from __future__ import annotations

import dataclasses
import os
import statistics
import sys
import time
from typing import Optional

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image

from ash_e_msgs.msg import SmokerDetection, SmokerDetectionArray

from ash_e_core.config import PerceptionConfig
from ash_e_core.depth_align import DepthAligner, DepthCalibration, load_extrinsics, rotation_to_quaternion
from ash_e_core.pipeline import PerceptionPipeline
from ash_e_core.types import CameraIntrinsics, DistanceSource
from ash_e_core.viz import draw_detections

from . import convert
from .inputs import (depth_to_meters, intrinsics_from_camera_info, resolve_path, stamp_to_sec, valid_depth_ratio)
from .params import DEPTH_ALIGNMENTS, INPUT_QOS, WRAPPER_DEFAULTS
from .sync import FrameMatcher, Matched

_WAIT = object()   # sentinel: color CameraInfo not here yet, skip this frame silently


def _coerce(default, value):
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return str(value)


class PerceptionNode(Node):
    def __init__(self):
        super().__init__("ash_e_perception")
        dyn = ParameterDescriptor(dynamic_typing=True)   # yaml "70" for a float key must not fail
        core_defaults = PerceptionConfig()
        for f in dataclasses.fields(PerceptionConfig):
            self.declare_parameter(f.name, getattr(core_defaults, f.name), dyn)
        for k, v in WRAPPER_DEFAULTS.items():
            self.declare_parameter(k, v, dyn)

        cfg_kw = {f.name: _coerce(getattr(core_defaults, f.name), self.get_parameter(f.name).value)
                  for f in dataclasses.fields(PerceptionConfig)}
        self.cfg = PerceptionConfig(**cfg_kw)
        self.w = {k: _coerce(v, self.get_parameter(k).value) for k, v in WRAPPER_DEFAULTS.items()}
        w = self.w
        log = self.get_logger()

        if w["depth_alignment"] not in DEPTH_ALIGNMENTS:
            log.error("depth_alignment=%r invalid (%s) -> using 'none'" % (w["depth_alignment"], DEPTH_ALIGNMENTS))
            w["depth_alignment"] = "none"
        if w["input_qos"] not in INPUT_QOS:
            log.error("input_qos=%r invalid (%s) -> using sensor_data" % (w["input_qos"], INPUT_QOS))
            w["input_qos"] = "sensor_data"
        self.equiv = bool(w["equivalence_mode"])
        if self.equiv:                       # spec 10.2: every frame is processed, no throttles
            self.cfg.process_rate_hz = 0.0
            self.cfg.roi_every_n = 1
            w["input_qos"] = "reliable"
            log.info("equivalence_mode: reliable keep_last 100, process_rate_hz and roi_every_n throttles off")
        self.use_depth = bool(w["use_depth"]) and w["depth_alignment"] != "none"

        # model / calibration file lookup (relative paths: cwd, model_dir, $ASH_E_MODEL_DIR, package share)
        share = self._share_dir()
        dirs = [w["model_dir"], os.environ.get("ASH_E_MODEL_DIR", ""), share, os.path.join(share, "models") if share else ""]
        self.cfg.pose_model_path = resolve_path(self.cfg.pose_model_path, dirs)
        self.cfg.cig_model_path = resolve_path(self.cfg.cig_model_path, dirs)
        ext_path = resolve_path(w["extrinsics_file"], [share, w["model_dir"]])

        self.pipeline = PerceptionPipeline(self.cfg)
        ready = self.pipeline.models_ready
        log.info("models: pose=%s (%s) cigarette=%s (%s)" % (
            "ready" if ready["pose"] else "MISSING", self.cfg.pose_model_path,
            "ready" if ready["cigarette"] else "MISSING", self.cfg.cig_model_path))
        if not all(ready.values()):
            log.warning("model file(s) missing: node runs and publishes empty/NONE results until the files exist "
                        "(see _workspace/02b_perception_notes.md, 'model files')")

        self.cal: Optional[DepthCalibration] = None
        if self.use_depth and w["depth_alignment"] == "software":
            try:
                self.cal = load_extrinsics(ext_path)
                log.info("extrinsics loaded: %s (rms_px=%.2f date=%s)" % (ext_path, self.cal.rms_px, self.cal.date))
            except Exception as e:  # noqa: BLE001
                log.warning("extrinsics file unusable (%s): %s -> depth_alignment=software falls back to PROXY "
                            "distance. Run calib_astra_extrinsics (see notes)." % (ext_path, e))

        self.bridge = CvBridge()
        self.matcher = FrameMatcher(w["sync_slop_s"], w["sync_wait_s"], use_depth=self.use_depth)
        self.color_info: Optional[CameraInfo] = None
        self.depth_info: Optional[CameraInfo] = None
        self._aligner = None
        self._aligner_key = None
        self._warned = set()
        self._t_start = self._now()
        self._last_proc_t = -1e18
        self._last_color_frame_id = ""
        self._depth_frame_id_seen = ""
        self._tf_done = False
        self._stats = self._new_stats()
        self._depth_stats = {"valid": [], "det": 0, "det_depth": 0, "dt": []}

        qos_in = self._input_qos()
        info_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        self.create_subscription(Image, w["color_topic"], self._on_color, qos_in)
        self.create_subscription(CameraInfo, w["color_info_topic"], self._on_color_info, info_qos)
        if self.use_depth:
            self.create_subscription(Image, w["depth_topic"], self._on_depth, qos_in)
            self.create_subscription(CameraInfo, w["depth_info_topic"], self._on_depth_info, info_qos)
        out_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=5,
                             durability=DurabilityPolicy.VOLATILE)
        self.pub_det = self.create_publisher(SmokerDetectionArray, w["detections_topic"], out_qos)
        dbg_qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        self.pub_dbg = self.create_publisher(Image, w["debug_image_topic"], dbg_qos) if w["publish_debug_image"] else None
        self.tf_bc = None
        if w["publish_extrinsics_tf"] and self.cal is not None:
            from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
            self.tf_bc = StaticTransformBroadcaster(self)

        self.create_timer(0.02, self._try_process)                       # wait-timeout for missing depth partner
        self.create_timer(float(w["log_period_s"]), self._log_stats)
        self.create_timer(float(w["depth_log_period_s"]), self._log_depth_stats)
        log.info("subscribed: color=%s info=%s%s | depth_alignment=%s use_depth=%s | out=%s" % (
            w["color_topic"], w["color_info_topic"],
            (" depth=%s depth_info=%s" % (w["depth_topic"], w["depth_info_topic"])) if self.use_depth else "",
            w["depth_alignment"], self.use_depth, w["detections_topic"]))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _share_dir() -> str:
        try:
            from ament_index_python.packages import get_package_share_directory
            return get_package_share_directory("ash_e_perception")
        except Exception:  # noqa: BLE001
            return ""

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _warn_once(self, key: str, text: str):
        if key not in self._warned:
            self._warned.add(key)
            self.get_logger().warning(text)

    def _input_qos(self) -> QoSProfile:
        if self.equiv:
            return QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=100)
        if self.w["input_qos"] == "reliable":
            return QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=1)
        return QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)

    @staticmethod
    def _new_stats():
        return {"n": 0, "inf": [], "align": [], "skipped": 0, "nodepth": 0, "waited_info": 0, "t0": time.monotonic(), "errors": 0}

    # ------------------------------------------------------------------ callbacks
    def _on_color_info(self, msg: CameraInfo):
        self.color_info = msg

    def _on_depth_info(self, msg: CameraInfo):
        self.depth_info = msg

    def _on_color(self, msg: Image):
        self.matcher.push_color(stamp_to_sec(msg.header.stamp.sec, msg.header.stamp.nanosec), msg, self._now())
        self._try_process()

    def _on_depth(self, msg: Image):
        self._depth_frame_id_seen = msg.header.frame_id
        self.matcher.push_depth(stamp_to_sec(msg.header.stamp.sec, msg.header.stamp.nanosec), msg)
        self._try_process()

    # ------------------------------------------------------------------ processing
    def _try_process(self):
        now = self._now()
        m = self.matcher.pop_ready(now)
        if m is None:
            return
        rate = self.cfg.process_rate_hz
        if rate > 0 and now - self._last_proc_t < 1.0 / rate:
            self._stats["skipped"] += 1
            return
        self._last_proc_t = now
        try:
            self._process(m)
        except Exception as e:  # noqa: BLE001  (the node must not die on one bad frame)
            self._stats["errors"] += 1
            self.get_logger().error("frame processing failed: %r" % (e,), throttle_duration_sec=5.0)

    def _color_intrinsics(self, W: int, H: int):
        """CameraInfo (matching size) > calibration file (matching size) > scaled CameraInfo > hfov fallback."""
        info = self.color_info
        if info is not None:
            r = intrinsics_from_camera_info(info.k, info.width, info.height, W, H)
            if r is None:
                self._warn_once("info_k0", "color CameraInfo K is empty (uncalibrated driver?) -> ignoring it")
            elif not r[1]:
                return r[0]
            else:
                if self.cal is not None and (self.cal.intr_color.width, self.cal.intr_color.height) == (W, H):
                    self._warn_once("info_size", "color CameraInfo size %dx%d != image %dx%d -> using color_K from the "
                                    "extrinsics file" % (info.width, info.height, W, H))
                    return self.cal.intr_color
                self._warn_once("info_scaled", "color CameraInfo size %dx%d != image %dx%d -> K scaled by size ratio"
                                % (info.width, info.height, W, H))
                return r[0]
        if not self.equiv and self._now() - self._t_start < self.w["info_wait_s"]:
            self._stats["waited_info"] += 1
            return _WAIT        # equivalence_mode never drops a frame: it falls back to hfov_deg at once (same as prototype)
        if self.cal is not None and (self.cal.intr_color.width, self.cal.intr_color.height) == (W, H):
            self._warn_once("info_cal", "no usable color CameraInfo -> using color_K from the extrinsics file")
            return self.cal.intr_color
        self._warn_once("info_hfov", "no color CameraInfo within %.1fs -> approximate intrinsics from hfov_deg=%.1f"
                        % (self.w["info_wait_s"], self.cfg.hfov_deg))
        return CameraIntrinsics.from_hfov(W, H, self.cfg.hfov_deg)

    def _depth_intrinsics(self, dh: int, dw: int) -> Optional[CameraIntrinsics]:
        info = self.depth_info
        scaled = None
        if info is not None:
            r = intrinsics_from_camera_info(info.k, info.width, info.height, dw, dh)
            if r is not None and not r[1]:
                return r[0]
            if r is not None:
                scaled = r[0]
        if self.cal is not None and (self.cal.intr_depth.width, self.cal.intr_depth.height) == (dw, dh):
            if info is not None:
                self._warn_once("dinfo_size", "depth CameraInfo unusable/size mismatch -> using depth_K from the "
                                "extrinsics file")
            return self.cal.intr_depth
        if scaled is not None:
            self._warn_once("dinfo_scaled", "depth CameraInfo size != depth image -> K scaled by size ratio")
        return scaled

    def _get_aligner(self, dshape, intr_c: CameraIntrinsics) -> Optional[DepthAligner]:
        if self.cal is None:
            return None
        dh, dw = dshape[:2]
        intr_d = self._depth_intrinsics(dh, dw)
        if intr_d is None:
            self._warn_once("no_dintr", "no depth intrinsics (depth CameraInfo missing and file size mismatch) -> PROXY")
            return None
        key = (dataclasses.astuple(intr_d), dataclasses.astuple(intr_c))
        if key != self._aligner_key:
            self._aligner = DepthAligner(intr_d, intr_c, self.cal.extr, decimate=self.cfg.depth_align_decimate,
                                         pixel_offset_uv=self.cal.depth_pixel_offset_uv)
            self._aligner_key = key
            self.get_logger().info("DepthAligner built: depth %dx%d -> color %dx%d decimate=%d fill_radius=%d" % (
                intr_d.width, intr_d.height, intr_c.width, intr_c.height, self._aligner.decimate,
                self._aligner.fill_radius))
        return self._aligner

    def _prepare_depth(self, dmsg: Image, W: int, H: int, intr_c: CameraIntrinsics):
        arr = self.bridge.imgmsg_to_cv2(dmsg, desired_encoding="passthrough")
        d = depth_to_meters(arr, dmsg.encoding)
        if self.w["depth_alignment"] == "hardware":
            if d.shape[:2] != (H, W):
                self._warn_once("hw_size", "depth_alignment=hardware but depth %dx%d != color %dx%d -> PROXY"
                                % (d.shape[1], d.shape[0], W, H))
                return None
            return d
        al = self._get_aligner(d.shape, intr_c)
        if al is None:
            return None
        t0 = time.perf_counter()
        out = al.align(d)
        self._stats["align"].append((time.perf_counter() - t0) * 1000.0)
        return out

    def _process(self, m: Matched):
        cmsg: Image = m.color
        intr = self._color_intrinsics(cmsg.width, cmsg.height)
        if intr is _WAIT:
            return
        frame = np.ascontiguousarray(self.bridge.imgmsg_to_cv2(cmsg, desired_encoding="bgr8"))
        H, W = frame.shape[:2]
        depth = None
        if self.use_depth:
            if m.depth is not None:
                depth = self._prepare_depth(m.depth, W, H, intr)
                self._depth_stats["dt"].append(m.dt)
            else:
                self._stats["nodepth"] += 1
        if depth is not None:
            self._depth_stats["valid"].append(valid_depth_ratio(depth, self.cfg.depth_min_m, self.cfg.depth_max_m))

        frame_id = self.w["color_frame_id_override"] or cmsg.header.frame_id or self.cfg.frame_id
        self._last_color_frame_id = frame_id
        arr = self.pipeline.process(frame, stamp_to_sec(cmsg.header.stamp.sec, cmsg.header.stamp.nanosec),
                                    frame_id, depth, intr)
        self.pub_det.publish(convert.array_to_msg(arr, SmokerDetectionArray, SmokerDetection))

        self._stats["n"] += 1
        self._stats["inf"].append(arr.inference_ms)
        for d in arr.detections:
            self._depth_stats["det"] += 1
            if d.distance_source == DistanceSource.DEPTH:
                self._depth_stats["det_depth"] += 1
        self._maybe_publish_tf(frame_id)
        if self.pub_dbg is not None and self.pub_dbg.get_subscription_count() > 0:
            img = draw_detections(frame.copy(), arr, self.pipeline.last)
            out = self.bridge.cv2_to_imgmsg(img, encoding="bgr8")
            out.header = cmsg.header
            out.header.frame_id = frame_id
            self.pub_dbg.publish(out)

    def _maybe_publish_tf(self, color_frame_id: str):
        """Static TF color_frame -> depth_frame from the extrinsics file (RViz check only; spec 4.4).
        p_c = R p_d + t is the pose of the depth frame expressed in the color frame."""
        if self.tf_bc is None or self._tf_done or self.cal is None:
            return
        depth_fid = self.w["depth_frame_id"] or self._depth_frame_id_seen
        if not depth_fid or not color_frame_id:
            return
        from geometry_msgs.msg import TransformStamped
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = color_frame_id
        t.child_frame_id = depth_fid
        e = self.cal.extr
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = [float(v) for v in e.t]
        qx, qy, qz, qw = rotation_to_quaternion(e.R)
        t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = qx, qy, qz, qw
        self.tf_bc.sendTransform(t)
        self._tf_done = True
        self.get_logger().info("static TF published: %s -> %s" % (color_frame_id, depth_fid))

    # ------------------------------------------------------------------ periodic logs
    def _log_stats(self):
        s = self._stats
        el = max(time.monotonic() - s["t0"], 1e-6)
        inf = s["inf"]
        msg = "perception: %.1f Hz (%d frames) | inference avg %.0f ms max %.0f ms" % (
            s["n"] / el, s["n"], (sum(inf) / len(inf)) if inf else 0.0, max(inf) if inf else 0.0)
        if s["align"]:
            msg += " | align avg %.1f ms" % (sum(s["align"]) / len(s["align"]))
        msg += " | skipped(rate) %d dropped(queue) %d no-depth-partner %d waiting-for-info %d errors %d" % (
            s["skipped"], self.matcher.dropped, s["nodepth"], s["waited_info"], s["errors"])
        if s["n"] == 0 and el > 10.0:
            msg += " | NO FRAMES: check color_topic=%s (ros2 topic list / info -v)" % self.w["color_topic"]
        self.get_logger().info(msg)
        self._stats = self._new_stats()

    def _log_depth_stats(self):
        if not self.use_depth:
            return
        d = self._depth_stats
        if not d["valid"] and not d["dt"]:
            self.get_logger().info("depth: no depth frames used in the last period (PROXY distance only)")
        else:
            v = d["valid"]
            dts = sorted(abs(x) for x in d["dt"] if x is not None)
            p95 = dts[min(len(dts) - 1, int(0.95 * len(dts)))] if dts else 0.0
            self.get_logger().info(
                "depth: valid ratio mean %.2f (aligned, %.1f-%.1f m) | detections with DEPTH distance %d/%d | "
                "color-depth |dt| median %.0f ms p95 %.0f ms (sync_slop_s=%.0f ms)" % (
                    (sum(v) / len(v)) if v else 0.0, self.cfg.depth_min_m, self.cfg.depth_max_m, d["det_depth"],
                    d["det"], (statistics.median(dts) * 1000) if dts else 0.0, p95 * 1000, self.w["sync_slop_s"] * 1000))
        self._depth_stats = {"valid": [], "det": 0, "det_depth": 0, "dt": []}


def main(argv=None):
    rclpy.init(args=argv if argv is not None else sys.argv)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
