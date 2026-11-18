"""Convert a video file into a rosbag2 for the equivalence check (spec 10.2 step 1).

  ros2 run ash_e_perception video_to_bag clip.mp4 out_bag --color-topic /image_raw --info-topic /camera_info \
      --frame-id webcam_optical --hfov-deg 70

Image stamp = frame_idx / fps (frame 0 -> stamp 0.0), bag record time = the same stamp (so `ros2 bag play --clock`
drives use_sim_time), CameraInfo = pinhole from hfov_deg (identical to CameraIntrinsics.from_hfov used by the
prototype). No depth topic is written. Topic names are mandatory arguments (nothing is hard-coded); use the same names
as the perception node's color_topic / color_info_topic parameters.

The ROS part is imported lazily; frame_stamp_ns() and build_camera_info_fields() are pure and tested on Windows.
"""
from __future__ import annotations

import argparse
import sys

from ..inputs import camera_info_dict


def frame_stamp_ns(idx: int, fps: float) -> int:
    """Integer nanosecond stamp of frame idx (no float drift over long videos)."""
    return int(round(idx * 1e9 / float(fps)))


def stamp_fields(ns: int):
    return ns // 1_000_000_000, ns % 1_000_000_000


def build_camera_info_fields(width: int, height: int, hfov_deg: float) -> dict:
    return camera_info_dict(width, height, hfov_deg)


def _topic_metadata(rosbag2_py, name, type_):
    try:
        return rosbag2_py.TopicMetadata(name=name, type=type_, serialization_format="cdr")
    except TypeError:   # newer rosbag2_py wants an id as well
        return rosbag2_py.TopicMetadata(id=0, name=name, type=type_, serialization_format="cdr")


def convert(video: str, out_dir: str, color_topic: str, info_topic: str, frame_id: str, hfov_deg: float,
            fps_override: float = 0.0, max_frames: int = 0) -> int:
    import cv2
    import rosbag2_py
    from builtin_interfaces.msg import Time
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import CameraInfo, Image

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise SystemExit("cannot open video: %s" % video)
    fps = fps_override or cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        raise SystemExit("video fps unknown; pass --fps")
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fields = build_camera_info_fields(w, h, hfov_deg)

    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=out_dir, storage_id="sqlite3"), rosbag2_py.ConverterOptions("", ""))
    writer.create_topic(_topic_metadata(rosbag2_py, color_topic, "sensor_msgs/msg/Image"))
    writer.create_topic(_topic_metadata(rosbag2_py, info_topic, "sensor_msgs/msg/CameraInfo"))

    n = 0
    while True:
        ok, frame = cap.read()
        if not ok or (max_frames and n >= max_frames):
            break
        ns = frame_stamp_ns(n, fps)
        sec, nsec = stamp_fields(ns)
        img = Image()
        img.header.stamp = Time(sec=sec, nanosec=nsec)
        img.header.frame_id = frame_id
        img.height, img.width, img.encoding, img.is_bigendian = h, w, "bgr8", 0
        img.step = w * 3
        img.data = frame.tobytes()
        info = CameraInfo()
        info.header = img.header
        info.height, info.width = fields["height"], fields["width"]
        info.distortion_model = fields["distortion_model"]
        info.d, info.k, info.r, info.p = fields["d"], fields["k"], fields["r"], fields["p"]
        # CameraInfo first: the node needs it before it can process the image with the same stamp
        writer.write(info_topic, serialize_message(info), ns)
        writer.write(color_topic, serialize_message(img), ns)
        n += 1
    cap.release()
    print("wrote %d frames (%dx%d @ %.3f fps) to %s" % (n, w, h, fps, out_dir))
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("out_dir", help="bag directory to create (must not exist)")
    ap.add_argument("--color-topic", required=True)
    ap.add_argument("--info-topic", required=True)
    ap.add_argument("--frame-id", default="webcam_optical")
    ap.add_argument("--hfov-deg", type=float, default=70.0, help="must equal the prototype's hfov_deg")
    ap.add_argument("--fps", type=float, default=0.0, help="override the file's fps")
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args(argv)
    convert(a.video, a.out_dir, a.color_topic, a.info_topic, a.frame_id, a.hfov_deg, a.fps, a.max_frames)


if __name__ == "__main__":
    main(sys.argv[1:])
