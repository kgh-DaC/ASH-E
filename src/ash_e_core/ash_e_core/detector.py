"""Pose (person + 17 keypoints) and ROI cigarette detectors on top of backends.
Pure numpy/cv2 pre- and post-processing (letterbox, NMS) so the same code runs on Windows and RPi5."""
from __future__ import annotations

from typing import List, Sequence, Tuple

import cv2
import numpy as np

from .types import CigBox, PersonPose


def letterbox(img: np.ndarray, size: int) -> Tuple[np.ndarray, float, float, float]:
    """Resize keeping aspect into size x size with gray padding.
    Returns (1x3xSxS float32 RGB [0,1], scale, pad_x, pad_y)."""
    h, w = img.shape[:2]
    s = min(size / h, size / w)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, np.uint8)
    ix, iy = int((size - nw) // 2), int((size - nh) // 2)
    canvas[iy:iy + nh, ix:ix + nw] = r
    x = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    return np.ascontiguousarray(x[None]), float(s), float(ix), float(iy)


def iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1]) + max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1]) - inter
    return float(inter / ua) if ua > 0 else 0.0


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float) -> List[int]:
    order = list(np.argsort(-scores, kind="stable"))
    keep: List[int] = []
    while order:
        i = order.pop(0)
        keep.append(int(i))
        order = [j for j in order if iou_xyxy(boxes[i], boxes[j]) <= iou_thresh]
    return keep


def _as_nc(out: np.ndarray, ch: int) -> np.ndarray:
    """(1,C,N) or (1,N,C) -> (N,C), where C == ch is the known channel count."""
    o = np.asarray(out)[0]
    return o.T if (o.shape[0] == ch and o.shape[1] != ch) else o


class PoseModel:
    """YOLO11n-pose ONNX: output (1, 56, N) = cx,cy,w,h,conf + 17*(x,y,conf)."""

    def __init__(self, model, cfg):
        self.model, self.cfg = model, cfg
        self.size = int(model.input_size) or int(cfg.pose_input)

    @property
    def is_stub(self) -> bool:
        return bool(getattr(self.model, "is_stub", False))

    def detect(self, frame_bgr: np.ndarray) -> List[PersonPose]:
        if self.is_stub:
            return []
        x, s, px, py = letterbox(frame_bgr, self.size)
        out = self.model.run(x)
        if out is None:
            return []
        return self.decode(out, s, px, py, frame_bgr.shape[1], frame_bgr.shape[0])

    def decode(self, out, s, px, py, W, H) -> List[PersonPose]:
        p = _as_nc(out, 56)
        if p.shape[1] < 56:
            return []
        p = p[p[:, 4] >= self.cfg.person_conf_thresh]
        if len(p) == 0:
            return []
        cx, cy, w, h = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1)
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - px) / s
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - py) / s
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clip(0, W - 1)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clip(0, H - 1)
        kp = p[:, 5:56].reshape(-1, 17, 3).copy()
        kp[:, :, 0] = (kp[:, :, 0] - px) / s
        kp[:, :, 1] = (kp[:, :, 1] - py) / s
        keep = nms(xyxy, p[:, 4], 0.5)
        res = []
        for i in keep:
            if (xyxy[i, 3] - xyxy[i, 1]) < self.cfg.min_person_h_px:
                continue
            res.append(PersonPose(xyxy[i].astype(np.float32), float(p[i, 4]), kp[i].astype(np.float32)))
        res.sort(key=lambda q: -(q.bbox_xyxy[3] - q.bbox_xyxy[1]))  # big (near) first
        return res[: self.cfg.max_persons]


class CigaretteRoiModel:
    """1-class YOLO11n detector run on letterboxed ROI crops. Output (1, 5, N) = cx,cy,w,h,conf."""

    def __init__(self, model, cfg):
        self.model, self.cfg = model, cfg
        self.size = int(model.input_size) or int(cfg.roi_input)

    @property
    def is_stub(self) -> bool:
        return bool(getattr(self.model, "is_stub", False))

    def decode(self, out, s, px, py, ox, oy, conf_thresh) -> List[CigBox]:
        p = _as_nc(out, 5)
        if p.shape[1] < 5:
            return []
        p = p[p[:, 4] >= conf_thresh]
        res = []
        for r in p:
            cx, cy, w, h = [float(v) for v in r[:4]]
            x1, y1 = (cx - w / 2 - px) / s + ox, (cy - h / 2 - py) / s + oy
            x2, y2 = (cx + w / 2 - px) / s + ox, (cy + h / 2 - py) / s + oy
            res.append(CigBox(np.array([x1, y1, x2, y2], np.float32), float(r[4])))
        return res

    def detect_crops(self, frame_bgr: np.ndarray, rois: Sequence[Sequence[int]],
                     conf_thresh: float = None) -> List[List[CigBox]]:
        """rois: list of (x1,y1,x2,y2) ints in frame coords. One CigBox list (frame coords) per ROI."""
        ct = self.cfg.cig_conf_thresh if conf_thresh is None else conf_thresh
        results: List[List[CigBox]] = []
        for (x1, y1, x2, y2) in rois:
            if self.is_stub or x2 - x1 < 2 or y2 - y1 < 2:
                results.append([])
                continue
            x, s, px, py = letterbox(frame_bgr[y1:y2, x1:x2], self.size)
            out = self.model.run(x)
            results.append([] if out is None else self.decode(out, s, px, py, x1, y1, ct))
        return results


def global_nms(boxes: List[CigBox], iou_thresh: float = 0.5) -> List[CigBox]:
    if not boxes:
        return []
    b = np.stack([c.xyxy for c in boxes])
    sc = np.array([c.conf for c in boxes])
    return [boxes[i] for i in nms(b, sc, iou_thresh)]
