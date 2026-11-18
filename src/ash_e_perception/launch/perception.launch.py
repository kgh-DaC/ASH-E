"""perception_node alone (spec 4.2, B4).

  ros2 launch ash_e_perception perception.launch.py
  ros2 launch ash_e_perception perception.launch.py color_topic:=/image_raw use_depth:=false
  ros2 launch ash_e_perception perception.launch.py camera_config:=/path/camera_astra_pro.yaml \
      extrinsics_file:=/home/ubuntu/ash_e/astra_pro_extrinsics.yaml model_dir:=/home/ubuntu/ash_e/models

Parameter layering (later wins): perception.yaml < camera_config yaml < launch arguments that are NOT empty.
Launch arguments default to '' = "keep the yaml / node default", so nothing here hard-codes a camera topic.
Static TF base_link -> camera optical frame (H7 defaults, [field check]) is published with publish_static_tf:=true.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
import os

# override name -> type of the value ("s" string, "b" bool, "f" float)
OVERRIDES = {
    "color_topic": "s", "color_info_topic": "s", "depth_topic": "s", "depth_info_topic": "s",
    "use_depth": "b", "depth_alignment": "s", "extrinsics_file": "s", "color_frame_id_override": "s",
    "depth_frame_id": "s", "sync_slop_s": "f", "input_qos": "s", "equivalence_mode": "b",
    "publish_debug_image": "b", "publish_extrinsics_tf": "b", "model_dir": "s", "process_rate_hz": "f",
    "pose_model_path": "s", "cig_model_path": "s", "num_threads": "i", "hfov_deg": "f",
}


def _conv(kind, text):
    if kind == "b":
        return text.strip().lower() in ("1", "true", "yes", "on")
    if kind == "f":
        return float(text)
    if kind == "i":
        return int(text)
    return text


def _launch_setup(context, *args, **kwargs):
    share = FindPackageShare("ash_e_perception").perform(context)
    lc = lambda n: LaunchConfiguration(n).perform(context)  # noqa: E731
    params = [lc("perception_config") or os.path.join(share, "config", "perception.yaml")]
    if lc("camera_config"):
        params.append(lc("camera_config"))
    ov = {"use_sim_time": lc("use_sim_time").strip().lower() in ("1", "true", "yes", "on")}
    for name, kind in OVERRIDES.items():
        v = lc(name)
        if v != "":
            ov[name] = _conv(kind, v)
    params.append(ov)
    actions = [Node(package="ash_e_perception", executable="perception_node", name="ash_e_perception",
                    output="screen", parameters=params)]
    if lc("publish_static_tf").strip().lower() in ("1", "true", "yes", "on"):
        actions.append(Node(
            package="tf2_ros", executable="static_transform_publisher", output="log",
            arguments=["--x", lc("cam_x"), "--y", lc("cam_y"), "--z", lc("cam_z"),
                       # optical frame (x right, y down, z forward) relative to base_link (x fwd, y left, z up)
                       "--qx", "-0.5", "--qy", "0.5", "--qz", "-0.5", "--qw", "0.5",
                       "--frame-id", lc("base_frame"), "--child-frame-id", lc("camera_frame")]))
    return actions


def generate_launch_description():
    decl = [DeclareLaunchArgument(n, default_value="", description="override of parameter '%s' (empty = keep yaml)" % n)
            for n in OVERRIDES]
    decl += [
        DeclareLaunchArgument("perception_config", default_value="", description="empty = share/config/perception.yaml"),
        DeclareLaunchArgument("camera_config", default_value="",
                              description="camera parameter yaml, e.g. share/ash_e_perception/config/camera_astra_pro.yaml"),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("publish_static_tf", default_value="false"),
        DeclareLaunchArgument("base_frame", default_value="base_link"),
        DeclareLaunchArgument("camera_frame", default_value="camera_color_optical_frame",
                              description="must equal the color image frame_id (or color_frame_id_override)"),
        DeclareLaunchArgument("cam_x", default_value="0.10", description="m forward of base_link [field check]"),
        DeclareLaunchArgument("cam_y", default_value="0.0"),
        DeclareLaunchArgument("cam_z", default_value="1.10", description="m above base_link [field check]"),
    ]
    return LaunchDescription(decl + [OpaqueFunction(function=_launch_setup)])
