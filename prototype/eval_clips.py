"""Clip-level evaluation (spec 9.2, 9.3-3/6/7/8, 9.4, 9.4.1): time-to-confirm, false confirmations per 10 min,
precision/recall on the STABILIZED state, smoking/holding accuracy, S5 target flicker. CPU only.

  python prototype/eval_clips.py                          # dev clips: data/eval/dev  (DEV, not a judgment)
  python prototype/eval_clips.py --clips-dir data/raw_clips   # any non-protected clip folder (see split checks)
  python prototype/eval_clips.py --final                  # HOLD-OUT: data/eval/holdout, hash-verified, logged

Input = a folder tree. A clip is either  <dir>/clip.mp4 + <dir>/labels.json  (run_webcam.py --record layout) or
<x>/clips/<id>.mp4 + <x>/labels/<id>.json  (spec 9.2). The evaluation ALWAYS replays clip.mp4 through the pipeline
(clip_io.replay_clip); the live events.jsonl is never used. Replay events go to _workspace/eval_out/clips_<tag>/replay/,
never next to the clip (hold-out folders are locked).

Protection (spec 9A.5; same scheme as eval_images.py):
  * acceptance/acceptance.yaml must match acceptance/acceptance.sha256 (every mode; missing sha file refuses --final).
  * hold-out clips (data/eval/holdout, or any clip whose participant is a hold-out participant) are refused without --final.
  * --final: acceptance/holdout_manifest.sha256 must verify; the hold-out clip folder's SHA-256 manifest
    (acceptance/holdout_clips_manifest.json) is written on the first --final run and must match exactly on every later
    run (changed, added or removed file -> refused). Every successful --final run appends to acceptance/holdout_runs.log.
  * participants of a clip must all belong to one group (train / dev / holdout); --final needs all holdout.
Thresholds come only from acceptance/acceptance.yaml.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "training"))
sys.path.insert(0, str(ROOT / "src" / "ash_e_core"))
import clip_io  # noqa: E402
from dataset_utils import is_under  # noqa: E402

LABELS = {"smoking": 2, "holding": 1, "none": 0}
POS = ("smoking", "holding")
CATS = {"cigarette", "similar_object", "gesture", "ecig_liquid", "ecig_heated", "plain"}
LOOKALIKE = ("similar_object", "gesture", "ecig_liquid")        # judged against lookalike_false_confirm_per_10min
BOOT_N = 2000
BOOT_SEED = 20261028
KEYS = ["rec_le3_n", "rec_le3_d", "rec_35_n", "rec_35_d", "prec_n", "prec_d", "sh_n", "sh_d",
        "lk_edges", "lk_sec", "plain_edges", "plain_sec", "heated_edges", "heated_sec", "occl_edges", "occl_sec", "pos_sec"]


def refuse(msg: str):
    sys.exit("REFUSED: " + msg)


# ------------------------------------------------------------------ paths
class Paths:
    """All protected locations in one object so tests can point it at a temp tree."""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.accept = self.root / "acceptance"
        self.holdout = self.root / "data/eval/holdout"
        self.dev = self.root / "data/eval/dev"
        self.splits = self.root / "data/splits/participants.json"
        self.out = self.root / "_workspace/eval_out"

    @property
    def clip_manifest(self):
        return self.accept / "holdout_clips_manifest.json"

    @property
    def runs_log(self):
        return self.accept / "holdout_runs.log"


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ guards
def check_acceptance(P: Paths, final: bool) -> dict:
    """acceptance.yaml vs acceptance.sha256. Returns the thresholds."""
    import yaml
    yml = P.accept / "acceptance.yaml"
    ah = P.accept / "acceptance.sha256"
    if ah.is_file():
        try:
            h, r = ah.read_text().strip().split("  ", 1)
        except ValueError:
            refuse("acceptance/acceptance.sha256 is malformed.")
        target = P.root / r
        if not target.is_file() or sha_file(target) != h:
            refuse("acceptance/acceptance.yaml does not match acceptance/acceptance.sha256 (modified?). No result produced.")
        print("acceptance.yaml hash: OK")
    elif final:
        refuse("acceptance/acceptance.sha256 is missing; --final needs the locked thresholds "
               "(python training/lock_acceptance.py --lock-thresholds).")
    else:
        print("WARNING: acceptance/acceptance.sha256 missing (run: python training/lock_acceptance.py --lock-thresholds)")
    if not yml.is_file():
        refuse("acceptance/acceptance.yaml is missing.")
    return yaml.safe_load(yml.read_text(encoding="utf-8")) or {}


def verify_global_manifest(P: Paths) -> None:
    """Same rule as lock_acceptance.verify(): every line '<sha256>  <relpath>' must match."""
    m = P.accept / "holdout_manifest.sha256"
    if not m.is_file():
        refuse("hold-out manifest missing (acceptance/holdout_manifest.sha256). No result produced.")
    bad = n = 0
    for line in m.read_text().splitlines():
        if not line.strip():
            continue
        h, r = line.split("  ", 1)
        n += 1
        p = P.root / r
        if not p.is_file() or sha_file(p) != h:
            print("MISMATCH:", r)
            bad += 1
    if bad:
        refuse("hold-out manifest mismatching (%d of %d files). No result produced." % (bad, n))
    print("holdout_manifest.sha256: verified %d files" % n)


def holdout_tree_hashes(P: Paths) -> Dict[str, str]:
    return {p.relative_to(P.holdout).as_posix(): sha_file(p) for p in sorted(P.holdout.rglob("*")) if p.is_file()}


def check_clip_manifest(P: Paths) -> str:
    """First --final run: record the SHA-256 of every file under data/eval/holdout. Later runs: must be identical."""
    cur = holdout_tree_hashes(P)
    if not cur:
        refuse("%s has no files." % P.holdout)
    mf = P.clip_manifest
    if not mf.is_file():
        mf.write_text(json.dumps({"created": datetime.now().isoformat(timespec="seconds"), "root": "data/eval/holdout",
                                  "files": cur}, indent=1, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(mf, 0o444)
        except OSError:
            pass
        print("hold-out clip manifest created (%d files): %s" % (len(cur), mf))
        return "created"
    try:
        old = json.loads(mf.read_text(encoding="utf-8"))["files"]
    except (ValueError, KeyError):
        refuse("%s is unreadable." % mf)
    changed = sorted(k for k in cur if k in old and cur[k] != old[k])
    added = sorted(k for k in cur if k not in old)
    removed = sorted(k for k in old if k not in cur)
    if changed or added or removed:
        refuse("hold-out clip folder differs from the manifest recorded at the first --final run "
               "(changed %d, added %d, removed %d; e.g. %s). No result produced."
               % (len(changed), len(added), len(removed), (changed + added + removed)[:3]))
    print("hold-out clip manifest: OK (%d files)" % len(cur))
    return "verified"


# ------------------------------------------------------------------ discovery, labels, split checks
class Item:
    def __init__(self, clip: Path, labels: Path):
        self.clip, self.labels = Path(clip), Path(labels)
        self.lab: dict = {}
        self.pids: List[str] = []

    def cid(self, base: Path) -> str:
        try:
            return self.clip.parent.relative_to(base).as_posix() if self.clip.name == "clip.mp4" \
                else self.clip.relative_to(base).with_suffix("").as_posix()
        except ValueError:
            return self.clip.parent.name


def discover(base: Path):
    """-> (items, skipped[(path, reason)]). Both layouts."""
    items, skipped = [], []
    for c in sorted(base.rglob("*.mp4")):
        if c.name == "clip.mp4":
            lp = c.with_name("labels.json")
        elif c.parent.name == "clips":
            lp = c.parent.parent / "labels" / (c.stem + ".json")
        else:
            continue
        if lp.is_file():
            items.append(Item(c, lp))
        else:
            skipped.append((str(c), "labels.json missing"))
    return items, skipped


def validate_labels(lab: dict) -> List[str]:
    """Problems that make a label file unusable (template not filled, bad numbers...)."""
    pr = []
    if not isinstance(lab, dict) or not isinstance(lab.get("persons"), list) or not lab["persons"]:
        return ["no persons"]
    parts = lab.get("participants") or ([lab["participant"]] if lab.get("participant") else [])
    nseg = 0
    for p in lab["persons"]:
        ref = p.get("person_ref", "?")
        an = p.get("anchor") or {}
        bb = an.get("bbox_xyxy")
        if not isinstance(an.get("t"), (int, float)) or not (isinstance(bb, list) and len(bb) == 4
                                                           and all(isinstance(v, (int, float)) for v in bb)):
            pr.append("%s: anchor.t / anchor.bbox_xyxy not filled" % ref)
        if len(parts) > 1 and not p.get("participant"):
            pr.append("%s: clip has several participants, persons[].participant is required" % ref)
        for sg in p.get("segments") or []:
            nseg += 1
            if not (isinstance(sg.get("t0"), (int, float)) and isinstance(sg.get("t1"), (int, float)) and sg["t1"] > sg["t0"]):
                pr.append("%s: segment needs numeric t0 < t1" % ref)
            if sg.get("label") not in LABELS:
                pr.append("%s: segment label must be smoking|holding|none (got %r)" % (ref, sg.get("label")))
            if sg.get("category") not in (None, "") and sg["category"] not in CATS:
                pr.append("%s: unknown category %r" % (ref, sg["category"]))
    if nseg == 0:
        pr.append("no segments (template not filled?)")
    return pr


def item_participants(it: Item) -> List[str]:
    out = set()
    lab = it.lab
    out.update(lab.get("participants") or [])
    if lab.get("participant"):
        out.add(lab["participant"])
    for p in lab.get("persons", []):
        if p.get("participant"):
            out.add(p["participant"])
    pid = clip_io._ids_from_path(it.clip)[0]
    if pid:
        out.add(pid)
    return sorted(out)


def participant_groups(P: Paths) -> Dict[str, str]:
    """pid -> 'train'|'dev'|'holdout'. Sources: data/splits/participants.json (holdout / val(=dev) / train) and the
    folders: any PID found under data/eval/holdout is holdout (wins), under data/eval/dev is dev."""
    g: Dict[str, str] = {}
    if P.splits.is_file():
        try:
            d = json.loads(P.splits.read_text(encoding="utf-8"))
        except ValueError:
            refuse("%s is unreadable; cannot tell which participants are hold-out." % P.splits)
        for name, grp in (("train", "train"), ("val", "dev"), ("holdout", "holdout")):
            for pid in d.get(name, []):
                g[pid] = grp
    def put(pid, grp):
        cur = g.get(pid)
        if cur is None:
            g[pid] = grp
        elif cur != grp:
            g[pid] = "conflict"                                # e.g. 'train' in participants.json but found in holdout/

    for base, grp in ((P.dev, "dev"), (P.holdout, "holdout")):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_dir() and re.fullmatch(r"P\d{2,3}", p.name):
                put(p.name, grp)
        for lp in list(base.rglob("labels.json")) + list(base.rglob("labels/*.json")):
            try:
                lab = json.loads(lp.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            for pid in (lab.get("participants") or []) + ([lab["participant"]] if lab.get("participant") else []):
                put(pid, grp)
    return g


def check_split(items: List[Item], groups: Dict[str, str], P: Paths, final: bool, allow_train=False, allow_unknown=False):
    """Cross-contamination rules. Returns notes (non-fatal warnings)."""
    notes = []
    for it in items:
        gs = {groups.get(p, "unknown") for p in item_participants(it)}
        where = it.clip.parent.as_posix()
        in_holdout_dir = is_under(it.clip, P.holdout)
        if "conflict" in gs:
            refuse("clip %s: participant %s has conflicting group info (participants.json vs folders). Fix the split first."
                   % (where, [p for p in item_participants(it) if groups.get(p) == "conflict"]))
        if final:
            if not in_holdout_dir:
                refuse("--final evaluates only clips under %s (found %s)." % (P.holdout, it.clip))
            if gs != {"holdout"}:
                refuse("clip %s has participants outside the hold-out group (groups: %s). Cross contamination; "
                       "remove it from data/eval/holdout." % (where, sorted(gs)))
            continue
        if in_holdout_dir or "holdout" in gs or str(it.lab.get("split", "")).lower() == "holdout":
            refuse("clip %s is hold-out data (path/participant/labels.split). Use --final (hash-verified, logged)." % where)
        if len(gs) > 1:
            refuse("clip %s mixes participant groups %s (spec 9A.5: not usable for any group)." % (where, sorted(gs)))
        if "train" in gs and not allow_train:
            refuse("clip %s belongs to a TRAINING participant; results would be optimistic. "
                   "Pass --allow-train to run it as a non-judgment check." % where)
        if "train" in gs:
            notes.append("%s: training participant (optimistic, not a generalization check)" % where)
        if "unknown" in gs:
            if not allow_unknown:
                refuse("clip %s: participant group unknown (no data/splits/participants.json and not under data/eval/dev). "
                       "Move it to data/eval/dev, run training/make_splits.py, or pass --allow-unknown-split "
                       "(never allowed for hold-out participants)." % where)
            notes.append("%s: participant group unknown (split not verified)" % where)
    return notes


# ------------------------------------------------------------------ statistics
def wilson(k: float, n: float, z: float = 1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def dbox(d):
    return [d["bbox_x"], d["bbox_y"], d["bbox_x"] + d["bbox_w"], d["bbox_y"] + d["bbox_h"]]


# ------------------------------------------------------------------ tracking labeled people through events
def track_persons(frames: List[dict], persons: List[dict]):
    """frames = processed frame records of replayed events. Spec 9.2: anchor IoU, then follow track_id; if the id is
    gone, re-match by IoU to the last box. One detection serves one person per frame.
    Returns ({ref: [obs]}, used_track_ids). obs = {t, state, found, dist, tid}."""
    obs = {p["person_ref"]: [] for p in persons}
    last = {p["person_ref"]: list(p["anchor"]["bbox_xyxy"]) for p in persons}
    tid = {p["person_ref"]: None for p in persons}
    lastd: Dict[str, Optional[float]] = {p["person_ref"]: None for p in persons}
    used_all = set()
    for f in frames:
        t = f["t"]
        taken = set()
        for p in persons:
            ref = p["person_ref"]
            if t < p["anchor"]["t"] - 1e-6:
                continue
            cands = [d for d in f.get("detections", []) if d["track_id"] not in taken]
            pick = next((d for d in cands if tid[ref] is not None and d["track_id"] == tid[ref]), None)
            if pick is None:
                sc = [(iou(last[ref], dbox(d)), d) for d in cands]
                sc = [s for s in sc if s[0] >= 0.2]
                pick = max(sc, key=lambda s: s[0])[1] if sc else None
            if pick is None:
                obs[ref].append(dict(t=t, state=0, found=False, dist=lastd[ref], tid=None))
                continue
            taken.add(pick["track_id"])
            used_all.add(pick["track_id"])
            tid[ref] = pick["track_id"]
            last[ref] = dbox(pick)
            dist = pick.get("distance_m")
            if dist is not None:
                lastd[ref] = float(dist)
            obs[ref].append(dict(t=t, state=int(pick["state"]), found=True, dist=lastd[ref], tid=pick["track_id"]))
    return obs, used_all


def clip_end(events: List[dict]) -> float:
    fr = [e for e in events if e.get("type") == "footer"]
    if fr and fr[-1].get("duration_s"):
        return float(fr[-1]["duration_s"])
    ts = [e["t"] for e in events if e.get("type") == "frame"]
    return max(ts) if ts else 0.0


# ------------------------------------------------------------------ per-clip evaluation
def eval_clip(cid: str, lab: dict, events: List[dict], pids: List[str]):
    """-> (units, fc_cases, miss_cases, seg_rows, info). Pure function of labels + replay events."""
    frames = sorted((e for e in events if e.get("type") == "frame" and e.get("processed")), key=lambda e: e["t"])
    hdr = next((e for e in events if e.get("type") == "header"), {})
    end = clip_end(events)
    persons = lab["persons"]
    obs, used = track_persons(frames, persons)
    scenario = lab.get("scenario") or hdr.get("scenario") or clip_io._ids_from_path(Path(cid))[2] or ""
    tags = {k: lab.get(k, "") for k in ("distance_tag", "lighting", "angle_tag")}
    units, fcs, misses, rows = [], [], [], []
    for p in persons:
        ref = p["person_ref"]
        part = p.get("participant") or (lab.get("participants") or pids or [None])[0]
        if not p.get("participant") and len(lab.get("participants") or []) > 1:
            part = None
        u = {k: 0.0 for k in KEYS}
        u.update(clip=cid, person=ref, participant=part, scenario=scenario, ttc=[])
        ob = sorted(obs[ref], key=lambda o: o["t"])
        segs = sorted(p["segments"], key=lambda s: s["t0"])
        for i, sg in enumerate(segs):
            t0, t1 = float(sg["t0"]), float(sg["t1"])
            label = sg["label"]
            pos = label in POS
            cat = sg.get("category") or ("cigarette" if pos else "plain")
            occl = bool(sg.get("occluded"))
            dur = max(0.0, min(t1, end) - t0)
            inside = [o for o in ob if t0 <= o["t"] < t1]
            adj = i > 0 and abs(segs[i - 1]["t1"] - t0) < 1e-3
            before = [o for o in ob if o["t"] < t0]
            prev_state = before[-1]["state"] if (adj and before) else 0
            prev_pos = adj and segs[i - 1]["label"] in POS
            row = dict(clip=cid, person=ref, participant=part, scenario=scenario, t0=t0, t1=t1, label=label, category=cat,
                       occluded=occl, n_frames=len(inside), **tags)
            if pos:
                u["pos_sec"] += dur
                conf = [o for o in inside if o["state"] != 0]
                for o in inside:
                    d = o["dist"]
                    if d is not None:
                        if d <= 3.0:
                            u["rec_le3_d"] += 1
                            u["rec_le3_n"] += o["state"] != 0
                        elif d <= 5.0:
                            u["rec_35_d"] += 1
                            u["rec_35_n"] += o["state"] != 0
                        if o["state"] != 0 and d <= 4.0:
                            u["prec_d"] += 1
                            u["prec_n"] += 1
                    if o["state"] != 0:
                        u["sh_d"] += 1
                        u["sh_n"] += o["state"] == LABELS[label]
                if conf:
                    ttc = conf[0]["t"] - t0
                    cont = prev_pos and prev_state != 0
                    row.update(confirmed=True, ttc=None if cont else round(ttc, 3), continuation=cont,
                               frac_confirmed=round(len(conf) / len(inside), 3))
                    if not cont:
                        u["ttc"].append(ttc)
                else:
                    reason = "no processed frames in segment" if not inside else (
                        "person never matched to a track" if not any(o["found"] for o in inside) else "tracked but never confirmed")
                    row.update(confirmed=False, ttc=None, frac_confirmed=0.0)
                    misses.append(dict(clip=cid, person=ref, participant=part, scenario=scenario, t0=t0, t1=t1, label=label,
                                       reason=reason, **tags))
            else:
                bucket = "occl" if occl else ("lk" if cat in LOOKALIKE else ("heated" if cat == "ecig_heated" else "plain"))
                u[bucket + "_sec"] += dur
                prev, edges = prev_state, 0
                for o in inside:
                    if o["state"] != 0 and prev == 0:
                        edges += 1
                        fcs.append(dict(clip=cid, person=ref, participant=part, scenario=scenario, t=round(o["t"], 3),
                                        label_seg="none/%s%s" % (cat, "/occluded" if occl else ""), state=o["state"],
                                        dist_m=None if o["dist"] is None else round(o["dist"], 2),
                                        counted_in=bucket, **tags))
                    prev = o["state"]
                    d = o["dist"]
                    if o["state"] != 0 and d is not None and d <= 4.0 and not occl:
                        u["prec_d"] += 1
                u[bucket + "_edges"] += edges
                row.update(false_confirms=edges, counted_in=bucket)
            rows.append(row)
        units.append(u)
    unl = set()
    for f in frames:
        for d in f.get("detections", []):
            if d["state"] != 0 and d["track_id"] not in used:
                unl.add(d["track_id"])
    info = dict(clip=cid, scenario=scenario, duration_s=round(end, 2), n_processed=len(frames),
                participants=pids, unlabeled_confirmed_tracks=sorted(unl), **tags)
    return units, fcs, misses, rows, info


# ------------------------------------------------------------------ S5 flicker
def target_ids(frames: List[dict]):
    ser, seen = [], False
    for f in frames:
        v = f.get("target_id")
        if v is None and isinstance(f.get("target"), dict):
            v = f["target"].get("track_id", f["target"].get("id"))
        seen = seen or ("target_id" in f or "target" in f)
        ser.append((f["t"], v))
    return ser if seen else None


def flicker_count(series, window_s: float = 10.0) -> int:
    """Number of target switches (id -> different id) that follow another switch within window_s (spec 9.3-6)."""
    sw, prev = [], None
    for t, v in series:
        if v is not None:
            if prev is not None and v != prev:
                sw.append(t)
            prev = v
    return sum(1 for a, b in zip(sw, sw[1:]) if b - a <= window_s)


# ------------------------------------------------------------------ aggregation
def agg(units: List[dict]) -> dict:
    a = {k: sum(u[k] for u in units) for k in KEYS}
    a["ttc"] = [x for u in units for x in u["ttc"]]
    return a


RATIO = {  # metric -> (num key, den key)
    "binary_precision_max4m": ("prec_n", "prec_d"),
    "binary_recall_max3m": ("rec_le3_n", "rec_le3_d"),
    "binary_recall_3to5m": ("rec_35_n", "rec_35_d"),
    "smoking_holding_accuracy": ("sh_n", "sh_d"),
}
DIRECTION = {"binary_precision_max4m": ">=", "binary_recall_max3m": ">=", "binary_recall_3to5m": ">=",
             "smoking_holding_accuracy": ">=", "lookalike_false_confirm_per_10min": "<=", "confirm_time_median_s": "<=",
             "priority_flicker_s5": "<="}
TITLES = {"binary_precision_max4m": "binary precision (state, <=4 m)", "binary_recall_max3m": "binary recall (state, <=3 m)",
          "binary_recall_3to5m": "binary recall (state, 3-5 m)", "smoking_holding_accuracy": "smoking/holding accuracy (true positives)",
          "lookalike_false_confirm_per_10min": "lookalike false confirmations per 10 min",
          "confirm_time_median_s": "time-to-confirm median [s]", "priority_flicker_s5": "S5 target flicker [count]"}


def metric_value(name: str, a: dict):
    if name in RATIO:
        n, d = RATIO[name]
        return a[n] / a[d] if a[d] else None
    if name == "lookalike_false_confirm_per_10min":
        return 600.0 * a["lk_edges"] / a["lk_sec"] if a["lk_sec"] else None
    if name == "confirm_time_median_s":
        return float(np.median(a["ttc"])) if a["ttc"] else None
    return None


def bootstrap(units: List[dict], name: str, n_boot: int = BOOT_N, seed: int = BOOT_SEED):
    """Clip-level bootstrap (resample whole clips). -> [lo, hi] or None when fewer than 2 clips."""
    by = {}
    for u in units:
        by.setdefault(u["clip"], []).append(u)
    clips = [agg(v) for v in by.values()]
    k = len(clips)
    if k < 2:
        return None
    rng = np.random.default_rng(seed)
    vals = []
    mat = np.array([[c[x] for x in KEYS] for c in clips], float)
    for _ in range(n_boot):
        idx = rng.integers(0, k, k)
        s = dict(zip(KEYS, mat[idx].sum(0)))
        s["ttc"] = [x for i in idx for x in clips[i]["ttc"]]
        v = metric_value(name, s)
        if v is not None:
            vals.append(v)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) >= 20 else None


def metric_block(name: str, units: List[dict]) -> dict:
    a = agg(units)
    v = metric_value(name, a)
    b = dict(value=v, wilson=None, boot=bootstrap(units, name) if v is not None else None)
    if name in RATIO:
        n, d = RATIO[name]
        b.update(num=a[n], den=a[d])
        b["wilson"] = wilson(a[n], a[d])
    elif name == "lookalike_false_confirm_per_10min":
        mins = a["lk_sec"] / 60.0
        b.update(num=a["lk_edges"], den=mins, exposure_min=mins)
        if a["lk_edges"] == 0 and mins > 0:
            b["rule_of_three_upper"] = 3.0 / (mins / 10.0)
    else:
        b.update(num=len(a["ttc"]), den=len(a["ttc"]))
    return b


def passes(v, thr, direction):
    if v is None or thr is None:
        return None
    return v >= thr if direction == ">=" else v <= thr


def judge(units: List[dict], flicker: dict, th: dict) -> dict:
    """Metric blocks + pass/fail vs thresholds from acceptance.yaml (never hard-coded) + 9.4.1 'uncertain' flags."""
    res, parts = {}, sorted({u["participant"] for u in units if u["participant"]})
    for name, direction in DIRECTION.items():
        thr = th.get(name)
        if name == "priority_flicker_s5":
            blk = dict(value=flicker.get("count"), num=flicker.get("n_clips"), den=flicker.get("n_clips"), wilson=None, boot=None)
        else:
            blk = metric_block(name, units)
        v = blk["value"]
        ok = passes(v, thr, direction)
        flags = []
        if ok is not None and name != "priority_flicker_s5":
            if direction == ">=":
                for lab_, ci in (("Wilson", blk["wilson"]), ("clip bootstrap", blk["boot"])):
                    if ci and thr is not None and ci[0] < thr:
                        flags.append("%s CI lower bound %.3f < threshold" % (lab_, ci[0]))
            else:
                hi = blk["boot"][1] if blk["boot"] else None
                if blk.get("rule_of_three_upper") is not None:
                    hi = blk["rule_of_three_upper"]
                if hi is not None and thr is not None and hi > thr:
                    flags.append("95%% upper bound %.2f > threshold" % hi)
            pp = {}
            for p in parts:
                pb = metric_value(name, agg([u for u in units if u["participant"] == p]))
                pp[p] = pb
                if pb is not None and passes(pb, thr, direction) is False:
                    flags.append("participant %s alone %.3f misses the threshold" % (p, pb))
            blk["per_participant"] = pp
        if name == "lookalike_false_confirm_per_10min" and blk.get("exposure_min", 0) < 10.0 and v is not None:
            flags.append("exposure %.1f min < 10 min: cannot really judge '<= %s per 10 min'" % (blk["exposure_min"], thr))
        blk.update(threshold=thr, direction=direction, passed=ok, uncertain=bool(flags), flags=flags)
        res[name] = blk
    return res


def verdict(res: dict, th: dict, final: bool, n_part: int, n_clips: int, pos_min: float) -> str:
    if not final:
        return "DEV result -- reference only, NOT a judgment (judgment = hold-out via --final)"
    miss = [n for n, b in res.items() if b["threshold"] is not None and b["passed"] is None and n != "priority_flicker_s5"]
    if miss:
        return "판정 불가 (데이터 없음: %s)" % ", ".join(miss)
    fail = [n for n, b in res.items() if b["passed"] is False]
    if fail:
        return "불합격 (미달: %s)" % ", ".join(fail)
    return "예비 합격 (holdout n=%d명, 클립 %d개, 양성 노출 %.1f분)" % (n_part, n_clips, pos_min)


# ------------------------------------------------------------------ full evaluation (pure; events supplied)
def evaluate(items: List[Item], events_by_clip: Dict[str, List[dict]], th: dict, base: Path, final: bool) -> dict:
    units, fcs, misses, rows, infos = [], [], [], [], []
    flick = dict(count=None, n_clips=0, reason="", per_clip=[])
    s5_series = []
    for it in items:
        cid = it.cid(base)
        ev = events_by_clip[cid]
        u, f, m, r, info = eval_clip(cid, it.lab, ev, item_participants(it))
        units += u
        fcs += f
        misses += m
        rows += r
        infos.append(info)
        if re.match(r"s5", (info["scenario"] or "").lower()):
            parts = {x for x in item_participants(it)}
            fr = [e for e in ev if e.get("type") == "frame" and e.get("processed")]
            ser = target_ids(fr)
            if ser is None:
                flick["reason"] = "events carry no target (priority output) -> not measured"
            elif len(parts) < 2:
                flick["reason"] = "S5 clip with only %d participant -> not measured (spec 9A.5/N7)" % len(parts)
            else:
                c = flicker_count(ser)
                s5_series.append(c)
                flick["per_clip"].append((cid, c))
    if s5_series:
        flick.update(count=sum(s5_series), n_clips=len(s5_series))
    elif not flick["reason"]:
        flick["reason"] = "no S5 clip in this set -> not measured"
    res = judge(units, flick, th)
    parts = sorted({p for i in infos for p in i["participants"]})
    a = agg(units)
    return dict(final=final, n_clips=len(items), participants=parts, units=len(units), pos_exposure_min=a["pos_sec"] / 60.0,
                lookalike_exposure_min=a["lk_sec"] / 60.0, metrics=res, flicker=flick, false_confirms=fcs, misses=misses,
                segments=rows, clips=infos,
                other_buckets=dict(plain=dict(edges=a["plain_edges"], min=a["plain_sec"] / 60.0),
                                   ecig_heated=dict(edges=a["heated_edges"], min=a["heated_sec"] / 60.0, note="reported only, not judged (S12)"),
                                   occluded_none=dict(edges=a["occl_edges"], min=a["occl_sec"] / 60.0, note="reported separately (9.2)")),
                participant_table={p: {n: metric_value(n, agg([u for u in units if u["participant"] == p]))
                                       for n in DIRECTION if n != "priority_flicker_s5"} for p in sorted({u["participant"] for u in units if u["participant"]})},
                verdict=verdict(res, th, final, len(parts), len(items), a["pos_sec"] / 60.0))


# ------------------------------------------------------------------ report
def f3(v):
    return "n/a" if v is None else "%.3f" % v


def ci_txt(ci):
    return "n/a" if not ci else "[%.3f, %.3f]" % tuple(ci)


def make_report(r: dict, meta: dict, dev: Optional[dict] = None) -> str:
    L = ["# eval_clips report %s (%s)" % (meta["when"], "FINAL hold-out" if r["final"] else "DEV"), ""]
    L.append("**판정: %s**" % r["verdict"])
    L.append("")
    L.append("조건: 참가자 %s, 클립 %d개, 양성 노출 %.1f분, 유사물 음성 노출 %.1f분. 웹캠 단계 A(프록시 거리), 이 참가자들·이 장소·이 카메라에서만 측정한 값이며 "
             "일반 사용자에 대한 성능을 뜻하지 않는다 (9.4.1)." % (", ".join(r["participants"]) or "?", r["n_clips"],
                                                              r["pos_exposure_min"], r["lookalike_exposure_min"]))
    L.append("models: %s | config process_rate_hz=%s | replay of clip.mp4 (live events not used)" % (meta.get("models", "?"), meta.get("rate", "?")))
    if r["final"]:
        L.append("holdout 실행 횟수: **%s** (이 값을 결과와 함께 보고. 여러 번 보고 고른 결과가 아님을 보이기 위함)" % meta.get("run_no", "?"))
        L.append("hold-out clip manifest: %s" % meta.get("manifest", "?"))
    L.append("")
    L.append("## 합격선 대비 (임계값은 acceptance/acceptance.yaml 에서 읽음)")
    L.append("| 지표 | 합격선 | 측정(점추정) | 분자/분모 | 95% Wilson (프레임, 낙관적) | 95% 클립 부트스트랩 | 결과 | 불확실 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for n, b in r["metrics"].items():
        thr = "%s %s" % (b["direction"], b["threshold"]) if b["threshold"] is not None else "기준 없음"
        nd = "" if b.get("num") is None else ("%g / %.1f분" % (b["num"], b["den"]) if n.startswith("lookalike") else "%g / %g" % (b["num"], b["den"]))
        if n == "priority_flicker_s5" and b["value"] is None:
            res_ = "미측정"
        else:
            res_ = {True: "통과", False: "미달", None: "데이터 없음"}[b["passed"]]
        unc = "불확실: " + "; ".join(b["flags"]) if b["uncertain"] else ""
        boot = ci_txt(b["boot"])
        if b.get("rule_of_three_upper") is not None:
            boot += " (0건 관측: rule of three 상한 %.2f)" % b["rule_of_three_upper"]
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (TITLES[n], thr, f3(b["value"]), nd, ci_txt(b["wilson"]), boot, res_, unc))
    L.append("")
    L.append("- RPi5 처리율(rpi5_rate_hz_min)은 이 스크립트 범위 밖(별도 bench 측정).")
    L.append("- S5 떨림: %s" % (("%d회 (S5 클립 %d개)" % (r["flicker"]["count"], r["flicker"]["n_clips"])) if r["flicker"]["count"] is not None
                              else r["flicker"]["reason"]))
    L.append("- 클립 수가 적어 부트스트랩 구간은 매우 넓거나(2클립 미만이면 n/a) 불안정할 수 있고, 프레임 Wilson 구간은 프레임 간 상관 때문에 좁게 나온다.")
    ob = r["other_buckets"]
    L.append("- 판정 제외 집계: plain none 오확정 %g회/%.1f분, ecig_heated(S12) %g회/%.1f분 (별도 보고만), occluded none %g회/%.1f분 (별도 집계)." % (
        ob["plain"]["edges"], ob["plain"]["min"], ob["ecig_heated"]["edges"], ob["ecig_heated"]["min"], ob["occluded_none"]["edges"], ob["occluded_none"]["min"]))
    L.append("- 노출 시간은 라벨된 사람-구간의 길이 합(여러 명이면 사람 수만큼 누적).")
    L.append("")
    if dev:
        L.append("## dev 대비")
        diffs = []
        for n in RATIO:
            dv, hv = dev["metrics"].get(n, {}).get("value"), r["metrics"][n]["value"]
            if dv is not None and hv is not None and abs(dv - hv) > 0.10:
                diffs.append("%s: dev %.3f vs holdout %.3f" % (TITLES[n], dv, hv))
        L.append("- dev-holdout 차이 0.10 초과(과적합 가능성): %s" % ("; ".join(diffs) if diffs else "없음"))
        L.append("")
    L.append("## 참가자별 값")
    names = [n for n in DIRECTION if n != "priority_flicker_s5"]
    L.append("| 참가자 | " + " | ".join(names) + " |")
    L.append("| --- |" + " --- |" * len(names))
    for p, d in r["participant_table"].items():
        L.append("| %s | %s |" % (p, " | ".join(f3(d[n]) for n in names)))
    if any(u is None for u in [None]) and not r["participant_table"]:
        L.append("| (참가자 미지정) | |")
    L.append("")
    L.append("## 오확정 전수 목록 (none 구간에서 양성 확정, %d건)" % len(r["false_confirms"]))
    L.append("| clip | person | participant | t[s] | 구간 | 시나리오 | state | 거리[m,proxy] | 거리태그 | 조명 | 집계 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in r["false_confirms"]:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (c["clip"], c["person"], c["participant"], c["t"], c["label_seg"],
                                                                         c["scenario"], c["state"], c["dist_m"], c["distance_tag"], c["lighting"], c["counted_in"]))
    L.append("")
    L.append("## 누락 전수 목록 (양성 구간인데 확정 없음, %d건)" % len(r["misses"]))
    L.append("| clip | person | participant | t0-t1[s] | label | 시나리오 | 사유 | 거리태그 | 조명 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in r["misses"]:
        L.append("| %s | %s | %s | %.1f-%.1f | %s | %s | %s | %s | %s |" % (c["clip"], c["person"], c["participant"], c["t0"], c["t1"], c["label"],
                                                                         c["scenario"], c["reason"], c["distance_tag"], c["lighting"]))
    L.append("")
    L.append("## 클립별")
    L.append("| clip | 시나리오 | 길이[s] | 처리 프레임 | 라벨 없는 확정 트랙(가능한 오확정) |")
    L.append("| --- | --- | --- | --- | --- |")
    for c in r["clips"]:
        L.append("| %s | %s | %s | %d | %s |" % (c["clip"], c["scenario"], c["duration_s"], c["n_processed"], c["unlabeled_confirmed_tracks"] or "-"))
    L.append("")
    L.append("## 양성 구간별 확정 시간")
    L.append("| clip | person | t0-t1 | label | confirmed | time-to-confirm[s] | 확정 프레임 비율 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- |")
    for s in r["segments"]:
        if s["label"] in POS:
            L.append("| %s | %s | %.1f-%.1f | %s | %s | %s | %s |" % (s["clip"], s["person"], s["t0"], s["t1"], s["label"], s["confirmed"],
                                                                 s["ttc"] if s["ttc"] is not None else ("(이어짐)" if s.get("continuation") else "-"), s["frac_confirmed"]))
    if meta.get("notes"):
        L.append("")
        L.append("## 주의")
        L += ["- " + n for n in meta["notes"]]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ replay
def replay_events(item: Item, cid: str, pipe, outdir: Path, rate: float, throttle: bool) -> List[dict]:
    out = outdir / "replay" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", cid) + ".events.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    clip_io.replay_clip(item.clip, pipe, out=out, rate_hz=rate, throttle=throttle)
    return clip_io.load_events(out)


def make_pipe(args):
    from ash_e_core.backends import load_model
    from ash_e_core.config import load_perception_config
    from ash_e_core.pipeline import PerceptionPipeline
    cfg = load_perception_config(args.config)
    pose = load_model(args.pose, "onnxruntime", cfg.num_threads)
    cig = load_model(args.cig_model, "onnxruntime", cfg.num_threads)
    return cfg, PerceptionPipeline(cfg, pose_model=pose, cig_model=cig), getattr(pose, "is_stub", False), getattr(cig, "is_stub", False)


# ------------------------------------------------------------------ main
def main(argv=None, P: Optional[Paths] = None, make_pipe_fn=None, replay_fn=None):
    P = P or Paths()
    try:
        sys.stdout.reconfigure(errors="replace")               # Korean text on a legacy Windows console codepage
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips-dir", default=None, help="folder tree with clips (default data/eval/dev)")
    ap.add_argument("--final", action="store_true", help="HOLD-OUT evaluation (hash-verified, logged)")
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--cig-model", default=str(ROOT / "models/cig_roi.onnx"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--rate", type=float, default=None, help="process rate Hz for replay (default cfg.process_rate_hz)")
    ap.add_argument("--no-throttle", action="store_true")
    ap.add_argument("--tag", default=None, help="output sub folder suffix (default dev|holdout)")
    ap.add_argument("--allow-train", action="store_true", help="allow clips of TRAINING participants (non-judgment check)")
    ap.add_argument("--allow-unknown-split", action="store_true", help="allow participants whose group is unknown (never for hold-out)")
    a = ap.parse_args(argv)

    # 1. hash guards (before anything else is read)
    th = check_acceptance(P, a.final)
    if a.final:
        if a.clips_dir and not is_under(Path(a.clips_dir), P.holdout):
            refuse("--final evaluates data/eval/holdout only; --clips-dir %s is outside." % a.clips_dir)
        verify_global_manifest(P)
        base = P.holdout
    else:
        base = Path(a.clips_dir) if a.clips_dir else P.dev
        if is_under(base, P.holdout) or is_under(P.holdout, base):
            refuse("%s is or contains hold-out data. Use --final (hash-verified, logged)." % base)
        if is_under(base, P.accept):
            refuse("acceptance/ is protected.")
    if not base.is_dir():
        print("평가 데이터 없음, 촬영 필요: %s 가 없습니다." % base)
        return None

    # 2. discover + validate labels + split checks (read only)
    items, skipped = discover(base)
    good = []
    for it in items:
        try:
            it.lab = json.loads(it.labels.read_text(encoding="utf-8"))
            pr = validate_labels(it.lab)
        except (ValueError, OSError) as e:
            pr = ["labels unreadable: %s" % e]
        if pr:
            skipped.append((str(it.clip), "labels not usable: " + "; ".join(pr[:3])))
        else:
            it.pids = item_participants(it)
            good.append(it)
    if a.final and skipped:
        refuse("hold-out clips without usable labels (all-or-nothing in --final, no cherry-picking): %s" % skipped[:3])
    if not good:
        print("평가 데이터 없음: %s 에서 labels.json 이 채워진 clip.mp4 를 찾지 못했습니다 (건너뜀 %d개)." % (base, len(skipped)))
        for s in skipped[:10]:
            print("  -", s)
        return None
    notes = check_split(good, participant_groups(P), P, a.final, a.allow_train, a.allow_unknown_split)

    # 3. clip-folder manifest (first --final run records, later runs must match)
    manifest = None
    run_no = None
    if a.final:
        manifest = check_clip_manifest(P)
        run_no = 1 + (len([x for x in P.runs_log.read_text(encoding="utf-8").splitlines() if x.strip()]) if P.runs_log.is_file() else 0)

    # 4. models + replay
    cfg = pipe = None
    cig_name = Path(a.cig_model).name
    if make_pipe_fn is None:
        cfg, pipe, pose_stub, cig_stub = make_pipe(a)
        if pose_stub:
            sys.exit("pose model missing: %s" % a.pose)
        if cig_stub:
            if a.final:
                refuse("cigarette model is a stub (%s); a hold-out run would be meaningless and still counts. Train/export first." % a.cig_model)
            notes.append("cigarette model missing -> every person predicted none (results meaningless)")
    else:
        cfg, pipe = make_pipe_fn(a)
    rate = a.rate or getattr(cfg, "process_rate_hz", 8.0)
    tag = a.tag or ("holdout" if a.final else "dev")
    outdir = P.out / ("clips_" + tag)
    outdir.mkdir(parents=True, exist_ok=True)
    events = {}
    for k, it in enumerate(good):
        cid = it.cid(base)
        print("[%d/%d] replay %s" % (k + 1, len(good), cid))
        events[cid] = (replay_fn or replay_events)(it, cid, pipe, outdir, rate, not a.no_throttle)

    # 5. metrics + report
    r = evaluate(good, events, th, base, a.final)
    dev = None
    dj = P.out / "clips_dev" / "metrics.json"
    if a.final and dj.is_file():
        try:
            dev = json.loads(dj.read_text(encoding="utf-8"))
        except ValueError:
            dev = None
    meta = dict(when=datetime.now().isoformat(timespec="seconds"), models="pose=%s cig=%s" % (Path(a.pose).name, cig_name), rate=rate,
                run_no=run_no, manifest=manifest, notes=notes + ["skipped: %s (%s)" % s for s in skipped])
    r["meta"] = meta
    if a.final:
        outdir = outdir / ("run_%03d" % run_no)       # never overwrite an earlier hold-out result
        outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "metrics.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    text = make_report(r, meta, dev)
    (outdir / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print("report + metrics.json -> %s" % outdir)
    if a.final:
        with open(P.runs_log, "a", encoding="utf-8") as f:
            f.write("%s run#%d eval_clips cig=%s clips=%d clip_manifest=%s\n" % (
                datetime.now().isoformat(timespec="seconds"), run_no, cig_name, len(good), manifest))
        print("hold-out run #%d logged to %s (report this count with the result)" % (run_no, P.runs_log))
    return r


if __name__ == "__main__":
    main()
