from glob import glob

from setuptools import find_packages, setup

package_name = "ash_e_priority"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
    ],
    install_requires=["setuptools", "pyyaml"],
    zip_safe=True,
    maintainer="ASH-E",
    maintainer_email="ash-e@example.com",
    description="ASH-E target priority node (thin ROS2 wrapper around ash_e_core.priority)",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "priority_node = ash_e_priority.priority_node:main",
            "fake_detections_pub = ash_e_priority.tools.fake_detections_pub:main",
        ],
    },
)
