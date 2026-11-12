"""Tests for prototype/fill_clip_labels.py (no models, no video; temp folders only).

  .venv\\Scripts\\python -m pytest prototype\\test_fill_clip_labels.py -q
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_clips as E  # noqa: E402
import fill_clip_labels as F  # noqa: E402


def det(tid, x=100):
    return dict(track_id=tid, state=0, bbox_x=x, bbox_y=50, bbox_w=200, bbox_h=400, distance_m=2.0)


def make_clip(tmp, rel="P02/S1/mouth_002", dets_fn=lambda k: [det(1)], n=80, labels=None):
    d = tmp / rel
    d.mkdir(parents=True)
    ev = [{"type": "header", "fps": 15.0}]
    for k in range(n):
        ev.append({"type": "frame", "frame_idx": k, "t": round(k / 15.0, 4), "processed": k % 2 == 0, "detections": dets_fn(k)})
    ev.append({"type": "footer", "duration_s": round(n / 15.0, 4)})
    (d / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev), encoding="utf-8")
    if labels is not None:
        (d / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
    return d


def read(d):
    return json.loads((d / "labels.json").read_text(encoding="utf-8"))


def test_fill_from_scenario_and_number(tmp_path):
    d = make_clip(tmp_path)
    st, _ = F.fill_one(d, {"P02": "dev"}, None, False)
    lab = read(d)
    assert st == "filled" and lab["split"] == "dev" and lab["distance_tag"] == "3m" and lab["reviewed"] is False
    sg = lab["persons"][0]["segments"]
    assert sg == [{"t0": 0.0, "t1": round(80 / 15.0, 4), "label": "smoking", "category": "cigarette"}]
    assert lab["persons"][0]["anchor"] == {"t": 0.0, "bbox_xyxy": [100.0, 50.0, 300.0, 450.0]}
    assert E.validate_labels(lab) == []                      # usable by the evaluator as is


@pytest.mark.parametrize("scenario,label,cat", [("holding", "holding", "cigarette"), ("similar", "none", "similar_object"),
                                                ("gesture", "none", "gesture"), ("none", "none", "plain"),
                                                ("walking", "smoking", "cigarette"), ("ecig_heated", "none", "ecig_heated")])
def test_scenario_table(tmp_path, scenario, label, cat):
    d = make_clip(tmp_path, "P03/S1/%s_001" % scenario)
    F.fill_one(d, {"P03": "holdout"}, None, False)
    lab = read(d)
    sg = lab["persons"][0]["segments"][0]
    assert (sg["label"], sg["category"], lab["split"]) == (label, cat, "holdout")


def test_anchor_is_the_person_present_longest(tmp_path):
    # a bystander (id 1) is seen first and briefly; the participant (id 2) appears later and stays
    d = make_clip(tmp_path, dets_fn=lambda k: [det(1, 900)] if k < 10 else [det(2, 300)] + ([det(3, 900)] if k % 4 == 0 else []))
    _, msg = F.fill_one(d, {}, None, False)
    an = read(d)["persons"][0]["anchor"]
    assert an["bbox_xyxy"][0] == 300.0 and an["t"] == pytest.approx(10 / 15.0, abs=1e-3)
    assert "OTHER PEOPLE" in msg


def test_never_overwrites_filled_labels_without_force(tmp_path):
    hand = {"persons": [{"person_ref": "p1", "segments": [{"t0": 1, "t1": 2, "label": "none"}], "anchor": {"t": 0, "bbox_xyxy": [0, 0, 1, 1]}}],
            "reviewed": True}
    d = make_clip(tmp_path, labels=hand)
    assert F.fill_one(d, {}, None, False)[0] == "kept" and read(d) == hand
    assert F.fill_one(d, {}, None, True)[0] == "filled" and read(d)["reviewed"] is False


def test_override_with_occluded_tail(tmp_path):
    d = make_clip(tmp_path, "P02/S1/side_001", n=150)
    F.fill_one(d, {}, [{"t0": 0, "t1": 4.0, "label": "smoking"}, {"t0": 4.0, "t1": None, "label": "none", "occluded": True}], False)
    a, b = read(d)["persons"][0]["segments"]
    assert (a["t1"], a["label"], a["category"]) == (4.0, "smoking", "cigarette")
    assert (b["t0"], b["t1"], b["label"], b.get("occluded")) == (4.0, 10.0, "none", True)
    assert E.validate_labels(read(d)) == []
    with pytest.raises(ValueError):
        F.build_segments("side", 10.0, [{"t0": 0, "t1": 5, "label": "smoke"}])


def test_skips_unknown_scenario_and_missing_events(tmp_path):
    assert F.fill_one(make_clip(tmp_path, "P02/S1/dancing_001"), {}, None, False)[0] == "skipped"
    d = make_clip(tmp_path, "P02/S1/mouth_001")
    (d / "events.jsonl").unlink()
    assert F.fill_one(d, {}, None, False)[0] == "skipped"
    assert F.fill_one(make_clip(tmp_path, "P02/S1/mouth_003", dets_fn=lambda k: []), {}, None, False)[0] == "skipped"
