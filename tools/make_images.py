#!/usr/bin/env python3
"""Generate Mass TV's channel poster and splash images (needs Pillow).

Usage: tools/make_images.py [--force] [--expect NAMES] [OUT_DIR]
Only writes files that are missing unless --force is given. OUT_DIR
defaults to src/images. --expect (the Makefile's list of images, space
separated) fails unless it names exactly the images this script makes.
`make` runs it when this script or its font changes, with Pillow from
tools/requirements.txt in the .venv it creates.
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFont

# Roku certification 6.4: artwork uses broadcast-safe colors, every RGB
# channel within 16..235. Anti-aliased edges blend between these colors,
# so they stay in range too; check_broadcast_safe() verifies the result.
SAFE_MIN = 16
SAFE_MAX = 235
BG = (16, 20, 24)
ACCENT = (90, 141, 232)
TEXT = (232, 232, 235)
MUTED = (154, 159, 176)
NOTE = (200, 214, 235)

# The emblem: a dot with arcs spreading to its right (sound going out),
# with music notes between and beyond the arcs. Lengths are in units of
# the emblem size r.
EMBLEM = {
    "first": 0.36,  # radius of the innermost arc
    "step": 0.62,  # radius added per arc
    "widths": (0.18, 0.14, 0.11),  # stroke of each arc, inside out
    "span": 44,  # degrees above and below the axis
    # (kind, gap, lift, size) per note: kind "eighth" or "beamed"; gap i
    # is between arcs i and i + 1 (the last gap is beyond the outer arc,
    # spaced as if another arc followed); lift raises the note's middle
    # above the axis (negative lowers it); size is the note's height.
    "notes": (
        ("eighth", 0, 0.05, 0.42),
        ("beamed", 1, -0.29, 0.40),
        ("eighth", 2, 0.45, 0.42),
    ),
    "note_color": NOTE,
    "arc_color": ACCENT,  # the arcs and the dot
    "scale": 0.86,
}


# The logo's text ("Mass TV" and its tagline): Roboto Bold, the font of
# Music Assistant's web UI (its "Music Assistant" title). The variable
# font is one of the sources pinned in fonts/sources.txt:
# `python3 tools/make_font.py fetch` (run by `make`) downloads it.
LOGO_FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts", "source", "Roboto[wdth,wght].ttf")


def font(size):
    if not os.path.exists(LOGO_FONT):
        sys.exit(f"{LOGO_FONT} is missing: run `python3 tools/make_font.py fetch`")
    fnt = ImageFont.truetype(LOGO_FONT, size)
    fnt.set_variation_by_name("Bold")
    return fnt


def centered(draw, box, text, fnt, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    w, h = right - left, bottom - top
    x = box[0] + (box[2] - box[0] - w) / 2 - left
    y = box[1] + (box[3] - box[1] - h) / 2 - top
    draw.text((x, y), text, font=fnt, fill=fill)


def arc_x(radius, dy, span):
    # Where an arc of this radius (centered on the axis) crosses the row dy
    # away from the axis, relative to its center; None beyond its ends.
    if abs(dy) > radius * math.sin(math.radians(span)):
        return None
    return math.sqrt(radius * radius - dy * dy)


def note_rows(kind, s):
    # The note's ink per row: {dy from its middle: (left, right)}.
    size = int(s * 2) + 4
    mask = Image.new("L", (size, size), 0)
    note(ImageDraw.Draw(mask), size / 2, size / 2, s, kind, 255)
    rows = {}
    for y in range(size):
        xs = [x for x in range(size) if mask.getpixel((x, y))]
        if xs:
            rows[y - size / 2] = (xs[0] - size / 2, xs[-1] + 1 - size / 2)
    return rows


def arc_runs(layer, ax, ay, y, radii, widths):
    # The arcs' ink on pixel row y as {arc index: (first x, last x)},
    # read from the drawn layer (Pillow's arcs don't match the ideal
    # circle to the pixel). A run belongs to the arc whose stroke band
    # (radius - width to radius; Pillow strokes inward) holds its middle.
    alpha = layer.getchannel("A")
    runs = {}
    x = int(ax)
    while x < layer.width:
        if alpha.getpixel((x, y)):
            start = x
            while x < layer.width and alpha.getpixel((x, y)):
                x += 1
            dist = math.hypot((start + x - 1) / 2 - ax, y - ay)
            for i, (rr, w) in enumerate(zip(radii, widths)):
                if rr - w - 2 <= dist <= rr + 2:
                    runs[i] = (start, x - 1)
        x += 1
    return runs


def note_x(layer, ax, ay, e, r, gap, lift, rows):
    # The note's middle x (on the layer) that leaves equal space to the arc
    # ink on each side, checked on every row the note covers since the arcs
    # curve. Beyond the outer arc, an ideal next arc stands in.
    n = len(e["widths"])
    radii = [r * (e["first"] + e["step"] * i) for i in range(n + 1)]
    widths = [r * w for w in e["widths"]] + [r * e["widths"][-1]]
    lo = hi = None
    for dy, (left, right) in rows.items():
        y = round(ay - lift * r + dy)
        runs = arc_runs(layer, ax, ay, y, radii[:n], widths[:n])
        if gap in runs:
            lo = left - (runs[gap][1] + 1) if lo is None else min(lo, left - (runs[gap][1] + 1))
        if gap + 1 < n:
            xo = runs[gap + 1][0] if gap + 1 in runs else None
        else:
            edge = arc_x(radii[n] - widths[n], y - ay, 90)
            xo = None if edge is None else ax + edge
        if xo is not None:
            hi = xo - right if hi is None else min(hi, xo - right)
    if lo is None or hi is None:
        raise ValueError(f"note in gap {gap} at lift {lift} is beyond the arcs' ends")
    # Space on the left is x + lo, on the right hi - x.
    return (hi - lo) / 2


def emblem(img, cx, cy, r, e=None):
    # Draws the mark on its own layer, then centers its ink horizontally on
    # cx with the axis (the dot's middle) at cy.
    e = dict(EMBLEM, **(e or {}))
    r = r * e["scale"]
    size = int(r * 6)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ax = ay = size / 2
    for i, width in enumerate(e["widths"]):
        rr = r * (e["first"] + e["step"] * i)
        draw.arc((ax - rr, ay - rr, ax + rr, ay + rr), start=-e["span"], end=e["span"], fill=e["arc_color"], width=max(2, int(r * width)))
    d = r * 0.22
    draw.ellipse((ax - d - r * 0.35, ay - d, ax + d - r * 0.35, ay + d), fill=e["arc_color"])
    for kind, gap, lift, size_ in e["notes"]:
        s = r * size_
        x = note_x(layer, ax, ay, e, r, gap, lift, note_rows(kind, s))
        note(draw, x, ay - lift * r, s, kind, e["note_color"])
    left, _, right, _ = layer.getbbox()
    img.paste(layer, (round(cx - (left + right) / 2), round(cy - ay)), layer)


def note_head(draw, x, y, s, fill):
    # A filled oval tilted up to the right, like engraved note heads.
    a, b, tilt = 0.24 * s, 0.16 * s, math.radians(25)
    pts = []
    for i in range(36):
        t = 2 * math.pi * i / 36
        px, py = a * math.cos(t), b * math.sin(t)
        pts.append((x + px * math.cos(tilt) + py * math.sin(tilt), y - px * math.sin(tilt) + py * math.cos(tilt)))
    draw.polygon(pts, fill=fill)


def note(draw, cx, cy, s, kind, fill):
    # Drawn rather than taken from a font, so stems stay thick enough to
    # read at the HD poster size. s is the note's height; (cx, cy) is the
    # middle of its bounding box.
    stem = max(2, 0.1 * s)
    top = cy - s / 2
    head_y = cy + s / 2 - 0.16 * s
    if kind == "eighth":
        hx = cx - 0.12 * s
        heads = [hx]
    else:
        hx = cx - 0.25 * s
        heads = [hx, hx + 0.48 * s]
    for h in heads:
        note_head(draw, h, head_y, s, fill)
        sx = h + 0.24 * s * math.cos(math.radians(25)) - stem / 2
        draw.rectangle((sx - stem / 2, top + (0.06 * s if h != heads[0] else 0), sx + stem / 2, head_y - 0.05 * s), fill=fill)
    sx0 = heads[0] + 0.24 * s * math.cos(math.radians(25)) - stem / 2
    if kind == "eighth":
        # Flag: a tapering curve off the top of the stem.
        draw.polygon([
            (sx0 + stem / 2, top),
            (sx0 + 0.34 * s, top + 0.28 * s),
            (sx0 + 0.30 * s, top + 0.52 * s),
            (sx0 + 0.24 * s, top + 0.34 * s),
            (sx0 + stem / 2, top + 0.24 * s),
        ], fill=fill)
    else:
        sx1 = heads[1] + 0.24 * s * math.cos(math.radians(25)) - stem / 2
        beam = 0.2 * s
        draw.polygon([(sx0 - stem / 2, top), (sx1 + stem / 2, top + 0.06 * s), (sx1 + stem / 2, top + 0.06 * s + beam), (sx0 - stem / 2, top + beam)], fill=fill)


# Pillow draws arcs, ellipses, and polygons without antialiasing (only
# text is smoothed), so posters and splashes are drawn at SUPERSAMPLE times
# their size and box-filtered down. A box filter only averages, so the
# result stays within the broadcast-safe range (a sharpening filter like
# Lanczos could overshoot it).
SUPERSAMPLE = 4


def ink_rows(img):
    """The first and last rows of an image's drawing (not the background)."""
    diff = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, BG))
    box = diff.getbbox()
    return box[1], box[3]


