"""Equivalence comparison proto.jsonl vs ros.jsonl (spec 10.2 step 4). Pure python, no ROS.

  .venv\\Scripts\\python prototype\\compare_jsonl.py proto.jsonl ros.jsonl [--align stamp|seq] [--json out.json]

Frames are paired by stamp (default, robust to a dropped first frame) or by frame_seq (the spec's wording); both
ways report the frame_seq offset and the unmatched frames. Tolerances (spec 10.2):
  processed frames equal | person-count & track_id set equal >= 99% frames | bbox IoU (same track_id) mean >= 0.98
  | state equal >= 99% | raw_confidence |diff| mean <= 0.02 | target_id equal >= 98% frames, event sequence identical.
Exit code 0 = all pass, 1 = any fail. Target checks are skipped when a log has no target.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List

TOL = {"set_match_min": 0.99, "iou_mean_min": 0.98, "state_match_min": 0.99,
       "rawconf_mean_max": 0.02, "target_id_match_min": 0.98}


def load(path: str) -> List[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError as e:
                    raise SystemExit("%s line %d: bad JSON (%s)" % (path, i, e))
    return out


def iou(d1: dict, d2: dict) -> float:
    ax1, ay1, ax2, ay2 = d1["bbox_x"], d1["bbox_y"], d1["bbox_x"] + d1["bbox_w"], d1["bbox_y"] + d1["bbox_h"]
    bx1, by1, bx2, by2 = d2["bbox_x"], d2["bbox_y"], d2["bbox_x"] + d2["bbox_w"], d2["bbox_y"] + d2["bbox_h"]
    iw, ih = min(ax2, bx2) - max(ax1, bx1), min(ay2, by2) - max(ay1, by1)
    inter = max(0, iw) * max(0, ih)
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def events(recs: List[dict]) -> List[tuple]:
    ev = []
    for r in recs:
        t = r.get("target")
        if t and t.get("last_event"):
            ev.append((t["last_event"], t["target_id"]))
    return ev


def compare(a: List[dict], b: List[dict], align: str = "stamp", tol: dict = TOL) -> dict:
    key = (lambda r: round(r["stamp"], 3)) if align == "stamp" else (lambda r: r["frame_seq"])
    ia: Dict = {key(r): r for r in a}
    ib: Dict = {key(r): r for r in b}
    common = sorted(set(ia) & set(ib))
    res = {"n_proto": len(a), "n_ros": len(b), "n_paired": len(common), "only_proto": len(set(ia) - set(ib)),
           "only_ros": len(set(ib) - set(ia)), "align": align}
    res["frame_seq_offsets"] = sorted({ib[k]["frame_seq"] - ia[k]["frame_seq"] for k in common})[:5]
    n_set = n_cnt = n_state = n_state_tot = 0
    ious: List[float] = []
    dconf: List[float] = []
    tmatch = tcnt = 0
    has_target = bool(common) and all(ia[k].get("target") and ib[k].get("target") for k in common)
    for k in common:
        da, db = ia[k]["detections"]["detections"], ib[k]["detections"]["detections"]
        ma, mb = {d["track_id"]: d for d in da}, {d["track_id"]: d for d in db}
        n_cnt += len(da) == len(db)
        n_set += set(ma) == set(mb)
        for tid in set(ma) & set(mb):
            ious.append(iou(ma[tid], mb[tid]))
            n_state_tot += 1
            n_state += ma[tid]["state"] == mb[tid]["state"]
            dconf.append(abs(ma[tid]["raw_confidence"] - mb[tid]["raw_confidence"]))
        if has_target:
            tcnt += 1
            tmatch += ia[k]["target"]["target_id"] == ib[k]["target"]["target_id"]
    N = max(len(common), 1)
    res["person_count_match"] = n_cnt / N
    res["track_set_match"] = n_set / N
    res["iou_mean"] = sum(ious) / len(ious) if ious else None
    res["state_match"] = n_state / n_state_tot if n_state_tot else None
    res["rawconf_diff_mean"] = sum(dconf) / len(dconf) if dconf else None
    res["n_matched_tracks"] = n_state_tot
    res["target_id_match"] = tmatch / tcnt if has_target and tcnt else None
    if has_target:
        pa, pb = events([ia[k] for k in common]), events([ib[k] for k in common])
        res["events_proto"], res["events_ros"], res["events_identical"] = pa, pb, pa == pb
    chk = {
        "frames_equal": res["n_proto"] == res["n_ros"] and res["only_proto"] == 0 and res["only_ros"] == 0,
        "person_count_and_track_set": min(res["person_count_match"], res["track_set_match"]) >= tol["set_match_min"],
        "bbox_iou": res["iou_mean"] is None or res["iou_mean"] >= tol["iou_mean_min"],
        "state": res["state_match"] is None or res["state_match"] >= tol["state_match_min"],
        "raw_conf": res["rawconf_diff_mean"] is None or res["rawconf_diff_mean"] <= tol["rawconf_mean_max"],
    }
    if has_target:
        chk["target_id"] = res["target_id_match"] >= tol["target_id_match_min"]
        chk["events_identical"] = res["events_identical"]
    res["checks"] = chk
    res["pass"] = all(chk.values()) and bool(common)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proto")
    ap.add_argument("ros")
    ap.add_argument("--align", choices=("stamp", "seq"), default="stamp")
    ap.add_argument("--json", default=None, help="also write the result dict here")
    a = ap.parse_args(argv)
    res = compare(load(a.proto), load(a.ros), a.align)
    for k, v in res.items():
        if k != "checks":
            print("%-22s %s" % (k, round(v, 4) if isinstance(v, float) else v))
    print("--- checks (spec 10.2)")
    for k, v in res["checks"].items():
        print("%-28s %s" % (k, "PASS" if v else "FAIL"))
    print("RESULT:", "PASS" if res["pass"] else "FAIL")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
