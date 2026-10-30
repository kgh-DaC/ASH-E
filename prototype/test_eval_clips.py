"""Tests for prototype/eval_clips.py: metrics on synthetic events/labels and the hold-out protection gates.
Everything runs in pytest tmp folders (a Paths object points the script at a temp tree); no models, no real data.

  .venv\\Scripts\\python -m pytest prototype\\test_eval_clips.py -q
"""
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_clips as E  # noqa: E402

TH = {"binary_precision_max4m": 0.9, "binary_recall_max3m": 0.8, "binary_recall_3to5m": 0.6, "smoking_holding_accuracy": 0.75,
      "lookalike_false_confirm_per_10min": 1, "confirm_time_median_s": 2.0, "priority_flicker_s5": 0, "rpi5_rate_hz_min": 5.0}
RATE = 8.0


def events(duration, state_fn, dist=lambda t: 2.0 if t < 5 else 4.0, target_fn=None, tid=1):
    """Header + processed frames at 8 Hz with one detection (state_fn(t) -> 0/1/2) + footer."""
    ev = [{"type": "header", "scenario": "mouth", "fps": 15.0}]
    for k in range(int(duration * RATE)):
        t = k / RATE
        f = {"type": "frame", "frame_idx": k, "t": t, "processed": True, "dup": False,
             "detections": [dict(track_id=tid, state=state_fn(t), bbox_x=100, bbox_y=100, bbox_w=100, bbox_h=300, distance_m=dist(t) if callable(dist) else dist)]}
        if target_fn:
            f["target_id"] = target_fn(t)
        ev.append(f)
    ev.append({"type": "footer", "duration_s": float(duration)})
    return ev


def labels(segments, participants=("P05",), scenario="mouth", persons_extra=None):
    return {"fps": 15.0, "participants": list(participants), "scenario": scenario, "distance_tag": "2m", "lighting": "indoor",
            "persons": [{"person_ref": "p1", "segments": segments, "anchor": {"t": 0.0, "bbox_xyxy": [100, 100, 200, 400]}}]}


def item(lab, path="clip.mp4"):
    it = E.Item(Path(path), Path("labels.json"))
    it.lab = lab
    return it


# ------------------------------------------------------------------ metrics
def test_wilson_known_value():
    lo, hi = E.wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert E.wilson(0, 0) is None


def test_metrics_on_synthetic_clip():
    # positive [0,10) smoking: none until 1.5 s then smoking (ttc 1.5); none [10,70) gesture: false confirm 30..32 s
    def st(t):
        return 2 if 1.5 <= t < 10 or 30 <= t < 32 else 0
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking", "category": "cigarette"},
                  {"t0": 10, "t1": 70, "label": "none", "category": "gesture"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(70, st)}, TH, Path("."), final=True)
    m = r["metrics"]
    assert m["confirm_time_median_s"]["value"] == pytest.approx(1.5)
    assert m["confirm_time_median_s"]["passed"] is True
    # 0-5 s at 2 m (40 frames, confirmed from 1.5 s -> 28), 5-10 s at 4 m (40 frames, all confirmed)
    assert m["binary_recall_max3m"]["value"] == pytest.approx(28 / 40)
    assert m["binary_recall_max3m"]["passed"] is False
    assert m["binary_recall_3to5m"]["value"] == pytest.approx(1.0) and m["binary_recall_3to5m"]["passed"] is True
    # predicted positives within 4 m: 68 true + 16 false (2 s) -> precision 68/84
    assert m["binary_precision_max4m"]["value"] == pytest.approx(68 / 84)
    assert m["binary_precision_max4m"]["passed"] is False
    assert m["smoking_holding_accuracy"]["value"] == pytest.approx(1.0)
    # one false confirm in 60 s of lookalike exposure = 10 per 10 min
    assert m["lookalike_false_confirm_per_10min"]["value"] == pytest.approx(10.0)
    assert m["lookalike_false_confirm_per_10min"]["passed"] is False
    assert len(r["false_confirms"]) == 1 and r["false_confirms"][0]["t"] == pytest.approx(30.0)
    assert r["verdict"].startswith("불합격")
    assert r["pos_exposure_min"] == pytest.approx(10 / 60)