def poster(w, h, e=None, bottom_margin=1.0, emblem_top_as_gap=False):
    # bottom_margin: the space below the name as a fraction of the usual.
    # Below 1 the name grows, its top staying put (the same gap under the
    # emblem), so it gets taller and wider but never closer to the emblem.
    # emblem_top_as_gap: the emblem grows upward, its bottom staying put,
    # until the space above it equals the gap between it and the name.
    k = SUPERSAMPLE
    img = Image.new("RGB", (w * k, h * k), BG)
    d = ImageDraw.Draw(img)
    cy, r = h * k * 0.38, h * k * 0.26
    if emblem_top_as_gap:
        # Measure the emblem as usual; its ink scales with r about cy.
        probe = Image.new("RGB", (w * k, h * k), BG)
        emblem(probe, w * k * 0.5, cy, r, e)
        top, bottom = ink_rows(probe)
        box = (0, int(h * k * 0.68), w * k, int(h * k * 0.88))
        left_, ttop, right_, tbottom = d.textbbox((0, 0), "Mass TV", font=font(int(h * k * 0.14)))
        gap = box[1] + (box[3] - box[1] - (tbottom - ttop)) / 2 - bottom
        scale = (bottom - gap) / (bottom - top)
        cy = bottom - (bottom - cy) * scale
        r = r * scale
    emblem(img, w * k * 0.5, cy, r, e)
    box = (0, int(h * k * 0.68), w * k, int(h * k * 0.88))
    size = int(h * k * 0.14)
    if bottom_margin == 1.0:
        centered(d, box, "Mass TV", font(size), TEXT)
        return img.reduce(k)
    # Where the name's ink sits as usual (centered in the box).
    left, top, right, bottom = d.textbbox((0, 0), "Mass TV", font=font(size))
    ink_top = box[1] + (box[3] - box[1] - (bottom - top)) / 2
    ink_bottom = ink_top + (bottom - top)
    target = h * k - (h * k - ink_bottom) * bottom_margin
    # The size whose ink fills ink_top..target (ink height scales with
    # the size; one correction for rounding).
    for _ in range(2):
        left, top, right, bottom = d.textbbox((0, 0), "Mass TV", font=font(size))
        size = round(size * (target - ink_top) / (bottom - top))
    fnt = font(size)
    left, top, right, bottom = d.textbbox((0, 0), "Mass TV", font=fnt)
    d.text(((w * k - (right - left)) / 2 - left, ink_top - top), "Mass TV", font=fnt, fill=TEXT)
    return img.reduce(k)


