# Mass TV

A Roku app for [Music Assistant](https://www.music-assistant.io/): browse
and play your music on the TV with the remote, and let Music Assistant
play to the TV.

Mass TV is both a client and a player. As a client it talks to your own
Music Assistant server: Home (recently played and recommendations),
Library (playlists, albums, artists, and tracks, as grids or lists, with
sorting), Browse (your music sources), Search, Now Playing, and the
queue. As a player it takes the streams Music Assistant sends to the TV,
so anything that controls Music Assistant (its web UI, phone app, or Home
Assistant) can play there.

- One profile per Music Assistant user, each on its own server, with a
  "Who's listening?" picker when there are several.
- Link a profile with the remote (server address, username, and
  password), or scan a QR code to finish on your phone; servers on your
  network are found automatically (mDNS).
- Roku's screen reader (Audio Guide) reads every screen.
- A bundled font for Chinese, Japanese, Korean, and emoji in titles and
  names, which Roku's own font can't show.

Mass TV is an independent project. It is not made by, affiliated with,
or endorsed by Music Assistant, the Open Home Foundation, or Roku.

## Requirements

- Music Assistant 2.10 or newer.
- A Roku running Roku OS 15.1 or newer.
- For playback on the TV, Music Assistant's **Media Assistant (Roku)**
  player provider, with its Roku app ID set to Mass TV's: `dev` for a
  sideloaded build (soon installable via the Roku Store). Mass TV plays
  the same deep links as the Media Assistant Roku app, so the provider
  needs nothing else. Settings > This TV's player shows the app ID to use.

## Building

You need Node.js 22, Python 3 (with `venv`), and GNU Make 4.3 or newer.

    npm ci
    make build        # debug build into build/debug
    make release      # release build into build/release
    make zip          # sideload package out/masstv-debug.zip
    make zip-release  # sideload package out/masstv-release.zip
    make check        # lint, unit tests, and the end-to-end test

`make check` runs everything off-device: the unit tests and the whole app
run in the `brs-cli` simulator (brs-node), the end-to-end test against
`tools/fake_ma.py`, a fake Music Assistant server. No Roku or Music
Assistant is needed.

## Running on a Roku

Native Roku Store app installation coming soon ...

## Sideloading on a Roku

Put the Roku in [developer mode](https://developer.roku.com/docs/developer-program/getting-started/developer-setup.md),
then name it and give its address and developer password in the
environment or in `.env`:

    ROKU_LIVINGROOM_IP=192.0.2.50
    ROKU_DEV_PASSWORD=...

and use `ROKU=<name>` with the device targets:

    ROKU=livingroom make deploy       # sideload the debug build
    ROKU=livingroom make console      # the BrightScript console
    ROKU=livingroom make logs         # the debug build's log
    ROKU=livingroom make screenshot

Debug builds serve their log at `http://<roku>:8889/`. `tools/roku.py`
has more (keys, deep links, packaging); run it without arguments for
help.

## Images and the bundled font

The app's images (`src/images/`) and its bundled font (`src/fonts/`) are
generated, not kept in git: `tools/make_images.py` draws the icons,
splash screens, and other images (Pillow), and `tools/make_font.py`
builds the font from Noto sources (fontTools). The build and test
targets depend on them, so the first `make` downloads the source fonts
pinned in `fonts/sources.txt` (about 40 MB, into `fonts/source/`,
checksums verified), installs the pinned Pillow and fontTools
(`tools/requirements.txt`) into `.venv`, and generates everything (under
a minute). After that, each is remade only when its script, inputs,
sources, or tool versions change. `make assets` does just this step.
`fonts/README.md` explains the font and how to choose its characters.

## License

Mass TV is licensed under the Apache License 2.0 (`LICENSE`).

The bundled font (`src/fonts/`) is built from Noto Sans, Noto Sans CJK,
Noto Emoji, Noto Sans Arabic, and Noto Sans Hebrew, and like them is
under the SIL Open Font License 1.1
(`fonts/OFL-*.txt`). The logo's lettering is drawn in Roboto, also under
the SIL Open Font License (`fonts/OFL-Roboto.txt`).

## Support

Questions, problems, and ideas: open an issue on this repository.