def test_pass_wording_and_uncertain_flag():
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}, {"t0": 10, "t1": 70, "label": "none", "category": "similar_object"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(70, lambda t: 2 if 0.5 <= t < 10 else 0)}, TH, Path("."), final=True)
    assert r["verdict"].startswith("예비 합격 (holdout n=1명, 클립 1개, 양성 노출 0.2분)")
    lk = r["metrics"]["lookalike_false_confirm_per_10min"]
    assert lk["value"] == 0.0 and lk["rule_of_three_upper"] == pytest.approx(30.0)     # 3 / (1 min / 10)
    assert lk["uncertain"] and any("exposure" in f for f in lk["flags"])
    assert "flicker" not in r["verdict"]


def test_dev_run_has_no_verdict_wording_of_pass():
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(10, lambda t: 2)}, TH, Path("."), final=False)
    assert "NOT a judgment" in r["verdict"] and "합격" not in r["verdict"]


def test_lingering_state_after_positive_is_not_a_false_confirm_but_new_edge_is():
    def st(t):
        return 2 if t < 11 or 20 <= t < 21 else 0      # state lingers 1 s into the none segment, then one real false confirm
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}, {"t0": 10, "t1": 40, "label": "none", "category": "gesture"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(40, st)}, TH, Path("."), final=True)
    assert [c["t"] for c in r["false_confirms"]] == [20.0]


def test_missed_positive_and_occluded_and_heated_not_judged():
    lab = labels([{"t0": 0, "t1": 10, "label": "holding"},
                  {"t0": 10, "t1": 20, "label": "none", "category": "cigarette", "occluded": True},
                  {"t0": 20, "t1": 30, "label": "none", "category": "ecig_heated"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(30, lambda t: 2 if t >= 10 else 0)}, TH, Path("."), final=True)
    assert len(r["misses"]) == 1 and r["misses"][0]["reason"] == "tracked but never confirmed"
    assert r["metrics"]["lookalike_false_confirm_per_10min"]["value"] is None        # no lookalike exposure
    assert r["other_buckets"]["occluded_none"]["edges"] == 1 and r["other_buckets"]["ecig_heated"]["edges"] == 0
    assert r["verdict"].startswith("판정 불가")


def test_smoking_holding_confusion_and_far_distance_bins():
    lab = labels([{"t0": 0, "t1": 10, "label": "holding"}])
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(10, lambda t: 2, dist=4.0)}, TH, Path("."), final=True)   # predicts smoking at 4 m
    m = r["metrics"]
    assert m["smoking_holding_accuracy"]["value"] == 0.0
    assert m["binary_recall_3to5m"]["value"] == 1.0 and m["binary_recall_max3m"]["value"] is None


def test_bootstrap_is_deterministic_and_needs_two_clips():
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}])
    its = [item(lab, "a/clip.mp4"), item(lab, "b/clip.mp4"), item(lab, "c/clip.mp4")]
    ev = {n: events(10, lambda t: 2 if t >= 1 + (0.5 if n == "b" else 0) else 0) for n in ("a", "b", "c")}
    base = Path(".")
    ev = {it.cid(base): ev[n] for it, n in zip(its, "abc")}
    r1 = E.evaluate(its, ev, TH, base, True)
    r2 = E.evaluate(its, ev, TH, base, True)
    assert r1["metrics"]["confirm_time_median_s"]["boot"] == r2["metrics"]["confirm_time_median_s"]["boot"] is not None
    one = E.evaluate(its[:1], {k: v for k, v in list(ev.items())[:1]}, TH, base, True)
    assert one["metrics"]["confirm_time_median_s"]["boot"] is None


def test_flicker_counting():
    assert E.flicker_count([(0, 1), (1, 2), (5, 1), (30, 2)]) == 1          # 1->2 at t=1 and 2->1 at t=5 are 4 s apart
    assert E.flicker_count([(0, 1), (1, 2), (30, 1)]) == 0
    assert E.flicker_count([(0, None), (1, 1), (2, 1)]) == 0


