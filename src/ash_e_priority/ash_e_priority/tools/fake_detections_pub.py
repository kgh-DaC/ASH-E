"""Fake /ash_e/detections publisher (spec B7). Replays a prototype/config/sim_scenarios.yaml scenario through ROS so
priority_node can be tested without perception or a camera. Scenario code is reused from prototype/sim_priority.py.

  ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed
  ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=target_departs_oor -p loop:=true
  # spec 12.2 scenario 8 (input cut): publish for 10 s, then stay silent for 5 s
  ros2 run ash_e_priority fake_detections_pub --ros-args -p scenario:=s5_mixed -p silence_from_s:=10.0 -p silence_for_s:=5.0
  ros2 run ash_e_priority fake_detections_pub --ros-args -p list:=true     # print scenario names and exit

Stamps = node clock at start + scenario time, so the node clock and the stamps agree (also with use_sim_time).
Parameters: scenario, scenarios_file, prototype_dir, rate_hz (0 = scenario's own), speed (1.0), loop, frame_id,
silence_from_s (<0 off), silence_for_s, list.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy

from geometry_msgs.msg import Point, PointStamped
from ash_e_msgs.msg import SmokerDetection, SmokerDetectionArray, TargetCandidate, TargetStatus

from ..convert import detections_to_msg

FACTORY = SimpleNamespace(Point=Point, PointStamped=PointStamped, SmokerDetection=SmokerDetection,
                          SmokerDetectionArray=SmokerDetectionArray, TargetCandidate=TargetCandidate,
                          TargetStatus=TargetStatus)


def find_prototype_dir(hint: str = "") -> Optional[Path]:
    """Locate <repo>/prototype (has sim_priority.py): hint param, $ASH_E_REPO, then walk up from this file and the cwd."""
    cands = []
    if hint:
        cands.append(Path(hint))
    if os.environ.get("ASH_E_REPO"):
        cands.append(Path(os.environ["ASH_E_REPO"]) / "prototype")
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        cands += [p / "prototype" for p in start.parents]
    for c in cands:
        if (c / "sim_priority.py").is_file():
            return c
    return None


def load_sim(hint: str = ""):
    d = find_prototype_dir(hint)
    if d is None:
        raise FileNotFoundError("prototype/sim_priority.py not found; set -p prototype_dir:=<repo>/prototype or $ASH_E_REPO")
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    return importlib.import_module("sim_priority"), d


class FakeDetectionsPub(Node):
    def __init__(self):
        super().__init__("fake_detections_pub", namespace="ash_e")
        self.declare_parameter("scenario", "s5_mixed")
        self.declare_parameter("scenarios_file", "")
        self.declare_parameter("prototype_dir", "")
        self.declare_parameter("rate_hz", 0.0)
        self.declare_parameter("speed", 1.0)
        self.declare_parameter("loop", False)
        self.declare_parameter("frame_id", "sim_optical")
        self.declare_parameter("silence_from_s", -1.0)
        self.declare_parameter("silence_for_s", 0.0)
        self.declare_parameter("list", False)

        sim, proto = load_sim(self.get_parameter("prototype_dir").value)
        path = self.get_parameter("scenarios_file").value or str(sim.DEFAULT_SCENARIOS)
        self._scenarios = sim.load_scenarios(path)
        self._sim = sim
        if self.get_parameter("list").value:
            for name, sc in self._scenarios.items():
                print("%-26s %5.0f s  %s" % (name, sc["duration_s"], sc.get("description", "")))
            self.wants_exit = True
            return
        self.wants_exit = False
        name = self.get_parameter("scenario").value
        if name not in self._scenarios:
            raise ValueError("unknown scenario %r; available: %s" % (name, ", ".join(self._scenarios)))
        self._sc = dict(self._scenarios[name])
        if float(self.get_parameter("rate_hz").value) > 0:
            self._sc["rate_hz"] = float(self.get_parameter("rate_hz").value)
        self._name = name
        self._frame_id = self.get_parameter("frame_id").value
        self._rate = float(self._sc.get("rate_hz", 8.0)) * float(self.get_parameter("speed").value)
        self._pub = self.create_publisher(
            SmokerDetectionArray, "/ash_e/detections",
            QoSProfile(reliability=QoSReliabilityPolicy.RELIABLE, history=QoSHistoryPolicy.KEEP_LAST, depth=5,
                       durability=QoSDurabilityPolicy.VOLATILE))
        self._frames = None
        self._t0 = self._now()
        self._rewind()
        self._timer = self.create_timer(1.0 / self._rate, self._tick)
        self.get_logger().info("replaying %r (%.0f s, %.1f Hz, frame_id=%s, %s)" % (
            name, self._sc["duration_s"], self._rate, self._frame_id, "loop" if self.get_parameter("loop").value else "once"))

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _rewind(self) -> None:
        self._frames = self._sim.scenario_frames(self._sc, frame_id=self._frame_id)
        self._t0 = self._now()

    def _tick(self) -> None:
        try:
            arr = next(self._frames)
        except StopIteration:
            if self.get_parameter("loop").value:
                self._rewind()
                self.get_logger().info("scenario %r restarted" % self._name)
            else:
                self.get_logger().info("scenario %r finished (node stays up; publishing stopped)" % self._name)
                self._timer.cancel()
            return
        s0, sl = float(self.get_parameter("silence_from_s").value), float(self.get_parameter("silence_for_s").value)
        if s0 >= 0.0 and s0 <= arr.stamp < s0 + sl:
            return  # simulated input cut: nothing published, stamps keep advancing
        scenario_t = arr.stamp
        arr.stamp = self._t0 + scenario_t
        self._pub.publish(detections_to_msg(arr, FACTORY))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = FakeDetectionsPub()
        if not node.wants_exit:
            rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception as e:  # config errors: message instead of traceback
        print("fake_detections_pub: %s" % e, file=sys.stderr)
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
