"""Paper / report material: quality and performance figures + tables built from the EXISTING evaluation outputs.

  python prototype/paper_report.py                    # real inputs -> _workspace/paper/   (missing inputs are skipped with a warning)
  python prototype/paper_report.py --lang ko          # Korean figure text (Malgun Gothic; falls back to en if the font is missing)
  python prototype/paper_report.py --demo             # SYNTHETIC inputs -> _workspace/paper_demo/ (watermarked, NOT results)
  python prototype/paper_report.py --collect-dev-scores   # dev replay events + labels -> _workspace/eval_out/dev_scores.json
  python prototype/paper_report.py --run-ablation         # dev clips replayed with the stabilizer on/off (eval_clips.main, dev only)
  python prototype/bench_latency.py                   # latency / FPS / model size -> _workspace/paper/latency.json

Inputs (all produced by the existing tools; nothing is re-implemented here):
  training/runs/<run>/results.csv, args.yaml          ultralytics training log
  _workspace/eval_out/clips_dev/metrics.json          eval_clips.py (dev)
  _workspace/eval_out/clips_holdout/run_NNN/metrics.json   eval_clips.py --final (READ ONLY, latest run)
  _workspace/eval_out/metrics_{dev,holdout}.json      eval_images.py (confusion matrix, binary counts)
  _workspace/eval_out/dev_scores.json                 per-frame dev scores (--collect-dev-scores)
  _workspace/eval_out/clips_ablation_stab_{on,off}/metrics.json   (--run-ablation)
  data/roi_ds_v2/build_report.json, data/SOURCES.md, acceptance/ (read only)

PROTECTION (do not weaken):
  * This tool never runs a model on hold-out data and never starts `--final`. Hold-out figures are drawn only from
    metrics.json files that eval_clips.py/eval_images.py --final already wrote. No such file -> the figure is skipped.
  * The threshold sweep / PR curve accept dev (or training-val) scores only (assert_dev_scores) and raise
    HoldoutRefusedError for anything else. No code here chooses a threshold or hyper-parameter from hold-out results.
  * acceptance/ is only read (hashes, thresholds). refuse_holdout() is not bypassed.
  * Faces: the case gallery needs --gallery-source public|synthetic, or --allow-own-faces for participant crops (blurred).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata as im
import json
import math
import platform
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

import eval_clips as E  # noqa: E402  (stats helpers, label rules, Paths; its protection code is reused, not copied)

DEMO_MARK = "SYNTHETIC DEMO – NOT RESULTS"
POS = E.POS
SWEEP_SEED = 20261030


class HoldoutRefusedError(RuntimeError):
    """Raised when a hold-out source reaches code that must only see dev / training-val data."""


# ------------------------------------------------------------------ palette / style
OKABE = dict(blue="#0072B2", orange="#E69F00", green="#009E73", verm="#D55E00", sky="#56B4E9", purple="#CC79A7",
             yellow="#F0E442", black="#000000", grey="#7f7f7f")
CYCLE = [OKABE[k] for k in ("blue", "orange", "green", "verm", "sky", "purple")]
MARKERS = ["o", "s", "^", "D", "v", "P"]
LINES = ["-", "--", "-.", ":", (0, (5, 1)), (0, (1, 1))]

I18N = {  # key: (en, ko)
    "epoch": ("Epoch", "에폭"), "loss": ("Loss", "손실"), "train": ("train", "학습"), "val": ("val", "검증"),
    "precision": ("Precision", "정밀도"), "recall": ("Recall", "재현율"), "map50": ("mAP@0.5", "mAP@0.5"),
    "map5095": ("mAP@0.5:0.95", "mAP@0.5:0.95"), "lr": ("Learning rate", "학습률"),
    "threshold": ("Confidence threshold", "신뢰도 임계값"), "f1": ("F1", "F1"), "score": ("Score", "점수"),
    "pr_title": ("Precision-recall (dev, frame level)", "정밀도-재현율 (dev, 프레임 단위)"),
    "sweep_title": ("Threshold sweep (dev only)", "임계값 스윕 (dev 전용)"),
    "operating": ("operating point", "운용점"), "noskill": ("prevalence", "양성 비율"),
    "dev_opt": ("dev-optimal F1 (info only)", "dev 최적 F1 (참고용)"),
    "pred": ("Predicted", "예측"), "gt": ("Ground truth", "정답"), "counts": ("Counts", "개수"),
    "rownorm": ("Row-normalised", "행 정규화"), "conf_title": ("Confusion matrix (frame level, raw state)", "혼동행렬 (프레임 단위, raw 상태)"),
    "dist_title": ("Recall by distance bin", "거리 구간별 재현율"), "dist_x": ("Proxy distance bin [m] (box-height based)", "프록시 거리 구간 [m] (박스 높이 기반)"),
    "wilson": ("95% Wilson (frames)", "95% Wilson (프레임)"), "boot": ("95% clip bootstrap", "95% 클립 부트스트랩"),
    "thr_line": ("acceptance threshold", "합격선"), "ttc_title": ("Time to confirm", "확정까지 걸린 시간"),
    "ttc_x": ("Time to confirm [s]", "확정 시간 [s]"), "count": ("Segments [count]", "구간 수 [개]"), "cdf": ("Cumulative fraction", "누적 비율"),
    "median": ("median", "중앙값"), "fc_title": ("False confirmations per 10 min", "10분당 오확정"),
    "fc_y": ("False confirmations / 10 min", "오확정 횟수 / 10분"), "ub3": ("rule-of-three upper bound", "rule of three 상한"),
    "judged": ("judged", "판정 대상"), "reported": ("reported only", "참고 집계"),
    "part_title": ("Per-participant values", "참가자별 지표"), "pooled": ("pooled 95% Wilson", "전체 95% Wilson"),
    "abl_title": ("Stabilizer ablation (dev clips)", "안정화 on/off ablation (dev 클립)"), "on": ("stabilizer on", "안정화 켬"),
    "off": ("stabilizer off", "안정화 끔"), "ds_title": ("Dataset composition (ROI samples)", "데이터셋 구성 (ROI 샘플)"),
    "samples": ("ROI samples [count]", "ROI 샘플 [개]"), "lat_title": ("Latency breakdown", "지연시간 분해"),
    "ms": ("Time per frame [ms]", "프레임당 시간 [ms]"), "fps": ("Throughput [frames/s]", "처리율 [frames/s]"),
    "params": ("Parameters [M]", "파라미터 [M]"), "gal_title": ("Error cases (ROI crops)", "오류 사례 (ROI 크롭)"),
    "nodata": ("no data", "데이터 없음"),
}
WARN_SKIPPED: List[str] = []


# ------------------------------------------------------------------ context
class Ctx:
    def __init__(self, out: Path, lang: str = "en", demo: bool = False):
        self.out = Path(out)
        self.figdir, self.tabdir = self.out / "figures", self.out / "tables"
        self.figdir.mkdir(parents=True, exist_ok=True)
        self.tabdir.mkdir(parents=True, exist_ok=True)
        self.demo = demo
        self.lang = setup_style(lang)
        self.registry: List[dict] = []
        self.skipped: List[str] = []
        self.inputs_used: Dict[str, str] = {}

    def t(self, key: str) -> str:
        en, ko = I18N[key]
        return ko if self.lang == "ko" else en

    def skip(self, what: str, why: str):
        msg = "SKIPPED %s: %s" % (what, why)
        print("WARNING: " + msg)
        self.skipped.append(msg)

    def used(self, p) -> str:
        r = rel(p)
        if Path(p).is_file():
            self.inputs_used[r] = sha_file(Path(p))
        return r


def rel(p) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def sha_file(p: Path) -> str:
    return E.sha_file(Path(p))


def setup_style(lang: str) -> str:
    if lang == "ko":
        try:
            font_manager.findfont("Malgun Gothic", fallback_to_default=False)
            plt.rcParams["font.family"] = "Malgun Gothic"
        except Exception:  # noqa: BLE001
            print("WARNING: Korean font (Malgun Gothic) not found -> using --lang en")
            lang = "en"
    plt.rcParams.update({"axes.unicode_minus": False, "figure.dpi": 100, "savefig.dpi": 300, "pdf.fonttype": 42,
                         "ps.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.alpha": 0.3, "grid.linewidth": 0.6, "font.size": 9, "axes.titlesize": 10,
                         "legend.fontsize": 8, "legend.frameon": False, "axes.prop_cycle": matplotlib.cycler(color=CYCLE)})
    if lang != "ko":
        plt.rcParams["font.family"] = "DejaVu Sans"
    return lang


def save_fig(ctx: Ctx, fig, stem: str, inputs: List[str], caption: str, footnote: str = ""):
    if footnote:
        try:
            fig.get_layout_engine().set(rect=(0, 0.05, 1, 0.95))
        except Exception:  # noqa: BLE001
            pass
        fig.text(0.005, 0.003, footnote, fontsize=6.5, color="#444444", ha="left", va="bottom")
    if ctx.demo:
        fig.text(0.5, 0.5, DEMO_MARK, fontsize=20, color="#cc0000", alpha=0.28, rotation=28, ha="center", va="center",
                 weight="bold", zorder=1000)
    png, pdf = ctx.figdir / (stem + ".png"), ctx.figdir / (stem + ".pdf")
    fig.savefig(png, dpi=300)
    fig.savefig(pdf)
    plt.close(fig)
    ctx.registry.append(dict(kind="figure", id=stem, files=[png.name, pdf.name], inputs=inputs, caption=caption))
    print("figure -> %s" % png)
    return png


# ------------------------------------------------------------------ loaders (read only)
def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def reject_demo_doc(doc, p, demo: bool):
    if isinstance(doc, dict) and doc.get("synthetic_demo") and not demo:
        raise HoldoutRefusedError("%s is SYNTHETIC demo data; refusing to use it for the real paper folder." % p)


def load_csv_columns(p: Path) -> Dict[str, List[float]]:
    cols: Dict[str, List[float]] = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for k, v in row.items():
                k = (k or "").strip()
                try:
                    cols.setdefault(k, []).append(float(v))
                except (TypeError, ValueError):
                    pass
    return cols


def latest_holdout_metrics(eval_out: Path) -> Optional[Path]:
    runs = []
    for d in (Path(eval_out) / "clips_holdout").glob("run_*"):
        m = re.fullmatch(r"run_(\d+)", d.name)
        if m and (d / "metrics.json").is_file():
            runs.append((int(m.group(1)), d / "metrics.json"))
    return max(runs)[1] if runs else None


def load_clip_metrics(ctx: Ctx, p: Optional[Path], split: str, what: str) -> Optional[dict]:
    """split 'dev' needs final=false, 'holdout' needs final=true. Wrong kind -> refuse (dev slot) / skip (holdout slot)."""
    if p is None or not Path(p).is_file():
        ctx.skip(what, "no metrics file (%s) -- run eval_clips.py%s first" % (rel(p) if p else "?", " --final" if split == "holdout" else ""))
        return None
    doc = read_json(p)
    reject_demo_doc(doc, p, ctx.demo)
    if split == "dev" and doc.get("final"):
        raise HoldoutRefusedError("%s is a --final (hold-out) result but was given as a dev input." % p)
    if split == "holdout" and not doc.get("final"):
        ctx.skip(what, "%s is not an eval_clips --final output (final != true)" % rel(p))
        return None
    ctx.used(p)
    doc["_path"] = rel(p)
    return doc


def load_images_metrics(ctx: Ctx, p: Path, split: str, what: str) -> Optional[dict]:
    if not Path(p).is_file():
        ctx.skip(what, "no %s (eval_images.py%s writes it)" % (rel(p), " --final" if split == "holdout" else ""))
        return None
    doc = read_json(p)
    reject_demo_doc(doc, p, ctx.demo)
    if split == "dev" and doc.get("final"):
        raise HoldoutRefusedError("%s is a hold-out result given as dev." % p)
    if split == "holdout" and not doc.get("final"):
        ctx.skip(what, "%s is not a --final output" % rel(p))
        return None
    ctx.used(p)
    return doc


# ------------------------------------------------------------------ statistics helpers
def wilson(k, n):
    return E.wilson(k, n)


def pr_curve(scores, labels):
    """Step PR curve over the distinct scores; AP = sum (r_i - r_{i-1}) p_i. Returns (recall, precision, ap)."""
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    npos = int(y.sum())
    if npos == 0 or len(s) == 0:
        return np.array([0.0]), np.array([1.0]), None
    o = np.argsort(-s, kind="stable")
    s, y = s[o], y[o]
    tp, fp = np.cumsum(y), np.cumsum(1 - y)
    last = np.r_[s[1:] != s[:-1], True]            # one point per distinct score
    tp, fp = tp[last], fp[last]
    prec, rec = tp / np.maximum(tp + fp, 1), tp / npos
    r0 = np.r_[0.0, rec]
    ap = float(np.sum((r0[1:] - r0[:-1]) * prec))
    return rec, prec, ap


def sweep(scores, labels, thresholds=None):
    """precision / recall / F1 at each threshold; positive prediction = score >= t (t > 0; score 0 = nothing detected)."""
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    th = np.linspace(0.0, 1.0, 101) if thresholds is None else np.asarray(thresholds, float)
    out = []
    for t in th:
        pred = s >= max(float(t), 1e-12)
        tp, fp, fn = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum()), int(((~pred) & (y == 1)).sum())
        p = tp / (tp + fp) if tp + fp else float("nan")
        r = tp / (tp + fn) if tp + fn else float("nan")
        f = 2 * p * r / (p + r) if (p == p and r == r and p + r > 0) else float("nan")
        out.append((float(t), p, r, f))
    return np.array(out)


def assert_dev_scores(doc: dict, path=None, P: Optional[E.Paths] = None):
    """The only door to sweep()/pr_curve() for files: dev or training-val scores, nothing else."""
    P = P or E.Paths()
    if path is not None:
        sp = Path(path)
        if E.is_under(sp, P.holdout) or any(c.lower() == "holdout" or c.lower().startswith("clips_holdout") for c in sp.parts):
            raise HoldoutRefusedError("threshold sweep refuses hold-out input: %s" % path)
    if doc.get("split") not in ("dev", "val") or doc.get("final"):
        raise HoldoutRefusedError("threshold sweep accepts split 'dev'/'val' scores only (got split=%r final=%r)" % (doc.get("split"), doc.get("final")))
    src = doc.get("source_dir")
    if src and (E.is_under(Path(src), P.holdout) or any(c.lower() == "holdout" for c in Path(src).parts)):
        raise HoldoutRefusedError("scores were collected from a hold-out folder: %s" % src)
    for r in doc.get("records", []):
        if r.get("split") not in (None, "dev", "val"):
            raise HoldoutRefusedError("a record has split=%r" % r.get("split"))
    return doc


def load_dev_scores(ctx: Ctx, p: Path, P: Optional[E.Paths] = None) -> Optional[dict]:
    if not Path(p).is_file():
        ctx.skip("PR curve / threshold sweep", "no %s (run: paper_report.py --collect-dev-scores after eval_clips.py dev)" % rel(p))
        return None
    doc = read_json(p)
    reject_demo_doc(doc, p, ctx.demo)
    assert_dev_scores(doc, p, P)
    ctx.used(p)
    return doc


def collect_dev_scores(P: E.Paths, replay_dir: Path, out: Path, base: Optional[Path] = None) -> Optional[dict]:
    """Per-frame (score, label) from DEV replay events + labels. Reads files only; runs no model.
    score = raw_confidence of the matched person's detection when a raw positive was checked, else 0."""
    base = Path(base) if base else P.dev
    if E.is_under(base, P.holdout) or E.is_under(P.holdout, base):
        raise HoldoutRefusedError("%s is or contains hold-out data." % base)
    if not base.is_dir():
        print("WARNING: %s does not exist (no dev clips)" % base)
        return None
    items, _ = E.discover(base)
    recs, used = [], 0
    for it in items:
        try:
            it.lab = json.loads(it.labels.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if E.validate_labels(it.lab):
            continue
        cid = it.cid(base)
        ev_path = Path(replay_dir) / (re.sub(r"[^A-Za-z0-9_.-]+", "_", cid) + ".events.jsonl")
        if not ev_path.is_file():
            print("WARNING: no replay events for %s (%s)" % (cid, ev_path.name))
            continue
        events = [json.loads(line) for line in ev_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        frames = sorted((e for e in events if e.get("type") == "frame" and e.get("processed")), key=lambda e: e["t"])
        obs, _u = E.track_persons(frames, it.lab["persons"])
        dets = {f["t"]: {d["track_id"]: d for d in f.get("detections", [])} for f in frames}
        used += 1
        for p in it.lab["persons"]:
            ref = p["person_ref"]
            for sg in p["segments"]:
                if sg.get("occluded"):
                    continue
                for o in obs[ref]:
                    if sg["t0"] <= o["t"] < sg["t1"]:
                        d = dets.get(o["t"], {}).get(o["tid"]) if o["found"] else None
                        sc = float(d["raw_confidence"]) if (d and d.get("cigarette_checked") and d.get("raw_state", 0) != 0) else 0.0
                        recs.append(dict(score=sc, label=int(sg["label"] in POS), clip=cid, person=ref, split="dev",
                                         category=sg.get("category") or ("cigarette" if sg["label"] in POS else "plain")))
    doc = dict(schema="ash_e_dev_scores/1", split="dev", final=False, source_dir=rel(base), replay_dir=rel(replay_dir), clips=used,
               when=datetime.now().isoformat(timespec="seconds"), records=recs,
               note="raw_confidence only exists above cig_conf_thresh; scores below it are 0, so the sweep cannot go below that threshold")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc), encoding="utf-8")
    print("dev scores: %d frames from %d clips -> %s" % (len(recs), used, out))
    return doc


