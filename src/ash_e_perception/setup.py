import os
from glob import glob

from setuptools import find_packages, setup

package_name = "ash_e_perception"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="ASH-E",
    maintainer_email="todo@example.com",
    description="ASH-E perception ROS2 wrapper",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "perception_node = ash_e_perception.perception_node:main",
            "video_to_bag = ash_e_perception.tools.video_to_bag:main",
            "dump_jsonl = ash_e_perception.tools.dump_jsonl:main",
            "calib_astra_extrinsics = ash_e_perception.tools.calib_astra_extrinsics:main",
            "depth_check = ash_e_perception.tools.depth_check:main",
        ],
    },
)
