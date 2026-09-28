# Mass TV Text (the bundled font)

Roku's system font has no CJK characters or emoji, and a Label draws
with one font (there's no fallback to a second one), so a title that
mixes Latin, CJK, and emoji needs all of them in one file. Mass TV
switches a label to this font only when its text needs it
(`src/source/lib/Fonts.bs`).

A label switches only for a character the system font doesn't draw,
after replacing lookalikes it does draw (U+2010 HYPHEN shows as "-",
thin spaces as a space; invisible marks are removed). What the system
font draws was measured on a Roku with `tools/glyph_probe.py`: Latin-1,
most of Latin Extended-A, basic Greek and Cyrillic, common punctuation,
and a few symbols (arrows, ✓, ♪, ★), the same in regular and bold. It
has no Vietnamese, Hebrew, Arabic, Indic, or other scripts; the bundled
font adds Vietnamese, the rest of Latin, Greek, and Cyrillic, Arabic,
and Hebrew, but not Indic or the other scripts. The ranges are `drawnRanges` in
`src/source/lib/Fonts.bs`; to measure again (e.g. on a new Roku OS), run
a debug build and `ROKU=<name> .venv/bin/python tools/glyph_probe.py`
(`--bold`, `--start`, `--end` in hex).

`src/fonts/MassTVText-Regular.ttf` is built by `tools/make_font.py` from
five sources pinned in `sources.txt`. Only the regular weight ships: the app emulates
bold by drawing a bold label twice, a little apart
(`src/components/widgets/BoldTwin`), which halves the size; the tool can
build a real bold too (`WEIGHTS`).

| Source | Gives | License |
|---|---|---|
| Noto Sans CJK JP 2.004 (TrueType variable) | kana, Hangul, Han, CJK punctuation, symbols | `OFL-NotoSansCJK.txt` |
| Noto Sans (google/fonts) | Latin with its extensions, Greek, Cyrillic, punctuation | `OFL-NotoSans.txt` |
| Noto Emoji, monochrome (google/fonts) | emoji | `OFL-NotoEmoji.txt` |
| Noto Sans Arabic (google/fonts) | Arabic script: the Arabic block, Persian and Urdu letters, and the presentation forms | `OFL-NotoSansArabic.txt` |
| Noto Sans Hebrew (google/fonts) | Hebrew: the Hebrew block and its presentation forms | `OFL-NotoSansHebrew.txt` |

Roku's renderer draws each character as one glyph, left to right: it
doesn't join Arabic letters or order right-to-left text. So the font
carries the presentation forms (each letter's isolated, final, initial,
and medial shapes, and the lam-alef ligatures), and the app picks them
and orders the line itself (`src/source/lib/Bidi.bs`, with its joining
table from `tools/arabic_forms.py`). Hebrew letters don't join, so it
needs only the ordering. Arabic vowel marks and Hebrew points are
dropped, since they'd need positioning the renderer can't do. Arabic
adds about 23 KB to the zipped package, Hebrew about 6 KB.

All are under the SIL Open Font License 1.1, and so is the built font.
None has a Reserved Font Name the build uses (Noto Sans CJK reserves
"Source"; the built font is named "Mass TV Text"). The font's name
table keeps each source's copyright notice and the license.

## Rebuilding

`make` builds the font (it isn't committed) whenever `make_font.py`,
`extra-chars.txt`, the sources, or the pinned fontTools change, and
`make font` does only that. By hand, with the venv `make` creates:

    python3 tools/make_font.py fetch           # into fonts/source/, checksums verified
    .venv/bin/python tools/make_font.py sets   # what each character set holds
    .venv/bin/python tools/make_font.py build

`fonts/source/` (about 40 MB) isn't committed either; `fetch` downloads
each file that's missing or doesn't match its pin in `sources.txt`, and
keeps a download only if its SHA-256 matches. The build is
reproducible: the same sources and fontTools give the same bytes (the
font is dated by its newest source).

## Choosing characters

The sets are named in `tools/make_font.py` (`SET_DEFS`, `LATIN_SETS`,
`CJK_SETS`) and come from Unicode ranges and Python's own codecs, so no
character lists are downloaded:

- Hangul: KS X 1001's 2,350 common syllables (`hangul-all`: all 11,172).
- Han: GB 2312 level 1 (3,755 Simplified Chinese) and JIS X 0208 level 1
  (2,965 Japanese kanji); `han-big5-common` adds Big5's 5,401 common
  Traditional Chinese characters.
- Emoji: every single-character emoji in Noto Emoji. Sequences (ZWJ
  families, flags, keycaps) show as their parts, since Roku's renderer
  doesn't combine them; skin-tone modifiers are invisible.

Add single characters in `fonts/extra-chars.txt`.

Shared Han characters take their Japanese forms (the JP-region source);
change `CJK_FONT` and its line in `sources.txt` to use another region's.

## Size

Roku's limit is 4 MB for the whole app package (zipped). The font is
about 3 MB, 1.8 MB zipped: Han about 960 KB, emoji 480 KB, Hangul
190 KB, the rest about 150 KB.

## The logo's font

The "Mass TV" logo text (splash screens, channel posters, the Settings
logo, and the nav bar's wordmark) is drawn in Roboto Bold, the font of
Music Assistant's web UI, by `tools/make_images.py`. Roboto isn't in the
bundled font; it's pinned in `sources.txt` only so `fetch` downloads
it (`OFL-Roboto.txt`). `make` regenerates the images (`make images` for
just those) when `make_images.py`, the sources, or the pinned Pillow
change; the same inputs give the same bytes. The image list is also
in the Makefile (`IMAGES`), and `make_images.py` fails when the two
differ. The nav bar's
wordmark and the Settings logo are made at the exact size they're shown,
for FHD and HD screens (`_fhd`/`_hd`, picked through the manifest's
`uri_resolution_autosub`), because Roku shrinks images without
smoothing; `NavBar.xml` and `SettingsScreen.xml` give those sizes, to
update if the images' dimensions change.

## Vertical metrics

Roku sets the first baseline one ascent (`usWinAscent`) below a label's
top. The sources' ascents put text about a third of an em lower than the
system font in the same label, so the build writes ascent 850 and
descent 250 to hhea and OS/2 alike (`ASCENT`, `DESCENT`), which lines the
baselines up (measured on a Roku, OS 15.3).