# ------------------------------------------------------------------ small formatting
def n_text(m: dict) -> str:
    return "n=%d participant(s), %d clip(s), %.1f min positive exposure" % (len(m.get("participants", [])), m.get("n_clips", 0), m.get("pos_exposure_min", 0.0))


def split_note(split: str, m: Optional[dict]) -> str:
    if split == "holdout":
        run = (m or {}).get("meta", {}).get("run_no", "?")
        return "Preliminary, %s; hold-out run #%s; not a general-population estimate." % (n_text(m or {}), run)
    return "Dev set (tuning, NOT a judgment); %s." % n_text(m or {})


def ci_str(ci, fmt="%.3f"):
    return "n/a" if not ci else "[" + ", ".join(fmt % v for v in ci) + "]"


# ------------------------------------------------------------------ FIGURES
def fig_training_curves(ctx: Ctx, run_dir: Path, ds_report: Optional[dict]):
    csvp = Path(run_dir) / "results.csv"
    if not csvp.is_file():
        return ctx.skip("training curves", "no %s" % rel(csvp))
    c = load_csv_columns(csvp)
    ep = c.get("epoch")
    if not ep:
        return ctx.skip("training curves", "results.csv has no epoch column")
    fig, ax = plt.subplots(2, 3, figsize=(10, 5.6), layout="constrained")
    a = ax[0, 0]
    k = 0
    for sp, pre in (("train", "train/"), ("val", "val/")):
        for nm in ("box", "cls", "dfl"):
            key = pre + nm + "_loss"
            if key in c:
                a.plot(ep, c[key], color=CYCLE[k % 3], ls="-" if sp == "train" else "--", marker=MARKERS[k], ms=3, label="%s %s" % (ctx.t(sp), nm))
                k += 1
    a.set_title(ctx.t("loss"))
    a.legend(ncol=2)
    for a, key, tk in ((ax[0, 1], "metrics/precision(B)", "precision"), (ax[0, 2], "metrics/recall(B)", "recall"),
                       (ax[1, 0], "metrics/mAP50(B)", "map50"), (ax[1, 1], "metrics/mAP50-95(B)", "map5095")):
        if key in c:
            a.plot(ep, c[key], color=OKABE["blue"], marker="o", ms=3)
        a.set_title(ctx.t(tk))
        a.set_ylim(0, 1)
    a = ax[1, 2]
    if "lr/pg0" in c:
        a.plot(ep, c["lr/pg0"], color=OKABE["grey"], marker="s", ms=3)
    a.set_title(ctx.t("lr"))
    for a in ax.ravel():
        a.set_xlabel(ctx.t("epoch"))
    nval = ""
    if ds_report and "val" in ds_report:
        v = ds_report["val"]
        nval = " Validation set: %d positive and %d negative ROI samples." % (v.get("pos", 0), v.get("neg", 0))
    inp = [ctx.used(csvp)]
    args_p = Path(run_dir) / "args.yaml"
    if args_p.is_file():
        inp.append(ctx.used(args_p))
    save_fig(ctx, fig, "fig01_training_curves", inp,
             "Training curves of the ROI cigarette detector (%s, %d epochs). Metrics are on the validation split of the ROI dataset "
             "(same data used for model selection), not on the evaluation clips.%s" % (Path(run_dir).name, len(ep), nval))


