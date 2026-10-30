"""Tests for paper_report.py / bench_latency.py: synthetic inputs only, temp folders, no models, no hold-out data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_report as PR  # noqa: E402


@pytest.fixture()
def demo(tmp_path):
    inp = PR.make_demo_inputs(tmp_path / "in")
    return inp, PR.Ctx(tmp_path / "out", "en", demo=True)


def load(p):
    d = json.loads(Path(p).read_text())
    d["_path"] = str(p)
    return d


def test_all_figures_and_tables_written(demo):
    inp, ctx = demo
    dev, hold = load(inp / "clips_dev/metrics.json"), load(inp / "clips_holdout/run_001/metrics.json")
    rep = load(inp / "build_report.json")
    PR.fig_training_curves(ctx, inp / "run", rep)
    sd = load(inp / "dev_scores.json")
    PR.fig_pr_and_sweep(ctx, sd, 0.35)
    im = load(inp / "metrics_dev.json")
    PR.fig_confusion(ctx, im, "dev", dev, "x")
    for split, m in (("dev", dev), ("holdout", hold)):
        PR.fig_distance_recall(ctx, m, split)
        PR.fig_ttc(ctx, m, split)
        PR.fig_false_confirm(ctx, m, split)
        PR.fig_participants(ctx, m, split)
    on, off = load(inp / "clips_ablation_stab_on/metrics.json"), load(inp / "clips_ablation_stab_off/metrics.json")
    PR.fig_ablation(ctx, on, off)
    PR.fig_dataset(ctx, rep, dev, hold, "r")
    lat = load(inp / "latency.json")
    PR.fig_latency(ctx, lat, "l")
    PR.fig_gallery(ctx, inp / "gallery", "synthetic", False)
    PR.table_summary(ctx, dev, hold)
    PR.table_dataset(ctx, rep, dev, hold, None, "r")
    PR.table_hyper(ctx, inp / "run", PR.pipeline_cfg(None))
    PR.table_latency(ctx, lat, "l")
    PR.table_ablation(ctx, on, off)
    figs = [r for r in ctx.registry if r["kind"] == "figure"]
    assert len(figs) == 16 and not ctx.skipped
    for r in ctx.registry:
        for f in r["files"]:
            assert (ctx.figdir / f if r["kind"] == "figure" else ctx.tabdir / f).stat().st_size > 0
    assert r"\toprule" in (ctx.tabdir / "tab01_metric_summary.tex").read_text(encoding="utf-8")
    assert "SYNTHETIC DEMO" in (ctx.tabdir / "tab01_metric_summary.csv").read_text(encoding="utf-8-sig")
    assert any("preliminary" in r["caption"].lower() for r in figs if r["id"].endswith("holdout"))


def test_missing_holdout_is_skipped_with_warning(tmp_path, capsys):
    ctx = PR.Ctx(tmp_path / "o", "en")
    assert PR.load_clip_metrics(ctx, None, "holdout", "hold-out clip figures") is None
    assert PR.load_images_metrics(ctx, tmp_path / "nope.json", "holdout", "hold-out confusion") is None
    assert len(ctx.skipped) == 2 and "WARNING" in capsys.readouterr().out


def test_holdout_slot_requires_final_true_and_dev_slot_refuses_final(tmp_path):
    ctx = PR.Ctx(tmp_path / "o", "en")
    f = tmp_path / "m.json"
    f.write_text(json.dumps(dict(final=False, metrics={})))
    assert PR.load_clip_metrics(ctx, f, "holdout", "h") is None
    f.write_text(json.dumps(dict(final=True, metrics={})))
    with pytest.raises(PR.HoldoutRefusedError):
        PR.load_clip_metrics(ctx, f, "dev", "d")


def test_sweep_refuses_holdout_inputs(tmp_path):
    P = PR.E.Paths(tmp_path)
    ok = dict(split="dev", final=False, records=[dict(score=0.5, label=1)])
    PR.assert_dev_scores(ok, tmp_path / "dev_scores.json", P)
    for bad in (dict(ok, split="holdout"), dict(ok, final=True), dict(ok, source_dir=str(P.holdout / "P05")),
                dict(ok, records=[dict(score=1, label=1, split="holdout")])):
        with pytest.raises(PR.HoldoutRefusedError):
            PR.assert_dev_scores(bad, None, P)
    for pth in (P.holdout / "x.json", tmp_path / "clips_holdout/run_001/dev_scores.json"):
        with pytest.raises(PR.HoldoutRefusedError):
            PR.assert_dev_scores(ok, pth, P)
    with pytest.raises(PR.HoldoutRefusedError):
        PR.collect_dev_scores(P, tmp_path, tmp_path / "o.json", base=P.holdout)


def test_load_dev_scores_rejects_holdout_file(tmp_path):
    ctx = PR.Ctx(tmp_path / "o", "en")
    f = tmp_path / "s.json"
    f.write_text(json.dumps(dict(split="holdout", records=[])))
    with pytest.raises(PR.HoldoutRefusedError):
        PR.load_dev_scores(ctx, f, PR.E.Paths(tmp_path))


def test_pr_and_sweep_values():
    s, y = [0.9, 0.8, 0.7, 0.2], [1, 1, 0, 1]
    r, p, ap = PR.pr_curve(s, y)
    assert abs(ap - (1 / 3 + 1 / 3 + 1 / 3 * 0.75)) < 1e-9
    sw = PR.sweep(s, y, [0.5])
    assert sw[0, 1] == pytest.approx(2 / 3) and sw[0, 2] == pytest.approx(2 / 3)


def test_synthetic_demo_data_refused_in_real_mode(tmp_path):
    f = tmp_path / "d.json"
    f.write_text("{}")
    with pytest.raises(PR.HoldoutRefusedError):
        PR.reject_demo_doc(dict(synthetic_demo=True), f, demo=False)
    PR.reject_demo_doc(dict(synthetic_demo=True), f, demo=True)


def test_gallery_needs_flag_for_own_faces(demo):
    inp, ctx = demo
    PR.fig_gallery(ctx, inp / "gallery", "own", False)
    assert len(ctx.skipped) == 1 and not ctx.registry
    PR.fig_gallery(ctx, inp / "gallery", "own", True, blur=True, pose_model=None)   # blur impossible -> refuses to show
    assert len(ctx.skipped) == 2 and not ctx.registry


def test_demo_output_dir_guard(tmp_path):
    with pytest.raises(SystemExit):
        PR.main(["--demo", "--out", str(tmp_path / "paper")])
    with pytest.raises(SystemExit):
        PR.main(["--out", str(PR.ROOT / "_workspace/paper_demo/x")])


def test_main_real_mode_with_nothing_skips_and_writes_repro(tmp_path):
    out = tmp_path / "paper"
    PR.main(["--out", str(out), "--eval-out", str(tmp_path / "ev"), "--run", str(tmp_path / "norun"),
             "--dataset-report", str(tmp_path / "none.json"), "--latency", str(tmp_path / "none2.json")])
    rep = json.loads((out / "reproducibility.json").read_text(encoding="utf-8"))
    assert rep["synthetic_demo"] is False and rep["skipped"] and "seeds" in rep and "acceptance" in rep
    assert "Skipped" in (out / "README.md").read_text(encoding="utf-8")


def test_ablation_runner_never_final_and_uses_dev_default(tmp_path):
    calls = []
    PR.run_ablation(tmp_path, ["--pose", "p.onnx"], None, main_fn=lambda argv: calls.append(argv))
    assert len(calls) == 2
    for argv in calls:
        assert "--final" not in argv and "--clips-dir" not in argv
    cfg = (tmp_path / "_ablation_cfg_off.yaml").read_text()
    assert "stab_min_obs: 1" in cfg
    with pytest.raises(PR.HoldoutRefusedError):
        PR.run_ablation(tmp_path, ["--final"], None, main_fn=lambda argv: None)


def test_tex_escape():
    assert PR.tex_escape("a_b 50%") == r"a\_b 50\%"