def test_s5_flicker_not_measured_without_target_or_second_participant():
    lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}], scenario="s5_mixed")
    r = E.evaluate([item(lab, "c/clip.mp4")], {"c": events(10, lambda t: 2)}, TH, Path("."), final=True)
    assert r["flicker"]["count"] is None and "not measured" in r["flicker"]["reason"]
    lab2 = labels([{"t0": 0, "t1": 10, "label": "smoking"}], participants=("P05", "P06"), scenario="s5_mixed")
    lab2["persons"][0]["participant"] = "P05"
    r = E.evaluate([item(lab2, "c/clip.mp4")], {"c": events(10, lambda t: 2, target_fn=lambda t: 1 if t < 3 else (2 if t < 5 else 1))}, TH, Path("."), final=True)
    assert r["flicker"]["count"] == 1 and r["metrics"]["priority_flicker_s5"]["passed"] is False


def test_validate_labels_rejects_template():
    tpl = {"persons": [{"person_ref": "p1", "segments": [], "anchor": {"t": None, "bbox_xyxy": None}}], "participants": ["P05"]}
    pr = E.validate_labels(tpl)
    assert any("anchor" in x for x in pr) and any("no segments" in x for x in pr)
    assert E.validate_labels(labels([{"t0": 0, "t1": 5, "label": "smoking"}])) == []
    assert E.validate_labels(labels([{"t0": 5, "t1": 1, "label": "x"}]))


# ------------------------------------------------------------------ protection gates
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class World:
    """Temp project tree with locked thresholds, a hold-out clip of P05 and (optionally) split info."""

    def __init__(self, tmp, global_manifest=True, accept_sha=True):
        self.P = E.Paths(tmp)
        P = self.P
        P.accept.mkdir(parents=True)
        (P.accept / "acceptance.yaml").write_text("\n".join("%s: %s" % kv for kv in TH.items()), encoding="utf-8")
        if accept_sha:
            (P.accept / "acceptance.sha256").write_text("%s  acceptance/acceptance.yaml\n" % sha(P.accept / "acceptance.yaml"))
        self.hclip = P.holdout / "P05/S1/mouth_001"
        self.write_clip(self.hclip, ["P05"])
        self.dclip = P.dev / "P04/S1/mouth_001"
        self.write_clip(self.dclip, ["P04"])
        if global_manifest:
            self.write_global()

    def write_clip(self, d, parts):
        d.mkdir(parents=True)
        (d / "clip.mp4").write_bytes(b"not a real video")
        lab = labels([{"t0": 0, "t1": 10, "label": "smoking"}, {"t0": 10, "t1": 70, "label": "none", "category": "gesture"}],
                     participants=parts)
        (d / "labels.json").write_text(json.dumps(lab), encoding="utf-8")

    def write_global(self):
        P = self.P
        files = [P.accept / "acceptance.yaml"] + [p for p in sorted(P.holdout.rglob("*")) if p.is_file()]
        (P.accept / "holdout_manifest.sha256").write_text(
            "".join("%s  %s\n" % (sha(p), p.relative_to(P.root).as_posix()) for p in files))

    def splits(self, **groups):
        self.P.splits.parent.mkdir(parents=True, exist_ok=True)
        self.P.splits.write_text(json.dumps(groups))

    def run(self, *argv):
        def rep(it, cid, pipe, outdir, rate, throttle):
            return events(70, lambda t: 2 if 0.5 <= t < 10 else 0)
        return E.main(list(argv), P=self.P, make_pipe_fn=lambda a: (types.SimpleNamespace(process_rate_hz=8.0), None), replay_fn=rep)


def test_holdout_clips_refused_without_final(tmp_path):
    w = World(tmp_path)
    with pytest.raises(SystemExit, match="hold-out"):
        w.run("--clips-dir", str(w.P.holdout))
    with pytest.raises(SystemExit, match="hold-out"):
        w.run("--clips-dir", str(w.P.root / "data/eval"))            # ancestor containing hold-out
    assert not (w.P.out / "clips_holdout").exists() and not w.P.runs_log.exists()


def test_holdout_participant_in_raw_clips_refused_without_final(tmp_path):
    w = World(tmp_path)
    w.splits(train=["P01"], val=["P04"], holdout=["P05"])
    raw = w.P.root / "data/raw_clips/P05/S1/mouth_001"
    w.write_clip(raw, ["P05"])
    with pytest.raises(SystemExit, match="hold-out"):
        w.run("--clips-dir", str(w.P.root / "data/raw_clips"))
    # even when only the holdout dir is known (no participants.json): PID found under data/eval/holdout
    (w.P.splits).unlink()
    with pytest.raises(SystemExit, match="hold-out"):
        w.run("--clips-dir", str(w.P.root / "data/raw_clips"))