def fig_pr_and_sweep(ctx: Ctx, doc: dict, op_thresh: float):
    recs = doc["records"]
    s, y = np.array([r["score"] for r in recs]), np.array([r["label"] for r in recs])
    npos, nneg = int(y.sum()), int((1 - y).sum())
    if npos == 0 or nneg == 0:
        return ctx.skip("PR curve / threshold sweep", "dev scores need both positive and negative frames (pos=%d, neg=%d)" % (npos, nneg))
    inp = [rel(Path(doc.get("_path", "_workspace/eval_out/dev_scores.json")))]
    r, p, ap = pr_curve(s, y)
    fig, a = plt.subplots(figsize=(4.6, 4.2), layout="constrained")
    a.step(np.r_[0, r], np.r_[p[0], p], where="post", color=OKABE["blue"], lw=1.8, label="AP = %.3f" % ap)
    a.axhline(npos / len(y), color=OKABE["grey"], ls=":", label=ctx.t("noskill"))
    sw = sweep(s, y, [op_thresh])
    a.plot(sw[0, 2], sw[0, 1], marker="D", color=OKABE["verm"], ls="none", ms=7, label="%s (t=%.2f)" % (ctx.t("operating"), op_thresh))
    a.set_xlabel(ctx.t("recall"))
    a.set_ylabel(ctx.t("precision"))
    a.set_xlim(0, 1.02)
    a.set_ylim(0, 1.02)
    a.set_title(ctx.t("pr_title"))
    a.legend(loc="lower left")
    cap = ("Precision-recall curve on dev clips, frame level (n=%d frames: %d positive, %d negative, from %d clip(s)); AP = %.3f. "
           "Frames of one clip are correlated, so the effective sample size is much smaller. Dev data only, not a judgment."
           % (len(y), npos, nneg, doc.get("clips", 0), ap))
    save_fig(ctx, fig, "fig02_pr_curve_dev", inp, cap, "dev only; n=%d frames" % len(y))
    sw = sweep(s, y)
    fig, a = plt.subplots(figsize=(5.4, 3.8), layout="constrained")
    for k, (col, key) in enumerate(((1, "precision"), (2, "recall"), (3, "f1"))):
        a.plot(sw[:, 0], sw[:, col], color=CYCLE[k], ls=LINES[k], marker=MARKERS[k], markevery=10, ms=4, label=ctx.t(key))
    a.axvline(op_thresh, color=OKABE["verm"], ls=":", label="%s (%.2f)" % (ctx.t("operating"), op_thresh))
    f = sw[:, 3]
    if np.isfinite(f).any():
        i = int(np.nanargmax(f))
        a.plot(sw[i, 0], f[i], marker="*", color=OKABE["black"], ls="none", ms=10, label="%s t=%.2f" % (ctx.t("dev_opt"), sw[i, 0]))
    a.set_xlabel(ctx.t("threshold"))
    a.set_ylabel("%s / %s / %s" % (ctx.t("precision"), ctx.t("recall"), ctx.t("f1")))
    a.set_ylim(0, 1.02)
    a.set_title(ctx.t("sweep_title"))
    a.legend(loc="lower left", ncol=2)
    save_fig(ctx, fig, "fig03_threshold_sweep_dev", inp,
             "Precision, recall and F1 versus confidence threshold on dev clips (n=%d frames). Scores below the configured cigarette "
             "threshold are not available, so the curves are flat below it. The dev-optimal point is informational; no threshold was "
             "chosen from hold-out data." % len(y), "dev only; n=%d frames" % len(y))


def fig_confusion(ctx: Ctx, im: dict, split: str, clip_m: Optional[dict], src: str):
    cm = np.array(im["confusion"], float)
    names = im.get("labels", ["none", "holding", "smoking"])
    fig, ax = plt.subplots(1, 2, figsize=(8.4, 3.9), layout="constrained")
    rs = cm.sum(1, keepdims=True)
    norm = np.divide(cm, rs, out=np.zeros_like(cm), where=rs > 0)
    for a, M, title, fmt in ((ax[0], cm, ctx.t("counts"), "%d"), (ax[1], norm, ctx.t("rownorm"), "%.2f")):
        a.grid(False)
        h = a.imshow(M, cmap="Blues", vmin=0, vmax=max(M.max(), 1e-9))
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                a.text(j, i, fmt % M[i, j], ha="center", va="center", color="white" if M[i, j] > 0.55 * M.max() else "black")
        a.set_xticks(range(len(names)), names)
        a.set_yticks(range(len(names)), names)
        a.set_xlabel(ctx.t("pred"))
        a.set_ylabel(ctx.t("gt"))
        a.set_title(title)
        a.spines[:].set_visible(False)
    fig.suptitle("%s [%s, n=%d]" % (ctx.t("conf_title"), split, int(cm.sum())), fontsize=10)
    note = split_note(split, clip_m) if clip_m else ("Preliminary hold-out result." if split == "holdout" else "Dev set, NOT a judgment.")
    save_fig(ctx, fig, "fig04_confusion_" + split, [src],
             "Frame-level confusion matrix of the raw (unstabilised) state on the %s image set, n=%d labelled persons (left: counts, right: "
             "row-normalised). %s" % (split, int(cm.sum()), note), note)


def fig_distance_recall(ctx: Ctx, m: dict, split: str):
    bins = [("binary_recall_max3m", "≤ 3 m"), ("binary_recall_3to5m", "3–5 m")]
    fig, a = plt.subplots(figsize=(5.2, 4.0), layout="constrained")
    any_ = False
    for i, (key, lab) in enumerate(bins):
        b = m["metrics"].get(key)
        if not b or b.get("value") is None:
            continue
        any_ = True
        v = b["value"]
        for off, ci, mk, col, nm in ((-0.09, b.get("wilson"), "o", OKABE["blue"], "wilson"), (0.09, b.get("boot"), "s", OKABE["orange"], "boot")):
            if ci:
                a.errorbar(i + off, v, yerr=[[v - ci[0]], [ci[1] - v]], fmt=mk, color=col, capsize=4, ms=6, label=ctx.t(nm) if i == 0 else None)
            else:
                a.plot(i + off, v, mk, color=col, ms=6, mfc="none", label=ctx.t(nm) + " (n/a)" if i == 0 else None)
        if b.get("threshold") is not None:
            a.hlines(b["threshold"], i - 0.3, i + 0.3, colors=OKABE["verm"], linestyles="--", lw=1.6, label=ctx.t("thr_line") if i == 0 else None)
        a.text(i, 0.03, "n=%g/%g" % (b.get("num", 0), b.get("den", 0)), ha="center", fontsize=8)
    if not any_:
        plt.close(fig)
        return ctx.skip("distance recall (%s)" % split, "metrics.json has no recall values")
    a.set_xticks(range(len(bins)), [b[1] for b in bins])
    a.set_xlim(-0.6, len(bins) - 0.4)
    a.set_ylim(0, 1.05)
    a.set_xlabel(ctx.t("dist_x"))
    a.set_ylabel(ctx.t("recall") + " [stabilised state]")
    a.set_title("%s [%s]" % (ctx.t("dist_title"), split))
    a.legend(loc="lower right")
    note = split_note(split, m)
    save_fig(ctx, fig, "fig05_distance_recall_" + split, [m["_path"]],
             "Recall of the stabilised state in two proxy-distance bins (bounding-box-height based, approximate; no depth camera in stage A) "
             "with the acceptance threshold; blue: frame-level Wilson 95%% CI (optimistic, frames are correlated), orange: 95%% clip-level "
             "bootstrap CI. n = positive frames per bin. %s" % note, note)


def ttc_values(m: dict) -> List[float]:
    return [s["ttc"] for s in m.get("segments", []) if s.get("label") in POS and s.get("ttc") is not None]


def fig_ttc(ctx: Ctx, m: dict, split: str):
    v = np.array(ttc_values(m), float)
    if len(v) == 0:
        return ctx.skip("time-to-confirm (%s)" % split, "no confirmed positive segments in metrics.json")
    thr = m["metrics"].get("confirm_time_median_s", {}).get("threshold")
    miss = sum(1 for s in m.get("segments", []) if s.get("label") in POS and not s.get("confirmed"))
    fig, ax = plt.subplots(1, 2, figsize=(8.4, 3.6), layout="constrained")
    top = max(float(v.max()), thr or 0) * 1.1 + 1e-9
    ax[0].hist(v, bins=np.linspace(0, top, 17), color=OKABE["sky"], edgecolor=OKABE["blue"], hatch="//")
    xs = np.sort(v)
    ax[1].step(np.r_[0, xs], np.r_[0, np.arange(1, len(xs) + 1) / len(xs)], where="post", color=OKABE["blue"], lw=1.8, marker="o", ms=3)
    for a in ax:
        a.axvline(float(np.median(v)), color=OKABE["orange"], ls="-.", lw=1.6, label="%s %.2f s" % (ctx.t("median"), np.median(v)))
        if thr is not None:
            a.axvline(thr, color=OKABE["verm"], ls="--", lw=1.6, label="%s %.1f s" % (ctx.t("thr_line"), thr))
        a.set_xlabel(ctx.t("ttc_x"))
        a.legend(loc="lower right" if a is ax[1] else "upper right")
    ax[0].set_ylabel(ctx.t("count"))
    ax[1].set_ylabel(ctx.t("cdf"))
    ax[1].set_ylim(0, 1.02)
    fig.suptitle("%s [%s, n=%d]" % (ctx.t("ttc_title"), split, len(v)), fontsize=10)
    note = split_note(split, m)
    bci = m["metrics"].get("confirm_time_median_s", {}).get("boot")
    save_fig(ctx, fig, "fig06_time_to_confirm_" + split, [m["_path"]],
             "Distribution (histogram and empirical CDF) of the time from the start of a labelled positive segment to the first stabilised "
             "confirmation, n=%d segments (%d positive segments never confirmed are not in the plot). Median %.2f s%s; dashed: acceptance "
             "threshold. %s" % (len(v), miss, np.median(v), (", 95%% bootstrap CI %s" % ci_str(bci, "%.2f")) if bci else "", note), note)


def fc_by_category(m: dict):
    """-> {category: (edges, exposure_min, judged)} from segment rows (exposure approximated by t1 - t0)."""
    cats: Dict[str, List[float]] = {}
    for s in m.get("segments", []):
        if s.get("label") in POS or s.get("counted_in") is None:
            continue
        if s.get("occluded"):
            continue
        c = cats.setdefault(s.get("category") or "plain", [0.0, 0.0, s["counted_in"] == "lk"])
        c[0] += s.get("false_confirms", 0) or 0
        c[1] += (s["t1"] - s["t0"]) / 60.0
    return {k: tuple(v) for k, v in cats.items()}


def fig_false_confirm(ctx: Ctx, m: dict, split: str):
    cats = fc_by_category(m)
    if not cats:
        return ctx.skip("false confirmations (%s)" % split, "no negative segments in metrics.json")
    thr = m["metrics"].get("lookalike_false_confirm_per_10min", {}).get("threshold")
    names = sorted(cats, key=lambda k: (not cats[k][2], k))
    fig, a = plt.subplots(figsize=(6.0, 3.9), layout="constrained")
    for i, k in enumerate(names):
        edges, mins, judged = cats[k]
        rate = 10.0 * edges / mins if mins > 0 else 0.0
        a.bar(i, rate, color=OKABE["blue"] if judged else OKABE["grey"], hatch=None if judged else "//", edgecolor="white")
        if edges == 0 and mins > 0:
            ub = 30.0 / mins
            a.errorbar(i, 0, yerr=[[0], [ub]], fmt="none", ecolor=OKABE["verm"], capsize=5, lw=1.4)
            a.plot(i, ub, marker="v", color=OKABE["verm"], ms=6, ls="none", label=ctx.t("ub3") if i == 0 else None)
        a.text(i, -0.02, "%d ev / %.1f min" % (edges, mins), ha="center", va="top", fontsize=7, transform=a.get_xaxis_transform())
    if thr is not None:
        a.axhline(thr, color=OKABE["verm"], ls="--", lw=1.6, label=ctx.t("thr_line"))
    a.set_xticks(range(len(names)), ["%s\n(%s)" % (k, ctx.t("judged") if cats[k][2] else ctx.t("reported")) for k in names])
    a.tick_params(axis="x", pad=14)
    a.set_ylabel(ctx.t("fc_y"))
    a.set_title("%s [%s]" % (ctx.t("fc_title"), split))
    a.legend(loc="upper right")
    note = split_note(split, m)
    save_fig(ctx, fig, "fig07_false_confirms_" + split, [m["_path"]],
             "Rising edges none to positive (false confirmations) per 10 min of labelled negative exposure, by lookalike category "
             "(events / exposure minutes under each bar). With zero events the red marker is the rule-of-three 95%% upper bound (30 / minutes). "
             "Hatched grey bars are reported only and not part of the criterion. Total lookalike exposure %.1f min. %s"
             % (m.get("lookalike_exposure_min", 0.0), note), note)


