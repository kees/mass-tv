#!/usr/bin/env python3
"""Which characters Roku's system font can draw, measured on a Roku.

Pages the debug build's glyph probe (masstv_glyphs, components/debug/
GlyphProbe) over a range of code points, screenshots each page, and
compares every cell with the reference box (U+25C0, known missing): a
cell that matches it is a missing glyph, a dark cell is blank (spaces,
zero-width and combining characters), anything else is drawn.

Usage (a debug build running on the Roku; Pillow from the .venv that
`make` creates; the Roku named as for tools/roku.py, from the
environment or .env):
  ROKU=livingroom .venv/bin/python tools/glyph_probe.py [--bold] [--start A0] [--end 2190]
Writes logs/glyph-probe/<regular|bold>/ (page screenshots,
results-<start>-<end>.json) and prints the missing characters by range.
source/lib/Fonts.bs's drawnRanges comes from these results.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import unicodedata
import urllib.request

from PIL import Image, ImageChops, ImageStat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLUMNS, ROWS, CELL = 32, 16, 60
PAGE = COLUMNS * ROWS


def load_env():
    """.env's settings, under what the environment already sets."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def env_ip():
    name = os.environ.get("ROKU", "")
    if not name:
        sys.exit("name the Roku: ROKU=<name> (its address in ROKU_<NAME>_IP)")
    var = "ROKU_%s_IP" % name.upper()
    if not os.environ.get(var):
        sys.exit("set %s (e.g. in .env)" % var)
    return os.environ[var]


def roku(*args):
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "roku.py")] + list(args), check=True,
                   stdout=subprocess.DEVNULL)


def log_seq(ip):
    return int(urllib.request.urlopen("http://%s:8889/seq" % ip, timeout=5).read().decode().strip() or 0)


def wait_shown(ip, since, start, bold, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        for line in urllib.request.urlopen("http://%s:8889/log?since=%d" % (ip, since), timeout=5).read().decode().splitlines():
            e = json.loads(line)
            d = e.get("d") or {}
            if e.get("c") == "glyphs" and e.get("m") == "shown" and d.get("start") == start and d.get("bold") == bold:
                return True
        time.sleep(0.3)
    return False


def cell(img, col, row):
    s = img.width / 1920.0
    box = (round(col * CELL * s), round(row * CELL * s), round((col + 1) * CELL * s), round((row + 1) * CELL * s))
    return img.crop(box)


def page_mark(img):
    """The page start the probe drew in binary at the top row's end."""
    value = 0
    for b in range(16):
        # A mark fills 44% of its cell (mean ~110); an empty cell is black.
        if ImageStat.Stat(cell(img, COLUMNS - 1 - b, 0)).mean[0] > 50:
            value |= 1 << b
    return value


def diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def classify(img):
    """Per cell of the page: 'missing', 'blank', or 'drawn', plus the
    calibration (the two reference boxes' difference, and 'A' vs a box)."""
    ref, ref2, letter = cell(img, 0, 0), cell(img, 1, 0), cell(img, 2, 0)
    noise = diff(ref, ref2)
    signal = diff(ref, letter)
    limit = max(3.0, noise * 3)
    out = []
    for i in range(PAGE):
        c = cell(img, i % COLUMNS, 1 + i // COLUMNS)
        if c.getextrema()[1] < 60:
            out.append("blank")
        elif diff(c, ref) < limit:
            out.append("missing")
        else:
            out.append("drawn")
    return out, {"noise": round(noise, 2), "signal": round(signal, 2), "limit": round(limit, 2)}


def ranges(cps):
    out = []
    for cp in sorted(cps):
        if out and out[-1][1] == cp - 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bold", action="store_true")
    p.add_argument("--start", default="A0")
    p.add_argument("--end", default="2190")
    args = p.parse_args()
    load_env()
    ip = env_ip()
    start, end = int(args.start, 16), int(args.end, 16)
    style = "bold" if args.bold else "regular"
    out_dir = os.path.join(ROOT, "logs", "glyph-probe", style)
    os.makedirs(out_dir, exist_ok=True)
    results = {}
    calib = []
    for page_start in range(start, end, PAGE):
        since = log_seq(ip)
        params = ["masstv_glyphs=%X" % page_start]
        if args.bold:
            params.append("masstv_glyphs_bold=1")
        roku("input", *params)
        if not wait_shown(ip, since, page_start, args.bold):
            sys.exit("page %04X: the app didn't log it as shown" % page_start)
        # The low-end Roku draws the 515 labels well after the app logs them:
        # take screenshots until the page mark reads this page and two in a
        # row agree.
        shot = os.path.join(out_dir, "page-%04X.jpg" % page_start)
        img, stable = None, False
        for _ in range(12):
            time.sleep(1.5)
            roku("screenshot", shot)
            new = Image.open(shot).convert("L")
            if page_mark(new) != page_start:
                img = None
                continue
            if img is not None and diff(new, img) < 0.5:
                stable = True
                break
            img = new
        if not stable:
            sys.exit("page %04X: the screen didn't settle on the page" % page_start)
        kinds, cal = classify(new)
        cal["page"] = "%04X" % page_start
        calib.append(cal)
        for i, k in enumerate(kinds):
            cp = page_start + i
            if cp < end:
                results[cp] = k
        print("page %04X: %d missing, %d blank; calibration %s" % (
            page_start, sum(1 for k in kinds if k == "missing"), sum(1 for k in kinds if k == "blank"), cal), flush=True)
    roku("input", "masstv_glyphs=off")
    missing = [cp for cp, k in results.items() if k == "missing"]
    blank = [cp for cp, k in results.items() if k == "blank"]
    with open(os.path.join(out_dir, "results-%04X-%04X.json" % (start, end)), "w") as f:
        json.dump({"style": style, "start": start, "end": end, "calibration": calib,
                   "missing": ranges(missing), "blank": ranges(blank)}, f, indent=1)
    print("\n%s: %d missing, %d blank, %d drawn of %d" % (style, len(missing), len(blank),
                                                        len(results) - len(missing) - len(blank), len(results)))
    for a, b in ranges(missing):
        first = unicodedata.name(chr(a), "?")
        print("  missing %04X-%04X (%d) %s%s" % (a, b, b - a + 1, first,
                                                 "" if a == b else " .. " + unicodedata.name(chr(b), "?")))


if __name__ == "__main__":
    main()
