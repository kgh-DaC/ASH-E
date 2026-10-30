"""Inference backends: OnnxModel (onnxruntime) and StubModel. NCNN is not implemented in stage A."""
from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

log = logging.getLogger("ash_e_core.backends")


class StubModel:
    """Placeholder when the model file is missing. Returns None; detectors treat it as 'no detections'."""
    is_stub = True
    input_size = 0

    def __init__(self, reason: str = "model not found"):
        self.reason = reason

    def run(self, x: np.ndarray) -> Optional[np.ndarray]:
        return None


class OnnxModel:
    is_stub = False

    def __init__(self, path: str, num_threads: int = 4):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(num_threads)
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])  # CPU only (spec 1.2)
        inp = self.sess.get_inputs()[0]
        self.input_name = inp.name
        shp = inp.shape
        self.input_size = int(shp[2]) if isinstance(shp[2], int) else 0
        self.path = path

    def run(self, x: np.ndarray) -> np.ndarray:
        return self.sess.run(None, {self.input_name: x})[0]


def load_model(path: str, backend: str = "onnxruntime", num_threads: int = 4):
    if backend != "onnxruntime":
        log.warning("backend %s not implemented in stage A, using onnxruntime", backend)
    if not path or not os.path.isfile(path):
        log.warning("model file missing: %s -> stub (no detections)", path)
        return StubModel(f"missing: {path}")
    try:
        return OnnxModel(path, num_threads)
    except Exception as e:  # noqa: BLE001
        log.error("failed to load %s: %s -> stub", path, e)
        return StubModel(str(e))
