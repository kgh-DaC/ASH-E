"""priority_node only (+ optional fake input). Node is /ash_e/priority, so ~/set_lock = /ash_e/priority/set_lock.

  ros2 launch ash_e_priority priority.launch.py
  ros2 launch ash_e_priority priority.launch.py fake:=true scenario:=s5_mixed loop:=true
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    cfg = LaunchConfiguration("priority_config")
    return LaunchDescription([
        DeclareLaunchArgument("priority_config",
                              default_value=PathJoinSubstitution([FindPackageShare("ash_e_priority"), "config", "priority.yaml"]),
                              description="ros__parameters yaml with weights/thresholds"),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("fake", default_value="false", description="also start fake_detections_pub"),
        DeclareLaunchArgument("scenario", default_value="s5_mixed"),
        DeclareLaunchArgument("loop", default_value="false"),
        Node(package="ash_e_priority", executable="priority_node", name="priority", namespace="ash_e", output="screen",
             parameters=[cfg, {"use_sim_time": LaunchConfiguration("use_sim_time")}]),
        Node(package="ash_e_priority", executable="fake_detections_pub", name="fake_detections_pub", namespace="ash_e",
             output="screen", condition=IfCondition(LaunchConfiguration("fake")),
             parameters=[{"scenario": LaunchConfiguration("scenario"), "loop": LaunchConfiguration("loop"),
                          "use_sim_time": LaunchConfiguration("use_sim_time")}]),
    ])