def fig_participants(ctx: Ctx, m: dict, split: str):
    pt = m.get("participant_table") or {}
    keys = [k for k in E.RATIO if k in m["metrics"]]
    if not pt:
        return ctx.skip("per-participant (%s)" % split, "metrics.json has no participants")
    fig, ax = plt.subplots(1, len(keys), figsize=(2.6 * len(keys), 3.6), layout="constrained", sharey=True)
    parts = sorted(pt)
    for a, k in zip(np.atleast_1d(ax), keys):
        b = m["metrics"][k]
        if b.get("wilson"):
            a.axhspan(b["wilson"][0], b["wilson"][1], color=OKABE["sky"], alpha=0.25, lw=0, label=ctx.t("pooled"))
        if b.get("value") is not None:
            a.axhline(b["value"], color=OKABE["blue"], lw=1, ls="-")
        if b.get("threshold") is not None:
            a.axhline(b["threshold"], color=OKABE["verm"], ls="--", lw=1.5, label=ctx.t("thr_line"))
        for i, p in enumerate(parts):
            v = pt[p].get(k)
            if v is not None:
                a.plot(i, v, marker=MARKERS[i % 6], color=CYCLE[i % 6], ls="none", ms=8, label=p)
        a.set_title(E.TITLES[k].replace("binary ", "").replace(" (state,", "\n(state,"), fontsize=8)
        a.set_xticks(range(len(parts)), parts, rotation=30)
        a.set_ylim(0, 1.05)
        a.set_xlim(-0.6, len(parts) - 0.4)
    np.atleast_1d(ax)[0].set_ylabel(ctx.t("part_title"))
    h, l = np.atleast_1d(ax)[0].get_legend_handles_labels()
    fig.legend(h, l, loc="outside lower center", ncol=min(6, len(l)))
    note = split_note(split, m)
    save_fig(ctx, fig, "fig08_participants_" + split, [m["_path"]],
             "Per-participant values of the ratio metrics (markers), the pooled value (blue line) with its frame-level Wilson 95%% CI "
             "(shaded) and the acceptance threshold (dashed). Per-participant confidence intervals are not stored in metrics.json "
             "and are not drawn; with %d participant(s) between-person variance cannot be estimated reliably. %s" % (len(parts), note), note)


def ablation_view(m: dict) -> dict:
    lk = m["metrics"].get("lookalike_false_confirm_per_10min", {})
    rc = m["metrics"].get("binary_recall_max3m", {})
    return dict(fc_rate=lk.get("value"), fc_n=lk.get("num"), fc_min=lk.get("exposure_min"), ub=lk.get("rule_of_three_upper"),
                fc_all=len(m.get("false_confirms", [])), ttc=ttc_values(m), recall3=rc.get("value"), recall3_ci=rc.get("wilson"),
                thr_ttc=m["metrics"].get("confirm_time_median_s", {}).get("threshold"), n_clips=m.get("n_clips"))


def fig_ablation(ctx: Ctx, on: dict, off: dict):
    A, B = ablation_view(on), ablation_view(off)
    fig, ax = plt.subplots(1, 3, figsize=(10, 3.7), layout="constrained")
    cols = (OKABE["blue"], OKABE["orange"])
    for i, (V, nm) in enumerate(((A, "on"), (B, "off"))):
        v = V["fc_rate"] or 0.0
        ax[0].bar(i, v, color=cols[i], hatch=("" if i == 0 else "//"), edgecolor="white")
        ax[0].text(i, v, "%g ev / %.1f min" % (V["fc_n"] or 0, V["fc_min"] or 0), ha="center", va="bottom", fontsize=7)
        if V["ub"] is not None:
            ax[0].plot(i, V["ub"], "v", color=OKABE["verm"], ms=6, label=ctx.t("ub3") if i == 0 else None)
        t = V["ttc"]
        if t:
            ax[1].scatter(np.full(len(t), i) + np.linspace(-0.12, 0.12, len(t)), t, color=cols[i], marker=MARKERS[i], s=18, alpha=0.8)
            ax[1].hlines(np.median(t), i - 0.3, i + 0.3, colors="black", lw=2)
        if V["recall3"] is not None:
            ci = V["recall3_ci"]
            ax[2].errorbar(i, V["recall3"], yerr=None if not ci else [[V["recall3"] - ci[0]], [ci[1] - V["recall3"]]], fmt=MARKERS[i],
                           color=cols[i], capsize=4, ms=7)
    thr = lambda k: on["metrics"].get(k, {}).get("threshold")  # noqa: E731
    if thr("lookalike_false_confirm_per_10min") is not None:
        ax[0].axhline(thr("lookalike_false_confirm_per_10min"), color=OKABE["verm"], ls="--", label=ctx.t("thr_line"))
    if A["thr_ttc"] is not None:
        ax[1].axhline(A["thr_ttc"], color=OKABE["verm"], ls="--", label=ctx.t("thr_line"))
    if thr("binary_recall_max3m") is not None:
        ax[2].axhline(thr("binary_recall_max3m"), color=OKABE["verm"], ls="--", label=ctx.t("thr_line"))
    ax[0].set_ylabel(ctx.t("fc_y"))
    ax[1].set_ylabel(ctx.t("ttc_x") + "  (— median)")
    ax[2].set_ylabel(ctx.t("recall") + " (≤ 3 m)")
    ax[2].set_ylim(0, 1.05)
    titles = ("lookalike false confirmations", "time to confirm (per segment)", "recall ≤ 3 m (Wilson 95% CI)")
    for a, tt in zip(ax, titles):
        a.set_xticks([0, 1], [ctx.t("on"), ctx.t("off")])
        a.set_xlim(-0.6, 1.6)
        a.set_title(tt, fontsize=9)
        a.legend(loc="upper right")
    fig.suptitle(ctx.t("abl_title"), fontsize=10)
    save_fig(ctx, fig, "fig09_stabilizer_ablation_dev", [on["_path"], off["_path"]],
             "Effect of the temporal stabiliser on dev clips (%s clips each, same replay, same models). 'Off' replays the same clips with the "
             "stabiliser configured as a pass-through (window 0, one observation, ratio 1.0, no release delay); core code is unchanged. "
             "Dev data only, no hold-out clip was used." % A["n_clips"], "dev clips only; stabiliser off = config pass-through")


def fig_dataset(ctx: Ctx, rep: Optional[dict], dev: Optional[dict], hold: Optional[dict], rep_path: str):
    if not rep:
        return ctx.skip("dataset composition", "no ROI dataset build_report.json")
    src_order = [("public_pos", "public positive (CigDet)"), ("synth_pos", "synthetic positive"), ("coco_none_neg", "COCO none (neg)"),
                 ("coco_similar_neg", "COCO similar (neg)"), ("public_neg", "public negative (CigDet ROI)")]
    splits = [s for s in ("train", "val") if s in rep]
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.6), layout="constrained", gridspec_kw=dict(width_ratios=[2.2, 1]))
    left = np.zeros(len(splits))
    for i, (key, lab) in enumerate(src_order):
        vals = np.array([rep[s]["counts"].get(key, 0) for s in splits], float)
        ax[0].barh(range(len(splits)), vals, left=left, color=CYCLE[i % 6], hatch=["", "//", "..", "xx", "\\\\"][i % 5], edgecolor="white", label=lab)
        for j, v in enumerate(vals):
            if v > 0.06 * max(left.max() + vals.max(), 1):
                ax[0].text(left[j] + v / 2, j, "%d" % v, ha="center", va="center", fontsize=7)
        left += vals
    ax[0].set_yticks(range(len(splits)), ["%s (n=%d)" % (s, sum(rep[s]["counts"].values())) for s in splits])
    ax[0].set_xlabel(ctx.t("samples"))
    ax[0].legend(loc="lower right", fontsize=7)
    ax[0].set_title(ctx.t("ds_title"))
    ev = [("dev", dev), ("hold-out", hold)]
    for i, (nm, m) in enumerate(ev):
        if m:
            ax[1].bar(i, m["n_clips"], color=CYCLE[i], hatch="" if i == 0 else "//", edgecolor="white")
            ax[1].text(i, m["n_clips"], "%d clip(s)\n%d participant(s)" % (m["n_clips"], len(m.get("participants", []))), ha="center", va="bottom", fontsize=7)
    ax[1].set_xticks([0, 1], [e[0] for e in ev])
    ax[1].set_ylabel("Evaluation clips [count]")
    ax[1].set_title("Evaluation data")
    if not (dev or hold):
        ax[1].text(0.5, 0.5, ctx.t("nodata"), transform=ax[1].transAxes, ha="center")
    save_fig(ctx, fig, "fig10_dataset", [rep_path] + [m["_path"] for m in (dev, hold) if m],
             "Left: composition of the ROI training/validation sets by source (positive = ROI contains a cigarette label, "
             "synthetic = copy-paste, train split only). Right: number of recorded evaluation clips and participants. "
             "Public and COCO data are never used for evaluation.")


