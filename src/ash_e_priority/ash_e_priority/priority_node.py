"""ash_e_priority node: thin ROS2 wrapper around ash_e_core.priority.PrioritySelector (spec 4.2, 7.6).

  sub  /ash_e/detections       SmokerDetectionArray  -> PrioritySelector.update(now=stamp)
  sub  /ash_e/target_feedback  TargetFeedback        -> PrioritySelector.on_feedback
  srv  ~/set_lock              std_srvs/SetBool      -> PrioritySelector.set_lock  (default node name => /ash_e/priority/set_lock)
  pub  /ash_e/target           TargetStatus          every update + whenever the watchdog changes something
  pub  /ash_e/target_point     PointStamped          only while has_target
  pub  /ash_e/priority/markers MarkerArray

A 10 Hz timer only runs the input-timeout watchdog (tick). Every callback is guarded: an exception is logged, the
selector is rebuilt from the current parameters and the node keeps running. Weights/thresholds are ROS parameters
named exactly like PriorityConfig fields and can be changed at runtime (`ros2 param set`) without losing the target.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Dict, Optional

import rclpy
from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import Point, PointStamped
from std_srvs.srv import SetBool
from visualization_msgs.msg import Marker, MarkerArray

from ash_e_core.priority import PrioritySelector, normalized_config
from ash_e_msgs.msg import (SmokerDetection, SmokerDetectionArray, TargetCandidate, TargetFeedback, TargetStatus)

from . import convert
from .markers import marker_specs
from .params import WRAPPER_DEFAULTS, config_field_defaults, config_from_values

FACTORY = SimpleNamespace(Point=Point, PointStamped=PointStamped, SmokerDetection=SmokerDetection,
                          SmokerDetectionArray=SmokerDetectionArray, TargetCandidate=TargetCandidate,
                          TargetStatus=TargetStatus)
_DYN = ParameterDescriptor(dynamic_typing=True)  # yaml `1` for a float parameter must not fail the declaration


def _qos(depth: int) -> QoSProfile:
    return QoSProfile(reliability=QoSReliabilityPolicy.RELIABLE, history=QoSHistoryPolicy.KEEP_LAST, depth=depth,
                      durability=QoSDurabilityPolicy.VOLATILE)


class PriorityNode(Node):
    def __init__(self):
        super().__init__("priority", namespace="ash_e")
        self._lock = threading.RLock()
        for name, default in {**config_field_defaults(), **WRAPPER_DEFAULTS}.items():
            self.declare_parameter(name, default, _DYN)

        self._cfg = self._load_cfg_or_default()
        self._sel = PrioritySelector(self._cfg)
        self._last_stamp: Optional[float] = None
        self._last_recv_clock: float = 0.0
        self._n_errors = 0

        self.add_on_set_parameters_callback(self._on_params)

        self._pub_target = self.create_publisher(TargetStatus, "/ash_e/target", _qos(1))
        self._pub_point = self.create_publisher(PointStamped, "/ash_e/target_point", _qos(1))
        self._pub_markers = self.create_publisher(MarkerArray, "/ash_e/priority/markers", _qos(1))
        self.create_subscription(SmokerDetectionArray, "/ash_e/detections", self._on_detections, _qos(5))
        self.create_subscription(TargetFeedback, "/ash_e/target_feedback", self._on_feedback, _qos(10))
        self.create_service(SetBool, "~/set_lock", self._on_set_lock)
        self.create_timer(1.0 / max(float(self._wp("tick_rate_hz")), 0.1), self._on_tick)
        self.get_logger().info("ash_e_priority up (weights %s)" % ", ".join(
            "%s=%.3f" % (k, getattr(self._sel.cfg, k)) for k in ("w_state", "w_dist", "w_conf", "w_center", "w_stay")))

    # ------------------------------------------------------------ parameters
    def _wp(self, name: str):
        return self.get_parameter(name).value

    def _values(self) -> Dict[str, object]:
        return {n: self.get_parameter(n).value for n in config_field_defaults()}

    def _load_cfg_or_default(self):
        try:
            return config_from_values(self._values())
        except Exception as e:  # never die on a bad yaml: log loudly and run with the defaults
            self.get_logger().error("invalid priority parameters (%s); using built-in defaults" % e)
            return config_from_values({})

    def _on_params(self, params) -> SetParametersResult:
        try:
            values = self._values()
            for p in params:
                if p.name in values:
                    values[p.name] = p.value
            cfg = config_from_values(values)
        except Exception as e:
            return SetParametersResult(successful=False, reason=str(e))
        with self._lock:
            self._cfg = cfg
            self._sel.cfg = normalized_config(cfg)  # keep the current target; applies from the next evaluation
        return SetParametersResult(successful=True)

    def _rebuild(self, why: str) -> None:
        self._sel = PrioritySelector(self._cfg)
        self._last_stamp = None
        self.get_logger().warning("selector reset (%s)" % why)

    def _clock_s(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    # ------------------------------------------------------------ publish
    def _publish(self, st) -> None:
        self._pub_target.publish(convert.target_status_to_msg(st, FACTORY))
        pt = convert.target_point_to_msg(st, FACTORY)
        if pt is not None:
            self._pub_point.publish(pt)
        if self._wp("publish_markers"):
            self._pub_markers.publish(self._markers(st))

    def _markers(self, st) -> MarkerArray:
        arr = MarkerArray()
        life = float(self._wp("marker_lifetime_s"))
        sec, nsec = convert.sec_to_stamp_parts(life)
        for s in marker_specs(st, int(self._wp("marker_max_candidates"))):
            m = Marker()
            m.header.frame_id = st.frame_id
            m.header.stamp.sec, m.header.stamp.nanosec = convert.sec_to_stamp_parts(st.stamp)
            if s["kind"] == "delete_all":
                m.action = Marker.DELETEALL
                arr.markers.append(m)
                continue
            m.ns, m.id, m.action = s["ns"], int(s["id"]), Marker.ADD
            m.type = Marker.SPHERE if s["kind"] == "sphere" else Marker.TEXT_VIEW_FACING
            m.pose.position.x, m.pose.position.y, m.pose.position.z = (float(v) for v in s["xyz"])
            m.pose.orientation.w = 1.0
            sc = float(s["scale"])
            if s["kind"] == "sphere":
                m.scale.x = m.scale.y = m.scale.z = sc
            else:
                m.scale.z = sc
                m.text = s["text"]
            m.color.r, m.color.g, m.color.b, m.color.a = (float(v) for v in s["rgba"])
            m.lifetime.sec, m.lifetime.nanosec = sec, nsec
            arr.markers.append(m)
        return arr

    # ------------------------------------------------------------ callbacks
    def _guard(self, where: str, exc: Exception) -> None:
        self._n_errors += 1
        self.get_logger().error("%s failed: %r (error #%d); selector reset" % (where, exc, self._n_errors),
                                throttle_duration_sec=2.0)
        try:
            self._rebuild(where)
        except Exception:
            pass

    def _on_detections(self, msg) -> None:
        with self._lock:
            try:
                arr = convert.detections_from_msg(msg)
                back = float(self._wp("time_jump_reset_s"))
                if self._last_stamp is not None and arr.stamp < self._last_stamp - back:
                    self._rebuild("input stamp went backwards %.2f -> %.2f (bag loop / clock reset)"
                                  % (self._last_stamp, arr.stamp))
                self._last_stamp = arr.stamp
                self._last_recv_clock = self._clock_s()
                self._publish(self._sel.update(arr, now=arr.stamp))
            except Exception as e:
                self._guard("update", e)

    def _on_tick(self) -> None:
        with self._lock:
            try:
                if self._last_stamp is None:
                    return
                now = convert.watchdog_now(self._last_stamp, self._last_recv_clock, self._clock_s())
                st = self._sel.tick(now)
                if st is not None:
                    self._publish(st)
            except Exception as e:
                self._guard("tick", e)

    def _on_feedback(self, msg) -> None:
        with self._lock:
            try:
                fb = convert.feedback_from_msg(msg)
                now = fb.stamp  # evaluate in the detections' stamp domain so cooldown times are comparable
                if self._last_stamp is not None:
                    now = convert.watchdog_now(self._last_stamp, self._last_recv_clock, self._clock_s())
                st = self._sel.on_feedback(fb, now)
                if st is not None:
                    self._publish(st)
            except Exception as e:
                self._guard("feedback", e)

    def _on_set_lock(self, req, res):
        with self._lock:
            try:
                self._sel.set_lock(bool(req.data))
                res.success = self._sel.locked == bool(req.data)
                res.message = "locked" if self._sel.locked else (
                    "unlocked" if not req.data else "no target: lock not applied")
            except Exception as e:
                res.success, res.message = False, repr(e)
        return res


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = PriorityNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
