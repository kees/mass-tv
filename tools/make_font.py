#!/usr/bin/env python3
"""Builds Mass TV's bundled text font: subsets of Noto Sans (Latin, Greek,
Cyrillic), Noto Sans CJK, and the monochrome Noto Emoji merged into one
file per weight (only Regular by default; see WEIGHTS).

Roku's system font has no CJK or emoji, and a Label draws with one font
(no fallback between fonts), so a title mixing Latin, CJK, and emoji
needs all of them in a single file. The app switches a label to this
font only when its text needs it (source/lib/Fonts.bs).

    tools/make_font.py fetch     download the sources pinned in
                                 fonts/sources.txt into fonts/source/
                                 (only those missing or not matching
                                 their SHA-256)
    tools/make_font.py build     write src/fonts/MassTVText-<Weight>.ttf
    tools/make_font.py sets      print each character set's size

`make` runs fetch and build when their inputs change, with fontTools
from tools/requirements.txt in the .venv it creates; to run a step by
hand, use that venv: `.venv/bin/python tools/make_font.py sets`. fetch
needs only the standard library.

The built fonts are under the SIL Open Font License 1.1, like their
sources (fonts/README.md); the name table keeps every source's copyright
notice and the license.

Which characters go in is decided by the *_SETS lists below; extra
characters can be listed in fonts/extra-chars.txt. Everything comes from
Unicode ranges and Python's own codecs (GB 2312, JIS X 0208, KS X 1001,
Big5), so no character lists need downloading.
"""

import argparse
import hashlib
import io
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DIR = os.path.join(ROOT, "fonts", "source")
OUT_DIR = os.path.join(ROOT, "src", "fonts")
EXTRA_CHARS = os.path.join(ROOT, "fonts", "extra-chars.txt")

FAMILY = "Mass TV Text"
FILE_STEM = "MassTVText"

# The source fonts, all pinned in fonts/sources.txt (why these, and
# their licenses, are noted there).
CJK_FONT = "NotoSansCJKjp-VF.ttf"
LATIN_FONT = "NotoSans[wdth,wght].ttf"
EMOJI_FONT = "NotoEmoji[wght].ttf"
ARABIC_FONT = "NotoSansArabic[wdth,wght].ttf"
HEBREW_FONT = "NotoSansHebrew[wdth,wght].ttf"
# The fonts merged into the bundled one.
BUNDLED = (CJK_FONT, LATIN_FONT, EMOJI_FONT, ARABIC_FONT, HEBREW_FONT)
SOURCES_LIST = os.path.join(ROOT, "fonts", "sources.txt")