def fig_latency(ctx: Ctx, lat: dict, src: str):
    st = lat["stages_ms"]
    names = [k for k in ("pose", "roi", "cig", "stab") if st.get(k)]
    fig, ax = plt.subplots(1, 3, figsize=(10.6, 3.7), layout="constrained", gridspec_kw=dict(width_ratios=[1.2, 1, 0.9]))
    left = 0.0
    for i, k in enumerate(names):
        v = st[k]["median"]
        ax[0].barh(0, v, left=left, color=CYCLE[i], hatch=["", "//", "..", "xx"][i], edgecolor="white", label="%s %.2f" % (k, v))
        left += v
    tot = lat["total_ms"]
    ax[0].errorbar(tot["median"], 0, xerr=[[0], [max(tot["p95"] - tot["median"], 0)]], fmt="D", color="black", capsize=4,
                   label="total median %.1f / p95 %.1f" % (tot["median"], tot["p95"]))
    ax[0].set_yticks([])
    ax[0].set_xlabel(ctx.t("ms"))
    ax[0].set_title(ctx.t("lat_title"))
    ax[0].legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=2)
    fs = np.array(lat.get("fps_samples", []), float)
    if len(fs):
        ax[1].hist(fs, bins=20, color=OKABE["sky"], edgecolor=OKABE["blue"], hatch="//")
        ax[1].axvline(np.median(fs), color=OKABE["orange"], ls="-.", lw=1.6, label="%s %.1f" % (ctx.t("median"), np.median(fs)))
        ax[1].legend()
    ax[1].set_xlabel(ctx.t("fps"))
    ax[1].set_ylabel("Iterations [count]")
    mods = [(k, v) for k, v in lat.get("models", {}).items() if v.get("present") and v.get("params")]
    for i, (k, v) in enumerate(mods):
        ax[2].bar(i, v["params"] / 1e6, color=CYCLE[i], hatch=["", "//"][i % 2], edgecolor="white")
        ax[2].text(i, v["params"] / 1e6, "%.2f M\n%.1f MB" % (v["params"] / 1e6, v["onnx_bytes"] / 1e6), ha="center", va="bottom", fontsize=7)
    ax[2].set_xticks(range(len(mods)), [k for k, _ in mods])
    ax[2].set_ylabel(ctx.t("params"))
    ax[2].margins(y=0.25)
    env = lat["env"]
    note = "WINDOWS PC, NOT RPi5: %s, %d ORT threads, onnxruntime %s" % (env["cpu"], env["ort_threads"], env["onnxruntime"])
    save_fig(ctx, fig, "fig11_latency", [src],
             "Per-frame latency breakdown (median per stage, black marker: median and p95 of the per-iteration total), distribution of the "
             "resulting throughput, and model size, measured on a Windows PC (%s, %d onnxruntime threads, onnxruntime %s, %d iterations "
             "after %d warm-up, %d synthetic person(s), %s input). This is NOT an RPi5 measurement; the RPi5 >= 5 Hz criterion is measured in stage B."
             % (env["cpu"], env["ort_threads"], env["onnxruntime"], lat["params"]["n"], lat["params"]["warmup"], lat["params"]["persons"],
                "synthetic" if lat.get("synthetic_input") else "clip"), note)