def test_dev_runs_and_cross_group_rules(tmp_path):
    w = World(tmp_path)
    w.splits(train=["P01"], val=["P04"], holdout=["P05"])
    r = w.run()                                                       # default = data/eval/dev
    assert r is not None and "NOT a judgment" in r["verdict"]
    assert (w.P.out / "clips_dev/report.md").is_file() and not w.P.runs_log.exists()
    tr = w.P.root / "data/raw_clips/P01/S1/mouth_001"
    w.write_clip(tr, ["P01"])
    with pytest.raises(SystemExit, match="TRAINING"):
        w.run("--clips-dir", str(w.P.root / "data/raw_clips"))
    mix = w.P.root / "data/raw_clips2/P04/S1/s5_001"
    w.write_clip(mix, ["P04", "P01"])
    lab = json.loads((mix / "labels.json").read_text())
    lab["persons"][0]["participant"] = "P04"
    (mix / "labels.json").write_text(json.dumps(lab))
    with pytest.raises(SystemExit, match="mixes participant groups"):
        w.run("--clips-dir", str(w.P.root / "data/raw_clips2"))


def test_unknown_split_refused_unless_flag(tmp_path):
    w = World(tmp_path)
    raw = w.P.root / "data/raw_clips/P09/S1/mouth_001"
    w.write_clip(raw, ["P09"])
    with pytest.raises(SystemExit, match="group unknown"):
        w.run("--clips-dir", str(w.P.root / "data/raw_clips"))
    assert w.run("--clips-dir", str(w.P.root / "data/raw_clips"), "--allow-unknown-split") is not None


def test_final_refuses_when_acceptance_hash_mismatch_or_missing(tmp_path):
    w = World(tmp_path)
    y = w.P.accept / "acceptance.yaml"
    y.write_text(y.read_text() + "\nconfirm_time_median_s: 99\n")
    with pytest.raises(SystemExit, match="does not match"):
        w.run("--final")
    with pytest.raises(SystemExit, match="does not match"):
        w.run()                                                        # every mode checks the hash
    assert not w.P.runs_log.exists() and not w.P.clip_manifest.exists()


def test_final_refuses_without_acceptance_sha_file(tmp_path):
    w = World(tmp_path, accept_sha=False)
    with pytest.raises(SystemExit, match="acceptance.sha256 is missing"):
        w.run("--final")


def test_final_refuses_without_or_with_bad_global_manifest(tmp_path):
    w = World(tmp_path, global_manifest=False)
    with pytest.raises(SystemExit, match="manifest missing"):
        w.run("--final")
    w.write_global()
    (w.hclip / "labels.json").write_text((w.hclip / "labels.json").read_text() + " ")
    with pytest.raises(SystemExit, match="mismatching"):
        w.run("--final")
    assert not w.P.runs_log.exists()


def test_final_records_manifest_logs_runs_and_detects_changes(tmp_path):
    w = World(tmp_path)
    r = w.run("--final")
    assert r["verdict"].startswith("예비 합격 (holdout n=1명, 클립 1개")
    assert w.P.clip_manifest.is_file()
    assert len(w.P.runs_log.read_text().splitlines()) == 1
    assert (w.P.out / "clips_holdout/run_001/report.md").is_file()
    assert "holdout 실행 횟수: **1**" in (w.P.out / "clips_holdout/run_001/report.md").read_text(encoding="utf-8")
    r = w.run("--final")                                               # unchanged -> verified, run #2, earlier result kept
    assert len(w.P.runs_log.read_text().splitlines()) == 2 and (w.P.out / "clips_holdout/run_001").is_dir()
    assert (w.P.out / "clips_holdout/run_002/report.md").is_file()
    # changed label -> clip manifest (and the global one) refuse; log unchanged
    lp = w.hclip / "labels.json"
    lp.write_text(lp.read_text().replace('"smoking"', '"holding"'))
    with pytest.raises(SystemExit, match="REFUSED"):
        w.run("--final")
    assert len(w.P.runs_log.read_text().splitlines()) == 2