def read_sources():
    """(file, sha256, url) per line of fonts/sources.txt."""
    out = []
    with open(SOURCES_LIST, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 3:
                sys.exit("%s:%d: expected: file sha256 url" % (SOURCES_LIST, n))
            out.append(tuple(fields))
    return out


SOURCES = read_sources()

# The weights to build (the wght axis value) and their file suffixes.
# Only Regular ships: the app emulates bold (widgets/BoldTwin), which
# halves the size. Add (700, "Bold") to build a real bold as well (and
# its file to the Makefile's FONTS).
WEIGHTS = [(400, "Regular")]


def span(first, last):
    return set(range(first, last + 1))


def codec_chars(codec, leads, trails=range(0xA1, 0xFF)):
    """Every character a double-byte codec decodes from lead x trail."""
    out = set()
    for lead in leads:
        for trail in trails:
            try:
                ch = bytes([lead, trail]).decode(codec)
            except UnicodeDecodeError:
                continue
            if len(ch) == 1:
                out.add(ord(ch))
    return out


def big5_common():
    """Big5's frequently used characters (常用字, 0xA440-0xC67E)."""
    out = set()
    for lead in range(0xA4, 0xC7):
        for trail in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            if (lead << 8 | trail) > 0xC67E:
                break
            try:
                out.add(ord(bytes([lead, trail]).decode("big5")))
            except (UnicodeDecodeError, TypeError):
                pass
    return out


# Character sets by name. Each is a function, so only the used ones run.
SET_DEFS = {
    # Latin (with Vietnamese), Greek, Cyrillic, and punctuation: a label
    # that switches fonts is drawn in this font entirely.
    "latin": lambda: span(0x20, 0x7E) | span(0xA0, 0x24F) | span(0x300, 0x36F) | span(0x1E00, 0x1EFF),
    "greek-cyrillic": lambda: span(0x370, 0x3FF) | span(0x400, 0x4FF),
    "punctuation": lambda: span(0x2000, 0x206F) | span(0x20A0, 0x20CF),
    # Arrows, shapes, and symbols (music notes, stars, triangles).
    "symbols": lambda: span(0x2070, 0x209F) | span(0x2100, 0x2BFF),
    # CJK punctuation, kana, half- and full-width forms.
    "cjk-punct": lambda: span(0x3000, 0x303F) | span(0xFF00, 0xFFEF),
    "kana": lambda: span(0x3040, 0x30FF) | span(0x31F0, 0x31FF),
    # Hangul: KS X 1001's 2,350 common syllables and the compatibility
    # jamo; "hangul-all" is every syllable (11,172).
    "hangul": lambda: codec_chars("euc_kr", range(0xB0, 0xC9)) | span(0x3130, 0x318F),
    "hangul-all": lambda: span(0xAC00, 0xD7A3) | span(0x3130, 0x318F),
    # Han: GB 2312 level 1 (3,755 most used Simplified Chinese), JIS X
    # 0208 level 1 (2,965 most used Japanese kanji), Big5 common
    # (5,401 Traditional Chinese).
    "han-gb2312-1": lambda: codec_chars("gb2312", range(0xB0, 0xD8)),
    "han-jis-1": lambda: codec_chars("euc_jp", range(0xB0, 0xD0)),
    "han-big5-common": big5_common,
    # Arabic script: the Arabic block and its supplement, the presentation
    # forms of the Persian and Urdu letters (Forms-A's first part), and
    # Forms-B, which has every basic letter's isolated, final, initial,
    # and medial form and the lam-alef ligatures. Roku's renderer neither
    # joins nor orders Arabic, so the app picks these forms itself
    # (source/lib/Bidi.bs).
    "arabic": lambda: span(0x600, 0x6FF) | span(0x750, 0x77F) | span(0xFB50, 0xFBFF) | span(0xFE70, 0xFEFF),
    # Hebrew: the Hebrew block (letters, final forms, points, and
    # punctuation) and its presentation forms (letters with dagesh, the
    # Yiddish ligatures). Its letters don't join; the app orders the text
    # (source/lib/Bidi.bs) and drops the points, which the renderer can't
    # place.
    "hebrew": lambda: span(0x590, 0x5FF) | span(0xFB1D, 0xFB4F),
}

# What goes in from each font. Noto Sans gives what it has of its sets;
# the CJK font gives the rest (whatever of LATIN_SETS Noto Sans lacks,
# then its own sets).
LATIN_SETS = ["latin", "greek-cyrillic", "punctuation"]
CJK_SETS = ["symbols", "cjk-punct", "kana", "hangul", "han-gb2312-1", "han-jis-1"]
# Noto Sans Arabic and Noto Sans Hebrew give these (whatever the fonts
# above don't).
ARABIC_SETS = ["arabic"]
HEBREW_SETS = ["hebrew"]
# The emoji font gives every emoji it has at U+2190 and above (below
# that it maps digits, #, *, and marks like (c) for keycap sequences,
# which the CJK font draws as text). Below EMOJI_PICTOGRAPHS, where most
# characters are text symbols by default (▶, ★, ♥), a text font's glyph
# wins when it has one; otherwise ▶ would be drawn as the boxed ▶️.
# Sequences (ZWJ families, flags, keycaps) aren't built: Roku's text
# renderer doesn't combine them (seen on the device), so they show as
# their parts, and skin-tone modifiers are left invisible (👍🏽 shows 👍).
EMOJI_FROM = 0x2190
EMOJI_PICTOGRAPHS = 0x1F000
SKIN_TONES = list(range(0x1F3FB, 0x1F400))

# Vertical metrics (units of the 1000-unit em), written to hhea and to
# OS/2's typo and win fields alike. Roku puts the first baseline one
# ascent below a label's top, and the CJK font's own ascent (1000 to
# 1160) set text about a third of an em lower than the system font in
# the same label; this ascent lines the baselines up (measured on a
# Roku, OS 15.3).
ASCENT = 850
DESCENT = 250

# Invisible joiners and selectors in emoji text, and the skin-tone
# modifiers, drawn as nothing.
ZERO_WIDTH = [0x200B, 0x200C, 0x200D, 0x2060, 0xFE0E, 0xFE0F] + SKIN_TONES


def charset(names):
    out = set()
    for n in names:
        out |= SET_DEFS[n]()
    return out


def extra_chars():
    if not os.path.exists(EXTRA_CHARS):
        return set()
    out = set()
    with open(EXTRA_CHARS, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            out |= {ord(c) for c in line if not c.isspace()}
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_fetch(_args):
    """Downloads each source that is missing or doesn't match its pin; a
    download replaces the file only once its SHA-256 matches."""
    os.makedirs(SOURCE_DIR, exist_ok=True)
    for name, want, url in SOURCES:
        path = os.path.join(SOURCE_DIR, name)
        if os.path.exists(path) and sha256(path) == want:
            print("ok", name)
            continue
        print("fetching", url)
        req = urllib.request.Request(url, headers={"User-Agent": "make_font.py"})
        with urllib.request.urlopen(req) as r, open(path + ".part", "wb") as f:
            f.write(r.read())
        got = sha256(path + ".part")
        if got != want:
            sys.exit("%s: sha256 %s, expected %s (kept as %s.part)" % (name, got, want, name))
        os.replace(path + ".part", path)
        print("ok", name)


def check_sources():
    for name, want, _url in SOURCES:
        path = os.path.join(SOURCE_DIR, name)
        if not os.path.exists(path) or sha256(path) != want:
            sys.exit("%s missing or changed: run `make_font.py fetch`" % name)


def subset(font, unicodes):
    from fontTools import subset as ftsubset
    opts = ftsubset.Options()
    opts.layout_features = ["kern", "liga", "ccmp"]
    opts.drop_tables += ["BASE", "DSIG", "vhea", "vmtx", "VORG", "VVAR", "STAT", "gasp"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = False
    s = ftsubset.Subsetter(opts)
    s.populate(unicodes=unicodes)
    s.subset(font)


def source_part(name, unicodes, location, upem):
    """One source's subset at one weight (a static font), as bytes."""
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.scaleUpem import scale_upem
    from fontTools.varLib import instancer
    font = TTFont(os.path.join(SOURCE_DIR, name))
    subset(font, unicodes)
    axes = {a.axisTag for a in font["fvar"].axes}
    font = instancer.instantiateVariableFont(font, {k: v for k, v in location.items() if k in axes})
    if font["head"].unitsPerEm != upem:
        scale_upem(font, upem)
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    return buf


def build_weight(wght, style, parts_codes):
    from fontTools.merge import Merger
    location = {"wght": wght, "wdth": 100}
    # The CJK font goes first: the merger keeps the first font's vertical
    # metrics, which leave room for CJK and emoji.
    parts = [source_part(name, codes_, location, 1000) for name, codes_ in parts_codes]
    merged = Merger().merge(parts)
    set_vertical_metrics(merged)
    add_zero_width(merged)
    rename(merged, style, wght)
    # The OFL asks for each source's copyright notice; the merger kept
    # only the first font's.
    merged["name"].setName(copyrights(), 0, 3, 1, 0x409)
    merged["name"].setName(copyrights(), 0, 1, 0, 0)
    # The same inputs give the same file: the font's dates are the newest
    # source's, not the time of the build.
    stamp = source_timestamp()
    merged["head"].created = stamp
    merged["head"].modified = stamp
    merged.recalcTimestamp = False
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "%s-%s.ttf" % (FILE_STEM, style))
    merged.save(path)
    return path, merged


def source_timestamp():
    """The newest modification date among the source fonts (head.modified)."""
    from fontTools.ttLib import TTFont
    return max(TTFont(os.path.join(SOURCE_DIR, name), lazy=True)["head"].modified
               for name in BUNDLED)


def copyrights():
    from fontTools.ttLib import TTFont
    notices = []
    for name in BUNDLED:
        text = TTFont(os.path.join(SOURCE_DIR, name), lazy=True)["name"].getDebugName(0)
        if text and text not in notices:
            notices.append(text.strip())
    return " ".join(notices)


def set_vertical_metrics(font):
    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = ASCENT, -DESCENT, 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ASCENT, -DESCENT, 0
    os2.usWinAscent, os2.usWinDescent = ASCENT, DESCENT


def add_zero_width(font):
    """Maps the joiners and selectors to an empty, zero-width glyph."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    cmap_missing = [c for c in ZERO_WIDTH if c not in font.getBestCmap()]
    if not cmap_missing:
        return
    name = "zerowidth"
    order = font.getGlyphOrder()
    if name not in order:
        font.setGlyphOrder(order + [name])
        font["glyf"][name] = TTGlyphPen(None).glyph()
        font["hmtx"][name] = (0, 0)
        font["maxp"].numGlyphs = len(font.getGlyphOrder())
    for table in font["cmap"].tables:
        if table.isUnicode():
            for c in cmap_missing:
                if table.format in (4,) and c > 0xFFFF:
                    continue
                table.cmap[c] = name


def rename(font, style, wght):
    name = font["name"]
    full = "%s %s" % (FAMILY, style)
    ps = "%s-%s" % (FILE_STEM, style)
    ids = {1: FAMILY, 2: style, 3: "%s;%s" % (ps, "make_font.py"), 4: full, 6: ps,
           16: FAMILY, 17: style}
    name.names = [r for r in name.names if r.nameID not in ids and r.nameID not in (21, 22, 25)]
    for nid, text in ids.items():
        name.setName(text, nid, 3, 1, 0x409)
        name.setName(text, nid, 1, 0, 0)
    font["OS/2"].usWeightClass = wght
    bold = style == "Bold"
    font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x61) | (0x20 if bold else 0x40)
    font["head"].macStyle = 1 if bold else 0


def cmap_of(name):
    from fontTools.ttLib import TTFont
    return set(TTFont(os.path.join(SOURCE_DIR, name), lazy=True).getBestCmap())


def codes():
    """Each source's code points, in merge order (CJK, Latin, emoji,
    Arabic, Hebrew). The emoji font's own (from EMOJI_FROM up) come
    first, then Noto Sans's of LATIN_SETS, then the CJK font takes the
    rest of the wanted sets, and Noto Sans Arabic and Hebrew their
    scripts'."""
    text_cmap = cmap_of(CJK_FONT) | cmap_of(LATIN_FONT)
    emoji_codes = {c for c in cmap_of(EMOJI_FONT)
                   if c >= EMOJI_FROM and c not in ZERO_WIDTH
                   and not (c < EMOJI_PICTOGRAPHS and c in text_cmap)}
    wanted = charset(LATIN_SETS) | charset(CJK_SETS) | extra_chars()
    latin_codes = (charset(LATIN_SETS) & cmap_of(LATIN_FONT)) - emoji_codes
    cjk_codes = (wanted & cmap_of(CJK_FONT)) - emoji_codes - latin_codes
    arabic_codes = (charset(ARABIC_SETS) & cmap_of(ARABIC_FONT)) - emoji_codes - latin_codes - cjk_codes
    hebrew_codes = (charset(HEBREW_SETS) & cmap_of(HEBREW_FONT)) - emoji_codes - latin_codes - cjk_codes - arabic_codes
    return [(CJK_FONT, cjk_codes), (LATIN_FONT, latin_codes), (EMOJI_FONT, emoji_codes),
            (ARABIC_FONT, arabic_codes), (HEBREW_FONT, hebrew_codes)]


def cmd_build(_args):
    check_sources()
    parts_codes = codes()
    for name, c in parts_codes:
        print("%-24s %6d characters" % (name, len(c)))
    for wght, style in WEIGHTS:
        path, font = build_weight(wght, style, parts_codes)
        print("%s: %d bytes, %d glyphs, %d characters" % (
            os.path.relpath(path, ROOT), os.path.getsize(path),
            len(font.getGlyphOrder()), len(font.getBestCmap())))


def cmd_sets(_args):
    check_sources()
    have = cmap_of(CJK_FONT) | cmap_of(LATIN_FONT)
    for n in SET_DEFS:
        s = SET_DEFS[n]()
        mark = "*" if n in CJK_SETS or n in LATIN_SETS else " "
        print("%s %-16s %6d characters, %6d in the sources" % (mark, n, len(s), len(s & have)))
    for name, c in codes():
        print("  from %-22s %6d" % (name, len(c)))
    print("  extra-chars.txt              %6d" % len(extra_chars()))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("build")
    sub.add_parser("sets")
    args = p.parse_args()
    {"fetch": cmd_fetch, "build": cmd_build, "sets": cmd_sets}[args.cmd](args)


if __name__ == "__main__":
    main()
