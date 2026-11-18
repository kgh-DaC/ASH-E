from setuptools import setup, find_packages

setup(
    name="ash_e_core",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    # data_files: ament index marker + package.xml so that colcon (ament_python) builds this package too.
    # Harmless for `pip install -e src/ash_e_core`.
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/ash_e_core"]),
        ("share/ash_e_core", ["package.xml"]),
    ],
    install_requires=["numpy<2", "opencv-python", "onnxruntime", "pyyaml"],
    zip_safe=True,
)
