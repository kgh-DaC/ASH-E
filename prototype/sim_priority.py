"""Priority simulator (spec A9): replays fake multi-person scenarios through ash_e_core.PrioritySelector. No camera, no ROS.

  python prototype/sim_priority.py                      # all scenarios, text summary
  python prototype/sim_priority.py --json               # machine readable
  python prototype/sim_priority.py --only s5_mixed --events --timeline
  python prototype/sim_priority.py --config prototype/config/priority.yaml --scenarios prototype/config/sim_scenarios.yaml
  python prototype/sim_priority.py --only target_departs --show    # OpenCV window (q to quit)

The scenario data (prototype/config/sim_scenarios.yaml) is separate from this code on purpose: the stage-B
fake_detections_pub (spec B7) reuses load_scenarios() / scenario_frames(). The S5 flicker count is eval_clips.flicker_count
(same definition as the clip evaluation: switches that follow another switch within 10 s). Reference only (spec N8):
a hold-out with one participant cannot measure S5 on real clips.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src" / "ash_e_core"))
from ash_e_core.config import PriorityConfig, load_priority_config  # noqa: E402
from ash_e_core.priority import PrioritySelector  # noqa: E402
from ash_e_core.types import (Detection, DetectionArray, DistanceSource, Point3, SmokerState, TargetEvent)  # noqa: E402
from eval_clips import flicker_count  # noqa: E402  (single S5 flicker definition)

DEFAULT_SCENARIOS = HERE / "config" / "sim_scenarios.yaml"
STATES = {"none": SmokerState.NONE, "holding": SmokerState.HOLDING, "smoking": SmokerState.SMOKING}
IMG_W, IMG_H = 640, 480


# ------------------------------------------------------------------ scenario data -> detections
def validate_scenarios(sc, src="scenarios") -> Dict[str, dict]:
    """Raise ValueError with a readable message for malformed scenario data."""
    if not isinstance(sc, dict) or not sc:
        raise ValueError("%s: no scenarios defined (expected a non-empty mapping under 'scenarios')" % src)
    for name, s in sc.items():
        if not isinstance(s, dict) or "duration_s" not in s:
            raise ValueError("scenario %r: needs duration_s" % name)
        if not isinstance(s.get("tracks"), list) or not s["tracks"]:
            raise ValueError("scenario %r: tracks must be a non-empty list" % name)
        for i, tr in enumerate(s["tracks"]):
            where = "scenario %r track #%d" % (name, i)
            if not isinstance(tr, dict):
                raise ValueError("%s: must be a mapping" % where)
            for k in ("id", "presence", "state", "distance"):
                if k not in tr:
                    raise ValueError("%s: missing field %r" % (where, k))
            if not isinstance(tr["state"], list) or not tr["state"]:
                raise ValueError("%s: state must be a list of [t, name]" % where)
            for _, v in tr["state"]:
                if str(v).lower() not in STATES:
                    raise ValueError("%s: unknown state %r (use %s)" % (where, v, "/".join(STATES)))
    return sc


def load_scenarios(path=DEFAULT_SCENARIOS) -> Dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return validate_scenarios(raw.get("scenarios", raw) if isinstance(raw, dict) else raw, str(path))


def _interp(kf, t: float) -> float:
    if isinstance(kf, (int, float)):
        return float(kf)
    if t <= kf[0][0]:
        return float(kf[0][1])
    for (t0, v0), (t1, v1) in zip(kf, kf[1:]):
        if t <= t1:
            return float(v0) + (float(v1) - float(v0)) * (t - t0) / (t1 - t0) if t1 > t0 else float(v1)
    return float(kf[-1][1])


def _step(kf, t: float):
    cur = kf[0][1]
    for tt, v in kf:
        if t >= tt:
            cur = v
    return cur


def _interval_start(presence, t: float) -> Optional[float]:
    for a, b in presence:
        if a <= t < b or (t == b and b == presence[-1][1]):
            return float(a)
    return None


def scenario_frames(sc: dict, frame_id: str = "sim") -> Iterator[DetectionArray]:
    """Yield one DetectionArray per frame (deterministic: seed in the scenario)."""
    rate = float(sc.get("rate_hz", 8.0))
    rng = random.Random(sc.get("seed", 0))
    nz = sc.get("noise") or {}
    ds, cs, bs = (float(nz.get("dist_sigma_m", 0)), float(nz.get("conf_sigma", 0)), float(nz.get("bearing_sigma_deg", 0)))
    n = int(round(float(sc["duration_s"]) * rate))
    for k in range(n + 1):
        t = round(k / rate, 6)
        dets: List[Detection] = []
        for tr in sc["tracks"]:
            start = _interval_start(tr["presence"], t)
            if start is None:
                continue
            dist = _interp(tr["distance"], t)
            w = tr.get("wobble")
            if w:
                dist += float(w["amp_m"]) * math.sin(2 * math.pi * t / float(w["period_s"]) + float(w.get("phase_rad", 0)))
            dist = max(0.3, dist + rng.gauss(0, ds))
            brg = math.radians(_interp(tr.get("bearing_deg", 0.0), t) + rng.gauss(0, bs))
            conf = min(1.0, max(0.0, _interp(tr.get("conf", 0.9), t) + rng.gauss(0, cs)))
            state = STATES[str(_step(tr["state"], t)).lower()]
            stay = (t - start) if tr.get("stationary", True) else 0.0
            half = math.tan(math.radians(35.0))  # hfov 70 deg
            bh = int(min(IMG_H, 0.9 * IMG_H / max(dist, 0.5) * 1.2))
            bw = bh // 3
            cx = IMG_W / 2 - math.tan(brg) / half * IMG_W / 2
            dets.append(Detection(
                track_id=int(tr["id"]), state=int(state), state_confidence=conf, raw_state=int(state), raw_confidence=conf,
                cigarette_checked=True, person_confidence=0.9, bbox_x=int(cx - bw / 2), bbox_y=int(IMG_H - bh - 10),
                bbox_w=bw, bbox_h=bh, position=Point3(-math.sin(brg) * dist, 0.0, math.cos(brg) * dist),
                distance_m=dist, distance_source=int(DistanceSource.PROXY), bearing_rad=brg, stationary_s=stay,
                frames_observed=k + 1))
        yield DetectionArray(stamp=t, frame_id=frame_id, frame_seq=k, image_width=IMG_W, image_height=IMG_H, detections=dets)


# ------------------------------------------------------------------ run + metrics
def run_scenario(name: str, sc: dict, cfg: Optional[PriorityConfig] = None, show: bool = False, speed: float = 1.0) -> dict:
    sel = PrioritySelector(cfg)
    series: List[Tuple[float, Optional[int]]] = []   # (t, target id or None) = eval_clips.target_ids format
    events: List[dict] = []
    for arr in scenario_frames(sc):
        st = sel.update(arr)
        series.append((arr.stamp, st.target_id if st.has_target else None))
        if st.last_event != TargetEvent.NONE:
            events.append(dict(t=arr.stamp, event=TargetEvent(st.last_event).name,
                               target_id=st.target_id if st.has_target else None, previous=st.previous_target_id))
        if show and not _show_frame(arr, st, name, speed, float(sc.get("rate_hz", 8.0))):
            show = False
    return summarize(name, sc, series, events)


def timeline(series) -> List[dict]:
    segs: List[dict] = []
    for t, v in series:
        if segs and segs[-1]["target_id"] == v:
            segs[-1]["t1"] = t
        else:
            segs.append(dict(t0=t, t1=t, target_id=v))
    return segs


def switch_times(series) -> List[float]:
    """Times the target changes id -> another id (a no-target gap in between does not hide it; same as flicker_count)."""
    out, prev = [], None
    for t, v in series:
        if v is not None:
            if prev is not None and v != prev:
                out.append(t)
            prev = v
    return out


def departure_delays(series, departures) -> List[dict]:
    out = []
    for d in departures or []:
        tid, t0 = int(d["track_id"]), float(d["t"])
        cur = None
        for t, v in series:
            if t <= t0:
                cur = v
        nxt = next(((t, v) for t, v in series if t > t0 and v is not None and v != tid), None)
        idle = next((t for t, v in series if t > t0 and v is None), None)
        out.append(dict(track_id=tid, t=t0, target_at_departure=cur,
                        next_target_t=nxt[0] if nxt else None, next_target_id=nxt[1] if nxt else None,
                        delay_s=round(nxt[0] - t0, 3) if nxt and cur == tid else None, idle_gap_start_t=idle))
    return out


def summarize(name, sc, series, events) -> dict:
    sw = switch_times(series)
    dt = 1.0 / float(sc.get("rate_hz", 8.0))
    return dict(
        scenario=name, description=sc.get("description", ""), duration_s=sc["duration_s"], n_frames=len(series),
        switches=len(sw), switch_times=sw, flicker_s5=flicker_count(series), n_events=len(events),
        event_counts={e: sum(1 for x in events if x["event"] == e) for e in sorted({x["event"] for x in events})},
        idle_s=round(min(sum(dt for _, v in series if v is None), float(sc["duration_s"])), 3),
        departures=departure_delays(series, sc.get("departures")), timeline=timeline(series), events=events,
        expect=sc.get("expect", ""))


# ------------------------------------------------------------------ output
def text_report(res: dict, show_events: bool, show_timeline: bool) -> str:
    L = ["== %s: %s" % (res["scenario"], res["description"]),
         "   %.0f s, %d frames | target switches %d | S5 flicker %d | events %s | idle %.2f s"
         % (res["duration_s"], res["n_frames"], res["switches"], res["flicker_s5"], res["event_counts"] or "{}", res["idle_s"])]
    for d in res["departures"]:
        L.append("   departure of #%d at %.1f s: target then #%s -> %s" % (
            d["track_id"], d["t"], d["target_at_departure"],
            "no next target" if d["delay_s"] is None else "switch to #%s after %.2f s" % (d["next_target_id"], d["delay_s"])))
    if show_timeline:
        L.append("   timeline: " + "  ".join("[%.1f-%.1f s] %s" % (s["t0"], s["t1"], "#%d" % s["target_id"] if s["target_id"] else "-")
                                           for s in res["timeline"]))
    if show_events:
        for e in res["events"]:
            L.append("   t=%6.2f  %-18s target=%s prev=%s" % (e["t"], e["event"], e["target_id"], e["previous"]))
    return "\n".join(L)


def _show_frame(arr, st, name, speed, rate) -> bool:
    import cv2
    import numpy as np
    from ash_e_core.viz import draw_priority
    img = np.full((IMG_H, IMG_W, 3), 40, np.uint8)
    for d in arr.detections:
        col = {0: (150, 150, 150), 1: (0, 200, 255), 2: (0, 0, 255)}[d.state]
        cv2.rectangle(img, (d.bbox_x, d.bbox_y), (d.bbox_x + d.bbox_w, d.bbox_y + d.bbox_h), col, 2)
        cv2.putText(img, "#%d %.1fm" % (d.track_id, d.distance_m), (d.bbox_x, d.bbox_y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
    ev = TargetEvent(st.last_event).name if st.last_event else ""
    draw_priority(img, st, arr, ev)
    cv2.putText(img, "%s  t=%.1fs" % (name, arr.stamp), (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    cv2.imshow("sim_priority", img)
    return cv2.waitKey(max(1, int(1000 / rate / max(speed, 1e-3)))) & 0xFF != ord("q")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS), help="scenario yaml (default prototype/config/sim_scenarios.yaml)")
    ap.add_argument("--config", default=None, help="priority yaml (default: built-in PriorityConfig defaults)")
    ap.add_argument("--only", action="append", help="scenario name (repeatable)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--out", default=None, help="also write the JSON result here")
    ap.add_argument("--events", action="store_true", help="text mode: list every event")
    ap.add_argument("--timeline", action="store_true", help="text mode: list target-id timeline segments")
    ap.add_argument("--show", action="store_true", help="OpenCV window (needs a display); q quits")
    ap.add_argument("--speed", type=float, default=1.0, help="--show playback speed")
    a = ap.parse_args(argv)
    try:
        scs = load_scenarios(a.scenarios)
        cfg = load_priority_config(a.config)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print("sim_priority: error: %s" % e, file=sys.stderr)
        return 2
    names = a.only or list(scs)
    unknown = [n for n in names if n not in scs]
    if unknown:
        ap.error("unknown scenario(s): %s (have %s)" % (unknown, list(scs)))
    results = [run_scenario(n, scs[n], cfg, show=a.show, speed=a.speed) for n in names]
    if a.show:
        import cv2
        cv2.destroyAllWindows()
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.json:
        print(json.dumps(results, indent=1, ensure_ascii=False))
    else:
        print("\n".join(text_report(r, a.events, a.timeline) for r in results))
        print("(reference only: S5 flicker on real clips needs 2 same-group participants, spec N8)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
