"""Model-history report figures for README (v1 .. v6 cigarette ROI detector).

Reads only EXISTING outputs (no model is run here, nothing under data/eval/holdout or P03 clips is read):
  training/runs/<run>/results.csv                      ultralytics training log per version
  data/<roi dataset>/build_report.json                 ROI counts per version
  data/raw/<PID>/<S>/meta.jsonl                        capture counts (P01 train, P02 dev; P03 only counted, not read as data)
  _workspace/eval_out/clips_dev_p02_<tag>/metrics.json eval_clips.py dev results (P02)
  _workspace/eval_out/metrics_<tag>.json               eval_images.py dev frame results (P02)
  _workspace/eval_out/val_common/<ver>.json            common-val results written by report_val_common.py

  python prototype/report_figures.py            # -> docs/figures/*.png, docs/figures/summary.json
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures"
EV = ROOT / "_workspace" / "eval_out"

for f in ("malgun.ttf", "malgunbd.ttf"):
    p = Path("C:/Windows/Fonts") / f
    if p.is_file():
        font_manager.fontManager.addfont(str(p))
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "figure.dpi": 110,
                     "savefig.dpi": 160, "axes.grid": True, "grid.alpha": 0.3})

# version -> (training run, ROI dataset folders, clip-eval tag, frame-eval tag, model file)
VERSIONS = {
    "v1": dict(run="cig_roi_v2", ds=["roi_ds_v2"], clip="clips_dev_p02_v1", frame="metrics_p02_reviewed_pass1.json",
               model="cig_roi.onnx"),
    "v3exp": dict(run="cig_roi_v3exp", ds=["roi_ds_v2", "roi_own_p01_pseudo"], clip="clips_dev_p02_v3exp",
                  frame="metrics_p02_reviewed_v3exp.json", model="cig_roi_v3exp.onnx"),
    "v3": dict(run="cig_roi_v3", ds=["roi_ds_v2", "roi_own_p01_reviewed"], clip="clips_dev_p02_v3_distfix",
               frame="metrics_p02_reviewed_v3.json", model="cig_roi_v3.onnx"),
    "v4": dict(run="cig_roi_v4", ds=["roi_ds_v2", "roi_own_p01_reviewed_v4"], clip="clips_dev_p02_v4",
               frame="metrics_p02_frames_v4.json", model="cig_roi_v4.onnx"),
    "v5": dict(run="cig_roi_v5", ds=["roi_ds_v2", "roi_own_p01_reviewed_v5"], clip="clips_dev_p02_v5",
               frame="metrics_p02_frames_v5.json", model="cig_roi_v5.onnx"),
    "v6": dict(run="cig_roi_v6", ds=["roi_ds_v2", "roi_own_p01_reviewed_v6"], clip="clips_dev_p02_v6",
               frame="metrics_p02_frames_v6.json", model="cig_roi_v6.onnx"),
}
COLORS = {"v1": "#7f7f7f", "v3exp": "#bcbd22", "v3": "#1f77b4", "v4": "#ff7f0e", "v5": "#2ca02c", "v6": "#d62728"}
ACCEPT = {"binary_precision_max4m": 0.90, "binary_recall_max3m": 0.80, "binary_recall_3to5m": 0.60,
          "smoking_holding_accuracy": 0.75, "lookalike_false_confirm_per_10min": 1.0, "confirm_time_median_s": 2.0}
METRIC_KO = {"binary_precision_max4m": "정밀도 (≤4 m)", "binary_recall_max3m": "재현율 (≤3 m)",
             "binary_recall_3to5m": "재현율 (3~5 m)", "smoking_holding_accuracy": "흡연/소지 구분",
             "lookalike_false_confirm_per_10min": "유사물 오확정 /10분", "confirm_time_median_s": "확정 시간 중앙값 [s]"}


def read_csv(p: Path):
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [{k.strip(): float(v) for k, v in r.items() if v.strip() != ""} for r in rows]


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name)
    plt.close(fig)
    print("wrote", OUT / name)


# ---------------------------------------------------------------- training curves
def fig_training(summary):
    runs = {v: read_csv(ROOT / "training/runs" / c["run"] / "results.csv")
            for v, c in VERSIONS.items() if (ROOT / "training/runs" / c["run"] / "results.csv").is_file()}
    summary["training"] = {}
    for v, rows in runs.items():
        # ultralytics 8.4 fitness = mAP50-95 only (utils/metrics.py, w = [0, 0, 0, 1]); best.pt is chosen by it
        best = max(rows, key=lambda r: r["metrics/mAP50-95(B)"])
        summary["training"][v] = dict(
            epochs=len(rows), wall_s=rows[-1]["time"], best_epoch=int(best["epoch"]),
            best=dict(P=best["metrics/precision(B)"], R=best["metrics/recall(B)"], mAP50=best["metrics/mAP50(B)"],
                      mAP50_95=best["metrics/mAP50-95(B)"]),
            last=dict(train_box=rows[-1]["train/box_loss"], train_cls=rows[-1]["train/cls_loss"],
                      val_box=rows[-1]["val/box_loss"], val_cls=rows[-1]["val/cls_loss"]))

    # overlay of val metrics for all versions
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.2))
    for v, rows in runs.items():
        ep = [r["epoch"] for r in rows]
        axs[0].plot(ep, [r["metrics/mAP50(B)"] for r in rows], color=COLORS[v], label=v)
        axs[1].plot(ep, [r["metrics/precision(B)"] for r in rows], color=COLORS[v], label=v)
        axs[2].plot(ep, [r["metrics/recall(B)"] for r in rows], color=COLORS[v], label=v)
    for a, t in zip(axs, ("val mAP50", "val Precision", "val Recall")):
        a.set_title(t); a.set_xlabel("epoch"); a.set_ylim(0, 1); a.legend(fontsize=8)
    fig.suptitle("버전별 검증(val) 지표 추이 — 각 버전의 val 세트가 서로 다르므로 절대값 직접 비교는 불가")
    save(fig, "train_val_metrics_all.png")

    # per-version loss + metric panels
    for v, rows in runs.items():
        ep = [r["epoch"] for r in rows]
        fig, axs = plt.subplots(2, 4, figsize=(16, 7))
        pairs = [("box_loss", "Box loss"), ("cls_loss", "Class loss"), ("dfl_loss", "DFL loss")]
        for i, (k, t) in enumerate(pairs):
            axs[0, i].plot(ep, [r["train/" + k] for r in rows], label="train", color="#1f77b4")
            axs[0, i].plot(ep, [r["val/" + k] for r in rows], label="val", color="#d62728")
            axs[0, i].set_title(t); axs[0, i].legend(); axs[0, i].set_xlabel("epoch")
        lr = [k for k in rows[0] if k.startswith("lr/pg0")]
        axs[0, 3].plot(ep, [r[lr[0]] for r in rows], color="#555"); axs[0, 3].set_title("학습률 (pg0)")
        for i, (k, t) in enumerate([("metrics/precision(B)", "Precision"), ("metrics/recall(B)", "Recall"),
                                    ("metrics/mAP50(B)", "mAP50"), ("metrics/mAP50-95(B)", "mAP50-95")]):
            axs[1, i].plot(ep, [r[k] for r in rows], color=COLORS[v], marker=".")
            axs[1, i].set_title("val " + t); axs[1, i].set_ylim(0, 1); axs[1, i].set_xlabel("epoch")
            b = summary["training"][v]["best_epoch"]
            axs[1, i].axvline(b, ls="--", color="k", lw=0.8)
        fig.suptitle(f"{v} 학습 곡선 (run {VERSIONS[v]['run']}, 점선 = best epoch {summary['training'][v]['best_epoch']})")
        save(fig, f"train_curves_{v}.png")


# ---------------------------------------------------------------- datasets
def ds_counts(name):
    r = jload(ROOT / "data" / name / "build_report.json")
    if r is None:
        return None
    if "stats" in r:  # own P01 dataset
        return {s: dict(pos=r["stats"][s]["pos"], neg=r["stats"][s]["neg"]) for s in ("train", "val")}
    return {s: dict(pos=r[s]["pos"], neg=r[s]["neg"]) for s in ("train", "val")}


def fig_datasets(summary):
    summary["datasets"] = {}
    labels, parts = [], defaultdict(list)
    for v, c in VERSIONS.items():
        pub, own = ds_counts(c["ds"][0]), (ds_counts(c["ds"][1]) if len(c["ds"]) > 1 else None)
        own = own or {s: dict(pos=0, neg=0) for s in ("train", "val")}
        summary["datasets"][v] = dict(public=pub, own=own)
        labels.append(v)
        parts["공개+합성 양성"].append(pub["train"]["pos"])
        parts["공개 음성"].append(pub["train"]["neg"])
        parts["P01 양성"].append(own["train"]["pos"])
        parts["P01 음성"].append(own["train"]["neg"])
    fig, ax = plt.subplots(figsize=(10, 4.8))
    bottom = [0] * len(labels)
    cols = {"공개+합성 양성": "#9ecae1", "공개 음성": "#d9d9d9", "P01 양성": "#d62728", "P01 음성": "#fcbba1"}
    for k, vals in parts.items():
        ax.bar(labels, vals, bottom=bottom, label=k, color=cols[k])
        bottom = [b + x for b, x in zip(bottom, vals)]
    for i, b in enumerate(bottom):
        ax.text(i, b, f"{b:,}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("학습(train) ROI 수"); ax.set_title("버전별 학습 ROI 구성 (train 분할)"); ax.legend()
    save(fig, "dataset_composition.png")


# ---------------------------------------------------------------- capture
def fig_capture(summary):
    rows = []
    for m in sorted((ROOT / "data/raw").glob("*/*/meta.jsonl")):
        pid, ses = m.parts[-3], m.parts[-2]
        for line in m.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            rows.append((pid, ses, d.get("scenario"), d.get("distance_tag") or "unk", d.get("angle_tag") or "unk"))
    cap = defaultdict(Counter)
    for pid, ses, sc, dist, ang in rows:
        cap[f"{pid}/{ses}"][sc] += 1
    summary["capture_meta"] = {k: dict(v) for k, v in cap.items()}
    dist = defaultdict(Counter)
    for pid, ses, sc, d, ang in rows:
        if pid == "P01":
            dist[sc][d] += 1
    summary["capture_P01_distance"] = {k: dict(v) for k, v in dist.items()}
    scen = ["holding", "mouth", "none", "similar", "gesture"]
    dtags = ["1m", "2m", "3m", "4m", "5m", "unk"]
    fig, axs = plt.subplots(1, 2, figsize=(14, 4.5))
    keys = list(cap)
    w = 0.8 / len(scen)
    for j, sc in enumerate(scen):
        axs[0].bar([i + j * w for i in range(len(keys))], [cap[k][sc] for k in keys], w, label=sc)
    axs[0].set_xticks([i + 0.4 - w / 2 for i in range(len(keys))]); axs[0].set_xticklabels(keys)
    axs[0].set_title("촬영 사진 수 (참가자/세션 × 시나리오, meta.jsonl 기준)"); axs[0].legend(); axs[0].set_ylabel("장")
    mat = [[dist[sc][d] for d in dtags] for sc in scen]
    im = axs[1].imshow(mat, cmap="Blues")
    axs[1].set_xticks(range(len(dtags))); axs[1].set_xticklabels(dtags)
    axs[1].set_yticks(range(len(scen))); axs[1].set_yticklabels(scen); axs[1].grid(False)
    for i in range(len(scen)):
        for j in range(len(dtags)):
            axs[1].text(j, i, mat[i][j], ha="center", va="center", fontsize=9,
                        color="white" if mat[i][j] > max(map(max, mat)) * 0.6 else "black")
    axs[1].set_title("P01(학습) 시나리오 × 거리 태그 (S1+S2+S3)")
    fig.colorbar(im, ax=axs[1], fraction=0.03)
    save(fig, "capture_counts.png")


# ---------------------------------------------------------------- P02 dev clip metrics
def fig_clip_metrics(summary):
    summary["clips_p02"] = {}
    for v, c in VERSIONS.items():
        m = jload(EV / c["clip"] / "metrics.json")
        if m:
            summary["clips_p02"][v] = {k: m["metrics"][k]["value"] for k in ACCEPT if k in m["metrics"]}
            summary["clips_p02"][v]["_models"] = m["meta"]["models"]
            summary["clips_p02"][v]["_wilson"] = {k: m["metrics"][k].get("wilson") for k in ACCEPT if k in m["metrics"]}
            summary["clips_p02"][v]["_counts"] = {k: [m["metrics"][k].get("num"), m["metrics"][k].get("den")]
                                                  for k in ACCEPT if k in m["metrics"]}
    vs = list(summary["clips_p02"])
    fig, axs = plt.subplots(2, 3, figsize=(15, 7.5))
    for a, k in zip(axs.flat, ACCEPT):
        vals = [summary["clips_p02"][v].get(k) for v in vs]
        vals = [x if x is not None else 0 for x in vals]
        bars = a.bar(vs, vals, color=[COLORS[v] for v in vs])
        a.axhline(ACCEPT[k], color="k", ls="--", lw=1, label=f"합격선 {ACCEPT[k]}")
        for b, x in zip(bars, vals):
            a.text(b.get_x() + b.get_width() / 2, x, f"{x:.2f}", ha="center", va="bottom", fontsize=8)
        a.set_title(METRIC_KO[k] + ("  (낮을수록 좋음)" if k in ("lookalike_false_confirm_per_10min",
                                                            "confirm_time_median_s") else ""))
        if k not in ("lookalike_false_confirm_per_10min", "confirm_time_median_s"):
            a.set_ylim(0, 1.08)
        a.legend(fontsize=8)
    fig.suptitle("P02 dev 영상 13개 평가 (eval_clips.py, 안정화 후 상태 기준, 판정 아님)")
    save(fig, "p02_clip_metrics.png")


# ---------------------------------------------------------------- P02 dev frame confusion
def fig_frame_confusion(summary):
    summary["frames_p02"] = {}
    have = [(v, jload(EV / c["frame"])) for v, c in VERSIONS.items()]
    have = [(v, m) for v, m in have if m]
    if not have:
        return
    fig, axs = plt.subplots(1, len(have), figsize=(3.6 * len(have), 3.8))
    axs = axs if len(have) > 1 else [axs]
    for a, (v, m) in zip(axs, have):
        cm, lab = m["confusion"], m["labels"]
        b = m["binary"]
        P = b["tp"] / max(1, b["tp"] + b["fp"]); R = b["tp"] / max(1, b["tp"] + b["fn"])
        acc = sum(cm[i][i] for i in range(3)) / max(1, sum(map(sum, cm)))
        summary["frames_p02"][v] = dict(n=m["n"], confusion=cm, labels=lab, binary=b, P=P, R=R,
                                        F1=2 * P * R / max(1e-9, P + R), acc3=acc,
                                        sh_acc=m["sh_ok"] / max(1, m["sh_n"]), fp_by_cat=m.get("per_cat_fp"),
                                        infer_ms=m.get("infer_ms"))
        a.imshow(cm, cmap="Blues"); a.grid(False)
        for i in range(3):
            for j in range(3):
                a.text(j, i, cm[i][j], ha="center", va="center",
                       color="white" if cm[i][j] > max(map(max, cm)) * 0.6 else "black")
        a.set_xticks(range(3)); a.set_xticklabels(lab); a.set_yticks(range(3)); a.set_yticklabels(lab)
        a.set_xlabel("예측"); a.set_ylabel("정답")
        a.set_title(f"{v}\nP {P:.2f} / R {R:.2f} / 3클래스 정확도 {acc:.2f}", fontsize=9)
    fig.suptitle("P02 dev 검수 사진 366장 혼동행렬 (eval_images.py, 프레임 단위 raw 상태, conf 0.35)")
    save(fig, "p02_frame_confusion.png")


# ---------------------------------------------------------------- common val
def fig_common_val(summary):
    d = EV / "val_common"
    res = {p.stem: jload(p) for p in sorted(d.glob("*.json"))} if d.is_dir() else {}
    res = {k: v for k, v in res.items() if k in VERSIONS}
    if not res:
        return
    summary["val_common"] = res
    vs = [v for v in VERSIONS if v in res]
    keys = [("P", "Precision"), ("R", "Recall"), ("mAP50", "mAP50"), ("mAP50_95", "mAP50-95")]
    fig, axs = plt.subplots(1, 2, figsize=(16, 4.8))
    w = 0.8 / len(keys)
    for a, part, title in ((axs[0], "all", "전체 (공개 506 + P01 1,330 ROI)"), (axs[1], "p01", "P01 로봇 시점 부분만 (1,330 ROI)")):
        for j, (k, t) in enumerate(keys):
            bars = a.bar([i + j * w for i in range(len(vs))], [res[v][part][k] for v in vs], w, label=t)
            for b in bars:
                a.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{b.get_height():.2f}", ha="center",
                       va="bottom", fontsize=6.5)
        a.set_xticks([i + 0.4 - w / 2 for i in range(len(vs))]); a.set_xticklabels(vs); a.set_ylim(0, 1.05)
        a.legend(fontsize=8); a.set_title("공통 검증 세트(v6 val) — " + title)
    save(fig, "val_common_metrics.png")


# ---------------------------------------------------------------- reference (metric explainer, worked example)
def fig_reference():
    """Toy example from the 'Recall and mAP50' explainer: 10 real cats, 11 boxes sorted by confidence."""
    conf = [0.95, 0.90, 0.85, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10]
    tp = [1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0]
    n_gt = 10
    P, R, ctp = [], [], 0
    for i, t in enumerate(tp):
        ctp += t
        P.append(ctp / (i + 1)); R.append(ctp / n_gt)
    fig, ax = plt.subplots(figsize=(6, 3.6))
    shift = [s / 100 for s in range(0, 101)]
    ax.plot(shift, [(1 - s) / (1 + s) for s in shift], color="#1f77b4")
    ax.axhline(0.5, ls="--", color="k", lw=1); ax.text(0.02, 0.52, "IoU 0.5 (mAP50 기준)", fontsize=9)
    ax.set_xlabel("옆으로 민 거리 (네모 한 변 대비)"); ax.set_ylabel("IoU")
    ax.set_title("같은 크기의 네모를 옆으로 밀었을 때의 IoU")
    save(fig, "ref_iou.png")
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    ax.plot(conf, P, marker="o", label="Precision"); ax.plot(conf, R, marker="s", label="Recall")
    ax.invert_xaxis(); ax.set_xlabel("기준선 (confidence threshold), 왼쪽→오른쪽으로 낮아짐"); ax.set_ylim(0, 1.05)
    ax.set_title("기준선을 낮추면 Recall↑ Precision↓ (고양이 예시)"); ax.legend()
    save(fig, "ref_threshold_pr.png")
    # PR curve + AP (all-point interpolation, as in COCO / ultralytics)
    mrec = [0.0] + R + [R[-1]]
    mpre = [1.0] + P + [0.0]
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    ap = sum((mrec[i + 1] - mrec[i]) * mpre[i + 1] for i in range(len(mrec) - 1))
    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.plot(R, P, "o-", color="#999", label="기준선별 (R, P)")
    ax.step(mrec, mpre, where="post", color="#d62728", label="보간된 PR 곡선")
    ax.fill_between(mrec, mpre, step="post", alpha=0.2, color="#d62728")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.05); ax.set_xlabel("Recall"); ax.set_ylabel("Precision")
    ax.set_title(f"PR 곡선과 AP = 넓이 {ap:.2f} (최대 Recall 0.70이 천장)"); ax.legend(loc="lower left")
    save(fig, "ref_pr_curve.png")


# ---------------------------------------------------------------- threshold sweep (P02 frames, all versions)
SWEEP_KEY = {"cig_roi": "v1", "cig_roi_v3exp": "v3exp", "cig_roi_v3": "v3", "cig_roi_v4": "v4", "cig_roi_v5": "v5",
             "cig_roi_v6": "v6"}


def fig_sweep(summary):
    d = jload(EV / "sweep_dev_thresholds.json")
    if not d:
        return
    summary["sweep_p02"] = {}
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
    for k, v in SWEEP_KEY.items():
        if k not in d:
            continue
        thr = sorted(d[k]["by_thr"], key=float)
        P = [d[k]["by_thr"][t]["all"]["P"] for t in thr]
        R = [d[k]["by_thr"][t]["all"]["R"] for t in thr]
        summary["sweep_p02"][v] = {t: dict(P=p, R=r) for t, p, r in zip(thr, P, R)}
        lw = 2.6 if v == "v6" else 1.2
        axs[0].plot(R, P, "o-", color=COLORS[v], label=v, lw=lw)
        axs[1].plot([float(t) for t in thr], [2 * p * r / max(1e-9, p + r) for p, r in zip(P, R)], "o-",
                    color=COLORS[v], label=v, lw=lw)
    axs[0].set_xlabel("Recall"); axs[0].set_ylabel("Precision"); axs[0].set_xlim(0, 1); axs[0].set_ylim(0, 1)
    axs[0].set_title("판정 기준값 0.25~0.65에서의 정밀도-재현율 (P02 사진 366장)")
    axs[1].set_xlabel("담배 신뢰도 기준값"); axs[1].set_ylabel("F1"); axs[1].set_ylim(0, 1)
    axs[1].axvline(0.35, color="k", ls="--", lw=0.8); axs[1].set_title("기준값별 F1 (점선 = 운영값 0.35)")
    for a in axs:
        a.legend(fontsize=8)
    save(fig, "p02_threshold_sweep.png")


# ---------------------------------------------------------------- v6 quality page
def fig_v6_quality(summary):
    m = jload(EV / "clips_dev_p02_v6" / "metrics.json")
    f = jload(EV / "metrics_p02_frames_v6.json")
    lat = jload(EV / "latency_v6.json")
    q = summary.setdefault("v6_quality", {})
    fig, axs = plt.subplots(1, 3, figsize=(17, 4.6))
    if m:
        pos = [(s["clip"].split("/")[-1], s.get("ttc")) for s in m["segments"] if s["label"] != "none"]
        # confirmed-frame ratio per positive segment, read from the eval_clips report table
        ratios = {}
        for line in (EV / "clips_dev_p02_v6" / "report.md").read_text(encoding="utf-8").splitlines():
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) == 7 and c[0].startswith("S1/") and c[3] in ("smoking", "holding"):
                ratios[c[0].split("/")[-1]] = float(c[6])
        q["confirmed_ratio"] = ratios
        q["time_to_confirm_s"] = dict(pos)
        names = [n for n, _ in pos]
        bars = axs[0].barh(names, [ratios.get(n, 0) for n in names],
                           color=["#2ca02c" if ratios.get(n, 0) > 0 else "#d62728" for n in names])
        for b, (n, t) in zip(bars, pos):
            axs[0].text(b.get_width() + 0.01, b.get_y() + b.get_height() / 2,
                        f"{b.get_width():.2f}" + (f"  (확정 {t:.1f}s)" if t is not None else "  (확정 안 됨)"),
                        va="center", fontsize=8)
        axs[0].set_xlim(0, 1.3); axs[0].set_xlabel("양성 구간 중 확정된 프레임 비율")
        axs[0].set_title("v6 · P02 양성 영상별 확정 비율"); axs[0].invert_yaxis()
    if f:
        bins = ["<=2m", "2-3m", "3-4m", "4-5m", ">5m"]
        pb = f["per_bin"]
        R = [pb[b]["tp"] / max(1, pb[b]["tp"] + pb[b]["fn"]) for b in bins]
        P = [pb[b]["tp"] / max(1, pb[b]["tp"] + pb[b]["fp"]) for b in bins]
        n = [pb[b]["tp"] + pb[b]["fn"] for b in bins]
        q["frame_per_bin"] = {b: dict(P=p, R=r, n_pos=k) for b, p, r, k in zip(bins, P, R, n)}
        x = range(len(bins))
        axs[1].bar([i - 0.2 for i in x], P, 0.4, label="정밀도", color="#1f77b4")
        axs[1].bar([i + 0.2 for i in x], R, 0.4, label="재현율", color="#d62728")
        axs[1].set_xticks(list(x)); axs[1].set_xticklabels([f"{b}\n(양성 {k})" for b, k in zip(bins, n)])
        axs[1].set_ylim(0, 1.05); axs[1].legend(); axs[1].set_title("v6 · P02 사진, 프록시 거리 구간별")
    if lat:
        st = lat["stages_ms"]
        names = ["pose", "roi", "cig", "stab"]
        ko = {"pose": "포즈 모델", "roi": "ROI 계산", "cig": "담배 모델 (ROI 9개)", "stab": "안정화"}
        med = [st[k]["median"] for k in names]
        p95 = [st[k]["p95"] for k in names]
        q["latency_ms"] = {k: dict(median=a, p95=b) for k, a, b in zip(names, med, p95)}
        q["latency_total_ms"] = lat["total_ms"]
        axs[2].barh([ko[k] for k in names], med, color="#7f7f7f", label="중앙값")
        axs[2].barh([ko[k] for k in names], [b - a for a, b in zip(med, p95)], left=med, color="#c7c7c7",
                    label="p95까지")
        for i, (a, b) in enumerate(zip(med, p95)):
            axs[2].text(b + 0.3, i, f"{a:.1f} / {b:.1f} ms", va="center", fontsize=8)
        axs[2].invert_yaxis(); axs[2].set_xlabel("ms (Windows PC, ONNX Runtime 4 스레드, 사람 3명)")
        axs[2].set_title(f"v6 처리 시간: 합계 중앙값 {lat['total_ms']['median']:.1f} ms")
        axs[2].legend(fontsize=8)
    save(fig, "v6_quality.png")


# ---------------------------------------------------------------- final: P02 dev vs P03 hold-out (v6)
def fig_final(summary):
    """Reads ONLY the metrics.json that `eval_clips.py --final` already wrote (no model is run on hold-out here)."""
    runs = sorted((EV / "clips_holdout_p03_v6").glob("run_*/metrics.json"))
    dev = jload(EV / "clips_dev_p02_v6" / "metrics.json")
    if not runs or not dev:
        return
    ho = jload(runs[-1])
    if not ho.get("final"):
        return
    summary["final_v6"] = {"run": runs[-1].parent.name,
                           "p03": {k: ho["metrics"][k]["value"] for k in ACCEPT},
                           "p03_counts": {k: [ho["metrics"][k].get("num"), ho["metrics"][k].get("den")] for k in ACCEPT},
                           "p03_wilson": {k: ho["metrics"][k].get("wilson") for k in ACCEPT},
                           "p03_boot": {k: ho["metrics"][k].get("boot") for k in ACCEPT},
                           "p03_passed": {k: ho["metrics"][k].get("passed") for k in ACCEPT},
                           "p02": {k: dev["metrics"][k]["value"] for k in ACCEPT},
                           "verdict": ho["verdict"]}
    fig, axs = plt.subplots(2, 3, figsize=(15, 7.5))
    for a, k in zip(axs.flat, ACCEPT):
        vals = [dev["metrics"][k]["value"], ho["metrics"][k]["value"]]
        bars = a.bar(["P02 (dev)", "P03 (hold-out)"], vals, color=["#9ecae1", "#d62728"])
        a.axhline(ACCEPT[k], color="k", ls="--", lw=1, label=f"합격선 {ACCEPT[k]}")
        for b, x in zip(bars, vals):
            a.text(b.get_x() + b.get_width() / 2, x, f"{x:.2f}", ha="center", va="bottom", fontsize=9)
        ok = ho["metrics"][k].get("passed")
        a.set_title(METRIC_KO[k] + ("  (통과)" if ok else "  (미달)"), color="#2ca02c" if ok else "#d62728")
        if k not in ("lookalike_false_confirm_per_10min", "confirm_time_median_s"):
            a.set_ylim(0, 1.08)
        a.legend(fontsize=8)
    fig.suptitle("v6 최종 시험: P03 hold-out 영상 12개 (eval_clips.py --final, run #1) vs P02 dev")
    save(fig, "final_v6_p02_vs_p03.png")


def main():
    summary = {}
    fig_final(summary)
    fig_reference()
    fig_sweep(summary)
    fig_v6_quality(summary)
    fig_training(summary)
    fig_datasets(summary)
    fig_capture(summary)
    fig_clip_metrics(summary)
    fig_frame_confusion(summary)
    fig_common_val(summary)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT / "summary.json")


if __name__ == "__main__":
    main()
