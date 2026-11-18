"""Self-test of compare_jsonl.py (equivalence comparison): identical / jittered / dropped first frame / wrong target."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_jsonl as cj  # noqa: E402


def _det(tid, x=100, state=2, conf=0.8):
    return {"track_id": tid, "state": state, "raw_confidence": conf, "bbox_x": x, "bbox_y": 50, "bbox_w": 200, "bbox_h": 400}


def _recs(n=30):
    out = []
    for i in range(n):
        ev = 1 if i == 3 else 0
        out.append({"frame_seq": i + 1, "stamp": round(i / 15.0, 4),
                    "detections": {"detections": [_det(1), _det(2, x=400, state=1)]},
                    "target": {"target_id": 1 if i >= 3 else 0, "last_event": ev}})
    return out


def test_identical_passes():
    a = _recs()
    r = cj.compare(a, copy.deepcopy(a))
    assert r["pass"] and r["iou_mean"] == 1.0 and r["events_identical"]


def test_small_jitter_passes():
    a, b = _recs(), _recs()
    for r in b:
        for d in r["detections"]["detections"]:
            d["bbox_x"] += 1
            d["raw_confidence"] += 0.01
    assert cj.compare(a, b)["pass"]


def test_dropped_first_frame_fails_frame_count_but_aligns_by_stamp():
    a = _recs()
    b = copy.deepcopy(a)[1:]
    r = cj.compare(a, b)
    assert not r["pass"] and not r["checks"]["frames_equal"]
    assert r["n_paired"] == len(a) - 1 and r["only_proto"] == 1


def test_state_flip_and_target_change_fail():
    a, b = _recs(), _recs()
    for r in b:
        r["detections"]["detections"][0]["state"] = 0
        r["target"]["target_id"] = 2 if r["target"]["target_id"] else 0
    r = cj.compare(a, b)
    assert not r["checks"]["state"] and not r["checks"]["target_id"] and not r["pass"]


def test_no_target_logs_skip_target_checks():
    a, b = _recs(), _recs()
    for r in a + b:
        r["target"] = None
    r = cj.compare(a, b)
    assert r["pass"] and "target_id" not in r["checks"]