# ------------------------------------------------------------------ face blur + gallery
def blur_faces(img: np.ndarray, pose_model=None):
    """Blur boxes around pose face keypoints (nose/eyes/ears). -> (image, status) status in blurred|no_person|no_model."""
    import cv2
    if pose_model is None:
        return img, "no_model"
    from ash_e_core.config import PerceptionConfig
    from ash_e_core.detector import PoseModel
    cfg = PerceptionConfig()
    cfg.person_conf_thresh, cfg.min_person_h_px = 0.25, 0
    persons = PoseModel(pose_model, cfg).detect(img)
    if not persons:
        return img, "no_person"
    out = img.copy()
    H, W = img.shape[:2]
    for p in persons:
        kp = p.keypoints[:5]
        ok = kp[kp[:, 2] > 0.3]
        if len(ok):
            cx, cy = ok[:, 0].mean(), ok[:, 1].mean()
            side = max(float(np.ptp(ok[:, 0])), float(np.ptp(ok[:, 1])), 0.25 * (p.bbox_xyxy[3] - p.bbox_xyxy[1]) * 0.5) * 1.8
            x1, y1, x2, y2 = cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2
        else:
            x1, y1, x2, y2 = p.bbox_xyxy[0], p.bbox_xyxy[1], p.bbox_xyxy[2], p.bbox_xyxy[1] + 0.3 * (p.bbox_xyxy[3] - p.bbox_xyxy[1])
        x1, y1, x2, y2 = int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2))
        if x2 > x1 and y2 > y1:
            roi = out[y1:y2, x1:x2]
            k = max(3, (min(roi.shape[:2]) // 3) | 1)
            out[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
    return out, "blurred"


def fig_gallery(ctx: Ctx, crops_dir: Path, source: str, allow_own_faces: bool, blur: bool = True, pose_model=None, max_n: int = 12):
    import cv2
    if source == "own" and not allow_own_faces:
        return ctx.skip("case gallery", "crops of participants/own images need --allow-own-faces (default off: face privacy); "
                        "use --gallery-source public|synthetic for non-personal images")
    crops_dir = Path(crops_dir)
    files = sorted(p for p in crops_dir.glob("*.jpg")) + sorted(p for p in crops_dir.glob("*.png"))
    files = files[:max_n]
    if not files:
        return ctx.skip("case gallery", "no crops in %s" % rel(crops_dir))
    tiles, notes = [], []
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            continue
        if source == "own" and blur:
            img, status = blur_faces(img, pose_model)
            if status == "no_model":
                return ctx.skip("case gallery", "face blur needs the pose model (models/pose.onnx); refusing to show participant crops unblurred")
            if status == "no_person":
                notes.append(f.name)
        tiles.append((f.stem, cv2.cvtColor(cv2.resize(img, (160, 160)), cv2.COLOR_BGR2RGB)))
    if not tiles:
        return ctx.skip("case gallery", "no readable crops")
    cols = min(6, len(tiles))
    rows = math.ceil(len(tiles) / cols)
    fig, ax = plt.subplots(rows, cols, figsize=(1.7 * cols, 1.9 * rows), layout="constrained", squeeze=False)
    for a in ax.ravel():
        a.axis("off")
    for a, (nm, im_) in zip(ax.ravel(), tiles):
        a.imshow(im_)
        a.set_title(nm[:24], fontsize=6)
    fig.suptitle(ctx.t("gal_title"), fontsize=10)
    warn = "" if source != "own" else " Faces blurred with pose keypoints; %d crop(s) had no detectable person (shown unmodified, check by eye)." % len(notes)
    save_fig(ctx, fig, "fig12_case_gallery", [rel(crops_dir)],
             "Error-case ROI crops (hand/mouth neighbourhood, up to %d; source: %s).%s Publication of participant images requires "
             "publication consent in the written participant consent." % (max_n, source, warn))


# ------------------------------------------------------------------ TABLES
def tex_escape(s) -> str:
    s = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"), ("≤", r"$\leq$"), ("≥", r"$\geq$")):
        s = s.replace(a, b)
    return s


def write_table(ctx: Ctx, stem: str, header: List[str], rows: List[List], caption: str, inputs: List[str]):
    csvp, texp = ctx.tabdir / (stem + ".csv"), ctx.tabdir / (stem + ".tex")
    with open(csvp, "w", newline="", encoding="utf-8-sig") as f:
        if ctx.demo:
            f.write("# %s\n" % DEMO_MARK)
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    cap = ("%s: " % DEMO_MARK if ctx.demo else "") + caption
    L = []
    if ctx.demo:
        L.append("% " + DEMO_MARK)
    L += [r"\begin{table}[t]", r"\centering", r"\caption{%s}" % tex_escape(cap), r"\label{tab:%s}" % stem, r"\small",
          r"\begin{tabular}{%s}" % ("l" * len(header)), r"\toprule", " & ".join(tex_escape(h) for h in header) + r" \\", r"\midrule"]
    L += [" & ".join(tex_escape(c) for c in r) + r" \\" for r in rows]
    L += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    texp.write_text("\n".join(L) + "\n", encoding="utf-8")
    ctx.registry.append(dict(kind="table", id=stem, files=[csvp.name, texp.name], inputs=inputs, caption=caption))
    print("table -> %s" % csvp)


def metric_row(split: str, name: str, b: dict):
    thr = "%s %s" % (b["direction"], b["threshold"]) if b.get("threshold") is not None else "-"
    v = b.get("value")
    if name == "lookalike_false_confirm_per_10min":
        val = "n/a" if v is None else "%.2f" % v
        n = "%g events / %.1f min" % (b.get("num", 0), b.get("exposure_min", 0))
        ci = "upper (rule of three) %.2f" % b["rule_of_three_upper"] if b.get("rule_of_three_upper") is not None else ci_str(b.get("boot"), "%.2f")
        wil = "-"
    elif name == "confirm_time_median_s":
        val, n, ci, wil = ("n/a" if v is None else "%.2f" % v), "%g segments" % b.get("num", 0), ci_str(b.get("boot"), "%.2f"), "-"
    elif name == "priority_flicker_s5":
        val, n, ci, wil = ("not measured" if v is None else "%g" % v), "-", "-", "-"
    else:
        val, n, ci, wil = ("n/a" if v is None else "%.3f" % v), "%g/%g frames" % (b.get("num", 0), b.get("den", 0)), ci_str(b.get("boot")), ci_str(b.get("wilson"))
    ok = b.get("passed")
    if name == "priority_flicker_s5" and v is None:
        verdict = "not measured"
    elif ok is None:
        verdict = "no data"
    elif split == "dev":
        verdict = "meets (dev, not a judgment)" if ok else "below (dev)"
    else:
        verdict = ("pass (preliminary)" if ok else "fail") + (", uncertain" if b.get("uncertain") else "")
    return [split, E.TITLES[name], thr, val, wil, ci, n, verdict]


def table_summary(ctx: Ctx, dev: Optional[dict], hold: Optional[dict]):
    rows, inp = [], []
    for split, m in (("dev", dev), ("hold-out", hold)):
        if not m:
            continue
        inp.append(m["_path"])
        for name in E.DIRECTION:
            if name in m["metrics"]:
                rows.append(metric_row("dev" if split == "dev" else "hold-out", name, m["metrics"][name]))
    if not rows:
        return ctx.skip("summary table", "no clip metrics (dev or hold-out)")
    rows.append(["-", "RPi5 processing rate [Hz]", ">= (see acceptance.yaml)", "not measured", "-", "-", "-", "stage B (RPi5)"])
    cap = "Metric summary against the acceptance thresholds (thresholds read from the locked acceptance.yaml)."
    if hold:
        cap += " Hold-out: preliminary, " + n_text(hold) + "; not a general-population estimate."
    cap += " Dev rows are tuning references, not judgments. Distances are proxy (box-height) estimates. CI: Wilson over frames (optimistic) and clip-level bootstrap."
    write_table(ctx, "tab01_metric_summary", ["Split", "Metric", "Threshold", "Measured", "95% Wilson", "95% bootstrap", "n", "Verdict"], rows, cap, inp)


def table_dataset(ctx: Ctx, rep: Optional[dict], dev: Optional[dict], hold: Optional[dict], splits_doc: Optional[dict], rep_path: str):
    rows = []
    if rep:
        lab = {"public_pos": ("CigDet (public, CC BY 4.0)", "positive"), "synth_pos": ("synthetic copy-paste", "positive"),
               "coco_none_neg": ("COCO 2017 subset: none", "negative"), "coco_similar_neg": ("COCO 2017 subset: similar objects", "negative"),
               "public_neg": ("CigDet ROIs without cigarette", "negative")}
        for s in ("train", "val"):
            for k, (src, cl) in lab.items():
                n = rep.get(s, {}).get("counts", {}).get(k)
                if n:
                    rows.append([s + " (ROI samples)", src, cl, n])
    for nm, m in (("dev", dev), ("hold-out", hold)):
        if m:
            rows.append([nm + " (recorded clips)", "own recordings", "positive and negative", "%d clips, %d participant(s), %.1f min positive, %.1f min lookalike"
                         % (m["n_clips"], len(m.get("participants", [])), m.get("pos_exposure_min", 0), m.get("lookalike_exposure_min", 0))])
    if splits_doc:
        rows.append(["participant split", "data/splits/participants.json", "-", ", ".join("%s: %d" % (k, len(v)) for k, v in splits_doc.items() if isinstance(v, list))])
    if not rows:
        return ctx.skip("dataset table", "no dataset report and no evaluation metrics")
    write_table(ctx, "tab02_dataset", ["Split", "Source", "Class", "n"], rows,
                "Dataset composition. ROI samples are crops around mouth/hand regions; evaluation recordings come only from own participants.",
                [rep_path] + [m["_path"] for m in (dev, hold) if m])


HP_RUN = ["model", "imgsz", "epochs", "batch", "optimizer", "lr0", "lrf", "momentum", "weight_decay", "patience", "seed", "workers", "device",
          "degrees", "fliplr", "hsv_v", "mosaic", "close_mosaic", "amp"]
HP_PIPE = ["pose_input", "roi_input", "person_conf_thresh", "cig_conf_thresh", "kp_conf_thresh", "mouth_roi_scale", "hand_roi_scale",
           "smoking_radius", "holding_radius", "stab_window_s", "stab_min_obs", "confirm_ratio", "release_ratio", "release_hold_s",
           "smoking_min_obs", "smoking_latch_s", "process_rate_hz", "num_threads", "max_roi_persons"]


def pipeline_cfg(cfg_path: Optional[str]) -> dict:
    from ash_e_core.config import config_to_dict, load_perception_config
    return config_to_dict(load_perception_config(cfg_path))


def train_args(run_dir: Path) -> dict:
    import yaml
    p = Path(run_dir) / "args.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else {}


def table_hyper(ctx: Ctx, run_dir: Path, cfg: dict):
    a = train_args(run_dir)
    # training overrides set in train_cig_roi.py call (not stored in args.yaml defaults? they are, but list the script constants too)
    rows = []
    for k in HP_RUN:
        if k in a:
            v = a[k]
            if k == "model" or k == "device":
                v = Path(str(v)).name
            rows.append(["training (ultralytics, %s)" % Path(run_dir).name, k, v])
    for k in HP_PIPE:
        if k in cfg:
            rows.append(["pipeline (PerceptionConfig)", k, cfg[k]])
    if not rows:
        return ctx.skip("hyper-parameter table", "no args.yaml and no config")
    inp = [ctx.used(Path(run_dir) / "args.yaml")] if (Path(run_dir) / "args.yaml").is_file() else []
    write_table(ctx, "tab03_hyperparameters", ["Group", "Parameter", "Value"], rows,
                "Training and pipeline hyper-parameters (training from args.yaml of the run, pipeline from the PerceptionConfig used in the evaluation).",
                inp + ["src/ash_e_core/ash_e_core/config.py"])


def table_latency(ctx: Ctx, lat: dict, src: str):
    env = lat["env"]
    rows = []
    for k, v in lat["stages_ms"].items():
        if v:
            rows.append([k, "%.2f" % v["mean"], "%.2f" % v["median"], "%.2f" % v["p95"], v["n"]])
    for k, nm in (("total_ms", "total (sum of stages)"), ("end_to_end_ms", "pipeline.process() end to end")):
        v = lat[k]
        rows.append([nm, "%.2f" % v["mean"], "%.2f" % v["median"], "%.2f" % v["p95"], v["n"]])
    v = lat["fps"]
    rows.append(["throughput [frames/s] (1000 / total)", "%.1f" % v["mean"], "%.1f" % v["median"], "%.1f (p95 of FPS)" % v["p95"], v["n"]])
    for k, mi in lat.get("models", {}).items():
        if mi.get("present"):
            rows.append(["model %s: %s params, %.2f MB ONNX" % (k, "%.2f M" % (mi["params"] / 1e6) if mi.get("params") else "?", mi["onnx_bytes"] / 1e6), "-", "-", "-", "-"])
    cap = ("Latency on a Windows PC (NOT RPi5): %s, %d onnxruntime threads, onnxruntime %s, %d iterations after %d warm-up, %d persons, %s input; "
           "all times in ms unless stated. The RPi5 >= 5 Hz criterion is measured in stage B." % (
               env["cpu"], env["ort_threads"], env["onnxruntime"], lat["params"]["n"], lat["params"]["warmup"], lat["params"]["persons"],
               "synthetic" if lat.get("synthetic_input") else "clip"))
    write_table(ctx, "tab04_latency", ["Stage", "Mean", "Median", "p95", "n"], rows, cap, [src])


def table_ablation(ctx: Ctx, on: dict, off: dict):
    rows = []
    for nm, m in (("on", on), ("off", off)):
        V = ablation_view(m)
        rows.append([nm, "n/a" if V["fc_rate"] is None else "%.2f" % V["fc_rate"], "%g / %.1f min" % (V["fc_n"] or 0, V["fc_min"] or 0), V["fc_all"],
                     "n/a" if not V["ttc"] else "%.2f" % np.median(V["ttc"]), len(V["ttc"]),
                     "n/a" if V["recall3"] is None else "%.3f" % V["recall3"]])
    write_table(ctx, "tab05_stabilizer_ablation", ["Stabiliser", "Lookalike FC / 10 min", "Events / exposure", "All false confirmations",
                                                  "Median time to confirm [s]", "n segments", "Recall <= 3 m"], rows,
                "Stabiliser on/off on dev clips (replay). Dev data only; no hold-out clip was used.", [on["_path"], off["_path"]])


# ------------------------------------------------------------------ reproducibility + README
PKGS = ["numpy", "matplotlib", "onnx", "onnxruntime", "opencv-python", "ultralytics", "torch", "PyYAML", "scipy", "pytest"]
DATA_FILES = ["data/roi_ds_v2/build_report.json", "data/roi_ds_v2/data.yaml", "data/SOURCES.md", "data/synth/meta.json",
              "data/splits/participants.json", "data/public/coco/subset/manifest.json"]


def build_repro(ctx: Ctx, args, cfg: dict, run_dir: Path, holdout_path: Optional[str]) -> dict:
    pk = {}
    for n in PKGS:
        try:
            pk[n] = im.version(n)
        except im.PackageNotFoundError:
            pk[n] = None
    models = {}
    for p in ("models/pose.onnx", "models/cig_roi.onnx", "models/yolo11n.pt", rel(Path(run_dir) / "weights/best.pt"), rel(Path(run_dir) / "weights/best.onnx")):
        f = ROOT / p
        if f.is_file():
            models[p] = sha_file(f)
    data = {p: sha_file(ROOT / p) for p in DATA_FILES if (ROOT / p).is_file()}
    manifest = hashlib.sha256("\n".join("%s:%s" % kv for kv in sorted(data.items())).encode()).hexdigest()
    acc = ROOT / "acceptance"
    ay, ash = acc / "acceptance.yaml", acc / "acceptance.sha256"
    accd = {}
    if ay.is_file():
        accd["acceptance.yaml_sha256"] = sha_file(ay)
    if ash.is_file():
        accd["recorded_in_acceptance.sha256"] = ash.read_text().split()[0] if ash.read_text().split() else None
        accd["matches_recorded"] = accd.get("acceptance.yaml_sha256") == accd["recorded_in_acceptance.sha256"]
    log = acc / "holdout_runs.log"
    hold = dict(runs_logged=len([x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]) if log.is_file() else 0,
                clips_manifest_sha256=sha_file(acc / "holdout_clips_manifest.json") if (acc / "holdout_clips_manifest.json").is_file() else None,
                metrics_file_used=holdout_path)
    ta = train_args(run_dir)
    return dict(
        synthetic_demo=ctx.demo, generated=datetime.now().isoformat(timespec="seconds"), command=" ".join([Path(sys.argv[0]).name] + sys.argv[1:]),
        cwd=str(Path.cwd()), python=platform.python_version(), platform=platform.platform(), packages=pk, models_sha256=models,
        config_snapshot=cfg, seeds=dict(training=ta.get("seed"), bootstrap=E.BOOT_SEED, bootstrap_resamples=E.BOOT_N, sweep=SWEEP_SEED,
                                        deterministic_training=ta.get("deterministic")),
        data_manifest=dict(files=data, sha256=manifest), acceptance=dict(accd, hash=hashlib.sha256(json.dumps(accd, sort_keys=True).encode()).hexdigest()),
        holdout=hold, inputs_sha256=ctx.inputs_used, outputs=[f for r in ctx.registry for f in r["files"]], skipped=ctx.skipped,
        note=("SYNTHETIC DEMO: all inputs are generated numbers, none of this is a result" if ctx.demo else
              "inputs listed under inputs_sha256 are the exact files the figures/tables were drawn from"))


def build_readme(ctx: Ctx, lang_used: str) -> str:
    L = ["# Paper material (ASH-E, stage A, Windows webcam prototype)", ""]
    if ctx.demo:
        L += ["> **%s** -- every number in this folder was generated by `paper_report.py --demo`. Nothing here is a measurement." % DEMO_MARK, ""]
    L += ["Generated %s by `prototype/paper_report.py` (language of figure text: `%s`; tables and captions are English)." % (datetime.now().isoformat(timespec="seconds"), lang_used), "",
          "## Read this before using anything", "",
          "- **Generalisation is not claimed.** Hold-out figures and tables are *preliminary*; always keep the \"preliminary, n=... participants\" wording. "
          "Evaluation uses very few participants, one camera and proxy (box-height) distances; confidence intervals are wide.",
          "- Hold-out figures are drawn only from `metrics.json` files that `eval_clips.py --final` / `eval_images.py --final` already wrote. "
          "This tool never ran a model on hold-out data. Missing file = figure skipped (see list below).",
          "- Thresholds and hyper-parameters were not chosen from hold-out results. The threshold sweep / PR curve use dev data only.",
          "- Latency numbers are from a Windows PC, **not RPi5**. The RPi5 >= 5 Hz criterion is measured in stage B.",
          "- **Publication of participant images**: the written participant consent must explicitly include consent to publication of images "
          "(the current consent text covers training/evaluation and no public release). Without it, do not publish any participant image or crop. "
          "The case gallery is off by default, participant crops need `--allow-own-faces` and are face-blurred by pose keypoints "
          "(automatic blur can fail: check every image by eye). COCO images have per-image licences (NC, attribution) -- see `data/SOURCES.md`.", ""]
    figs = [r for r in ctx.registry if r["kind"] == "figure"]
    tabs = [r for r in ctx.registry if r["kind"] == "table"]
    L += ["## Figures (PNG 300 dpi + vector PDF in `figures/`)", "", "| Figure | Files | Input files | Caption draft (EN) |", "| --- | --- | --- | --- |"]
    for r in figs:
        L.append("| %s | %s | %s | %s |" % (r["id"], ", ".join(r["files"]), "<br>".join("`%s`" % i for i in r["inputs"]), r["caption"].replace("|", "/")))
    L += ["", "## Tables (CSV + LaTeX booktabs in `tables/`)", "", "| Table | Files | Input files | Caption draft (EN) |", "| --- | --- | --- | --- |"]
    for r in tabs:
        L.append("| %s | %s | %s | %s |" % (r["id"], ", ".join(r["files"]), "<br>".join("`%s`" % i for i in r["inputs"]), r["caption"].replace("|", "/")))
    L += ["", "## Skipped (no data)", ""] + (["- " + s for s in ctx.skipped] or ["- none"])
    L += ["", "## Reproduce", "", "```", "python prototype/eval_clips.py                    # dev metrics.json",
          "python prototype/eval_images.py --cig-model models/cig_roi.onnx   # dev metrics_dev.json",
          "python prototype/paper_report.py --collect-dev-scores", "python prototype/paper_report.py --run-ablation",
          "python prototype/bench_latency.py", "python prototype/paper_report.py [--lang ko]", "```", "",
          "`reproducibility.json` holds package versions, model SHA-256, config snapshot, seeds, data-manifest hash, acceptance hash, the command and the time.",
          "", "## Known limits of these figures", "",
          "- Per-participant confidence intervals are not in `metrics.json`; the participant figure shows points plus the pooled CI.",
          "- Per-category false-confirmation exposure is approximated from segment lengths (t1 - t0); the pooled value in the summary table is exact.",
          "- The PR curve / sweep is frame level on dev clips and cannot go below the configured cigarette threshold (raw scores below it are not recorded).",
          "- Stabiliser 'off' is a pass-through configuration of the unchanged core stabiliser (one frame of release lag, no smoking latch).",
          "- Parameter counts are the sum of ONNX initializer elements."]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ ablation runner (dev only, via eval_clips.main)
OFF_CFG = dict(stab_window_s=0.0, stab_min_obs=1, confirm_ratio=1.0, release_ratio=0.5, release_hold_s=0.0, smoking_min_obs=1, smoking_latch_s=0.001)


def run_ablation(out_dir: Path, passthrough: List[str], cfg_path: Optional[str] = None, P: Optional[E.Paths] = None, main_fn=None):
    """Replays the DEV clips twice with eval_clips.main (stabiliser as configured / pass-through). Never passes --final or --clips-dir."""
    import yaml
    main_fn = main_fn or E.main
    base = {}
    if cfg_path:
        base = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
    res = {}
    for name, over in (("on", {}), ("off", OFF_CFG)):
        cp = Path(out_dir) / ("_ablation_cfg_%s.yaml" % name)
        cp.write_text(yaml.safe_dump({**base, **over}), encoding="utf-8")
        argv = ["--config", str(cp), "--tag", "ablation_stab_" + name] + list(passthrough)
        bad = [x for x in argv if x in ("--final", "--clips-dir")]
        if bad:
            raise HoldoutRefusedError("ablation runs on the default dev folder only (got %s)" % bad)
        res[name] = main_fn(argv, P) if P is not None else main_fn(argv)
    return res


# ------------------------------------------------------------------ demo (synthetic) inputs
def make_demo_inputs(d: Path, seed: int = 7):
    """Writes SYNTHETIC inputs in the same formats as the real tools. Everything is flagged synthetic_demo."""
    import yaml
    import cv2
    rng = np.random.default_rng(seed)
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    th = yaml.safe_load((ROOT / "acceptance/acceptance.yaml").read_text(encoding="utf-8")) if (ROOT / "acceptance/acceptance.yaml").is_file() else {}
    th = {**dict(binary_precision_max4m=0.9, binary_recall_max3m=0.8, binary_recall_3to5m=0.6, smoking_holding_accuracy=0.75,
                 lookalike_false_confirm_per_10min=1, confirm_time_median_s=2.0, priority_flicker_s5=0), **th}
    run = d / "run"
    run.mkdir(exist_ok=True)
    ne = 30
    ep = np.arange(1, ne + 1)
    dec = np.exp(-ep / 9.0)
    sat = 1 - np.exp(-ep / 8.0)
    hdr = "epoch,time,train/box_loss,train/cls_loss,train/dfl_loss,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),metrics/mAP50-95(B),val/box_loss,val/cls_loss,val/dfl_loss,lr/pg0,lr/pg1,lr/pg2"
    lines = [hdr]
    for i, e in enumerate(ep):
        n = rng.normal(0, 0.01)
        lines.append(",".join("%.5f" % v for v in [e, 60.0 * e, 1.0 + 1.6 * dec[i] + n, 0.8 + 3.0 * dec[i] + n, 1.2 + 0.9 * dec[i], 0.8 * sat[i] + n, 0.75 * sat[i] + n,
                                                    0.78 * sat[i] + n, 0.5 * sat[i] + n, 1.3 + 1.4 * dec[i] + n, 1.1 + 2.8 * dec[i] + n, 1.3 + 0.9 * dec[i], 1e-3 * (1 - e / 40), 1e-3 * (1 - e / 40), 1e-3 * (1 - e / 40)]))
    (run / "results.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run / "args.yaml").write_text(yaml.safe_dump(dict(model="yolo11n.pt", imgsz=192, epochs=ne, batch=32, optimizer="auto", patience=20, seed=0, workers=2, device="cpu",
                                                       close_mosaic=5, amp=False, synthetic_demo=True)), encoding="utf-8")

    def clip_metrics(final: bool, seed_: int, parts, stab_off=False):
        r = np.random.default_rng(seed_)
        n_clips = 6 * len(parts)
        segs, fcs = [], []
        for ci in range(n_clips):
            p = parts[ci % len(parts)]
            for k in range(3):
                ttc = float(np.clip(r.normal(1.4 if not stab_off else 0.6, 0.5), 0.2, 4.0))
                segs.append(dict(clip="c%d" % ci, person="p1", participant=p, scenario="mouth", t0=10.0 * k, t1=10.0 * k + 8, label=["holding", "smoking"][k % 2],
                                 category="cigarette", occluded=False, confirmed=bool(r.random() > 0.08), ttc=ttc, continuation=False, frac_confirmed=0.8, distance_tag="2m"))
            for cat in ("similar_object", "gesture", "ecig_liquid", "ecig_heated"):
                ev = int(r.poisson(0.35 if not stab_off else 3.0))
                segs.append(dict(clip="c%d" % ci, person="p1", participant=p, scenario="similar", t0=40.0, t1=100.0, label="none", category=cat, occluded=False, n_frames=60,
                                 false_confirms=ev, counted_in="heated" if cat == "ecig_heated" else "lk"))
                for _ in range(ev):
                    fcs.append(dict(clip="c%d" % ci, t=45.0, label_seg="none/" + cat))
        for s in segs:
            if s["label"] in POS and not s["confirmed"]:
                s["ttc"] = None
        lk = [s for s in segs if s.get("counted_in") == "lk"]
        edges = sum(s["false_confirms"] for s in lk)
        mins = sum(s["t1"] - s["t0"] for s in lk) / 60.0
        tt = [s["ttc"] for s in segs if s.get("ttc") is not None]

        def ratio(name, p0, den, thr_):
            num = int(round(p0 * den))
            w = wilson(num, den)
            boot = [max(0.0, p0 - 0.09), min(1.0, p0 + 0.09)]
            return dict(value=num / den, num=num, den=den, wilson=w, boot=boot, threshold=thr_, direction=">=", passed=(num / den) >= thr_,
                        uncertain=w[0] < thr_, flags=[], per_participant={})
        mets = {"binary_precision_max4m": ratio("p", 0.93 if not stab_off else 0.84, 900, th["binary_precision_max4m"]),
                "binary_recall_max3m": ratio("r3", 0.86 if not stab_off else 0.9, 1200, th["binary_recall_max3m"]),
                "binary_recall_3to5m": ratio("r5", 0.66, 700, th["binary_recall_3to5m"]),
                "smoking_holding_accuracy": ratio("sh", 0.81, 1500, th["smoking_holding_accuracy"])}
        val = 10 * edges / mins
        mets["lookalike_false_confirm_per_10min"] = dict(value=val, num=edges, den=mins, exposure_min=mins, wilson=None, boot=[max(0, val - 0.6), val + 0.9],
                                                         threshold=th["lookalike_false_confirm_per_10min"], direction="<=", passed=val <= th["lookalike_false_confirm_per_10min"],
                                                         uncertain=False, flags=[], rule_of_three_upper=3.0 / (mins / 10) if edges == 0 else None)
        mets["confirm_time_median_s"] = dict(value=float(np.median(tt)), num=len(tt), den=len(tt), wilson=None, boot=[float(np.median(tt)) - 0.2, float(np.median(tt)) + 0.2],
                                             threshold=th["confirm_time_median_s"], direction="<=", passed=float(np.median(tt)) <= th["confirm_time_median_s"], uncertain=False, flags=[])
        mets["priority_flicker_s5"] = dict(value=None, num=None, den=None, wilson=None, boot=None, threshold=0, direction="<=", passed=None, uncertain=False, flags=[])
        ptab = {p: {k: min(1.0, max(0.0, mets[k]["value"] + r.normal(0, 0.05))) for k in E.RATIO} for p in parts}
        return dict(synthetic_demo=True, final=final, n_clips=n_clips, participants=list(parts), pos_exposure_min=n_clips * 0.4, lookalike_exposure_min=mins, metrics=mets,
                    false_confirms=fcs, misses=[], segments=segs, participant_table=ptab, meta=dict(run_no=1 if final else None), verdict="synthetic")
    (d / "clips_dev").mkdir(exist_ok=True)
    (d / "clips_ablation_stab_on").mkdir(exist_ok=True)
    (d / "clips_ablation_stab_off").mkdir(exist_ok=True)
    (d / "clips_holdout/run_001").mkdir(parents=True, exist_ok=True)
    dev = clip_metrics(False, 1, ["P02"])
    (d / "clips_dev/metrics.json").write_text(json.dumps(dev), encoding="utf-8")
    (d / "clips_ablation_stab_on/metrics.json").write_text(json.dumps(dev), encoding="utf-8")
    (d / "clips_ablation_stab_off/metrics.json").write_text(json.dumps(clip_metrics(False, 1, ["P02"], stab_off=True)), encoding="utf-8")
    (d / "clips_holdout/run_001/metrics.json").write_text(json.dumps(clip_metrics(True, 2, ["P03", "P04"])), encoding="utf-8")
    for tag, final, m in (("dev", False, [[240, 8, 2], [14, 150, 30], [6, 25, 170]]), ("holdout", True, [[210, 9, 3], [20, 120, 40], [9, 33, 140]])):
        (d / ("metrics_%s.json" % tag)).write_text(json.dumps(dict(synthetic_demo=True, final=final, tag=tag, n=int(np.sum(m)), labels=["none", "holding", "smoking"], confusion=m)), encoding="utf-8")
    recs = []
    for _ in range(1500):
        pos = rng.random() < 0.4
        sc = float(np.clip(rng.beta(6, 2.5) if pos else rng.beta(1.2, 7), 0, 1))
        sc = sc if sc >= 0.35 else 0.0
        recs.append(dict(score=sc, label=int(pos), split="dev", clip="c%d" % rng.integers(0, 6)))
    (d / "dev_scores.json").write_text(json.dumps(dict(synthetic_demo=True, split="dev", final=False, source_dir="synthetic", clips=6, records=recs)), encoding="utf-8")
    (d / "build_report.json").write_text(json.dumps(dict(
        synthetic_demo=True, train=dict(counts=dict(public_pos=1200, synth_pos=300, coco_none_neg=2000, coco_similar_neg=380, public_neg=1100), pos=1500, neg=3480),
        val=dict(counts=dict(public_pos=180, coco_none_neg=190, coco_similar_neg=40, public_neg=80), pos=180, neg=310))), encoding="utf-8")
    st = {"pose": 6.8, "roi": 0.2, "cig": 18.0, "stab": 0.03}
    base = np.array([sum(st.values())] * 200) * (1 + np.abs(rng.normal(0, 0.06, 200)))
    stats_ = lambda x: dict(n=len(x), mean=float(np.mean(x)), median=float(np.median(x)), p95=float(np.percentile(x, 95)), min=float(np.min(x)), max=float(np.max(x)))  # noqa: E731
    (d / "latency.json").write_text(json.dumps(dict(
        synthetic_demo=True, synthetic_input=True, env=dict(cpu="DEMO CPU", logical_cpus=8, ort_threads=4, onnxruntime="x.y"), params=dict(n=200, warmup=20, persons=3, frame=[1280, 720]),
        stages_ms={k: stats_(v * (1 + np.abs(rng.normal(0, 0.05, 200)))) for k, v in st.items()}, total_ms=stats_(base), end_to_end_ms=stats_(base * 0.3), fps=stats_(1000 / base),
        fps_samples=[float(v) for v in 1000 / base],
        models=dict(pose=dict(present=True, params=3_300_000, onnx_bytes=11_000_000), cig=dict(present=True, params=2_600_000, onnx_bytes=10_000_000)))), encoding="utf-8")
    g = d / "gallery"
    g.mkdir(exist_ok=True)
    for i in range(8):
        im_ = np.full((120, 120, 3), 90 + 15 * i, np.uint8)
        cv2.circle(im_, (60, 60), 25 + 3 * i, (60, 140 + 10 * i, 220 - 10 * i), -1)
        cv2.imwrite(str(g / ("FP_%02d_synthetic.jpg" % i)), im_)
    return d


# ------------------------------------------------------------------ main
def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", choices=["en", "ko"], default="en")
    ap.add_argument("--out", default=None, help="default _workspace/paper (or _workspace/paper_demo with --demo)")
    ap.add_argument("--demo", action="store_true", help="synthetic inputs, watermarked, written to _workspace/paper_demo only")
    ap.add_argument("--run", default=None, help="training run dir (default: training/runs/cig_roi, else the newest run with results.csv)")
    ap.add_argument("--eval-out", default=str(ROOT / "_workspace/eval_out"))
    ap.add_argument("--dev-metrics", default=None)
    ap.add_argument("--holdout-metrics", default=None, help="a metrics.json written by eval_clips.py --final (default: latest run)")
    ap.add_argument("--images-dev", default=None)
    ap.add_argument("--images-holdout", default=None)
    ap.add_argument("--dev-scores", default=None)
    ap.add_argument("--latency", default=None)
    ap.add_argument("--dataset-report", default=str(ROOT / "data/roi_ds_v2/build_report.json"))
    ap.add_argument("--config", default=None, help="perception yaml used in the evaluation (default: PerceptionConfig defaults)")
    ap.add_argument("--collect-dev-scores", action="store_true")
    ap.add_argument("--run-ablation", action="store_true", help="replay DEV clips with the stabiliser on/off (needs models)")
    ap.add_argument("--pose", default=None)
    ap.add_argument("--cig-model", default=None)
    ap.add_argument("--allow-train", action="store_true")
    ap.add_argument("--allow-unknown-split", action="store_true")
    ap.add_argument("--gallery-dir", default=None, help="folder with error-case ROI crops (e.g. _workspace/eval_out/dev)")
    ap.add_argument("--gallery-source", choices=["own", "public", "synthetic"], default="own")
    ap.add_argument("--allow-own-faces", action="store_true", help="allow participant crops in the gallery (face-blurred unless --no-blur)")
    ap.add_argument("--no-blur", action="store_true")
    a = ap.parse_args(argv)

    paper, demo_dir = ROOT / "_workspace/paper", ROOT / "_workspace/paper_demo"
    out = Path(a.out) if a.out else (demo_dir if a.demo else paper)
    if a.demo and not E.is_under(out, demo_dir):
        sys.exit("REFUSED: --demo writes only under _workspace/paper_demo (synthetic numbers must never land in _workspace/paper).")
    if not a.demo and E.is_under(out, demo_dir):
        sys.exit("REFUSED: _workspace/paper_demo is reserved for --demo.")
    ctx = Ctx(out, a.lang, a.demo)
    if a.lang == "ko" and ctx.lang != "ko":
        print("WARNING: continuing in English")

    if a.demo:
        ev = make_demo_inputs(out / "_demo_inputs")
        run_dir, eval_out = ev / "run", ev
        dev_p, hold_p = ev / "clips_dev/metrics.json", ev / "clips_holdout/run_001/metrics.json"
        imd, imh, sc_p, lat_p, rep_p = ev / "metrics_dev.json", ev / "metrics_holdout.json", ev / "dev_scores.json", ev / "latency.json", ev / "build_report.json"
        on_p, off_p = ev / "clips_ablation_stab_on/metrics.json", ev / "clips_ablation_stab_off/metrics.json"
        gal = (ev / "gallery", "synthetic")
    else:
        eval_out = Path(a.eval_out)
        if a.run:
            run_dir = Path(a.run)
        else:
            cands = [p.parent for p in (ROOT / "training/runs").glob("*/results.csv")]
            run_dir = ROOT / "training/runs/cig_roi" if (ROOT / "training/runs/cig_roi/results.csv").is_file() else \
                (max(cands, key=lambda p: (p / "results.csv").stat().st_mtime) if cands else ROOT / "training/runs/cig_roi")
        if a.collect_dev_scores:
            collect_dev_scores(E.Paths(), eval_out / "clips_dev/replay", eval_out / "dev_scores.json")
        if a.run_ablation:
            pt = (["--pose", a.pose] if a.pose else []) + (["--cig-model", a.cig_model] if a.cig_model else []) + \
                 (["--allow-train"] if a.allow_train else []) + (["--allow-unknown-split"] if a.allow_unknown_split else [])
            run_ablation(out, pt, a.config)
        dev_p = Path(a.dev_metrics) if a.dev_metrics else eval_out / "clips_dev/metrics.json"
        hold_p = Path(a.holdout_metrics) if a.holdout_metrics else latest_holdout_metrics(eval_out)
        imd = Path(a.images_dev) if a.images_dev else eval_out / "metrics_dev.json"
        imh = Path(a.images_holdout) if a.images_holdout else eval_out / "metrics_holdout.json"
        sc_p = Path(a.dev_scores) if a.dev_scores else eval_out / "dev_scores.json"
        lat_p = Path(a.latency) if a.latency else out / "latency.json"
        rep_p = Path(a.dataset_report)
        on_p, off_p = eval_out / "clips_ablation_stab_on/metrics.json", eval_out / "clips_ablation_stab_off/metrics.json"
        gal = (Path(a.gallery_dir), a.gallery_source) if a.gallery_dir else None
    if hold_p is not None and not E.is_under(Path(hold_p), eval_out) and not a.demo:
        pass  # explicit path allowed; it is read only and must carry final=true

    cfg = pipeline_cfg(a.config)
    rep = None
    if Path(rep_p).is_file():
        rep = read_json(rep_p)
        reject_demo_doc(rep, rep_p, a.demo)
        ctx.used(rep_p)
    else:
        ctx.skip("dataset report", "no %s" % rel(rep_p))
    dev = load_clip_metrics(ctx, dev_p, "dev", "dev clip figures")
    hold = load_clip_metrics(ctx, hold_p, "holdout", "hold-out clip figures")
    im_dev = load_images_metrics(ctx, imd, "dev", "dev confusion matrix")
    im_hold = load_images_metrics(ctx, imh, "holdout", "hold-out confusion matrix")

    fig_training_curves(ctx, run_dir, rep)
    sd = load_dev_scores(ctx, sc_p)
    if sd:
        sd["_path"] = rel(sc_p)
        fig_pr_and_sweep(ctx, sd, cfg["cig_conf_thresh"])
    for split, imm, cm in (("dev", im_dev, dev), ("holdout", im_hold, hold)):
        if imm:
            fig_confusion(ctx, imm, split, cm, rel(imd if split == "dev" else imh))
    for split, m in (("dev", dev), ("holdout", hold)):
        if m:
            fig_distance_recall(ctx, m, split)
            fig_ttc(ctx, m, split)
            fig_false_confirm(ctx, m, split)
            fig_participants(ctx, m, split)
    on = load_clip_metrics(ctx, on_p, "dev", "stabiliser ablation (on)")
    off = load_clip_metrics(ctx, off_p, "dev", "stabiliser ablation (off)")
    if on and off:
        fig_ablation(ctx, on, off)
        table_ablation(ctx, on, off)
    fig_dataset(ctx, rep, dev, hold, rel(rep_p))
    lat = None
    if Path(lat_p).is_file():
        lat = read_json(lat_p)
        reject_demo_doc(lat, lat_p, a.demo)
        ctx.used(lat_p)
        fig_latency(ctx, lat, rel(lat_p))
        table_latency(ctx, lat, rel(lat_p))
    else:
        ctx.skip("latency figure/table", "no %s (run prototype/bench_latency.py)" % rel(lat_p))
    if gal:
        pm = None
        if gal[1] == "own" and a.allow_own_faces and not a.no_blur:
            from ash_e_core.backends import load_model
            pm = load_model(a.pose or str(ROOT / "models/pose.onnx"), "onnxruntime", 2)
            pm = None if getattr(pm, "is_stub", False) else pm
        fig_gallery(ctx, gal[0], gal[1], a.allow_own_faces, blur=not a.no_blur, pose_model=pm)
    table_summary(ctx, dev, hold)
    splits_doc = None
    sp = ROOT / "data/splits/participants.json"
    if sp.is_file() and not a.demo:
        splits_doc = read_json(sp)
    table_dataset(ctx, rep, dev, hold, splits_doc, rel(rep_p))
    table_hyper(ctx, run_dir, cfg)

    repro = build_repro(ctx, a, cfg, run_dir, hold["_path"] if hold else None)
    (out / "reproducibility.json").write_text(json.dumps(repro, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "README.md").write_text(build_readme(ctx, ctx.lang), encoding="utf-8")
    print("\n%d figure(s)/table(s), %d skipped -> %s" % (len(ctx.registry), len(ctx.skipped), out))
    return ctx


if __name__ == "__main__":
    main()
