"""Fill the labels.json of recorded clips from the clip convention (README 5-2): one person, one action per clip.

  python prototype/fill_clip_labels.py                       # fill every unfilled clip under data/raw_clips (draft)
  python prototype/fill_clip_labels.py --sheets              # + one check image per clip in data/label_check/
  python prototype/fill_clip_labels.py --review --pid P02    # play each clip with its label; SPACE = correct, x = wrong

What is written (a DRAFT until a person confirms it; "reviewed": false):
  * one segment [0, clip end) with the label implied by the scenario name (table SCENARIOS below);
  * anchor = first box of the person who is tracked for most of the clip in the live events.jsonl (pose model only;
    the cigarette model is not involved, so this is safe for hold-out clips too);
  * distance_tag from the clip number (mouth_001/002/003 = 1.5/3/4.5 m, holding_001/002 = 2/4 m), split from
    data/splits/participants.json.
Exceptions to "one action per clip" (e.g. side clips where the person turns their back, so the cigarette is hidden)
go into <root>/label_overrides.json:  {"P02/S1/side_001": [{"t0": 0, "t1": 15.0, "label": "smoking"},
{"t0": 15.0, "t1": null, "label": "none", "occluded": true}]}   (t1 null = clip end).
A labels.json that already has segments is never touched without --force. Nothing here reads model results on the
cigarette, and nothing is uploaded: clips and check images show faces and stay under data/ (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

# scenario -> (label, category).  Spec 9.2: smoking = cigarette at the mouth, holding = cigarette in the hand.
# mouth/walking/side clips are labeled smoking for the whole clip (the smoker lowers the hand between puffs; the
# pipeline's smoking latch is built for exactly that), so the smoking-vs-holding accuracy on them is approximate.
SCENARIOS = {
    "mouth": ("smoking", "cigarette"),
    "walking": ("smoking", "cigarette"),
    "side": ("smoking", "cigarette"),
    "holding": ("holding", "cigarette"),
    "none": ("none", "plain"),
    "similar": ("none", "similar_object"),
    "gesture": ("none", "gesture"),
    "ecig_liquid": ("none", "ecig_liquid"),
    "ecig_heated": ("none", "ecig_heated"),
}
DISTANCE = {("mouth", 1): "1.5m", ("mouth", 2): "3m", ("mouth", 3): "4.5m", ("holding", 1): "2m", ("holding", 2): "4m"}
VALID_LABELS = ("smoking", "holding", "none")


def load_jsonl(p: Path) -> List[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def clip_ids(d: Path) -> Optional[Tuple[str, str, str, int]]:
    """(pid, session, scenario, number) from .../<PID>/<SESSION>/<scenario>_<NNN>/ , else None."""
    m = re.fullmatch(r"([a-z0-9_]+)_(\d{3})", d.name)
    if not m or not re.fullmatch(r"S\d{1,2}", d.parent.name) or not re.fullmatch(r"P\d{2,3}", d.parent.parent.name):
        return None
    return d.parent.parent.name, d.parent.name, m.group(1), int(m.group(2))


def box_xyxy(det: dict) -> List[float]:
    return [round(float(v), 1) for v in (det["bbox_x"], det["bbox_y"], det["bbox_x"] + det["bbox_w"], det["bbox_y"] + det["bbox_h"])]


def main_track(events: List[dict]) -> Optional[dict]:
    """The person present for most of the clip: {tid, n, t, bbox_xyxy (first box), n_tracks}. None if nobody."""
    n: Dict[int, int] = defaultdict(int)
    first: Dict[int, Tuple[float, List[float]]] = {}
    for e in events:
        if e.get("type") != "frame" or not e.get("processed"):
            continue
        for det in e.get("detections", []):
            tid = det["track_id"]
            n[tid] += 1
            first.setdefault(tid, (float(e["t"]), box_xyxy(det)))
    if not n:
        return None
    tid = max(n, key=lambda k: (n[k], -k))
    return {"tid": tid, "n": n[tid], "t": first[tid][0], "bbox_xyxy": first[tid][1], "n_tracks": len(n),
            "others": sorted((k, v) for k, v in n.items() if k != tid)}


def duration(events: List[dict]) -> float:
    ft = [e for e in events if e.get("type") == "footer"]
    if ft and ft[-1].get("duration_s"):
        return float(ft[-1]["duration_s"])
    hdr = next((e for e in events if e.get("type") == "header"), {})
    fr = [e for e in events if e.get("type") == "frame"]
    return (len(fr) / float(hdr["fps"])) if fr and hdr.get("fps") else 0.0


def build_segments(scenario: str, end: float, override: Optional[List[dict]]) -> List[dict]:
    """Whole-clip segment from SCENARIOS, or the override list (t1 None = clip end, category defaults per label)."""
    if override is None:
        label, cat = SCENARIOS[scenario]
        return [{"t0": 0.0, "t1": round(end, 4), "label": label, "category": cat}]
    segs = []
    for o in override:
        label = o["label"]
        if label not in VALID_LABELS:
            raise ValueError("override label must be one of %s (got %r)" % (VALID_LABELS, label))
        t1 = end if o.get("t1") is None else min(float(o["t1"]), end)
        sg = {"t0": float(o["t0"]), "t1": round(t1, 4), "label": label,
              "category": o.get("category") or ("cigarette" if label != "none" or o.get("occluded") else SCENARIOS[scenario][1])}
        if o.get("occluded"):
            sg["occluded"] = True
        if not sg["t1"] > sg["t0"]:
            raise ValueError("override segment needs t0 < t1 (got %s)" % o)
        segs.append(sg)
    return segs


def fill_one(d: Path, groups: Dict[str, str], override: Optional[List[dict]], force: bool) -> Tuple[str, str]:
    """-> (status, message). status in filled|kept|skipped."""
    ids = clip_ids(d)
    if ids is None:
        return "skipped", "folder name is not <scenario>_<NNN> under <PID>/<SESSION>"
    pid, session, scenario, num = ids
    if scenario not in SCENARIOS:
        return "skipped", "unknown scenario %r (known: %s)" % (scenario, ", ".join(sorted(SCENARIOS)))
    lp, ep = d / "labels.json", d / "events.jsonl"
    if not ep.is_file():
        return "skipped", "events.jsonl missing (needed for the person box)"
    lab = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else {}
    had = any(p.get("segments") for p in lab.get("persons", []))
    if had and not force:
        return "kept", "already filled (reviewed=%s)" % lab.get("reviewed")
    events = load_jsonl(ep)
    mt = main_track(events)
    if mt is None:
        return "skipped", "no person detected in the clip"
    end = duration(events)
    hdr = next((e for e in events if e.get("type") == "header"), {})
    lab.pop("segment_example", None)
    lab.update({
        "_comment": "Draft from prototype/fill_clip_labels.py (scenario name + clip number). Times are seconds on the "
                    "clip.mp4 timeline. A person must confirm it (reviewed: true) before it is used for a judgment.",
        "schema": 1, "clip": "clip.mp4", "fps": hdr.get("fps", lab.get("fps")), "camera": lab.get("camera") or "webcam",
        "participants": [pid], "participant": pid, "session": session, "scenario": scenario,
        "split": {"dev": "dev", "holdout": "holdout", "train": "train"}.get(groups.get(pid, ""), ""),
        "distance_tag": lab.get("distance_tag") or DISTANCE.get((scenario, num), ""),
        "auto_filled": True, "reviewed": False,
        "persons": [{"person_ref": "p1", "segments": build_segments(scenario, end, override),
                     "anchor": {"t": mt["t"], "bbox_xyxy": mt["bbox_xyxy"]}}],
    })
    for k in ("lighting", "angle_tag", "notes"):
        lab.setdefault(k, "")
    lp.write_text(json.dumps(lab, indent=2, ensure_ascii=False), encoding="utf-8")
    msg = "%s, %.1f s, anchor t=%.2f" % (" + ".join("%s%s" % (s["label"], "(occluded)" if s.get("occluded") else "")
                                                     for s in lab["persons"][0]["segments"]), end, mt["t"])
    if mt["others"]:
        msg += "  | OTHER PEOPLE tracked: %s" % ", ".join("id%d x%d" % o for o in mt["others"])
    return "filled", msg


def participant_groups(root: Path = ROOT) -> Dict[str, str]:
    p = root / "data/splits/participants.json"
    if not p.is_file():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {pid: grp for key, grp in (("train", "train"), ("val", "dev"), ("holdout", "holdout")) for pid in d.get(key, [])}


def clip_dirs(base: Path, pid: Optional[str]) -> List[Path]:
    out = sorted(p.parent for p in base.rglob("clip.mp4"))
    return [d for d in out if pid is None or (clip_ids(d) or ("",))[0] == pid]


# ------------------------------------------------------------------ check images / review (GUI, local only)
def _seg_at(lab: dict, t: float) -> str:
    for sg in lab["persons"][0]["segments"]:
        if sg["t0"] <= t < sg["t1"]:
            return "%s / %s%s" % (sg["label"], sg.get("category", ""), " / OCCLUDED" if sg.get("occluded") else "")
    return "(no label)"


def _draw(frame, lab: dict, t: float, extra: str = ""):
    import cv2
    an = lab["persons"][0]["anchor"]
    x1, y1, x2, y2 = [int(v) for v in an["bbox_xyxy"]]
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(frame, "labeled person (box at t=%.1f)" % an["t"], (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(frame, "t=%5.1fs  %s  %s" % (t, _seg_at(lab, t), extra), (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return frame


def write_sheet(d: Path, out_dir: Path, base: Path) -> Optional[Path]:
    import cv2
    import numpy as np
    lab = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    cap = cv2.VideoCapture(str(d / "clip.mp4"))
    n, fps = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), float(cap.get(cv2.CAP_PROP_FPS) or lab.get("fps") or 15.0)
    tiles = []
    for k in range(8):
        i = int(n * (k + 0.5) / 8)
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        tiles.append(cv2.resize(_draw(fr, lab, i / fps), (640, 360)))
    cap.release()
    if len(tiles) < 8:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (d.relative_to(base).as_posix().replace("/", "_") + ".jpg")
    cv2.imwrite(str(p), np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return p


def review(dirs: List[Path]) -> None:
    """Plays each clip (looping, 2x) with its label. SPACE/Enter = label is right, x = wrong, n = skip, q = quit."""
    import cv2
    for k, d in enumerate(dirs):
        lp = d / "labels.json"
        lab = json.loads(lp.read_text(encoding="utf-8"))
        if lab.get("reviewed") or not any(p.get("segments") for p in lab.get("persons", [])):
            continue
        cap = cv2.VideoCapture(str(d / "clip.mp4"))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 15.0)
        i, key = 0, -1
        name = "%s/%s  [%d/%d]  SPACE=ok x=wrong n=skip q=quit" % (d.parent.parent.name, d.name, k + 1, len(dirs))
        while True:
            ok, fr = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                i = 0
                continue
            cv2.imshow("label review (local)", _draw(fr, lab, i / fps, name))
            i += 1
            key = cv2.waitKey(max(1, int(500 / fps))) & 0xFF
            if key in (32, 13, ord("x"), ord("n"), ord("q")):
                break
        cap.release()
        if key in (32, 13):
            lab["reviewed"] = True
        elif key == ord("x"):
            lab["reviewed"] = False
            lab["notes"] = (lab.get("notes", "") + " FLAGGED: label wrong, needs fixing").strip()
        if key in (32, 13, ord("x")):
            lp.write_text(json.dumps(lab, indent=2, ensure_ascii=False), encoding="utf-8")
        if key == ord("q"):
            break
    cv2.destroyAllWindows()


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips-dir", default=str(ROOT / "data/raw_clips"))
    ap.add_argument("--pid", default=None, help="only this participant, e.g. P02")
    ap.add_argument("--force", action="store_true", help="re-draft clips that are already filled (drops reviewed)")
    ap.add_argument("--sheets", action="store_true", help="write a check image per clip to data/label_check/")
    ap.add_argument("--review", action="store_true", help="play unreviewed clips and confirm the labels (GUI)")
    ap.add_argument("--mark-reviewed", action="store_true",
                    help="set reviewed=true on the filled clips of --pid (after a person confirmed the check images)")
    a = ap.parse_args(argv)
    base = Path(a.clips_dir)
    if not base.is_dir():
        sys.exit("no such folder: %s" % base)
    dirs = clip_dirs(base, a.pid)
    if not dirs:
        sys.exit("no clip.mp4 under %s" % base)
    ov_path = base / "label_overrides.json"
    overrides = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.is_file() else {}
    groups = participant_groups()
    count: Dict[str, int] = defaultdict(int)
    for d in dirs:
        cid = d.relative_to(base).as_posix()
        st, msg = fill_one(d, groups, overrides.get(cid), a.force)
        count[st] += 1
        print("%-8s %-28s %s" % (st, cid, msg))
    print("filled %d, kept %d, skipped %d" % (count["filled"], count["kept"], count["skipped"]))
    filled = [d for d in dirs if (d / "labels.json").is_file()
              and any(p.get("segments") for p in json.loads((d / "labels.json").read_text(encoding="utf-8")).get("persons", []))]
    if a.sheets:
        out = ROOT / "data/label_check"
        for d in filled:
            write_sheet(d, out, base)
        print("check images -> %s" % out)
    if a.review:
        review(filled)
    if a.mark_reviewed:
        if not a.pid:
            sys.exit("--mark-reviewed needs --pid")
        for d in filled:
            lp = d / "labels.json"
            lab = json.loads(lp.read_text(encoding="utf-8"))
            if "FLAGGED" not in lab.get("notes", ""):
                lab["reviewed"] = True
                lp.write_text(json.dumps(lab, indent=2, ensure_ascii=False), encoding="utf-8")
        print("marked reviewed: %s" % a.pid)


if __name__ == "__main__":
    main()
