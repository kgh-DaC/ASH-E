"""Whole stack: [camera driver] + perception_node + priority_node (+ static TF base_link -> camera optical frame).

Spec 4.2/4.4/B8. Same parameter layering as ash_e_perception/launch/perception.launch.py (later wins):
  perception.yaml < camera_config yaml < launch arguments that are NOT empty.
All perception launch arguments default to '' = keep the yaml / node default, so no camera topic is hard-coded here.

  ros2 launch ash_e_priority ash_e_all.launch.py camera_config:=<share>/ash_e_perception/config/camera_astra_pro.yaml \
      extrinsics_file:=/home/ubuntu/ash_e/astra_pro_extrinsics.yaml model_dir:=/home/ubuntu/ash_e/models
  ros2 launch ash_e_priority ash_e_all.launch.py color_topic:=/image_raw color_info_topic:=/camera_info use_depth:=false
  ros2 launch ash_e_priority ash_e_all.launch.py camera_launch:=/path/to/driver.launch.py     # also start the driver
  ros2 launch ash_e_priority ash_e_all.launch.py equivalence_mode:=true use_sim_time:=true     # rosbag equivalence run

perception_node is started as node `ash_e_perception` (same as perception.launch.py).
"""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

# perception parameter overrides: name -> type ("s" string, "b" bool, "f" float, "i" int). Must match the
# perception_node parameters (same list as ash_e_perception/launch/perception.launch.py OVERRIDES).
OVERRIDES = {
    "color_topic": "s", "color_info_topic": "s", "depth_topic": "s", "depth_info_topic": "s",
    "use_depth": "b", "depth_alignment": "s", "extrinsics_file": "s", "color_frame_id_override": "s",
    "depth_frame_id": "s", "sync_slop_s": "f", "input_qos": "s", "equivalence_mode": "b",
    "publish_debug_image": "b", "publish_extrinsics_tf": "b", "model_dir": "s", "process_rate_hz": "f",
    "pose_model_path": "s", "cig_model_path": "s", "num_threads": "i", "hfov_deg": "f",
}
_TRUE = ("1", "true", "yes", "on")


def _conv(kind, text):
    if kind == "b":
        return text.strip().lower() in _TRUE
    if kind == "f":
        return float(text)
    if kind == "i":
        return int(text)
    return text


def _launch_setup(context, *args, **kwargs):
    lc = lambda n: LaunchConfiguration(n).perform(context)  # noqa: E731
    sim = lc("use_sim_time").strip().lower() in _TRUE

    # ---- perception
    perc_share = FindPackageShare("ash_e_perception").perform(context)
    params = [lc("perception_config") or os.path.join(perc_share, "config", "perception.yaml")]
    if lc("camera_config"):
        params.append(lc("camera_config"))
    ov = {"use_sim_time": sim}
    for name, kind in OVERRIDES.items():
        v = lc(name)
        if v != "":
            ov[name] = _conv(kind, v)
    params.append(ov)
    perception = Node(package="ash_e_perception", executable="perception_node", name="ash_e_perception",
                      output="screen", parameters=params)

    # ---- priority
    prio_share = FindPackageShare("ash_e_priority").perform(context)
    priority = Node(package="ash_e_priority", executable="priority_node", name="priority", namespace="ash_e",
                    output="screen",
                    parameters=[lc("priority_config") or os.path.join(prio_share, "config", "priority.yaml"),
                                {"use_sim_time": sim}])
    actions = [perception, priority]

    # ---- optional camera driver
    if lc("camera_launch"):
        actions.insert(0, IncludeLaunchDescription(PythonLaunchDescriptionSource(lc("camera_launch"))))

    # ---- static TF: optical frame (x right, y down, z forward) relative to base_link (x fwd, y left, z up)
    if lc("publish_static_tf").strip().lower() in _TRUE:
        actions.append(Node(
            package="tf2_ros", executable="static_transform_publisher", output="log",
            arguments=["--x", lc("cam_x"), "--y", lc("cam_y"), "--z", lc("cam_z"),
                       "--qx", "-0.5", "--qy", "0.5", "--qz", "-0.5", "--qw", "0.5",
                       "--frame-id", lc("base_frame"), "--child-frame-id", lc("camera_frame")]))
    return actions


def generate_launch_description():
    decl = [DeclareLaunchArgument(n, default_value="", description="override of perception parameter '%s' (empty = keep yaml)" % n)
            for n in OVERRIDES]
    decl += [
        DeclareLaunchArgument("camera_launch", default_value="",
                              description="camera driver launch file to include; empty = driver started elsewhere"),
        DeclareLaunchArgument("camera_config", default_value="",
                              description="camera parameter yaml, e.g. <share>/ash_e_perception/config/camera_astra_pro.yaml"),
        DeclareLaunchArgument("perception_config", default_value="", description="empty = ash_e_perception share/config/perception.yaml"),
        DeclareLaunchArgument("priority_config", default_value="", description="empty = ash_e_priority share/config/priority.yaml"),
        DeclareLaunchArgument("use_sim_time", default_value="false", description="true when replaying a rosbag with --clock"),
        DeclareLaunchArgument("publish_static_tf", default_value="true",
                              description="base_link -> camera frame; set false if the driver publishes it [field check]"),
        DeclareLaunchArgument("base_frame", default_value="base_link"),
        DeclareLaunchArgument("camera_frame", default_value="camera_color_optical_frame",
                              description="must equal the color image frame_id (or color_frame_id_override)"),
        DeclareLaunchArgument("cam_x", default_value="0.10", description="m forward of base_link [field check]"),
        DeclareLaunchArgument("cam_y", default_value="0.0"),
        DeclareLaunchArgument("cam_z", default_value="1.10", description="m above base_link [field check]"),
    ]
    return LaunchDescription(decl + [OpaqueFunction(function=_launch_setup)])