# The splash's drawing (emblem, name, tagline) is laid out at SPLASH_SCALE
# around the screen's middle: at 1.5 it spans about 72% of the height,
# inside Roku's title-safe area (the middle 90%); at 1 it spanned 48%.
SPLASH_SCALE = 1.5
# The middle of the drawing as laid out at scale 1 (fraction of the height).
SPLASH_CENTER = 0.507


def splash(w, h, e=None):
    k = SUPERSAMPLE
    img = Image.new("RGB", (w * k, h * k), BG)
    d = ImageDraw.Draw(img)

    def y(frac):
        return int(h * k * (0.5 + (frac - SPLASH_CENTER) * SPLASH_SCALE))

    s = SPLASH_SCALE
    emblem(img, w * k * 0.5, y(0.42), h * k * 0.16 * s, e)
    centered(d, (0, y(0.60), w * k, y(0.70)), "Mass TV", font(int(h * k * 0.07 * s)), TEXT)
    centered(d, (0, y(0.70), w * k, y(0.76)), "for Music Assistant", font(int(h * k * 0.03 * s)), MUTED)
    return img.reduce(k)


def shown_at(img, height):
    """The image scaled to the height it's shown at, box-filtered (an
    average, so colors stay broadcast-safe)."""
    width = round(img.width * height / img.height)
    return img.resize((width, height), Image.BOX)