def test_clip_manifest_alone_detects_changed_and_added_files(tmp_path):
    w = World(tmp_path)
    assert E.check_clip_manifest(w.P) == "created"
    assert E.check_clip_manifest(w.P) == "verified"
    (w.hclip / "clip.mp4").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="changed 1"):
        E.check_clip_manifest(w.P)
    (w.hclip / "clip.mp4").write_bytes(b"not a real video")
    assert E.check_clip_manifest(w.P) == "verified"
    w.write_clip(w.P.holdout / "P05/S1/gesture_001", ["P05"])
    with pytest.raises(SystemExit, match="added 2"):
        E.check_clip_manifest(w.P)
    # removing a file is also a change
    for f in (w.P.holdout / "P05/S1/gesture_001").iterdir():
        f.unlink()
    (w.P.holdout / "P05/S1/gesture_001").rmdir()
    (w.hclip / "labels.json").unlink()
    with pytest.raises(SystemExit, match="removed 1"):
        E.check_clip_manifest(w.P)


def test_final_refuses_holdout_clip_with_non_holdout_participant(tmp_path):
    w = World(tmp_path)
    w.splits(train=["P01"], val=["P04"], holdout=["P05"])
    d = w.P.holdout / "P05/S1/s5_001"
    w.write_clip(d, ["P05", "P01"])
    lab = json.loads((d / "labels.json").read_text())
    lab["persons"][0]["participant"] = "P05"
    (d / "labels.json").write_text(json.dumps(lab))
    w.write_global()
    with pytest.raises(SystemExit, match="conflicting group info|Cross contamination"):
        w.run("--final")
    assert not w.P.clip_manifest.exists() and not w.P.runs_log.exists()


def test_final_refuses_unlabeled_holdout_clip_and_outside_dir(tmp_path):
    w = World(tmp_path)
    d = w.P.holdout / "P05/S1/gesture_001"
    d.mkdir(parents=True)
    (d / "clip.mp4").write_bytes(b"x")
    (d / "labels.json").write_text(json.dumps({"persons": [{"person_ref": "p1", "segments": [], "anchor": {"t": None, "bbox_xyxy": None}}]}))
    w.write_global()
    with pytest.raises(SystemExit, match="all-or-nothing"):
        w.run("--final")
    with pytest.raises(SystemExit, match="outside"):
        w.run("--final", "--clips-dir", str(w.P.dev))


def test_training_refuse_holdout_covers_raw_clips_and_ancestors():
    sys.path.insert(0, str(E.ROOT / "training"))
    import dataset_utils as D
    for rel in ("data/eval/holdout/x", "data/raw_clips/P01/S1/a", "data/raw_clips", "data", "data/eval", "acceptance/acceptance.yaml",
                "DATA/Raw_Clips/P01"):
        with pytest.raises(SystemExit):
            D.refuse_holdout(D.ROOT / rel)
    for rel in ("data/roi_ds", "data/labeled/P01/a.jpg", "data/eval/dev"):
        D.refuse_holdout(D.ROOT / rel)


def test_end_to_end_real_replay_of_recorded_clip(tmp_path):
    """Record a synthetic clip with the fake-model pipeline (clip_io), label it, evaluate through the real replay path."""
    import test_clip_io as T
    w = World(tmp_path)
    pipe = T.make_pipe()
    rec = E.clip_io.ClipRecorder(pipe, w.P.dev, "P04", "S2", "mouth", fps=15.0, rate_hz=8.0)
    now = 1000.0
    for _ in range(120):                                   # 4 s
        now += 1 / 30
        rec.feed(T.FRAME, now)
    rec.stop()
    d = w.P.dev / "P04/S2/mouth_001"
    lab = json.loads((d / "labels.json").read_text())
    lab["persons"] = [{"person_ref": "p1", "anchor": {"t": 0.0, "bbox_xyxy": [110, 20, 210, 300]},
                       "segments": [{"t0": 0.0, "t1": 4.0, "label": "smoking"}]}]
    (d / "labels.json").write_text(json.dumps(lab))
    r = E.main(["--clips-dir", str(w.P.dev / "P04/S2")], P=w.P, make_pipe_fn=lambda a: (types.SimpleNamespace(process_rate_hz=8.0), pipe))
    assert (w.P.out / "clips_dev/replay/mouth_001.events.jsonl").is_file()
    assert not (d / "events.replay.jsonl").exists()              # replay output never lands next to the clip
    seg = [s for s in r["segments"] if s["clip"] == "mouth_001"][0]
    assert seg["n_frames"] > 10 and seg["confirmed"] is True and seg["ttc"] is not None
