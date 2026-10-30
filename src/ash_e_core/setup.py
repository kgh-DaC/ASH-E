from setuptools import setup, find_packages

setup(
    name="ash_e_core",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    install_requires=["numpy<2", "opencv-python", "onnxruntime", "pyyaml"],
    zip_safe=True,
)