def trimmed(img, bg=BG):
    """The image cropped to its drawing (everything not the background),
    so a Poster showing it covers nothing around the drawing."""
    diff = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, bg))
    return img.crop(diff.getbbox())


CARD_BG = (35, 42, 51)  # PosterCard's artBg, #232A33
ROW_BG = (42, 49, 59)  # TrackRow's artBox, #2A313B


def mix(color, bg, amount):
    # amount 0 is the background, 1 the color itself.
    return tuple(round(b + (c - b) * amount) for c, b in zip(color, bg))


def placeholder(size, bg, amount, frac):
    # A missing-cover square: the emblem blended toward bg (amount is its
    # strength), its ink fitted to frac of the width and centered both
    # ways. The app draws a card's letter over it with a Label.
    e = dict(EMBLEM, arc_color=mix(ACCENT, bg, amount), note_color=mix(NOTE, bg, amount))
    probe = Image.new("RGB", (2000, 2000), bg)
    emblem(probe, 1000, 1000, 100, e)
    left, top, right, bottom = ImageChops.difference(probe, Image.new("RGB", probe.size, bg)).getbbox()
    k = SUPERSAMPLE
    big = size * k
    img = Image.new("RGB", (big, big), bg)
    r = 100 * frac * big / (right - left)
    mid = (top + bottom) / 2 - 1000
    emblem(img, big / 2, big / 2 - mid * r / 100, r, e)
    return img.reduce(k)


def focus_ring(size=48, radius=14, border=3, fill=(255, 255, 255, round(255 * 0.15)), outline=ACCENT):
    # The focus highlight for text rows (nav bar, tabs, button rows): a
    # rounded translucent white fill with a blue border; track lists use the same
    # shape with their opaque gray fill. A Roku 9-patch: a 1 px frame whose
    # black pixels (top and left) mark the stretchable middle, so the
    # corners stay round at any size. Transparent pixels carry the
    # border's color so the downsampled edge doesn't darken. With the
    # outline in the fill's color it is a plain rounded pill.
    k = SUPERSAMPLE
    big = Image.new("RGBA", (size * k, size * k), outline + (0,))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle(
        (0, 0, size * k - 1, size * k - 1), radius=radius * k,
        fill=fill, outline=outline + (255,), width=border * k,
    )
    img = Image.new("RGBA", (size + 2, size + 2), (0, 0, 0, 0))
    img.paste(big.reduce(k), (1, 1))
    for i in range(radius + 4, size - radius - 4):
        img.putpixel((1 + i, 0), (0, 0, 0, 255))
        img.putpixel((0, 1 + i), (0, 0, 0, 255))
    return img


def wordmark(cap_height, scale=1):
    # "Mass TV" as in the logo (Roboto Bold, TEXT color) on a
    # transparent background, cropped to its ink, with capitals
    # cap_height px tall: the nav bar shows it instead of system-font text.
    # scale: the same drawing for a screen drawn at that scale (2/3 for an
    # HD Roku), exactly its box on that screen, so nothing is resampled.
    k = SUPERSAMPLE
    probe = font(100 * k)
    left, top, right, bottom = probe.getbbox("M")
    size = round(100 * cap_height / ((bottom - top) / k))
    fnt = font(size * k)
    left, top, right, bottom = fnt.getbbox("Mass TV")
    # Transparent pixels carry the text color, so edges don't darken.
    img = Image.new("RGBA", (right - left + 2 * k, bottom - top + 2 * k), TEXT + (0,))
    ImageDraw.Draw(img).text((k - left, k - top), "Mass TV", font=fnt, fill=TEXT + (255,))
    img = img.crop(img.getbbox())
    w, h = img.size
    return img.resize((round(round(w / k) * scale), round(round(h / k) * scale)), Image.BOX)


def check_broadcast_safe(img, name):
    lo, hi = zip(*img.convert("RGB").getextrema())
    if min(lo) < SAFE_MIN or max(hi) > SAFE_MAX:
        sys.exit(f"{name}: colors outside {SAFE_MIN}..{SAFE_MAX} (channel minimums {lo}, maximums {hi})")


