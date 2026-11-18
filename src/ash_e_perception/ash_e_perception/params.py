"""Wrapper-only parameter defaults (spec 4.2). One place, so the node, the launch file and the tools agree.
No ROS imports. The camera topic names below are DEFAULTS of parameters only; nothing else in the wrapper may hard-code a
camera topic (QA greps for it). Real values come from config/camera_astra_pro.yaml or launch arguments."""
from __future__ import annotations

WRAPPER_DEFAULTS = {
    # input topics (driver dependent, B0 decides; D1/D3 guess [estimate])
    "color_topic": "/camera/color/image_raw",
    "color_info_topic": "/camera/color/camera_info",
    "depth_topic": "/camera/depth/image_raw",
    "depth_info_topic": "/camera/depth/camera_info",
    # output topics
    "detections_topic": "/ash_e/detections",
    "debug_image_topic": "/ash_e/perception/debug_image",
    # depth handling
    "use_depth": True,
    "depth_alignment": "software",            # software | hardware | none
    "extrinsics_file": "config/astra_pro_extrinsics.yaml",
    "color_frame_id_override": "",
    "depth_frame_id": "",                      # only for publish_extrinsics_tf; empty -> depth image header.frame_id
    "sync_slop_s": 0.05,
    "sync_wait_s": 0.12,                       # wait this long (arrival time) for a depth partner, then use PROXY
    "info_wait_s": 5.0,                        # wait for the color CameraInfo, then fall back to hfov_deg
    "input_qos": "sensor_data",                # sensor_data | reliable
    # modes
    "equivalence_mode": False,
    "publish_debug_image": False,
    "publish_extrinsics_tf": False,
    # misc
    "model_dir": "",                           # relative model paths are also searched here (and in $ASH_E_MODEL_DIR)
    "log_period_s": 5.0,
    "depth_log_period_s": 10.0,
}

DEPTH_ALIGNMENTS = ("software", "hardware", "none")
INPUT_QOS = ("sensor_data", "reliable")
