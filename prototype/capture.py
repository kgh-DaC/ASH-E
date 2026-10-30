"""Self-capture tool: save laptop-webcam frames per scenario for training/evaluation (spec 9A.3).

Only for consenting adult participants, UNLIT props only. Everything stays local under data/raw/.

  python prototype/capture.py --participant P01 --session S1 --consent-confirmed
Keys: 1-7 pick scenario | SPACE start/stop auto capture | s save one frame | d cycle distance tag |
      c cycle camera angle tag | q quit
Headless smoke test:  --no-gui --scenario none --seconds 3 --consent-confirmed

Layout: data/raw/<PID>/<SESSION>/<scenario>/<PID>_<SESSION>_<scenario>_<NNNNN>.jpg
        data/raw/<PID>/<SESSION>/meta.jsonl   (one line per frame: participant, scenario, category, tags...)
The participant ID is in every path/file name so splits can be done per person (make_splits.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]

# key -> (scenario id, category, on-screen instruction, expected label)
SCENARIOS = {
    "1": ("holding", "cigarette", "HOLD an unlit cigarette in hand (chest height / hand down). Vary left/right hand.", "holding"),
    "2": ("mouth", "cigarette", "Put the unlit cigarette to/in the MOUTH, then lower it. Repeat. Vary hand.", "smoking"),
    "3": ("none", "plain", "NO cigarette in view. Stand/sit normally, hands visible, some moving.", "none"),
    "4": ("similar", "similar_object", "Pen / straw / chopstick / lollipop / lip balm: in hand AND at mouth.", "none"),
    "5": ("gesture", "gesture", "NO cigarette: phone call, drink, cover mouth, chin on hand, bite finger, yawn.", "none"),
    "6": ("ecig_liquid", "ecig_liquid", "Liquid e-cig (pod/mod), POWERED OFF: in hand and at mouth. Skip if you have none.", "none"),
    "7": ("ecig_heated", "ecig_heated", "Heated-tobacco device with stick (OFF/unlit). Skip if you have none.", "none"),
}
DISTANCES = ["unk", "1m", "2m", "3m", "4m", "5m"]
ANGLES = ["front", "left45", "right45", "side", "back"]


def count_existing(sess_dir: Path):
    return {sid: len(list((sess_dir / sid).glob("*.jpg"))) if (sess_dir / sid).is_dir() else 0
            for sid, *_ in SCENARIOS.values()}


def open_camera(idx: int, w: int, h: int):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    return cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participant", required=True, help="e.g. P01 (ID only, never a name)")
    ap.add_argument("--session", default="S1")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=float, default=2.0, help="auto-capture rate")
    ap.add_argument("--out", default=str(ROOT / "data/raw"))
    ap.add_argument("--consent-confirmed", action="store_true",
                    help="I confirm this adult participant gave written consent (spec 9A.3).")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--scenario", default="none", help="(no-gui) scenario id")
    ap.add_argument("--seconds", type=float, default=3.0, help="(no-gui) duration")
    a = ap.parse_args()

    if not re.fullmatch(r"P\d{2,3}", a.participant):
        sys.exit("participant must look like P01 (an ID, not a name)")
    if not a.consent_confirmed:
        sys.exit("Refusing to record: pass --consent-confirmed after getting the participant's written consent.")

    sess = Path(a.out) / a.participant / a.session
    sess.mkdir(parents=True, exist_ok=True)
    meta_f = open(sess / "meta.jsonl", "a", encoding="utf-8")
    counts = count_existing(sess)
    cap = open_camera(a.camera, a.width, a.height)
    if not cap.isOpened():
        sys.exit("cannot open camera %d" % a.camera)

    state = {"key": "3" if a.no_gui else "1", "rec": a.no_gui, "dist": 0, "ang": 0}
    if a.no_gui:
        for k, v in SCENARIOS.items():
            if v[0] == a.scenario:
                state["key"] = k

    def save(frame):
        sid, cat, _, label = SCENARIOS[state["key"]]
        d = sess / sid
        d.mkdir(exist_ok=True)
        counts[sid] += 1
        name = "%s_%s_%s_%05d.jpg" % (a.participant, a.session, sid, counts[sid])
        cv2.imwrite(str(d / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        meta_f.write(json.dumps({"file": "%s/%s" % (sid, name), "participant": a.participant, "session": a.session,
                                 "scenario": sid, "category": cat, "expected_label": label,
                                 "distance_tag": DISTANCES[state["dist"]], "angle_tag": ANGLES[state["ang"]],
                                 "width": frame.shape[1], "height": frame.shape[0], "camera": "webcam",
                                 "ts": datetime.now().isoformat(timespec="milliseconds")}) + "\n")
        meta_f.flush()

    last_save, t_start, saved = 0.0, time.time(), 0
    print("recording to", sess)
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        now = time.time()
        if state["rec"] and now - last_save >= 1.0 / a.fps:
            save(frame)
            last_save, saved = now, saved + 1
        if a.no_gui:
            if now - t_start >= a.seconds:
                break
            continue
        disp = frame.copy()
        sid, cat, text, label = SCENARIOS[state["key"]]
        cv2.rectangle(disp, (0, 0), (disp.shape[1], 70), (0, 0, 0), -1)
        cv2.putText(disp, "[%s] %s -> label:%s   dist:%s angle:%s   %s" % (
            state["key"], sid, label, DISTANCES[state["dist"]], ANGLES[state["ang"]], "REC" if state["rec"] else "paused"),
            (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255) if state["rec"] else (255, 255, 255), 2)
        cv2.putText(disp, text[:110], (8, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 255, 200), 1)
        y = disp.shape[0] - 10 - 18 * len(SCENARIOS)
        for k, (s, *_r) in SCENARIOS.items():
            cv2.putText(disp, "%s %-12s %5d" % (k, s, counts[s]), (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 255, 255) if k == state["key"] else (200, 200, 200), 1)
            y += 18
        cv2.putText(disp, "SPACE rec | s one frame | d dist | c angle | 1-7 scenario | q quit | UNLIT props only",
                    (8, disp.shape[0] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.imshow("ASH-E capture (local only)", disp)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        elif chr(k) in SCENARIOS:
            state["key"] = chr(k)
        elif k == ord(" "):
            state["rec"] = not state["rec"]
        elif k == ord("s"):
            save(frame)
            saved += 1
        elif k == ord("d"):
            state["dist"] = (state["dist"] + 1) % len(DISTANCES)
        elif k == ord("c"):
            state["ang"] = (state["ang"] + 1) % len(ANGLES)
    cap.release()
    meta_f.close()
    cv2.destroyAllWindows()
    print("saved %d frames; counts: %s" % (saved, counts))


if __name__ == "__main__":
    main()
