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


def test_select_frames_review_state():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_roi_own_reviewed import select_frames
    fr = [("P01/S1/holding/a.jpg", "/a", "holding"), ("P01/S1/holding/b.jpg", "/b", "holding"),
          ("P01/S1/mouth/c.jpg", "/c", "mouth"), ("P01/S1/mouth/d.jpg", "/d", "mouth"),
          ("P01/S1/none/e.jpg", "/e", "none"), ("P01/S1/similar/f.jpg", "/f", "similar"),
          ("P01/S1/holding/g.jpg", "/g", "holding")]
    state = {"P01/S1/holding/a.jpg": "ok", "P01/S1/holding/b.jpg": "ignore", "P01/S1/mouth/c.jpg": "ok",
             "P01/S1/mouth/d.jpg": "ok"}
    keep, drop = select_frames(fr, state, {"/f"}, lambda p: p != "/d")
    assert [k[1] for k in keep] == ["/a", "/c", "/e"]
    assert drop["state_ignore"] == 1 and drop["unreviewed"] == 1 and drop["ok_but_boxless"] == 1 and drop["ignored"] == 1


def test_bystanders_ok_ignores_edge_person_and_takes_largest_inner():
    from dataset_utils import own_subject as f
    subj, edge = person(500, 800), person(1000, 1279, n_vis=12)        # seated bystander cut off at the right border
    assert f([subj, edge], W) == [] and f([subj, edge], W, True) == [subj]
    small = person(850, 950)
    assert f([small, subj], W, True) == [subj]                           # two fully visible: the larger one
    assert f([edge], W, True) == []                                      # nobody fully visible -> still dropped


def test_bystanders_consented_reads_session_list(tmp_path):
    from dataset_utils import bystanders_consented as c
    p = tmp_path / "data/raw/P01/S2/mouth/x.jpg"
    assert c(p, tmp_path) is False                                       # no file -> strict
    (tmp_path / "data/splits").mkdir(parents=True)
    (tmp_path / "data/splits/bystander_consent.json").write_text('{"sessions": ["P01/S2"]}')
    assert c(p, tmp_path) is True
    assert c(tmp_path / "data/labeled/P01/S2/holding/y.jpg", tmp_path) is True
    assert c(tmp_path / "data/raw/P01/S1/mouth/x.jpg", tmp_path) is False