def fade(to_bottom, width=8, height=64, max_alpha=0.85):
    # List edge fade: the screen background color, transparent at one end
    # and max_alpha at the edge the list continues past.
    img = Image.new("RGBA", (width, height))
    for y in range(height):
        t = y / (height - 1)
        if not to_bottom:
            t = 1.0 - t
        alpha = int(255 * max_alpha * (t ** 1.3))
        for x in range(width):
            img.putpixel((x, y), BG + (alpha,))
    return img


def spinner(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size * 0.08
    d.arc((pad, pad, size - pad, size - pad), start=0, end=270, fill=ACCENT + (255,), width=int(size * 0.1))
    return img


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--force", action="store_true", help="rewrite existing files")
    p.add_argument("--expect", help="the image names the caller expects, space separated")
    p.add_argument("out", nargs="?", default="src/images")
    args = p.parse_args()
    targets = {
        # The app's tile on the Roku home screen: the name larger, its
        # bottom margin a third smaller, and the emblem grown up to a top
        # margin equal to its gap above the name.
        "icon_focus_fhd.png": lambda: poster(540, 405, bottom_margin=2 / 3, emblem_top_as_gap=True),
        "icon_focus_hd.png": lambda: poster(290, 218, bottom_margin=2 / 3, emblem_top_as_gap=True),
        # The Settings screen's logo: the 864x648 poster trimmed to its
        # drawing (its opaque border covered text next to it), made at the
        # size it's shown (200x246 on the FHD screen): Roku shrinks a
        # Poster's image without smoothing, which made the text jagged.
        # One per UI resolution; the manifest's uri_resolution_autosub
        # picks it ("logo_settings_$$RES$$.png").
        "logo_settings_fhd.png": lambda: shown_at(trimmed(poster(864, 648)), 246),
        "logo_settings_hd.png": lambda: shown_at(trimmed(poster(864, 648)), 164),
        # Missing-cover placeholders: cards show their
        # letter over an 8% emblem, or a 25% emblem with no letter; track
        # rows show a 25% emblem at their 66 px size.
        "placeholder_card_letter.png": lambda: placeholder(256, CARD_BG, 0.08, 0.72),
        "placeholder_card.png": lambda: placeholder(256, CARD_BG, 0.25, 0.72),
        "placeholder_row.png": lambda: placeholder(66, ROW_BG, 0.25, 0.8),
        # A Detail page's 340 px header cover.
        "placeholder_header.png": lambda: placeholder(340, CARD_BG, 0.25, 0.72),
        # Now Playing's 520 px cover.
        "placeholder_nowplaying.png": lambda: placeholder(520, CARD_BG, 0.25, 0.72),
        "splash_fhd.png": lambda: splash(1920, 1080),
        "splash_hd.png": lambda: splash(1280, 720),
        "spinner.png": lambda: spinner(96),
        "focus_ring.9.png": lambda: focus_ring(),
        # The nav bar's "Mass TV", matching the system-font text it replaces
        # (25 px capitals on the FHD screen), per UI resolution like the
        # Settings logo: an HD Roku draws the FHD screen at 2/3.
        "wordmark_nav_fhd.png": lambda: wordmark(25),
        "wordmark_nav_hd.png": lambda: wordmark(25, 2 / 3),
        # Track rows' focus: TrackRow's gray (#232A33) inside the ring.
        "focus_row.9.png": lambda: focus_ring(fill=(35, 42, 51, 255)),
        # Something to press, at rest: a faint rounded
        # fill (#1C232C) behind buttons and rows outside the nav bar,
        # grids, and lists; the focus ring draws over the same shape.
        "pill.9.png": lambda: focus_ring(fill=(28, 35, 44, 255), outline=(28, 35, 44)),
        "fade_top.png": lambda: fade(False),
        "fade_bottom.png": lambda: fade(True),
    }
    if args.expect is not None:
        expected = set(args.expect.split())
        if expected != set(targets):
            sys.exit("the image lists differ: only expected: %s; only made here: %s" % (
                " ".join(sorted(expected - set(targets))) or "-",
                " ".join(sorted(set(targets) - expected)) or "-"))
    os.makedirs(args.out, exist_ok=True)
    for name, make in targets.items():
        path = os.path.join(args.out, name)
        if args.force or not os.path.exists(path):
            img = make()
            if name.startswith(("icon_", "splash_", "logo_", "placeholder_")):
                check_broadcast_safe(img, name)
            img.save(path, optimize=True)
            print("wrote", path)


if __name__ == "__main__":
    main()
