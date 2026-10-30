"""Download a SUBSET of COCO val2017 (individual images, no big archive) as none / similar (hard negative) images.

No login/API key. Uses data/public/coco/annotations/instances_val2017.json (annotations: CC BY 4.0).
Images: Flickr originals with per-image licenses (field `license` in the json). We drop ND (3, 6) so that
copy-paste/cropping is allowed; the rest (BY, BY-SA, BY-NC*, no-known-restrictions, US-gov) is used
INTERNALLY for training only. Never redistribute, never publish; faces of third parties stay local.

  python training/fetch_coco_subset.py --n-none 1000 --n-similar 500
Outputs: data/public/coco/subset/{none,similar}/<id>.jpg + manifest.json (id, license, flickr_url, category, classes)
"""
from __future__ import annotations

import argparse
import json
import random
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COCO = ROOT / "data/public/coco"
BAD_LICENSES = {3, 6}  # BY-NC-ND, BY-ND
THIN = {"toothbrush": 90, "fork": 48, "knife": 49, "spoon": 50, "baseball bat": 39}
PHONE = {"cell phone": 77}
# a thin object counts as "near hand/mouth" if its box overlaps/touches a person box and is small relative to it
MIN_PERSON_H_FRAC = 0.30


def iou_touch(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy / max(1e-6, aw * ah)  # fraction of a inside b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-none", type=int, default=1000)
    ap.add_argument("--n-similar", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-mb", type=float, default=600, help="abort if the subset would exceed this")
    a = ap.parse_args()
    js = json.loads((COCO / "annotations/instances_val2017.json").read_text())
    cats = {c["id"]: c["name"] for c in js["categories"]}
    imgs = {i["id"]: i for i in js["images"]}
    by_img = {}
    for an in js["annotations"]:
        by_img.setdefault(an["image_id"], []).append(an)

    rng = random.Random(a.seed)
    none_c, sim_c = [], []
    for iid, anns in by_img.items():
        im = imgs[iid]
        if im["license"] in BAD_LICENSES:
            continue
        H = im["height"]
        persons = [x for x in anns if x["category_id"] == 1 and not x["iscrowd"] and x["bbox"][3] >= MIN_PERSON_H_FRAC * H]
        if not persons:
            continue
        sim = []
        for x in anns:
            n = cats[x["category_id"]]
            if n in THIN or n in PHONE:
                if any(iou_touch(x["bbox"], p["bbox"]) > 0.8 for p in persons):
                    sim.append(n)
        (sim_c if sim else none_c).append((iid, sorted(set(sim))))
    print("candidates none=%d similar=%d" % (len(none_c), len(sim_c)))
    rng.shuffle(none_c)
    rng.shuffle(sim_c)
    chosen = [(i, "none", c) for i, c in none_c[: a.n_none]] + [(i, "similar", c) for i, c in sim_c[: a.n_similar]]
    est = len(chosen) * 0.17
    print("chosen %d images, est %.0f MB" % (len(chosen), est))
    if est > a.max_mb:
        raise SystemExit("estimate over --max-mb")

    lic = {l["id"]: l["name"] for l in js["licenses"]}
    man = []

    def get(t):
        iid, cat, cl = t
        im = imgs[iid]
        d = COCO / "subset" / cat
        d.mkdir(parents=True, exist_ok=True)
        dst = d / ("coco_%012d.jpg" % iid)
        if not dst.is_file():
            urllib.request.urlretrieve(im["coco_url"], dst)
        return {"id": iid, "file": dst.relative_to(ROOT).as_posix(), "category": cat, "classes": cl,
                "license_id": im["license"], "license": lic[im["license"]], "flickr_url": im.get("flickr_url")}

    with ThreadPoolExecutor(8) as ex:
        man = list(ex.map(get, chosen))
    (COCO / "subset/manifest.json").write_text(json.dumps(man, indent=1))
    from collections import Counter
    print("downloaded", Counter(m["category"] for m in man), "licenses", Counter(m["license"] for m in man))
    print("similar classes", Counter(c for m in man for c in m["classes"]))


if __name__ == "__main__":
    main()
