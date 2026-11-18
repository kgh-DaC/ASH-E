"""Record /ash_e/detections (+ /ash_e/target) as JSONL in the same format as the prototype log (spec 3.8, 10.2):
one line per frame {"frame_seq","stamp","detections":..., "target":...} written with ash_e_core.serialize.frame_to_jsonl.

  ros2 run ash_e_perception dump_jsonl ros.jsonl [--no-target] [--max-frames N] [--idle-exit-s 5]

Target pairing: the priority node publishes TargetStatus with stamp == the input detections stamp, so a detections
frame is written when the target with the same stamp arrives (or, if it never does, when 3 newer frames are pending
or at shutdown, with target=null). JsonlPairer is pure and tested on Windows.
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from typing import List

from ash_e_core.serialize import frame_to_jsonl
from ash_e_core.types import DetectionArray, TargetStatus


class JsonlPairer:
    def __init__(self, with_target: bool = True, max_pending: int = 3):
        self.with_target = with_target
        self.max_pending = max_pending
        self._pending: "OrderedDict[int, DetectionArray]" = OrderedDict()
        self._targets: "dict[int, TargetStatus]" = {}

    @staticmethod
    def _key(stamp: float) -> int:
        return int(round(stamp * 1e6))        # microsecond key: tolerant to float32/float64 round trips

    def add_detections(self, arr: DetectionArray) -> List[str]:
        if not self.with_target:
            return [frame_to_jsonl(arr.frame_seq, arr.stamp, arr, None)]
        k = self._key(arr.stamp)
        if k in self._targets:
            return [frame_to_jsonl(arr.frame_seq, arr.stamp, arr, self._targets.pop(k))]
        self._pending[k] = arr
        out = []
        while len(self._pending) > self.max_pending:
            _, old = self._pending.popitem(last=False)
            out.append(frame_to_jsonl(old.frame_seq, old.stamp, old, None))
        return out

    def add_target(self, st: TargetStatus) -> List[str]:
        k = self._key(st.stamp)
        arr = self._pending.pop(k, None)
        if arr is not None:
            return [frame_to_jsonl(arr.frame_seq, arr.stamp, arr, st)]
        self._targets[k] = st                  # target before detections (reordering): keep a few
        while len(self._targets) > 10:
            self._targets.pop(next(iter(self._targets)))
        return []

    def flush(self) -> List[str]:
        out = [frame_to_jsonl(a.frame_seq, a.stamp, a, None) for a in self._pending.values()]
        self._pending.clear()
        return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--detections-topic", default="/ash_e/detections")
    ap.add_argument("--target-topic", default="/ash_e/target")
    ap.add_argument("--no-target", action="store_true")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--idle-exit-s", type=float, default=0.0, help="exit after this many seconds without detections (0=never)")
    a, ros_args = ap.parse_known_args(argv)

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from ash_e_msgs.msg import SmokerDetectionArray, TargetStatus as TargetStatusMsg
    from ash_e_perception import convert

    rclpy.init(args=ros_args)
    node = Node("ash_e_dump_jsonl")
    pairer = JsonlPairer(with_target=not a.no_target)
    f = open(a.out, "w", encoding="utf-8")
    state = {"n": 0, "last": node.get_clock().now()}
    qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_ALL)  # never lose a frame

    def write(lines):
        for ln in lines:
            f.write(ln + "\n")
            state["n"] += 1
        f.flush()

    def on_det(m):
        state["last"] = node.get_clock().now()
        write(pairer.add_detections(convert.array_from_msg(m)))

    def on_target(m):
        write(pairer.add_target(convert.target_status_from_msg(m)))

    node.create_subscription(SmokerDetectionArray, a.detections_topic, on_det, qos)
    if not a.no_target:
        node.create_subscription(TargetStatusMsg, a.target_topic, on_target, qos)
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.2)
            if a.max_frames and state["n"] >= a.max_frames:
                break
            if a.idle_exit_s and state["n"] > 0 and \
                    (node.get_clock().now() - state["last"]).nanoseconds * 1e-9 > a.idle_exit_s:
                break
    except KeyboardInterrupt:
        pass
    write(pairer.flush())
    f.close()
    print("wrote %d lines to %s" % (state["n"], a.out))
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv[1:])
