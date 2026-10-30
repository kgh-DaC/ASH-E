"""PerceptionPipeline: shared entry point for the Windows prototype and the ROS wrapper (spec 5.4).
No ROS / Windows-only imports. All decisions use the frame stamp; perf_counter is only for inference_ms."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .backends import load_model
from .config import PerceptionConfig
from .detector import CigaretteRoiModel, PoseModel, global_nms
from .distance import depth_median_position, proxy_position
from .roi import Roi, compute_rois, person_anchors
from .stabilizer import Stabilizer
from .state import Anchors, RawResult, assign_states
from .tracker import Tracker
from .types import (CameraIntrinsics, CigBox, Detection, DetectionArray, DistanceSource, PersonPose,
                    Point3, SmokerState)

log = logging.getLogger("ash_e_core.pipeline")


@dataclass
class PersonDebug:
    track_id: int
    pose: PersonPose
    rois: List[Roi]
    checked: bool
    raw: RawResult
    published: bool


@dataclass
class FrameDebug:
    persons: List[PersonDebug] = field(default_factory=list)
    cig_boxes: List[CigBox] = field(default_factory=list)
    ms_pose: float = 0.0
    ms_cig: float = 0.0
    ms_total: float = 0.0


class PerceptionPipeline:
    def __init__(self, cfg: Optional[PerceptionConfig] = None, pose_model=None, cig_model=None):
        self.cfg = cfg or PerceptionConfig()
        c = self.cfg
        self.pose = PoseModel(pose_model if pose_model is not None else
                              load_model(c.pose_model_path, c.backend, c.num_threads), c)
        self.cig = CigaretteRoiModel(cig_model if cig_model is not None else
                                     load_model(c.cig_model_path, c.backend, c.num_threads), c)
        self.tracker = Tracker(c)
        self.stabs: Dict[int, Stabilizer] = {}
        self.frame_seq = 0
        self.last = FrameDebug()
        if self.pose.is_stub:
            log.warning("pose model missing -> pipeline returns no persons")
        if self.cig.is_stub:
            log.warning("cigarette model missing -> cigarette_checked=False, state stays NONE")

    @property
    def models_ready(self) -> Dict[str, bool]:
        return {"pose": not self.pose.is_stub, "cigarette": not self.cig.is_stub}

    def process(self, frame_bgr: np.ndarray, stamp: float, frame_id: str = "",
                depth: Optional[np.ndarray] = None, intr: Optional[CameraIntrinsics] = None) -> DetectionArray:
        t0 = time.perf_counter()
        c = self.cfg
        H, W = frame_bgr.shape[:2]
        intr = intr or CameraIntrinsics.from_hfov(W, H, c.hfov_deg)
        self.frame_seq += 1
        dbg = FrameDebug()

        persons = self.pose.detect(frame_bgr)
        t1 = time.perf_counter()
        dbg.ms_pose = (t1 - t0) * 1000.0
        tmap = self.tracker.update([p.bbox_xyxy for p in persons], stamp)

        # which persons get a cigarette check this frame
        checked_idx: List[int] = []
        if not self.cig.is_stub and persons and (c.roi_every_n <= 1 or self.frame_seq % c.roi_every_n == 0):
            order = sorted(range(len(persons)),
                           key=lambda i: (tmap[i].last_checked_stamp,
                                          -(persons[i].bbox_xyxy[3] - persons[i].bbox_xyxy[1]), i))
            checked_idx = sorted(order[: c.max_roi_persons])

        rois_by_person: Dict[int, List[Roi]] = {i: compute_rois(persons[i], c, W, H) for i in checked_idx}
        flat = [(i, r) for i in checked_idx for r in rois_by_person[i]]
        cig_all: List[CigBox] = []
        if flat:
            per_roi = self.cig.detect_crops(frame_bgr, [r.xyxy for _, r in flat])
            for lst in per_roi:
                cig_all.extend(lst)
            cig_all = global_nms(cig_all, 0.5)
        dbg.cig_boxes = cig_all
        dbg.ms_cig = (time.perf_counter() - t1) * 1000.0

        anchors = []
        for i in checked_idx:
            m, hands, h = person_anchors(persons[i], c)
            anchors.append(Anchors(m, hands, h))
        results = assign_states(anchors, cig_all, c.smoking_radius, c.holding_radius) if checked_idx else []
        raw_by_person = {i: r for i, r in zip(checked_idx, results)}

        dets: List[Detection] = []
        live = set()
        for i, p in enumerate(persons):
            tr = tmap[i]
            live.add(tr.track_id)
            stab = self.stabs.setdefault(tr.track_id, Stabilizer(c))
            checked = i in raw_by_person
            raw = raw_by_person.get(i, RawResult())
            if checked:
                tr.last_checked_stamp = stamp
                # a ROI that was too small / absent still counts as checked only if at least one ROI was run
                checked = len(rois_by_person.get(i, [])) > 0
            state, sconf = stab.update(stamp, checked, raw.state, raw.conf)
            publish = tr.hits >= 2
            dbg.persons.append(PersonDebug(tr.track_id, p, rois_by_person.get(i, []), checked, raw, publish))
            if not publish:
                continue
            if depth is not None:
                pos = depth_median_position(p, depth, intr, c) or proxy_position(p, intr, c, H)
            else:
                pos = proxy_position(p, intr, c, H)
            pt, dist, src, bearing = pos
            x1, y1, x2, y2 = [int(round(float(v))) for v in p.bbox_xyxy]
            d = Detection(
                track_id=tr.track_id, state=state, state_confidence=float(sconf),
                raw_state=int(raw.state), raw_confidence=float(raw.conf) if checked else 0.0,
                cigarette_checked=bool(checked), person_confidence=float(p.conf),
                bbox_x=x1, bbox_y=y1, bbox_w=x2 - x1, bbox_h=y2 - y1,
                position=pt, distance_m=float(dist), distance_source=int(src), bearing_rad=float(bearing),
                stationary_s=float(tr.stationary_s), frames_observed=int(tr.frames_observed))
            if raw.box is not None:
                bx = raw.box.xyxy
                d.has_cigarette_box = True
                d.cig_x, d.cig_y = int(round(float(bx[0]))), int(round(float(bx[1])))
                d.cig_w, d.cig_h = int(round(float(bx[2] - bx[0]))), int(round(float(bx[3] - bx[1])))
            dets.append(d)
        for tid in [t for t in self.stabs if t not in self.tracker.tracks]:
            del self.stabs[tid]
        dets.sort(key=lambda d: d.track_id)
        dbg.ms_total = (time.perf_counter() - t0) * 1000.0
        self.last = dbg
        return DetectionArray(stamp=float(stamp), frame_id=frame_id or c.frame_id, frame_seq=self.frame_seq,
                              image_width=W, image_height=H, inference_ms=float(dbg.ms_total), detections=dets)
