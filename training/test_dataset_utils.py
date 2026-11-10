"""Unit tests for own_subject (third-party filter for own captures, capture QC 2026-11-10)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import own_subject  # noqa: E402
from ash_e_core.types import PersonPose  # noqa: E402

W = 1280


def person(x1, x2, n_vis=17):
    k = np.zeros((17, 3), np.float32)
    k[:n_vis, 2] = 0.9
    return PersonPose(bbox_xyxy=np.array([x1, 100, x2, 700], np.float32), conf=0.9, keypoints=k)


def test_single_subject_kept():
    p = person(500, 800)
    assert own_subject([p], W) == [p]


def test_seated_third_party_at_edge_ignored():
    subj, third = person(500, 800), person(1110, 1279, n_vis=3)
    assert own_subject([subj, third], W) == [subj]


def test_two_inner_people_drop_frame():
    assert own_subject([person(200, 500), person(800, 1100)], W) == []


def test_subject_half_out_at_edge_drops_frame():
    # P01 cut off at the left edge (many joints visible) while the third party stands inside -> ambiguous
    assert own_subject([person(0, 585, n_vis=11), person(860, 1200)], W) == []


def test_only_edge_people_drop_frame():
    assert own_subject([person(1100, 1279, n_vis=3)], W) == []


def test_no_people():
    assert own_subject([], W) == []
