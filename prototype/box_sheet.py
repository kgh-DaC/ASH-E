"""Contact sheet of where the cigarette box lands in an eval_clips replay (diagnosis, 2026-11-18).

  python prototype/box_sheet.py <eval_out dir> <clips S1 dir> <out dir> clip [clip ...]
  e.g. python prototype/box_sheet.py _workspace/eval_out/clips_dev_p02_v6 data/raw_clips/P02/S1 _workspace/eval_out/box_v6 mouth_002 mouth_003 holding_002

Up to 8 frames per clip (confirmed ones first), cropped to the person, red = cigarette box.
"""
import json, sys
from pathlib import Path
import cv2, numpy as np

ev_dir, clips_root, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
for clip in sys.argv[4:]:
    evs = [json.loads(l) for l in open(ev_dir / "replay" / f"S1_{clip}.events.jsonl", encoding="utf-8")]
    frames = [e for e in evs if e.get("type") == "frame"]
    hits = []
    for e in frames:
        for d in e["detections"]:
            if d.get("has_cigarette_box"):
                hits.append((e["frame_idx"], e["t"], d))
    conf = [h for h in hits if h[2]["confirmed"]]
    print(f"{clip}: frames {len(frames)}, frames-with-cigbox {len(hits)}, confirmed {len(conf)}")
    pool = conf if conf else hits
    if not pool:
        continue
    pick = [pool[int(i)] for i in np.linspace(0, len(pool) - 1, min(8, len(pool)))]
    cap = cv2.VideoCapture(str(clips_root / clip / "clip.mp4"))
    tiles = []
    for fi, t, d in pick:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, img = cap.read()
        if not ok:
            continue
        x, y, w, h = d["bbox_x"], d["bbox_y"], d["bbox_w"], d["bbox_h"]
        cx, cy, cw, ch = d["cig_x"], d["cig_y"], d["cig_w"], d["cig_h"]
        cv2.rectangle(img, (cx, cy), (cx + cw, cy + ch), (0, 0, 255), 2)
        H, W = img.shape[:2]
        crop = img[max(0, y - 20):min(H, y + h + 20), max(0, x - 20):min(W, x + w + 20)]
        s = 300 / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=s, fy=s)
        tile = np.zeros((320, 300, 3), np.uint8)
        tile[:crop.shape[0], :crop.shape[1]] = crop
        cv2.putText(tile, f"t={t:.1f} c={d['raw_confidence']:.2f} {'CONF' if d['confirmed'] else ''}",
                    (4, 314), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tiles.append(tile)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    cv2.imwrite(str(out_dir / f"{clip}.jpg"), np.vstack(rows))
