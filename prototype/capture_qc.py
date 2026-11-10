"""Capture quality statistics for data/raw/<PID> (statistics only; never used for training/tuning).

  python prototype/capture_qc.py --participants P01,P02,P03 --out _workspace/capture_qc.json

Per participant: counts by scenario x distance tag x angle tag (vs spec 9A.3 tables A/B), resolution,
blur (variance of Laplacian), dark/bright frames, near-duplicate rate (pHash) and pose detection
(share of frames with exactly one person). Pose/pHash are only measured, nothing is written back,
no image leaves the machine, no labels are produced.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import hamming, phash  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402

BLUR_THR = 30.0     # Laplacian variance (grayscale, 640 px wide) below this = "blurry" (heuristic)
DARK_THR = 50.0     # mean gray below = too dark
BRIGHT_THR = 200.0  # mean gray above = too bright
DUP_NEIGHBOR = 4    # pHash hamming <= 4 vs previous frame in sequence
DUP_ANY = 2         # pHash hamming <= 2 vs ANY earlier frame of the same scenario


def analyse(pid: str, pose: PoseModel):
    root = ROOT / "data/raw" / pid
    meta = {}
    for mf in root.rglob("meta.jsonl"):
        for line in mf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = json.loads(line)
                meta[(mf.parent.name + "/" + m["file"]).replace("\\", "/")] = m
    out = {"scenarios": {}, "resolution": Counter()}
    for sc_dir in sorted(p for s in root.iterdir() if s.is_dir() for p in s.iterdir() if p.is_dir()):
        sess, sc = sc_dir.parent.name, sc_dir.name
        files = sorted(sc_dir.glob("*.jpg"))
        lap, means, persons, hashes = [], [], [], []
        dup_nb = dup_any = 0
        dist, ang, n_nometa = Counter(), Counter(), 0
        for i, f in enumerate(files):
            img = cv2.imread(str(f))
            if img is None:
                continue
            h, w = img.shape[:2]
            out["resolution"]["%dx%d" % (w, h)] += 1
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gs = cv2.resize(g, (640, int(640 * h / w)))
            lap.append(float(cv2.Laplacian(gs, cv2.CV_64F).var()))
            means.append(float(g.mean()))
            ph = phash(img)
            if hashes and hamming(ph, hashes[-1]) <= DUP_NEIGHBOR:
                dup_nb += 1
            if any(hamming(ph, o) <= DUP_ANY for o in hashes):
                dup_any += 1
            hashes.append(ph)
            persons.append(len(pose.detect(img)))
            m = meta.get("%s/%s/%s" % (sess, sc, f.name))
            if m is None:
                n_nometa += 1
            else:
                dist[m.get("distance_tag", "unk")] += 1
                ang[m.get("angle_tag", "unk")] += 1
        n = len(lap)
        lap_a, mean_a, per_a = np.array(lap), np.array(means), np.array(persons)
        out["scenarios"][sc] = {
            "n": n, "dist": dict(dist), "angle": dict(ang), "no_meta": n_nometa,
            "blur_median": float(np.median(lap_a)), "blur_p10": float(np.percentile(lap_a, 10)),
            "blur_frac": float((lap_a < BLUR_THR).mean()),
            "dark_frac": float((mean_a < DARK_THR).mean()), "bright_frac": float((mean_a > BRIGHT_THR).mean()),
            "bright_median": float(np.median(mean_a)),
            "dup_neighbor_frac": dup_nb / n, "dup_any_frac": dup_any / n,
            "pose_one": float((per_a == 1).mean()), "pose_zero": float((per_a == 0).mean()),
            "pose_multi": float((per_a >= 2).mean()),
        }
        print(pid, sc, n, flush=True)
    out["resolution"] = dict(out["resolution"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participants", default="P01,P02,P03")
    ap.add_argument("--out", default=str(ROOT / "_workspace/capture_qc.json"))
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    cfg = PerceptionConfig(person_conf_thresh=0.30)
    pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", a.threads), cfg)
    if pose.is_stub:
        sys.exit("pose model missing")
    res = {pid: analyse(pid, pose) for pid in a.participants.split(",")}
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
