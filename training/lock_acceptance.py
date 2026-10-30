"""Lock acceptance thresholds + hold-out data (spec 9A.5): SHA-256 manifest and read-only attributes.

  python training/lock_acceptance.py --create     # after make_splits.py (and eval/holdout clips if any)
  python training/lock_acceptance.py --verify     # exit code 1 on any mismatch
Manifest: acceptance/holdout_manifest.sha256 ("<sha256>  <relative path>"), covering acceptance/acceptance.yaml,
data/splits/holdout.txt, every image/label listed there, and everything under data/eval/holdout/.
Tuning scripts do not call --create. Re-creating overwrites the manifest, so it refuses if one already exists
(delete it by hand only with the user's approval).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_utils import ROOT  # noqa: E402

MANIFEST = ROOT / "acceptance/holdout_manifest.sha256"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def targets():
    t = [ROOT / "acceptance/acceptance.yaml"]
    hs = ROOT / "data/splits/holdout.txt"
    if hs.is_file():
        t.append(hs)
        for line in hs.read_text().splitlines():
            if line.strip():
                img = Path(line.strip())
                t += [img] + ([img.with_suffix(".txt")] if img.with_suffix(".txt").is_file() else [])
    ev = ROOT / "data/eval/holdout"
    if ev.is_dir():
        t += [p for p in sorted(ev.rglob("*")) if p.is_file()]
    return t


def rel(p: Path) -> str:
    return os.path.relpath(p, ROOT).replace("\\", "/")


def verify() -> bool:
    if not MANIFEST.is_file():
        print("no manifest:", MANIFEST)
        return False
    bad = 0
    n = 0
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        h, r = line.split("  ", 1)
        p = ROOT / r
        n += 1
        if not p.is_file() or sha(p) != h:
            print("MISMATCH:", r)
            bad += 1
    print("verified %d files, %d mismatches" % (n, bad))
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--create", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--lock-thresholds", action="store_true",
                   help="lock only acceptance.yaml now (acceptance/acceptance.sha256); holdout is locked later")
    a = ap.parse_args()
    if a.lock_thresholds:
        y = ROOT / "acceptance/acceptance.yaml"
        f = ROOT / "acceptance/acceptance.sha256"
        if f.is_file():
            sys.exit("already locked")
        f.write_text("%s  %s\n" % (sha(y), rel(y)))
        os.chmod(y, stat.S_IREAD)
        os.chmod(f, stat.S_IREAD)
        print("locked thresholds:", f.read_text().strip())
        return
    if a.verify:
        ok = verify()
        f = ROOT / "acceptance/acceptance.sha256"
        if f.is_file():
            h, r = f.read_text().strip().split("  ", 1)
            good = (ROOT / r).is_file() and sha(ROOT / r) == h
            print("acceptance.yaml hash:", "OK" if good else "MISMATCH")
            ok = ok and good if MANIFEST.is_file() else good
        sys.exit(0 if ok else 1)
    if MANIFEST.is_file():
        sys.exit("manifest exists; refusing to overwrite (needs user approval to delete by hand)")
    ts = targets()
    MANIFEST.write_text("".join("%s  %s\n" % (sha(p), rel(p)) for p in ts))
    for p in ts:
        os.chmod(p, stat.S_IREAD)  # read-only attribute on Windows
    os.chmod(MANIFEST, stat.S_IREAD)
    print("locked %d files -> %s" % (len(ts), MANIFEST))


if __name__ == "__main__":
    main()
