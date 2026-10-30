"""Copy-paste augmentation: paste CigDet cigarettes near the mouth / wrist of people from COCO 'none' images.

TRAINING ONLY. Output goes to data/synth/{images,labels}/synth_*.jpg|txt (never mixed with real data, never used for
evaluation/dev/holdout). Sources: cigarette crops from CigDet *train* images only (CC BY 4.0), person images from
the COCO subset *train* split (internal use only). Faces of third parties stay local.

  python training/synth_copy_paste.py --n 300 --real-pos 1297 --max-ratio 0.25
`--max-ratio` caps synth count at ratio * --real-pos (real positive samples available), so synthetic data stays a
minority of the positives.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT, coco_split, list_images, read_yolo, write_yolo  # noqa: E402

from ash_e_core.backends import load_model  # noqa: E402
from ash_e_core.config import PerceptionConfig  # noqa: E402
from ash_e_core.detector import PoseModel  # noqa: E402
from ash_e_core.roi import person_anchors  # noqa: E402


def cig_sprite(img, box):
    """Returns (rgb crop, alpha 0..1, long-axis angle deg) or None. GrabCut mask with elliptical fallback."""
    H, W = img.shape[:2]
    pad = 2
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), min(W, x2 + pad), min(H, y2 + pad)
    crop = img[y1:y2, x1:x2].copy()
    h, w = crop.shape[:2]
    if w < 8 or h < 8:
        return None
    mask = np.zeros((h, w), np.uint8)
    try:
        rect = (1, 1, w - 2, h - 2)
        bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
        cv2.grabCut(crop, mask, rect, bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
        fg = ((mask == 1) | (mask == 3)).astype(np.uint8)
    except cv2.error:
        fg = np.zeros((h, w), np.uint8)
    frac = fg.mean()
    if not (0.12 < frac < 0.85):
        fg = np.zeros((h, w), np.uint8)
        cv2.ellipse(fg, (w // 2, h // 2), (max(1, w // 2 - 1), max(1, h // 2 - 1)), 0, 0, 360, 1, -1)
    ys, xs = np.nonzero(fg)
    if len(xs) < 20:
        return None
    pts = np.stack([xs, ys], 1).astype(np.float32)
    pts -= pts.mean(0)
    vals, vecs = np.linalg.eigh(np.cov(pts.T))
    if math.sqrt(max(vals[1], 1e-6) / max(vals[0], 1e-6)) < 2.5:  # not elongated -> not a clean cigarette sprite
        return None
    ang = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))  # principal axis angle
    alpha = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 1.0)
    return crop, np.clip(alpha, 0, 1), ang


def paste(dst, sprite, center, long_side, target_angle, rng):
    crop, alpha, cur = sprite
    h, w = crop.shape[:2]
    cur_long = max(w, h) * 1.0
    # rotate so that the principal axis becomes target_angle, scale so the long side becomes long_side
    scale = long_side / max(8.0, cur_long)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), cur - target_angle, scale)
    nw, nh = int(abs(M[0, 0]) * w + abs(M[0, 1]) * h) + 4, int(abs(M[1, 0]) * w + abs(M[1, 1]) * h) + 4
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    rc = cv2.warpAffine(crop, M, (nw, nh), flags=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
    ra = cv2.warpAffine(alpha, M, (nw, nh), flags=cv2.INTER_LINEAR)
    H, W = dst.shape[:2]
    x0, y0 = int(center[0] - nw / 2), int(center[1] - nh / 2)
    sx1, sy1 = max(0, -x0), max(0, -y0)
    sx2, sy2 = min(nw, W - x0), min(nh, H - y0)
    if sx2 - sx1 < 4 or sy2 - sy1 < 4:
        return None
    a = ra[sy1:sy2, sx1:sx2]
    ys, xs = np.nonzero(a > 0.35)
    if len(xs) < 10:
        return None
    patch = rc[sy1:sy2, sx1:sx2].astype(np.float32)
    reg = dst[y0 + sy1:y0 + sy2, x0 + sx1:x0 + sx2].astype(np.float32)
    # light color matching: shift sprite mean/std toward the local surroundings (half strength)
    m = a > 0.35
    for c in range(3):
        pm, ps = patch[..., c][m].mean(), patch[..., c][m].std() + 1e-3
        rm, rs = reg[..., c].mean(), reg[..., c].std() + 1e-3
        patch[..., c] = np.clip((patch[..., c] - pm) * (0.5 + 0.5 * min(2.0, rs / ps)) + 0.5 * pm + 0.5 * rm, 0, 255)
    out = dst.copy()
    out[y0 + sy1:y0 + sy2, x0 + sx1:x0 + sx2] = (a[..., None] * patch + (1 - a[..., None]) * reg).astype(np.uint8)
    box = (x0 + sx1 + xs.min(), y0 + sy1 + ys.min(), x0 + sx1 + xs.max() + 1, y0 + sy1 + ys.max() + 1)
    return out, box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="target number of synthetic images")
    ap.add_argument("--real-pos", type=int, required=True, help="number of real positive samples (for the ratio cap)")
    ap.add_argument("--max-ratio", type=float, default=0.25, help="synth <= ratio * real-pos")
    ap.add_argument("--out", default=str(ROOT / "data/synth"))
    ap.add_argument("--pose", default=str(ROOT / "models/pose.onnx"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--montage", default=str(ROOT / "_workspace/eval_out/synth_montage.jpg"))
    a = ap.parse_args()

    n = min(a.n, int(a.max_ratio * a.real_pos))
    print("synth target n=%d (cap %.2f * %d)" % (n, a.max_ratio, a.real_pos))
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)

    # sprites: CigDet TRAIN only
    base = ROOT / "data/public/cigdet/raw/CigDet_dataset/train"
    sprites = []
    for p in list_images(base):
        img = cv2.imread(str(p))
        if img is None:
            continue
        for c, b in read_yolo(p.with_suffix(".txt"), img.shape[1], img.shape[0]):
            if c == 0:
                s = cig_sprite(img, b)
                if s is not None:
                    sprites.append(s)
    print("sprites", len(sprites))

    man = json.loads((ROOT / "data/public/coco/subset/manifest.json").read_text())
    persons_src = [ROOT / m["file"] for m in man if m["category"] == "none" and coco_split(m["id"]) == "train"]
    rng.shuffle(persons_src)
    cfg = PerceptionConfig(person_conf_thresh=0.4, min_person_h_px=100, kp_conf_thresh=0.5)
    pose = PoseModel(load_model(a.pose, "onnxruntime", 4), cfg)
    if pose.is_stub:
        raise SystemExit("pose model missing")

    made, meta, tiles = 0, [], []
    for sp in persons_src:
        if made >= n:
            break
        img = cv2.imread(str(sp))
        if img is None:
            continue
        H, W = img.shape[:2]
        ps = [p for p in pose.detect(img)]
        rng.shuffle(ps)
        for p in ps[:1]:
            mouth, hands, h = person_anchors(p, cfg)
            if h < 18:
                continue
            kpc = p.keypoints[:, 2]
            frontal = kpc[1] >= 0.5 and kpc[2] >= 0.5 and kpc[0] >= 0.5  # nose + both eyes
            opts = ([("mouth", mouth)] if mouth and frontal else []) + [("hand", hp) for hp in hands]
            if not opts:
                continue
            kind, pt = opts[int(rng.integers(len(opts)))]
            L = float(rng.uniform(0.35, 0.75)) * h
            if L < 14:
                continue
            spr = sprites[int(rng.integers(len(sprites)))]
            if kind == "mouth":
                side = rng.choice([-1, 1])
                ang = (0 if side > 0 else 180) + rng.uniform(-35, 35)
                c = (pt[0] + math.cos(math.radians(ang)) * L * 0.5, pt[1] + math.sin(math.radians(ang)) * L * 0.5)
            else:
                ang, c = rng.uniform(0, 180), pt
            r = paste(img, spr, c, L, ang, rng)
            if r is None:
                continue
            res, box = r
            if max(box[2] - box[0], box[3] - box[1]) > 1.5 * L:
                continue
            name = "synth_%s_%d" % (sp.stem, made)
            cv2.imwrite(str(out / "images" / (name + ".jpg")), res, [cv2.IMWRITE_JPEG_QUALITY, 92])
            write_yolo(out / "labels" / (name + ".txt"), [box], W, H)
            meta.append({"name": name, "src": sp.name, "kind": kind, "box": [int(v) for v in box]})
            made += 1
            if len(tiles) < 24:
                x1, y1 = int(max(0, c[0] - 80)), int(max(0, c[1] - 80))
                t = res[y1:y1 + 160, x1:x1 + 160].copy()
                bx = [int(box[0] - x1), int(box[1] - y1), int(box[2] - x1), int(box[3] - y1)]
                cv2.rectangle(t, (bx[0], bx[1]), (bx[2], bx[3]), (0, 255, 0), 1)
                tiles.append(cv2.resize(t, (200, 200)))
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    if tiles:
        while len(tiles) % 6:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]
        Path(a.montage).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(a.montage, np.vstack(rows))
    print("synth images", made, "->", out)


if __name__ == "__main__":
    main()
