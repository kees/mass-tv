#!/usr/bin/env python3
"""Generate synthetic test tracks and cover art for tools/fake_ma.py.

Every track in fake_ma's catalog gets audio of its catalog duration, so a
listener (or a screenshot of the progress bar) can tell where playback is:

  - a quiet drone at a per-track pitch (fake_ma.TONES): track changes are
    audible;
  - a soft tick every second;
  - at each 10 s mark, N short high beeps, where N is the tens digit of the
    seconds (1-5);
  - at each minute mark, a low chime followed by M beeps at a middle pitch,
    where M is the minute number (none at 0:00).

So "beep beep beep" means :30 into a minute; "chime, beep beep" means 2:00.

Formats (what MA can send to a Roku):
  flac-44k    FLAC 16-bit 44.1 kHz (MA's default)     test-media/flac-44k/<id>.flac
  flac-48k    FLAC 16-bit 48 kHz                        test-media/flac-48k/<id>.flac
  mp3         MP3 320 kbit/s 44.1 kHz                   test-media/mp3/<id>.mp3
  aac         AAC 256 kbit/s 44.1 kHz, ADTS             test-media/aac/<id>.aac
  flac-96k24  FLAC 24-bit 96 kHz, first track only      test-media/flac-96k24/t1.flac
Cover art: test-media/art/<proxy_id>.jpg (labeled, one color per item).

Needs ffmpeg (with libmp3lame) and Pillow. Existing files are kept unless
--force is given.

Usage: python3 tools/make_test_media.py [--out test-media] [--force]
"""

import argparse
import colorsys
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_ma  # noqa: E402

FORMATS = {
    "flac-44k": (".flac", ["-ar", "44100", "-sample_fmt", "s16", "-c:a", "flac"]),
    "flac-48k": (".flac", ["-ar", "48000", "-sample_fmt", "s16", "-c:a", "flac"]),
    "mp3": (".mp3", ["-ar", "44100", "-c:a", "libmp3lame", "-b:a", "320k"]),
    "aac": (".aac", ["-ar", "44100", "-c:a", "aac", "-b:a", "256k", "-f", "adts"]),
}
HIRES = ("flac-96k24", ".flac", ["-ar", "96000", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", "-c:a", "flac"])


def signal_expr(tone):
    """ffmpeg aevalsrc expression for one channel."""
    sec10 = "floor(mod(t,60)/10)"      # tens digit of the seconds, 0-5
    p = "mod(t,10)"                    # position within the 10 s window
    parts = [
        "0.12*sin(2*PI*%g*t)" % tone,                                   # drone
        "0.25*sin(2*PI*2000*t)*lt(mod(t,1),0.02)",                      # tick
        # 10 s marks: N beeps of 0.12 s every 0.25 s.
        "0.4*sin(2*PI*1320*t)*gte(%s,1)*lt(%s,%s*0.25)*lt(mod(%s,0.25),0.12)" % (sec10, p, sec10, p),
        # minute marks: 0.6 s chime, then M beeps from 0.8 s.
        "0.4*sin(2*PI*660*t)*eq(%s,0)*lt(%s,0.6)" % (sec10, p),
        "0.4*sin(2*PI*880*t)*eq(%s,0)*gte(%s,0.8)*lt(%s,0.8+floor(t/60)*0.3)*lt(mod(%s-0.8,0.3),0.15)" % (sec10, p, p, p),
    ]
    return "+".join(parts)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed: %s\n%s" % (" ".join(cmd), r.stderr[-2000:]))


def make_master(track, rate, path):
    e = signal_expr(fake_ma.TONES[track["item_id"]])
    fade_out = max(0, track["duration"] - 0.05)
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "aevalsrc=exprs='%s|%s':s=%d:d=%d" % (e, e, rate, track["duration"]),
         "-af", "afade=t=in:d=0.05,afade=t=out:st=%g:d=0.05" % fade_out,
         "-c:a", "pcm_f32le", path])


def encode(master, args, path):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", master] + args + [path])


def cover(path, title, subtitle, hue):
    from PIL import Image, ImageDraw, ImageFont

    size = 512
    r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.55, 0.75)]
    im = Image.new("RGB", (size, size), (r, g, b))
    d = ImageDraw.Draw(im)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    big = ImageFont.truetype(font_path, 56) if os.path.exists(font_path) else ImageFont.load_default()
    small = ImageFont.truetype(font_path, 30) if os.path.exists(font_path) else ImageFont.load_default()
    d.rectangle((0, size - 150, size, size), fill=(0, 0, 0))
    d.text((24, size - 140), title[:16], font=big, fill=(255, 255, 255))
    d.text((24, size - 60), subtitle[:28], font=small, fill=(200, 200, 200))
    d.text((24, 24), "TEST", font=small, fill=(255, 255, 255))
    im.save(path, quality=90)


def make_art(out, force):
    os.makedirs(os.path.join(out, "art"), exist_ok=True)
    items = []
    for a in fake_ma.ALBUMS.values():
        items.append((a["metadata"]["images"][0]["proxy_id"], a["name"], a["artists"][0]["name"]))
    for p in fake_ma.PLAYLISTS.values():
        items.append((p["metadata"]["images"][0]["proxy_id"], p["name"], "Playlist"))
    for a in fake_ma.ARTISTS.values():
        items.append((a["metadata"]["images"][0]["proxy_id"], a["name"], "Artist"))
    for i, (pid, title, sub) in enumerate(items):
        path = os.path.join(out, "art", pid + ".jpg")
        if force or not os.path.exists(path):
            cover(path, title, sub, (i * 0.13) % 1.0)
    print("art: %d covers" % len(items))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "test-media"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    make_art(a.out, a.force)
    with tempfile.TemporaryDirectory() as tmp:
        for t in fake_ma.TRACKS:
            tid = t["item_id"]
            wanted = [(name, ext, args) for name, (ext, args) in FORMATS.items()]
            if tid == "t1":
                wanted.append(HIRES)
            todo = [(n, e, ar) for n, e, ar in wanted if a.force or not os.path.exists(os.path.join(a.out, n, tid + e))]
            if not todo:
                continue
            master = os.path.join(tmp, tid + ".wav")
            make_master(t, 48000, master)
            hires_master = None
            for name, ext, args in todo:
                os.makedirs(os.path.join(a.out, name), exist_ok=True)
                src = master
                if name == HIRES[0]:
                    hires_master = os.path.join(tmp, tid + "-96k.wav")
                    make_master(t, 96000, hires_master)
                    src = hires_master
                encode(src, args, os.path.join(a.out, name, tid + ext))
            print("%s %-16s %4ds  %s" % (tid, t["name"], t["duration"], ", ".join(n for n, _, _ in todo)))
    print("test media in %s" % a.out)


if __name__ == "__main__":
    main()
