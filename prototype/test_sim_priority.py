"""Tests for prototype/sim_priority.py (spec A9): scenario data -> detections -> PrioritySelector, flicker definition reuse.

  .venv\\Scripts\\python -m pytest prototype\\test_sim_priority.py -q
"""
import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_clips  # noqa: E402
import sim_priority as S  # noqa: E402
from ash_e_core.config import PriorityConfig, load_priority_config  # noqa: E402

SCS = S.load_scenarios()


def run(name, cfg=None):
    return S.run_scenario(name, SCS[name], cfg)


def test_scenarios_load_and_cover_required_cases():
    for n in ("s5_mixed", "two_smokers_close", "target_departs_oor", "target_dropout_reappear"):
        assert n in SCS
    for s in SCS.values():
        assert s["duration_s"] > 0 and s["tracks"]


def test_frames_deterministic_and_presence():
    a = [[(d.track_id, round(d.distance_m, 9), d.state) for d in f.detections] for f in S.scenario_frames(SCS["target_dropout_reappear"])]
    b = [[(d.track_id, round(d.distance_m, 9), d.state) for d in f.detections] for f in S.scenario_frames(SCS["target_dropout_reappear"])]
    assert a == b
    frames = list(S.scenario_frames(SCS["target_dropout_reappear"]))
    ids_at = lambda t: {d.track_id for d in frames[int(round(t * 8))].detections}  # noqa: E731
    assert ids_at(5) == {1, 2} and ids_at(10.5) == {2} and ids_at(22) == {2} and ids_at(30) == {1, 2}
    # stationary_s restarts when the track re-enters
    d1 = next(d for d in frames[int(round(25 * 8))].detections if d.track_id == 1)
    assert d1.stationary_s == pytest.approx(1.0)


def test_flicker_uses_eval_clips_definition():
    assert S.flicker_count is eval_clips.flicker_count
    ser = [(0, 1), (1, 2), (5, 1), (30, 2), (50, 1)]  # switches at 1, 5, 30, 50 -> only (1,5) within 10 s
    assert S.flicker_count(ser) == 1
    assert S.switch_times(ser) == [1, 5, 30, 50]


def test_s5_mixed_no_flicker_and_single_handover():
    r = run("s5_mixed")
    assert r["flicker_s5"] == 0 and r["switches"] == 1
    assert r["timeline"][0]["target_id"] == 1            # smoker, not the nearer non-smoker
    d = r["departures"][0]
    assert d["next_target_id"] == 2 and d["delay_s"] is not None and d["delay_s"] <= 3.0


def test_two_close_smokers_no_switch():
    r = run("two_smokers_close")
    assert r["switches"] == 0 and r["flicker_s5"] == 0 and r["event_counts"] == {"ACQUIRED": 1}


def test_out_of_range_release_hands_over():
    r = run("target_departs_oor")
    assert r["event_counts"].get("OUT_OF_RANGE") == 1
    d = r["departures"][0]
    assert d["next_target_id"] == 2 and 0.5 <= d["delay_s"] <= 2.0   # out_of_range_hold_s = 1 s (+ one frame)
    assert r["idle_s"] == 0.0


def test_dropout_short_ignored_long_lost():
    r = run("target_dropout_reappear")
    losts = [e for e in r["events"] if e["event"] == "LOST_TIMEOUT"]
    assert len(losts) == 1 and losts[0]["t"] > 20.0                  # nothing at the 1.2 s gap near t=10
    assert not [e for e in r["events"] if 10 <= e["t"] <= 13]
    assert r["departures"][0]["next_target_id"] == 2


def test_stress_scenario_shows_flicker_with_default_weights():
    # informational scenario: wobble larger than the margin must produce switches (guards against a vacuous sim)
    r = run("two_smokers_stress")
    assert r["switches"] >= 2 and r["flicker_s5"] >= 1


def test_larger_margin_suppresses_stress_switches():
    cfg = PriorityConfig(switch_margin=0.40)
    assert run("two_smokers_stress", cfg)["switches"] == 0


def test_priority_yaml_equals_defaults():
    cfg = load_priority_config(str(Path(S.HERE) / "config" / "priority.yaml"))
    assert cfg == PriorityConfig()


def test_custom_scenario_file_and_cli_json(tmp_path, capsys):
    sc = {"scenarios": {"mini": {"duration_s": 5, "tracks": [
        {"id": 7, "presence": [[0, 5]], "state": [[0, "holding"]], "distance": [[0, 2.0]]}]}}}
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(sc), encoding="utf-8")
    out = tmp_path / "o.json"
    assert S.main(["--scenarios", str(p), "--json", "--out", str(out)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res[0]["scenario"] == "mini" and res[0]["timeline"][0]["target_id"] == 7
    assert json.loads(out.read_text(encoding="utf-8"))[0]["flicker_s5"] == 0


def test_cli_text_and_unknown_scenario(capsys):
    assert S.main(["--only", "s5_mixed", "--events", "--timeline"]) == 0
    assert "SWITCHED_BETTER" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        S.main(["--only", "nope"])


def test_scenario_does_not_mutate_data():
    before = copy.deepcopy(SCS)
    run("s5_mixed")
    assert SCS == before


def _cli_err(tmp_path, capsys, text, extra=()):
    p = tmp_path / "bad.yaml"
    p.write_text(text, encoding="utf-8")
    rc = S.main(["--scenarios", str(p), *extra])
    return rc, capsys.readouterr().err


@pytest.mark.parametrize("text,msg", [
    ("", "no scenarios"),
    ("scenarios: {}", "no scenarios"),
    ("scenarios: {a: {duration_s: 5, tracks: []}}", "tracks"),
    ("scenarios: {a: {duration_s: 5, tracks: [{id: 1, presence: [[0, 5]], state: [[0, bogus]], distance: [[0, 2]]}]}}", "bogus"),
    ("scenarios: {a: {duration_s: 5, tracks: [{id: 1}]}}", "missing field"),
])
def test_cli_bad_scenario_file_clear_error(tmp_path, capsys, text, msg):
    rc, err = _cli_err(tmp_path, capsys, text)
    assert rc == 2 and msg in err and "Traceback" not in err


def test_cli_missing_files(tmp_path, capsys):
    assert S.main(["--scenarios", str(tmp_path / "nope.yaml")]) == 2
    assert "error" in capsys.readouterr().err
    assert S.main(["--config", str(tmp_path / "nope.yaml")]) == 2
    assert "error" in capsys.readouterr().err


def test_idle_never_exceeds_duration():
    sc = {"duration_s": 5, "tracks": [{"id": 1, "presence": [], "state": [[0, "smoking"]], "distance": [[0, 2.0]]}]}
    r = S.run_scenario("absent", sc)
    assert r["idle_s"] <= 5.0 and r["switches"] == 0


def test_departure_delay_none_when_target_was_not_departing_track():
    ser = [(0.0, 2), (1.0, 2), (2.0, 3), (3.0, 3)]
    d = S.departure_delays(ser, [{"track_id": 1, "t": 1.0}])[0]
    assert d["target_at_departure"] == 2 and d["delay_s"] is None and d["next_target_id"] == 3
