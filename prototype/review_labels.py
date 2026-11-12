"""Human review of draft cigarette boxes (prelabel.py output) - small OpenCV tool, nothing leaves the PC.

  python prototype/review_labels.py --pid P01                 # resumes at the first unreviewed frame
  python prototype/review_labels.py --pid P01 --redo          # walk through everything again
  python prototype/review_labels.py --selftest                # no GUI: coordinate/save checks

Order = data/labeled/review_queue_<PID>.csv (missed-looking frames first, then lowest confidence).
The view is zoomed on the subject (pose model) so a cigarette at 4-5 m is big enough to box.

  mouse left-drag   draw a cigarette box          mouse right-click  delete the box under the cursor
  SPACE / ENTER     boxes are correct -> save, mark reviewed, next
  i                 cigarette < 30% visible -> mark IGNORE (frame left out of training, spec 9A.5), next
  n / b             next / back without marking   u  undo last drawn box     c  clear all boxes
  z                 zoom: subject / tighter / full frame                      q / ESC  save and quit
Decisions: data/labeled/review_state_<PID>.json (ok / ignore), ignore list: data/labeled/ignore.txt.
Labels are YOLO txt next to each image (class 0 = cigarette), written on every SPACE/ENTER.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))
from dataset_utils import bystanders_consented, own_subject, read_yolo, write_yolo  # noqa: E402

WIN = "ASH-E label review"
VIEW_W, VIEW_H = 1100, 760
ZOOMS = ("subject", "tight", "full")


class View:
    """Crop (x0, y0, x1, y1) in full-image px shown scaled to fit VIEW_W x VIEW_H."""

    def __init__(self, crop, img_w, img_h):
        x0, y0, x1, y1 = crop
        self.x0, self.y0 = max(0, int(x0)), max(0, int(y0))
        self.x1, self.y1 = min(img_w, int(x1)), min(img_h, int(y1))
        self.s = min(VIEW_W / (self.x1 - self.x0), VIEW_H / (self.y1 - self.y0))

    def to_view(self, x, y):
        return (x - self.x0) * self.s, (y - self.y0) * self.s

    def to_img(self, u, v):
        return u / self.s + self.x0, v / self.s + self.y0

    def render(self, img):
        c = img[self.y0:self.y1, self.x0:self.x1]
        return cv2.resize(c, (int(c.shape[1] * self.s), int(c.shape[0] * self.s)),
                          interpolation=cv2.INTER_CUBIC if self.s > 1 else cv2.INTER_AREA)


def subject_crop(person_box, W, H, mode):
    if mode == "full" or person_box is None:
        return (0, 0, W, H)
    x1, y1, x2, y2 = person_box
    pw, ph = x2 - x1, y2 - y1
    if mode == "tight":  # head + hands region: upper 65% of the person, small margin
        x1, x2, y2 = x1 - 0.1 * pw, x2 + 0.1 * pw, y1 + 0.65 * ph
        y1 -= 0.05 * ph
    else:
        x1, x2, y1, y2 = x1 - 0.3 * pw, x2 + 0.3 * pw, y1 - 0.08 * ph, y2 + 0.03 * ph
    # match the window aspect so nothing is wasted
    cx, cy, w, h = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
    ar = VIEW_W / VIEW_H
    w, h = (h * ar, h) if w / h < ar else (w, w / ar)
    w, h = max(w, 160), max(h, 160 / ar)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def load_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    path.write_text(json.dumps(state, indent=0, ensure_ascii=False), encoding="utf-8")


def set_ignore(ignore_txt: Path, img: Path, on: bool):
    lines = [x.strip() for x in ignore_txt.read_text(encoding="utf-8").splitlines()] if ignore_txt.is_file() else []
    key = img.resolve().as_posix()
    lines = [x for x in lines if x and x != key] + ([key] if on else [])
    ignore_txt.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def queue_images(pid):
    q = ROOT / "data/labeled" / ("review_queue_%s.csv" % pid)
    if not q.is_file():
        sys.exit("missing %s (run prototype/prelabel.py --src data/raw/%s first)" % (q, pid))
    with open(q, encoding="utf-8") as f:
        return [Path(r["image"]) for r in csv.DictReader(f)]


def review(pid, redo, pose):
    labeled = ROOT / "data/labeled"
    state_path, ignore_txt = labeled / ("review_state_%s.json" % pid), labeled / "ignore.txt"
    state = load_state(state_path)
    imgs = queue_images(pid)
    key_of = lambda p: p.resolve().relative_to(labeled.resolve()).as_posix()  # noqa: E731
    i = 0 if redo else next((k for k, p in enumerate(imgs) if key_of(p) not in state), len(imgs))
    if i >= len(imgs):
        print("all %d frames already reviewed (use --redo to go through them again)" % len(imgs))
        return
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    ui = {"drag": None, "cur": None, "boxes": [], "added": [], "view": None, "dirty": False}

    def on_mouse(ev, u, v, flags, _):
        vw = ui["view"]
        if vw is None:
            return
        if ev == cv2.EVENT_LBUTTONDOWN:
            ui["drag"], ui["cur"] = (u, v), (u, v)
        elif ev == cv2.EVENT_MOUSEMOVE and ui["drag"] is not None:
            ui["cur"] = (u, v)
        elif ev == cv2.EVENT_LBUTTONUP and ui["drag"] is not None:
            (a, b), (c, d) = ui["drag"], (u, v)
            ui["drag"] = None
            x1, y1 = vw.to_img(min(a, c), min(b, d))
            x2, y2 = vw.to_img(max(a, c), max(b, d))
            if x2 - x1 >= 2 and y2 - y1 >= 2:
                ui["boxes"].append(np.array([x1, y1, x2, y2], np.float32))
                ui["added"].append(len(ui["boxes"]) - 1)
                ui["dirty"] = True
        elif ev == cv2.EVENT_RBUTTONDOWN:
            x, y = vw.to_img(u, v)
            hits = [k for k, bb in enumerate(ui["boxes"]) if bb[0] - 3 <= x <= bb[2] + 3 and bb[1] - 3 <= y <= bb[3] + 3]
            if hits:
                k = min(hits, key=lambda k: (ui["boxes"][k][2] - ui["boxes"][k][0]) * (ui["boxes"][k][3] - ui["boxes"][k][1]))
                ui["boxes"].pop(k)
                ui["added"] = [a - (a > k) for a in ui["added"] if a != k]
                ui["dirty"] = True

    cv2.setMouseCallback(WIN, on_mouse)
    zoom, loaded = 0, -1
    img = person_box = None
    while 0 <= i < len(imgs):
        p = imgs[i]
        if loaded != i:
            img = cv2.imread(str(p))
            if img is None:
                print("cannot read", p)
                i += 1
                continue
            H, W = img.shape[:2]
            ps = own_subject(pose.detect(img), W, bystanders_consented(p)) if pose is not None else []
            person_box = ps[0].bbox_xyxy if ps else None
            ui.update(boxes=[b for c, b in read_yolo(p.with_suffix(".txt"), W, H) if c == 0], added=[], dirty=False)
            loaded = i
        ui["view"] = vw = View(subject_crop(person_box, W, H, ZOOMS[zoom]), W, H)
        canvas = vw.render(img).copy()
        for k, bb in enumerate(ui["boxes"]):
            (a, b), (c, d) = vw.to_view(bb[0], bb[1]), vw.to_view(bb[2], bb[3])
            cv2.rectangle(canvas, (int(a), int(b)), (int(c), int(d)), (0, 255, 255) if k in ui["added"] else (0, 220, 0), 2)
        if ui["drag"] is not None:
            cv2.rectangle(canvas, tuple(map(int, ui["drag"])), tuple(map(int, ui["cur"])), (255, 0, 255), 1)
        st = state.get(key_of(p), "-")
        hud = "%d/%d  %s  %s  boxes=%d  state=%s  zoom=%s%s" % (
            i + 1, len(imgs), p.parent.name, p.name, len(ui["boxes"]), st, ZOOMS[zoom], "  *edited*" if ui["dirty"] else "")
        help_ = "drag=box  rclick=del  SPACE=ok  i=ignore(<30%)  n/b=next/back  u=undo  c=clear  z=zoom  q=quit"
        bar = np.zeros((48, canvas.shape[1], 3), np.uint8)
        cv2.putText(bar, hud, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(bar, help_, (6, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)
        cv2.imshow(WIN, np.vstack([bar, canvas]))
        k = cv2.waitKeyEx(30)
        if k == -1:
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break
            continue
        ch = k & 0xFF
        if ch in (32, 13):  # SPACE / ENTER: accept
            write_yolo(p.with_suffix(".txt"), ui["boxes"], W, H)
            if st == "ignore":
                set_ignore(ignore_txt, p, False)
            state[key_of(p)] = "ok"
            save_state(state_path, state)
            i += 1
        elif ch == ord("i"):
            set_ignore(ignore_txt, p, True)
            state[key_of(p)] = "ignore"
            save_state(state_path, state)
            i += 1
        elif ch == ord("n"):
            i += 1
        elif ch == ord("b"):
            i = max(0, i - 1)
        elif ch == ord("u") and ui["added"]:
            ui["boxes"].pop(ui["added"].pop())
            ui["dirty"] = True
        elif ch == ord("c"):
            ui.update(boxes=[], added=[], dirty=True)
        elif ch == ord("z"):
            zoom = (zoom + 1) % len(ZOOMS)
        elif ch in (ord("q"), 27):
            break
    cv2.destroyAllWindows()
    n_ok = sum(1 for v in state.values() if v == "ok")
    n_ig = sum(1 for v in state.values() if v == "ignore")
    print("reviewed %d / %d (ok %d, ignore %d). state: %s" % (n_ok + n_ig, len(imgs), n_ok, n_ig, state_path))


def selftest():
    vw = View(subject_crop(np.array([500, 200, 700, 700], np.float32), 1280, 720, "tight"), 1280, 720)
    for x, y in ((550.0, 260.0), (690.5, 400.25)):
        u, v = vw.to_view(x, y)
        assert np.allclose(vw.to_img(u, v), (x, y), atol=1e-3)
    assert vw.s > 1.0, "tight view must magnify"
    full = View(subject_crop(None, 1280, 720, "subject"), 1280, 720)
    assert (full.x0, full.y0, full.x1, full.y1) == (0, 0, 1280, 720)
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "a.txt"
        box = np.array([600, 300, 640, 312], np.float32)
        write_yolo(t, [box], 1280, 720)
        back = read_yolo(t, 1280, 720)
        assert len(back) == 1 and np.allclose(back[0][1], box, atol=0.05)
        ig, im = Path(d) / "ignore.txt", Path(d) / "x.jpg"
        set_ignore(ig, im, True)
        set_ignore(ig, im, True)
        assert ig.read_text(encoding="utf-8").splitlines() == [im.resolve().as_posix()]
        set_ignore(ig, im, False)
        assert ig.read_text(encoding="utf-8") == ""
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", default="P01")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--no-pose", action="store_true", help="do not zoom on the subject (full frame only)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    pose = None
    if not a.no_pose:
        from ash_e_core.backends import load_model
        from ash_e_core.config import PerceptionConfig
        from ash_e_core.detector import PoseModel
        pose = PoseModel(load_model(str(ROOT / "models/pose.onnx"), "onnxruntime", 4), PerceptionConfig(person_conf_thresh=0.30))
        if pose.is_stub:
            pose = None
    review(a.pid, a.redo, pose)


if __name__ == "__main__":
    main()
