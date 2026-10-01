#!/usr/bin/env python3
"""End-to-end test of the Mass TV debug build in the brs-cli simulator,
against tools/fake_ma.py. No Roku or Music Assistant needed.

Checks: profile injection and bootstrap, token renewal, player id discovery, playback
driven by MA-style ECP deep links, pause via keypress, next track, remote
navigation, the debug log endpoints, and that no token reaches the logs.

Usage: python3 tools/e2e_sim.py [--zip out/masstv-debug.zip] [--keep]
"""

import argparse
import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRS = os.path.join(ROOT, "node_modules", ".bin", "brs-cli")
# Not 8095: a real MA server may be running on this host.
FAKE_PORT = 18095
# The fake answers the server screen's mDNS queries here (unicast on
# loopback), so the test needs no network and sees no real servers.
FAKE_MDNS_PORT = 18353
# A second fake Music Assistant, for a profile on another server (its
# test user has the same user ID as the first's).
FAKE2_PORT = 18096
LOG_URL = "http://127.0.0.1:8889"
ECP_URL = "http://127.0.0.1:8060"

results = []

# Timing, reported with each check (the time since the previous check and
# where it went): key presses (count, total, slowest), and requests to the
# app's /state and /log endpoints (count, total).
T = {"last": time.time(), "start": time.time()}
STATS = {}


def stat(kind, secs):
    s = STATS.setdefault(kind, [0, 0.0, 0.0])
    s[0] += 1
    s[1] += secs
    s[2] = max(s[2], secs)


def timing():
    now = time.time()
    parts = ["+%.1f s" % (now - T["last"])]
    for kind in ["key", "seq", "state", "log"] + sorted(k for k in STATS if k.startswith("key ")):
        n, total, worst = STATS.get(kind, [0, 0.0, 0.0])
        if n:
            parts.append("%s %d: %.1f s (max %.2f)" % (kind, n, total, worst))
    T["last"] = now
    STATS.clear()
    return "[" + ", ".join(parts) + "]"


# Each check must come within this many seconds of the previous one; a
# stuck step (a wait that never ends, the simulator's ECP hanging) then
# fails fast with a report instead of stalling the run.
CHECK_BUDGET = 45


class Stalled(Exception):
    pass


def on_alarm(signum, frame):
    raise Stalled("no check completed within %d s" % CHECK_BUDGET)


class StopEarly(Exception):
    """--stop-after reached: end the run here, as a finished one."""


STOP_AFTER = [None]


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -- " + detail) + "  " + timing(), flush=True)
    signal.alarm(CHECK_BUDGET)
    if STOP_AFTER[0] and STOP_AFTER[0] in name:
        raise StopEarly(name)


def http(url, data=None, method=None, timeout=5, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    finally:
        if url.startswith(LOG_URL + "/state"):
            stat("state", time.time() - t0)
        elif url.startswith(LOG_URL + "/log"):
            stat("log", time.time() - t0)
        elif url.startswith(LOG_URL + "/seq"):
            stat("seq", time.time() - t0)


def lower_keys(v):
    # Associative arrays stored in node fields come back with lowercased
    # keys (Roku behavior, mirrored by the simulator).
    if isinstance(v, dict):
        return {k.lower(): lower_keys(x) for k, x in v.items()}
    if isinstance(v, list):
        return [lower_keys(x) for x in v]
    return v


def state():
    try:
        return lower_keys(json.loads(http(LOG_URL + "/state")))
    except Exception:  # noqa: BLE001
        return {}


def seq():
    """The app's newest log entry number (the cheap /seq endpoint; /state
    reads the app's global fields, a round trip to its render thread)."""
    try:
        return int(http(LOG_URL + "/seq").strip())
    except Exception:  # noqa: BLE001
        return 0


def wait_for(pred, timeout=30, interval=0.1):
    end = time.time() + timeout
    last = {}
    while time.time() < end:
        last = state()
        if last and pred(last):
            return last
        time.sleep(interval)
    return last


def wait_for_fake(pred, timeout=5, interval=0.2):
    """Polls the fake MA's state until pred(queue) holds; returns the state."""
    end = time.time() + timeout
    fs = {}
    while time.time() < end:
        fs = json.loads(http("http://127.0.0.1:%d/_fake/state" % FAKE_PORT))
        if pred(fs["queue"]):
            return fs
        time.sleep(interval)
    return fs


def wait_for_log(pred, since, timeout=5, interval=0.1):
    """Polls the app's log for an entry after seq `since` matching pred."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            for line in http(LOG_URL + "/log?since=%d" % since).splitlines():
                if pred(line):
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval)
    return False


def find_log(pred, since, timeout=5, interval=0.1):
    """Like wait_for_log, but returns the first matching entry (parsed)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            for line in http(LOG_URL + "/log?since=%d" % since).splitlines():
                if pred(line):
                    return json.loads(line)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval)
    return None


def is_focus(widget=None, **fields):
    """A predicate for the app's focus log lines (category "focus", the
    widget as the message, its details in the data, what the screen
    reader said for the move as `said`): `widget` (nav, buttons, tabs,
    letters, menu, rows, items, tracks, lines, servers, address; None for
    any), and fields that must match exactly, or as a substring for
    `name` and `said` (e.g. label="Favorite", id="home", kind="track",
    name="Digital Love", said="button 2 of 5")."""
    def pred(line):
        if '"c":"focus"' not in line:
            return False
        entry = json.loads(line)
        if widget is not None and entry.get("m") != widget:
            return False
        d = entry.get("d") or {}
        for k, v in fields.items():
            if k in ("name", "said"):
                if v not in str(d.get(k, "")):
                    return False
            elif d.get(k) != v:
                return False
        return True
    return pred


def is_ring(widget, shown):
    """A predicate for a widget's focus ring appearing (shown True) or going
    away (category "ring", the widget kind as the message)."""
    def pred(line):
        if '"c":"ring"' not in line:
            return False
        entry = json.loads(line)
        return entry.get("m") == widget and (entry.get("d") or {}).get("shown") is shown
    return pred


def last_log(pred, since, timeout=5, settle=0.6):
    """The last entry after seq `since` matching pred (parsed), once one
    has appeared and `settle` seconds passed: where a cursor ended up when
    it may move twice for one key (focus arriving, then aimed)."""
    if not find_log(pred, since, timeout=timeout):
        return None
    time.sleep(settle)
    found = None
    for line in http(LOG_URL + "/log?since=%d" % since).splitlines():
        if pred(line):
            found = json.loads(line)
    return found


def said(*parts, since, timeout=5):
    """True once the app logged a screen-reader line (speech.say) holding
    every part: what Audio Guide would say for Mass TV's own widgets."""
    def pred(line):
        return '"c":"speech"' in line and all(p in line for p in parts)
    return wait_for_log(pred, since, timeout=timeout)


# The nav bar's entries, left to right (MainScene's m.nav.entries).
NAV = ["home", "library", "browse", "search", "nowplaying", "queue", "settings"]


def nav_to(entry, select=True):
    """Up to the nav bar, then Left/Right from wherever Up aimed (the entry
    above the cursor) to `entry`, and OK (unless select is False). Returns
    the entry Up aimed at."""
    # Up first moves within a list until its top row; then the bar takes it.
    aimed = None
    for _ in range(12):
        since = seq()
        key("Up")
        aimed = find_log(lambda l: '"c":"nav"' in l and '"m":"aim up"' in l, since, timeout=1)
        if aimed:
            break
    got = (aimed or {}).get("d", {}).get("entry", "")
    if got not in NAV:
        return got
    steps = NAV.index(entry) - NAV.index(got)
    for _ in range(abs(steps)):
        key("Right" if steps > 0 else "Left")
    if select:
        key("Select")
    return got


LETTERS = ["All", "#"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]


def letter_to(start, target):
    """Left/Right along the letter row from `start` to `target`."""
    steps = LETTERS.index(target) - LETTERS.index(start) if start in LETTERS else 0
    for _ in range(abs(steps)):
        key("Right" if steps > 0 else "Left")


def on_screen(st, name):
    return st.get("screen") == name, "screen=%r" % st.get("screen")


def ecp_input(query):
    """Sends deep-link parameters to the running app (ECP /input)."""
    http(ECP_URL + "/input?" + query, data=b"", method="POST")


MIN_KEY_GAP = 0.35
LAST_KEY = [0.0]


def key(k, timeout=2):
    """Presses a remote key, then waits until the app logs something (every
    key it handles logs at DEBUG) instead of pausing a fixed time."""
    # brs-cli dropped a key press that came about 0.3 s after the previous
    # one (once /seq made the waits short): keep a gap.
    gap = LAST_KEY[0] + MIN_KEY_GAP - time.time()
    if gap > 0:
        time.sleep(gap)
    t0 = time.time()
    before = seq()
    # brs-cli's ECP server sometimes stops answering for a while: a short
    # timeout and one retry instead of a long wait.
    for attempt in range(2):
        try:
            http(ECP_URL + "/keypress/" + k, data=b"", method="POST", timeout=2)
            break
        except Exception:  # noqa: BLE001
            stat("key ecp retry " + k, time.time() - t0)
    LAST_KEY[0] = time.time()
    end = time.time() + timeout
    while time.time() < end:
        # Gentle polling: hammering the simulator's sockets starved its
        # ECP server (keys got lost).
        time.sleep(0.15)
        if seq() > before:
            stat("key", time.time() - t0)
            return
    # Nothing logged: the whole timeout was spent waiting.
    stat("key", time.time() - t0)
    stat("key timeout " + k, timeout)


def hold(k, seconds):
    """Holds a remote key (ECP keydown, then keyup after `seconds`)."""
    gap = LAST_KEY[0] + MIN_KEY_GAP - time.time()
    if gap > 0:
        time.sleep(gap)
    http(ECP_URL + "/keydown/" + k, data=b"", method="POST", timeout=2)
    time.sleep(seconds)
    http(ECP_URL + "/keyup/" + k, data=b"", method="POST", timeout=2)
    LAST_KEY[0] = time.time()


def primary_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=os.path.join(ROOT, "out", "masstv-debug.zip"))
    ap.add_argument("--keep", action="store_true", help="leave processes running at the end")
    ap.add_argument("--stop-after", metavar="TEXT",
                    help="end the run after the first check whose name contains TEXT (the checks run in one "
                         "sequence, each from the state the last left, so this is the way to run part of it)")
    a = ap.parse_args()
    STOP_AFTER[0] = a.stop_after
    a.zip = os.path.abspath(a.zip)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    fake_log = open(os.path.join(ROOT, "logs", "e2e-fake-ma.log"), "w")
    sim_log = open(os.path.join(ROOT, "logs", "e2e-sim.log"), "w")

    # The app finds its player in players/all by its own address, not the
    # loopback address the fake reaches it at.
    fake = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools", "fake_ma.py"), "--roku", "127.0.0.1",
                             "--roku-player-ip", primary_ip(),
                             "--port", str(FAKE_PORT), "--host", "127.0.0.1", "--mdns-port", str(FAKE_MDNS_PORT),
                             "--mdns-count", "6"],
                            stdout=fake_log, stderr=subprocess.STDOUT)
    fake2_log = open(os.path.join(ROOT, "logs", "e2e-fake-ma2.log"), "w")
    fake2 = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "tools", "fake_ma.py"), "--roku", "127.0.0.1",
                              "--port", str(FAKE2_PORT), "--host", "127.0.0.1"],
                             stdout=fake2_log, stderr=subprocess.STDOUT)
    sim = None
    signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(CHECK_BUDGET + 30)  # the first check also waits for boot
    try:
        for _ in range(40):
            try:
                http("http://127.0.0.1:%d/info" % FAKE_PORT)
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        # The test's own API calls use a separate token: the app renews and
        # revokes the one it is given, which expires within the renewal window.
        token = http("http://127.0.0.1:%d/_fake/token?user=testuser" % FAKE_PORT)
        near_expiry = http("http://127.0.0.1:%d/_fake/token?user=testuser&days=30" % FAKE_PORT)
        # The fake reports the Roku player at the simulator's own address.
        # Library pages of two items, so the fake's short listings take
        # several pages, placeholders, and the end search.
        link = ("masstv_server=127.0.0.1:%d,masstv_token=%s,masstv_log=DEBUG,masstv_mdns_to=127.0.0.1:%d,"
                "masstv_page_size=2") % (FAKE_PORT, near_expiry, FAKE_MDNS_PORT)
        sim = subprocess.Popen([BRS, "--ecp", "-k", link, a.zip], stdout=sim_log, stderr=subprocess.STDOUT,
                               cwd=os.path.dirname(a.zip))

        st = wait_for(lambda s: s.get("screen") == "home", timeout=40)
        check("boots to home with injected profile", st.get("screen") == "home", "screen=%r" % st.get("screen"))
        st = wait_for(lambda s: s.get("session", {}).get("schema") == 77, timeout=15)
        check("session has server and user", st.get("session", {}).get("server") == "http://127.0.0.1:%d" % FAKE_PORT
              and st.get("session", {}).get("displayname") == "Test User", json.dumps(st.get("session")))
        check("state endpoint redacts the token", st.get("session", {}).get("token") == "<redacted>")
        check("server schema read from /info", st.get("session", {}).get("schema") == 77, str(st.get("session")))
        check("the screen reader names Home's first row and where it landed",
              said("Recently played, ", " of ", since=0, timeout=10),
              "no speech of the first row's name and item")
        # No one has moved the cursor since launch, so Play is taken as
        # Music Assistant's (its pause and play are this same key): it
        # would start MA's queue (nothing yet: no player id so early), not
        # Home's focused card.
        since = seq()
        key("Play")
        check("Play before any cursor move doesn't play the focused card",
              wait_for_log(lambda l: '"m":"global toggle"' in l, since)
              and not wait_for_log(lambda l: '"m":"play_media"' in l, since, timeout=1.5),
              "no global toggle, or a play_media of the card")
        # A Streaming Store deep link (contentId and mediaType, as Roku's test
        # tools send them) finds no catalog: it's rejected, nothing plays, and
        # Home stays.
        since = seq()
        ecp_input("contentId=http%3A%2F%2F192.0.2.10%2Fvideo.mp4&mediaType=movie")
        rejected = wait_for_log(lambda l: '"m":"deep link rejected"' in l and "store deep link" in l, since)
        st = state()
        check("a Streaming Store deep link is rejected, and Home stays",
              rejected and st.get("screen") == "home"
              and st.get("nowplaying", {}).get("status") in (None, "idle", "stopped"),
              "rejected=%r screen=%r nowplaying=%r" % (rejected, st.get("screen"), st.get("nowplaying")))

        # A Detail page of an item in Home's "Recently played" offers to
        # remove it (More); Home's row reloads without it.
        key("Select")  # the row's first card: the album Ágætis byrjun
        st = wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        since = seq()
        for _ in range(4):
            key("Right")
        wait_for_log(is_focus("buttons", label="More"), since)
        key("Select")
        since = seq()
        found = False
        for _ in range(5):
            key("Down")
            if wait_for_log(is_focus("menu", label="Remove from Recently played"), since, timeout=1):
                found = True
                break
        check("a recently played item's More menu offers to remove it", found,
              "no 'Remove from Recently played' in the menu")
        since = seq()
        key("Select")
        check("removing it reloads Home's row without it",
              wait_for_log(lambda l: '"c":"home"' in l and '"m":"recently played reloaded"' in l and '"items":2' in l, since),
              "no reload of the row with 2 items")
        unplayed = json.loads(http("http://127.0.0.1:%d/_fake/state" % FAKE_PORT)).get("unplayed", [])
        check("MA was asked to mark the logged item unplayed", ["example_music--fake01", "al2", "album"] in unplayed, json.dumps(unplayed))
        key("Back")
        wait_for(lambda s: s.get("screen") == "home", timeout=8)
        old_id = json.loads(base64.urlsafe_b64decode(near_expiry.split(".")[1] + "==="))["jti"]
        end = time.time() + 10
        revoked = []
        while time.time() < end and old_id not in revoked:
            revoked = json.loads(http("http://127.0.0.1:%d/_fake/state" % FAKE_PORT)).get("revoked", [])
            time.sleep(0.5)
        check("near-expiry token renewed and the old one revoked", old_id in revoked, json.dumps(revoked))

        http("http://127.0.0.1:%d/_fake/play?uri=%s" % (FAKE_PORT, urllib.parse.quote("example_music--fake01://album/al1")),
             data=b"", method="POST")
        st = wait_for(lambda s: s.get("nowplaying", {}).get("title") == "One More Time", timeout=15)
        np = st.get("nowplaying", {})
        check("MA deep link starts playback", np.get("title") == "One More Time" and np.get("status") in ("loading", "playing"),
              json.dumps(np))
        # The fake enqueues the next item a moment after the play; wait for
        # it rather than sampling the instant the title appears.
        st = wait_for(lambda s: s.get("nowplaying", {}).get("hasnext") is True, timeout=10)
        np = st.get("nowplaying", {})
        check("enqueued next item held", np.get("hasnext") is True, json.dumps(np))
        st = wait_for(lambda s: s.get("session", {}).get("playerid") == "ROKU_FAKE0001", timeout=10)
        check("player id learned", st.get("session", {}).get("playerid") == "ROKU_FAKE0001", json.dumps(st.get("session")))

        # brs-cli's Video node never reports playing or paused, so the
        # status can't change here. Check what we control: the Play key
        # reaches the player as a toggle. How node states drive the status
        # (pause, resume) is unit-tested in PlaybackTests. With an item
        # focused (Home's cards) the key would play that item instead, so
        # from the nav bar.
        since = seq()
        key("Up")
        wait_for_log(is_focus("nav"), since)
        since = seq()
        key("Play")
        found = wait_for_log(lambda line: '"m":"command toggle"' in line, since)
        check("Play key off any item reaches the player as a toggle", found, "no 'command toggle' log entry after the key")
        since = seq()
        key("Down")  # back to Home's rows, where nav_to starts from
        wait_for_log(is_focus("items", screen="home"), since)

        http("http://127.0.0.1:%d/api" % FAKE_PORT, data=json.dumps({"command": "player_queues/next", "args": {"queue_id": "ROKU_FAKE0001"}}).encode(),
             method="POST", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        st = wait_for(lambda s: s.get("nowplaying", {}).get("title") == "Aerodynamic", timeout=10)
        check("next track via MA", st.get("nowplaying", {}).get("title") == "Aerodynamic", json.dumps(st.get("nowplaying")))
        # The fake's tracks carry no year; the playing bar's comes from their
        # album, asked once (the fake's albums are from 2001).
        def queue_year(s):
            return (((s.get("queuestate") or {}).get("current_item") or {}).get("media_item") or {}).get("year")
        st = wait_for(lambda s: queue_year(s) == "2001", timeout=15)
        check("the playing track's year comes from its album", queue_year(st) == "2001", "year=%r" % queue_year(st))

        opened = seq()
        nav_to("library")
        st = wait_for(lambda s: s.get("screen") == "library", timeout=8)
        check("remote navigation to Library", st.get("screen") == "library", "screen=%r" % st.get("screen"))
        # Library opens on its tab row with the cursor on the shown tab: OK
        # there reloads the tab (a new page request) and, as OK on any tab,
        # goes down to what it shows: here the first playlist.
        wait_for_log(lambda l: '"c":"library"' in l and '"m":"page"' in l, opened, timeout=8)
        since = seq()
        key("Select")
        check("OK on the shown Library tab reloads it",
              wait_for_log(lambda l: '"m":"tab ok"' in l and '"reload":true' in l, since)
              and wait_for_log(lambda l: '"c":"library"' in l and '"m":"page"' in l, since),
              "no 'tab ok' reload and new page after OK")
        # The focus may land while the row is still a placeholder; it's said
        # by name once its page fills it in.
        check("OK on Playlists goes down to the first playlist",
              wait_for_log(is_focus("items", index=0, screen="library"), since, timeout=8)
              and wait_for_log(lambda l: '"c":"speech"' in l and ("Flow" in l or "Late Night" in l), since, timeout=8),
              "no focus on the first item, or no playlist said")
        since = seq()
        key("Up")
        wait_for_log(is_focus("tabs", id="playlists"), since)
        # An album with a description: More offers "View description",
        # which opens the text panel; the fake's first album (Discovery)
        # has a long text, so the panel scrolls; Back closes it.
        since = seq()
        key("Right")
        key("Select")
        wait_for_log(lambda l: '"m":"page"' in l and '"tab":"albums"' in l, since, timeout=8)
        # Two-item pages: the end search finds the three albums, a
        # placeholder stands in for the third, and its page fills it.
        check("Albums' length comes from the end search, and its second page fills in",
              wait_for_log(lambda l: '"m":"range"' in l and '"total":3' in l, since, timeout=8)
              and wait_for_log(lambda l: '"m":"placeholders"' in l and '"extent":3' in l, since, timeout=8)
              and wait_for_log(lambda l: '"m":"page"' in l and '"tab":"albums"' in l and '"page":1' in l
                               and '"shown":1' in l, since, timeout=8),
              "no range of 3, placeholder, and filled second page")
        # Albums has the letter row under the tabs: OK on the tab went down
        # to it, on the shown letter (All). The fake sorts like MA (Ágætis
        # byrjun, async, Discovery).
        landed = find_log(is_focus("letters"), since, timeout=5)
        letter = (landed or {}).get("d", {}).get("label", "")
        check("OK on the Albums tab goes down to the letter row, on the shown letter", letter == "All",
              "letter=%r" % letter)
        check("the screen reader names the letter row",
              said("Letters, %s, %d of 28" % (letter, LETTERS.index(letter) + 1 if letter in LETTERS else 0), since=since),
              "no speech of the letter row")
        letter_to(letter, "B")
        since = seq()
        key("Select")
        check("an empty letter says so",
              wait_for_log(lambda l: '"m":"empty"' in l and "No albums under B." in l, since, timeout=8),
              "no 'No albums under B.'")
        since = seq()
        key("Down")
        check("Down from an empty letter stays on the letter row",
              wait_for_log(lambda l: '"m":"nothing below"' in l, since)
              and not wait_for_log(is_focus("items"), since, timeout=0.5),
              "no 'nothing below', or an item got the focus")
        letter_to("B", "D")
        since = seq()
        key("Select")
        check("a letter shows only its albums, found by the start search",
              wait_for_log(lambda l: '"m":"letter start"' in l and '"letter":"D"' in l, since, timeout=8)
              and wait_for_log(lambda l: '"m":"page"' in l and '"letter":"D"' in l and '"shown":1' in l, since, timeout=8),
              "no letter start and one-album page for D")
        since = seq()
        key("Down")
        check("Down from the letter row focuses Discovery",
              wait_for_log(is_focus("items", kind="album", name="Discovery"), since),
              "no album focus on Discovery")
        check("the screen reader says the album, its second line, then its place",
              said('"text":"Discovery, Daft Punk, 2001, button 1 of ', since=since),
              "no speech of Discovery's title, artist and year, and place")
        # Play/Pause held: Now Playing over the Library; Back returns to the
        # Library as it was, focus still on Discovery (the next OK opens it).
        since = seq()
        hold("Play", 1.0)
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("holding Play/Pause opens Now Playing over the current screen",
              st.get("screen") == "nowplaying"
              and wait_for_log(lambda l: '"m":"Play held: Now Playing"' in l and '"over":"library"' in l, since),
              "screen=%r" % st.get("screen"))
        # The fake reports FLAC 16/44.1 with the generated test media, else
        # its built-in tone (WAV, 16-bit, 22.05 kHz, shown to one decimal).
        quality = ("FLAC", "16-bit", "44.1 kHz") if os.path.isdir(os.path.join(ROOT, "test-media")) else ("WAV", "16-bit", "22 kHz")
        check("Now Playing shows the stream's quality from MA's stream details",
              wait_for_log(lambda l: '"c":"nowplaying"' in l and '"m":"quality"' in l
                           and ("\\u00B7".join(" %s " % q for q in quality).strip() in l
                                or " · ".join(quality) in l), since),
              "no quality line %s" % " · ".join(quality))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "library", timeout=8)
        check("Back from that Now Playing returns to the Library", *on_screen(st, "library"))
        since = seq()
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        check("OK on an album opens its Detail page (focus kept through Now Playing)", *on_screen(st, "detail"))
        # Now Playing held open over the album's page, then closed: the nav
        # bar marks Library again (the nav screen beneath the page).
        hold("Play", 1.0)
        wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        closed = seq()  # (the checks below still look from `since`)
        key("Back")
        wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        marked = last_log(lambda l: '"c":"nav"' in l and '"m":"current"' in l, closed)
        check("after Now Playing over a page closes, the nav bar marks the screen beneath",
              (marked or {}).get("d", {}).get("id") == "library", json.dumps(marked))
        check("an album's info ends with its source",
              wait_for_log(lambda l: '"c":"detail"' in l and '"m":"info"' in l and "tracks" in l and "Example Music" in l, since, timeout=8),
              "no info line with its track count and Example Music")
        check("the screen reader names the album before its first button",
              said("Discovery, album", "Play, button 1 of 5", since=since),
              "no speech of the album and Play")
        # Play/Pause on a focused track plays that track (MA's "play now"),
        # even with something playing.
        since = seq()
        key("Down")
        wait_for_log(is_focus("tracks"), since)
        key("Down")
        since = seq()
        key("Down")
        wait_for_log(is_focus("tracks", name="Digital Love"), since)
        since = seq()
        key("Play")
        fs = wait_for_fake(lambda q: (q.get("current_item") or {}).get("name") == "Digital Love")
        check("Play/Pause on a focused track plays just that track, over what plays",
              (fs["queue"].get("current_item") or {}).get("name") == "Digital Love"
              and wait_for_log(lambda l: '"m":"play_media"' in l and "track/t3" in l and '"option":"play"' in l, since),
              json.dumps((fs["queue"].get("current_item") or {}).get("name")))
        # Once the app knows that track is the one playing, another tap on
        # it pauses (or resumes) instead of starting it over.
        wait_for(lambda s: ((s.get("queuestate") or {}).get("current_item") or {}).get("name") == "Digital Love", timeout=10)
        since = seq()
        key("Play")
        check("Play/Pause on the playing track pauses it instead of restarting it",
              wait_for_log(lambda l: '"m":"command toggle"' in l, since)
              and not wait_for_log(lambda l: '"m":"play_media"' in l, since, timeout=0.5),
              "no toggle, or a new play_media")
        # OK on a track opens its page (album and artists below the
        # buttons); its Play plays the track, and More's "Play album from
        # here" the album from it (which leaves Aerodynamic, with synced
        # lyrics, playing for the Lyrics checks).
        since = seq()
        key("Up")
        wait_for_log(is_focus("tracks", name="Aerodynamic"), since)
        since = seq()
        key("Select")
        check("OK on an album's track opens the track's page",
              wait_for_log(lambda l: '"m":"track page"' in l and '"Aerodynamic"' in l and "album/al1" in l, since, timeout=8),
              "no track page for Aerodynamic from the album")
        check("a track's info is its length and source",
              wait_for_log(lambda l: '"m":"info"' in l and "3:32" in l and "Example Music" in l, since, timeout=8),
              "no info line with 3:32 and Example Music")
        since = seq()
        key("Select")  # Play, the first button
        fs = wait_for_fake(lambda q: (q.get("current_item") or {}).get("name") == "Aerodynamic")
        check("the track page's Play plays just the track",
              (fs["queue"].get("current_item") or {}).get("name") == "Aerodynamic"
              and wait_for_log(lambda l: '"m":"play_media"' in l and "track/t2" in l and '"option":"play"' in l, since),
              json.dumps((fs["queue"].get("current_item") or {}).get("name")))
        since = seq()
        for _ in range(4):
            key("Right")
        wait_for_log(is_focus("buttons", label="More"), since)
        key("Select")
        since = seq()
        found = False
        for _ in range(5):
            key("Down")
            if wait_for_log(is_focus("menu", label="Play album from here"), since, timeout=1):
                found = True
                break
        check("a track page's More offers Play album from here", found, "no 'Play album from here' in the menu")
        key("Select")
        # Discovery is three tracks; MA drops the one before Aerodynamic.
        fs = wait_for_fake(lambda q: (q.get("current_item") or {}).get("name") == "Aerodynamic" and q.get("items") == 2)
        check("Play album from here plays the track's album from it",
              (fs["queue"].get("current_item") or {}).get("name") == "Aerodynamic" and fs["queue"].get("items") == 2,
              json.dumps({"current": (fs["queue"].get("current_item") or {}).get("name"), "items": fs["queue"].get("items")}))
        since = seq()
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        wait_for_log(is_focus("tracks"), since, timeout=3)
        # Back from the track list goes up to the buttons (the one last
        # used), not off the page.
        since = seq()
        key("Back")
        st = state()
        check("Back from an album's tracks goes to its buttons",
              wait_for_log(is_focus("buttons", label="Play"), since) and st.get("screen") == "detail",
              "screen=%r, no button focus on Play" % st.get("screen"))
        since = seq()
        for _ in range(4):
            key("Right")
        wait_for_log(is_focus("buttons", label="More"), since)
        since = seq()
        key("Select")
        key("Up")  # the menu wraps to its last item
        check("the album's More menu ends with View description",
              wait_for_log(is_focus("menu", label="View description"), since),
              "no menu focus on View description")
        check("the screen reader says the menu's title, then its rows",
              said("Discovery, menu, Play next, button 1 of 4", since=since)
              and said("View description, button 4 of 4", since=since),
              "no speech of the menu title and rows")
        since = seq()
        key("Select")
        check("View description opens the text panel, scrollable for a long text",
              wait_for_log(lambda l: '"c":"textpanel"' in l and '"m":"layout"' in l and '"scrolls":true' in l, since),
              "no scrollable text panel layout")
        since = seq()
        key("Down")
        check("Down scrolls the text panel",
              wait_for_log(lambda l: '"c":"textpanel"' in l and '"m":"scroll"' in l and '"moved":true' in l, since),
              "no text panel scroll")
        since = seq()
        key("Back")
        check("Back closes the text panel and refocuses More",
              wait_for_log(lambda l: '"m":"menu closed"' in l, since)
              and wait_for_log(is_focus("buttons", label="More"), since),
              "no 'menu closed' and More focus after Back")
        key("Back")
        wait_for(lambda s: s.get("screen") == "library", timeout=8)
        # Back goes up one level at a time: the grid, the letter row (on
        # the shown letter), the tab row (on the shown tab), the nav bar
        # (on Library), then Home's entry.
        since = seq()
        key("Back")
        check("Back from the grid goes to the shown letter",
              wait_for_log(is_focus("letters", label="D"), since),
              "no letter row focus on D")
        since = seq()
        key("Back")
        check("Back from the letter row goes to the shown tab",
              wait_for_log(is_focus("tabs", id="albums"), since),
              "no tab row focus on Albums")
        since = seq()
        key("Back")
        check("Back from the tab row goes to the nav bar's Library",
              wait_for_log(is_focus("nav", id="library"), since),
              "no nav focus on library")
        # The rings follow the focus (the nav bar has had it before, so this
        # is a return to it).
        check("the focus ring moves from the tab row to the nav bar",
              wait_for_log(is_ring("nav", True), since) and wait_for_log(is_ring("tabs", False), since),
              "no nav ring shown, or the tab row's ring still shown")
        since = seq()
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "home", timeout=8)
        check("Back from the nav bar returns home, still on the nav bar",
              st.get("screen") == "home"
              and wait_for_log(is_focus("nav", id="home"), since),
              "screen=%r, no nav focus on home" % st.get("screen"))
        key("Down")  # into Home's rows, where nav_to starts
        # Library opens where it was left while the app runs: Albums, under D,
        # with the focus on the shown tab.
        since = seq()
        nav_to("library")
        wait_for(lambda s: s.get("screen") == "library", timeout=8)
        check("Library opens on the tab and letter it was left on",
              wait_for_log(is_focus("tabs", id="albums"), since, timeout=8)
              and wait_for_log(lambda l: '"m":"page"' in l and '"tab":"albums"' in l and '"letter":"D"' in l,
                               since, timeout=8),
              "no Albums tab focus and page under D")
        key("Back")  # the tab row to the nav bar's Library
        since = seq()
        key("Back")
        wait_for(lambda s: s.get("screen") == "home", timeout=8)
        wait_for_log(is_focus("nav", id="home"), since)
        key("Down")

        # Now Playing via the nav bar.
        since = seq()
        nav_to("nowplaying")
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("nav bar reaches Now Playing", st.get("screen") == "nowplaying", "screen=%r" % st.get("screen"))
        check("the screen reader says nav bar entries with their place",
              said("Now Playing, 5 of 7", since=since),
              "no speech of the nav bar's entries")
        # Lists use rewind/fast-forward to page (Roku convention); on Now
        # Playing a tap seeks: expect a server seek (the fake re-sends the item).
        key("Fwd")
        fs = wait_for_fake(lambda q: q["elapsed_time"] >= 9)
        check("fast-forward tap on Now Playing sends a seek", fs["queue"]["elapsed_time"] >= 9, json.dumps(fs["queue"]["elapsed_time"]))
        # Instant replay rewinds 10 s (Roku certification 4.9), also a
        # server seek.
        key("InstantReplay")
        before = fs["queue"]["elapsed_time"]
        fs2 = wait_for_fake(lambda q: q["elapsed_time"] < before)
        check("instant replay seeks back", fs2["queue"]["elapsed_time"] < before,
              "%r -> %r" % (before, fs2["queue"]["elapsed_time"]))

        # Now Playing's buttons are two rows: playback (with Shuffle,
        # Repeat, and Favorite), then Queue, Lyrics, and More. Down goes to
        # the second row; Lyrics sits before More, its last button, and
        # Queue before Lyrics. Queue and the lyrics open on top of Now
        # Playing; the fake's Aerodynamic has invented synced lyrics.
        since = seq()
        key("Down")
        check("Down from Now Playing's transport row reaches its second row",
              wait_for_log(lambda l: is_focus("buttons")(l)
                           and any('"label":"%s"' % b in l for b in ("Queue", "Lyrics", "More")), since),
              "no focus on the second row")
        for _ in range(4):
            key("Right")
        since = seq()
        key("Left")
        check("Now Playing has a Lyrics button before More",
              wait_for_log(is_focus("buttons", label="Lyrics"), since),
              "no button focus on Lyrics")
        since = seq()
        key("Left")
        check("Now Playing has a Queue button before Lyrics",
              wait_for_log(is_focus("buttons", label="Queue"), since),
              "no button focus on Queue")
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "queue", timeout=8)
        check("Queue opens the queue", *on_screen(st, "queue"))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("Back from the queue returns to Now Playing", *on_screen(st, "nowplaying"))
        since = seq()
        key("Right")
        wait_for_log(is_focus("buttons", label="Lyrics"), since)
        since = seq()
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "lyrics", timeout=8)
        check("Lyrics opens the lyrics screen", *on_screen(st, "lyrics"))
        check("the playing track's synced lyrics load",
              wait_for_log(lambda l: '"c":"lyrics"' in l and '"m":"loaded"' in l and '"synced":true' in l, since, timeout=8),
              "no synced lyrics loaded")
        since = seq()
        key("Down")
        check("Down moves through the lyrics",
              wait_for_log(is_focus("lines"), since),
              "no line focus")
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("Back from the lyrics returns to Now Playing", *on_screen(st, "nowplaying"))

        # Now Playing's More (its last button): the playing track's options,
        # ending with View album, which opens the album's Detail page; Back
        # returns to Now Playing.
        since = seq()
        key("Right")
        check("Now Playing's last button is More",
              wait_for_log(is_focus("buttons", label="More"), since),
              "no button focus on More")
        since = seq()
        key("Select")
        check("More on Now Playing offers Play album from here",
              wait_for_log(lambda l: '"m":"item options"' in l and '"albumfrom"' in l, since),
              "no albumfrom among the playing track's options")
        key("Up")  # the menu wraps to its last item
        check("More on Now Playing ends with View album",
              wait_for_log(is_focus("menu", label="View album"), since),
              "no menu focus on View album")
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        check("View album opens the playing track's album", *on_screen(st, "detail"))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("Back from that album returns to Now Playing", *on_screen(st, "nowplaying"))

        # Up from the second row goes to the transport row first.
        since = seq()
        key("Up")
        check("Up from Now Playing's second row returns to its transport row",
              wait_for_log(lambda l: is_focus("buttons")(l)
                           and any('"label":"%s"' % b in l for b in ("Prev", "Play", "Pause", "Next", "Shuffle", "Repeat", "Favorite")), since),
              "no focus on the transport row")
        # Queue (the nav bar entry after Now Playing): OK on a row opens its
        # options in Mass TV's own menu (not a Roku dialog); Back closes it
        # and the list has focus again.
        # Two more albums after it, so the queue has rows past the ones
        # the Roku already has (the playing track and the next).
        for album in ("al2", "al3"):
            http("http://127.0.0.1:%d/api" % FAKE_PORT, method="POST",
                 data=json.dumps({"command": "player_queues/play_media",
                                  "args": {"queue_id": "ROKU_FAKE0001", "media": ["example_music--fake01://album/%s" % album], "option": "add"}}).encode(),
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        opened = seq()
        aimed = nav_to("queue")
        check("Up from Now Playing's transport row reaches the nav bar", aimed in NAV, "aimed at %r" % aimed)
        st = wait_for(lambda s: s.get("screen") == "queue", timeout=8)
        check("the nav bar's Queue opens the queue", *on_screen(st, "queue"))
        wait_for_log(is_focus("items", kind="track", screen="queue"), opened, timeout=8)
        since = seq()
        key("Select")
        check("OK on a queue row opens its options menu",
              wait_for_log(is_focus("menu", label="Play now"), since),
              "no OptionsMenu focus on Play now")
        # The playback keys work over a menu too (and it stays open).
        since = seq()
        key("Play")
        check("Play/Pause over a menu reaches the player",
              wait_for_log(lambda l: '"m":"command toggle"' in l, since)
              and not wait_for_log(lambda l: '"m":"menu closed"' in l, since, timeout=0.5),
              "no 'command toggle', or the menu closed")
        key("Play")  # and back
        since = seq()
        key("Down")
        check("the playing row's menu has no Play next or Remove (MA won't move it)",
              wait_for_log(is_focus("menu"), since)
              and not wait_for_log(lambda l: is_focus("menu")(l) and ('"label":"Play next"' in l or '"label":"Remove from queue"' in l), since, timeout=0.5),
              "Play next or Remove offered on the playing row")
        since = seq()
        key("Back")
        check("Back closes the menu and refocuses the queue",
              wait_for_log(lambda l: '"m":"menu closed"' in l, since)
              and wait_for_log(is_focus("items", kind="track", screen="queue"), since),
              "no 'menu closed' and queue focus after Back")
        # The row's menu ends with Clear queue, after View artist and View
        # album (like an item's More); View album opens the row's album
        # above the queue.
        since = seq()
        key("Select")
        wait_for_log(is_focus("menu", label="Play now"), since)
        since = seq()
        key("Up")  # the menu wraps to its last item
        check("a queue row's menu ends with Clear queue",
              wait_for_log(is_focus("menu", label="Clear queue"), since),
              "no menu focus on Clear queue")
        since = seq()
        key("Up")
        check("View album comes before it",
              wait_for_log(is_focus("menu", label="View album"), since),
              "no menu focus on View album")
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "detail", timeout=8)
        check("View album opens the queue row's album", *on_screen(st, "detail"))
        since = seq()
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "queue", timeout=8)
        check("Back from that album returns to the queue", *on_screen(st, "queue"))
        wait_for_log(is_focus("items", kind="track", screen="queue"), since, timeout=8)
        # Two rows down, past the playing track and the next one the Roku
        # already has: that row can be removed, and the list shows it gone.
        before = json.loads(http("http://127.0.0.1:%d/_fake/state" % FAKE_PORT))["queue"]["items"]
        rows = last_log(lambda l: '"c":"queue"' in l and '"m":"rows"' in l, opened, settle=0)
        now_row = (rows or {}).get("d", {}).get("cursor", -1)
        key("Down")
        key("Down")
        since = seq()
        key("Select")
        wait_for_log(is_focus("menu", label="Play now"), since)
        since = seq()
        key("Down")
        check("a later row's menu offers Play next",
              wait_for_log(is_focus("menu", label="Play next"), since),
              "no menu focus on Play next")
        since = seq()
        key("Down")
        wait_for_log(is_focus("menu", label="Remove from queue"), since)
        since = seq()
        key("Select")
        reloaded = find_log(lambda l: '"c":"queue"' in l and '"m":"rows"' in l, since)
        after = json.loads(http("http://127.0.0.1:%d/_fake/state" % FAKE_PORT))["queue"]["items"]
        check("Remove from queue removes the row, and the list is read again",
              reloaded and after == before - 1,
              "items %d -> %d, reloaded %r" % (before, after, bool(reloaded)))
        cursor = (reloaded or {}).get("d", {}).get("cursor", -1)
        check("the cursor stays on its row (now the next item), not back on NOW",
              now_row >= 0 and cursor == now_row + 2, "NOW row %r, cursor %r" % (now_row, cursor))
        # Queue is a root screen (Back would ask to exit): back to Now
        # Playing through the nav bar. Up from a full-width queue row aims
        # at the current screen's entry.
        aimed = nav_to("nowplaying")
        check("Up from a full-width row aims at the current screen's entry", aimed == "queue",
              "aimed at %r" % aimed)
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=8)
        check("the nav bar returns from the queue to Now Playing", *on_screen(st, "nowplaying"))
        # Down from the nav bar aims too: from the profile entry (right end)
        # onto Now Playing's buttons lands on More, the button below it.
        nav_to("settings", select=False)
        # The nav bar wraps: Right from the profile name is Home, Left
        # from Home is the profile name again.
        since = seq()
        key("Right")
        check("Right from the profile name wraps to Home",
              wait_for_log(is_focus("nav", id="home"), since),
              "no nav focus on home")
        since = seq()
        key("Left")
        check("Left from Home wraps to the profile name",
              wait_for_log(is_focus("nav", id="settings"), since),
              "no nav focus on settings")
        since = seq()
        key("Down")
        # Aimed: the button nearest below the entry, in the first row
        # (Favorite, its rightmost).
        check("Down from the profile entry lands on the button below it",
              wait_for_log(is_focus("buttons", label="Favorite"), since),
              "no button focus on Favorite")
        # Favorite is a switch: on at once when pressed (MA's queue items keep
        # the flag they were queued with), off again on the next press.
        since = seq()
        key("Select")
        wait_for_log(lambda l: '"m":"favorite"' in l and '"add":true' in l, since)
        since = seq()
        key("Left")
        key("Right")
        check("Favorite on Now Playing turns on when pressed",
              said("Favorite, on", since=since),
              "no 'Favorite, on'")
        since = seq()
        key("Select")
        wait_for_log(lambda l: '"m":"favorite"' in l and '"add":false' in l, since)
        since = seq()
        key("Left")
        key("Right")
        check("and off again on the next press",
              said("Favorite, button", since=since),
              "no 'Favorite, button' without 'on'")

        def ma_play():
            http("http://127.0.0.1:%d/_fake/play?uri=%s" % (FAKE_PORT, urllib.parse.quote("example_music--fake01://album/al1")),
                 data=b"", method="POST")

        def ma_next():
            http("http://127.0.0.1:%d/api" % FAKE_PORT, data=json.dumps({"command": "player_queues/next", "args": {"queue_id": "ROKU_FAKE0001"}}).encode(),
                 method="POST", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})

        def ma_stop():
            ecp_input("u=%20&t=a")  # how MA's Roku provider stops playback
            wait_for(lambda s: s.get("nowplaying", {}).get("status") == "stopped", timeout=8)

        def screen_after(name, settle=1.0):
            """Waits for screen `name`, then lets a wrong flip show up."""
            wait_for(lambda s: s.get("screen") == name, timeout=8)
            time.sleep(settle)
            return state()

        def on(st, name):
            return st.get("screen") == name, "screen=%r np=%s" % (st.get("screen"), json.dumps(st.get("nowplaying")))

        def roku_listed(listed):
            http("http://127.0.0.1:%d/_fake/roku_player?listed=%d" % (FAKE_PORT, 1 if listed else 0),
                 data=b"", method="POST")

        # MA can lose and find this TV while running (its Roku provider
        # reloading): opening Settings looks among MA's players again and
        # drops a player ID MA no longer lists. Once MA lists the TV again,
        # a play asked for meanwhile looks again, says the TV is back, and
        # is sent. (Nothing may play meanwhile: a stream from MA names the
        # player, and teaches its ID back at once.)
        ma_stop()
        roku_listed(False)
        nav_to("settings")
        wait_for(lambda s: s.get("screen") == "settings", timeout=8)
        st = wait_for(lambda s: s.get("session", {}).get("playerid") == "", timeout=8)
        check("opening Settings drops a player ID MA no longer lists",
              st.get("session", {}).get("playerid") == "", json.dumps(st.get("session")))
        roku_listed(True)
        nav_to("home")
        wait_for(lambda s: s.get("screen") == "home", timeout=8)
        since = seq()
        key("Down")  # a cursor move, so Play plays the focused card
        wait_for_log(is_focus("items", screen="home"), since)
        since = seq()
        key("Play")
        check("a play with no player ID waits for a new look among MA's players",
              wait_for_log(lambda l: '"m":"play without player id: looking for the player"' in l, since)
              and wait_for_log(lambda l: '"m":"sending the play that waited for the player"' in l, since, timeout=8)
              and wait_for_log(lambda l: '"m":"play_media"' in l and "ROKU_FAKE0001" in l, since, timeout=8),
              "no wait, resend, or play_media to the player")
        check("finding the TV again says so",
              said("Reconnected to Music Assistant", since=since),
              "no 'Reconnected' toast")
        st = wait_for(lambda s: s.get("session", {}).get("playerid") == "ROKU_FAKE0001", timeout=8)
        check("the player ID is known again", st.get("session", {}).get("playerid") == "ROKU_FAKE0001",
              json.dumps(st.get("session")))

        # "Who's listening?" (via Settings > Switch profile, still signed
        # in) with music playing: arriving doesn't flip, a new track from MA
        # brings up Now Playing on top, Back dismisses it through track
        # changes until playback stops, and MA's stop returns to the picker.
        # Settings is the nav bar's last entry, shown as the profile name.
        # (Log waits here start from a recent seq, never 0: a whole ring
        # buffer is more than brs-cli's sockets send in one reply.)
        opened = seq()
        nav_to("settings")
        st = wait_for(lambda s: s.get("screen") == "settings", timeout=8)
        check("the profile name opens Settings", *on(st, "settings"))
        # Settings has tabs (Profile, This TV) over the shown tab's rows;
        # OK on the profile name goes down to its first level, the tabs.
        check("OK on the profile name lands on the shown tab",
              wait_for_log(is_focus("tabs", label="Profile"), opened, timeout=8),
              "no tab focus on Profile")
        # Down from the nav bar aims at the tab below the nav cursor, not
        # the shown one: from the profile name (the bar's right end), the
        # last tab.
        key("Up")
        for _ in range(len(NAV) - 1):
            key("Right")
        since = seq()
        key("Down")
        last_log(is_focus("tabs"), since)
        landed = [json.loads(l)["d"].get("label") for l in http(LOG_URL + "/log?since=%d" % since).splitlines()
                  if is_focus("tabs")(l)]
        check("Down from the nav bar lands on the tab below its cursor, reported once",
              landed == ["This TV"], "tab focus logged: %r" % landed)
        since = seq()
        key("Left")
        key("Down")
        wait_for_log(is_focus("rows", id="switch", screen="settings"), since)
        # The profile's "Queue collection when playing a track" is a
        # checkbox.
        since = seq()
        for _ in range(4):
            key("Down")
        check("the Profile tab ends with its checkbox",
              wait_for_log(is_focus("rows", id="listfrom"), since),
              "no focus on the listfrom row")
        since = seq()
        key("Select")
        check("OK on the checkbox checks it",
              wait_for_log(lambda l: '"m":"select listfrom"' in l, since)
              and said("checked, When checked", since=since),
              "no select or 'checked' speech")
        key("Select")  # and unchecks it again
        for _ in range(4):
            key("Up")
        since = seq()
        key("Up")
        check("Up from the first row goes to the tabs",
              wait_for_log(is_focus("tabs", label="Profile"), since),
              "no tab focus on Profile")
        since = seq()
        key("Left")
        check("Left from the first tab wraps to the last",
              wait_for_log(is_focus("tabs", label="This TV"), since),
              "no tab focus on This TV")
        since = seq()
        key("Select")
        check("OK on This TV shows its rows",
              wait_for_log(lambda l: '"m":"tab"' in l and '"shown":1' in l, since),
              "no This TV tab")
        check("OK on a tab goes down to its first row",
              wait_for_log(is_focus("rows", id="screensaver"), since),
              "no focus on the screensaver row")
        key("Up")
        # Up from either tab aims at the nav entry above it: Home.
        since = seq()
        key("Up")
        check("Up from the This TV tab goes to Home",
              wait_for_log(is_focus("nav", id="home"), since),
              "no nav focus on home")
        check("and the focus ring goes with it",
              wait_for_log(is_ring("nav", True), since) and wait_for_log(is_ring("tabs", False), since),
              "no nav ring shown, or the tab row's ring still shown")
        # Down from Home: whichever tab is nearer; then on to Profile.
        since = seq()
        key("Down")
        got = last_log(is_focus("tabs"), since)
        if (got or {}).get("d", {}).get("label") != "Profile":
            key("Left")
        since = seq()
        key("Up")
        check("and from the Profile tab",
              wait_for_log(is_focus("nav", id="home"), since),
              "no nav focus on home")
        since = seq()
        key("Down")
        got = last_log(is_focus("tabs"), since)
        if (got or {}).get("d", {}).get("label") != "Profile":
            key("Left")
        since = seq()
        key("Select")
        wait_for_log(is_focus("rows", id="switch"), since)
        key("Select")  # "Switch profile", the first entry
        st = screen_after("profiles")
        check("the picker opens, and music already playing doesn't flip it", *on(st, "profiles"))
        ma_next()
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=10)
        check("a new track on the picker shows Now Playing", *on(st, "nowplaying"))
        key("Back")
        wait_for(lambda s: s.get("screen") == "profiles", timeout=8)
        ma_next()
        st = screen_after("profiles", settle=2.0)
        check("after Back, a track change doesn't flip again", *on(st, "profiles"))
        ma_stop()
        ma_play()
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=10)
        check("new playback after a stop flips again", *on(st, "nowplaying"))
        ma_stop()
        st = wait_for(lambda s: s.get("screen") == "profiles", timeout=8)
        check("stop returns to the picker", *on(st, "profiles"))
        # The picker wraps through its button: Up from the profile to "Link
        # a new profile" (a button under the list), Down back to the
        # profile; Right from the list goes to the button too, and Left
        # from the button back to the list.
        since = seq()
        key("Up")
        check("Up from the picker's first row wraps to its Link button",
              wait_for_log(is_focus("buttons", label="Link a new profile"), since),
              "no focus on the Link a new profile button")
        since = seq()
        key("Down")
        key("Right")
        check("Right from the picker's list goes to its Link button",
              wait_for_log(is_focus("buttons", label="Link a new profile"), since),
              "no focus on the Link a new profile button after Right")
        since = seq()
        key("Left")
        # The list keeps its row, so nothing logs a focus change; the
        # screen reader says the row again as the list gets the focus.
        check("Left from the Link button returns to the picker's list",
              said("Test User, button 1 of 1", since=since),
              "no speech of the picker's row after Left")
        key("Right")
        since = seq()
        key("Down")
        check("Down from the Link button wraps to the picker's first row",
              wait_for_log(is_focus("rows", index=0, screen="profiles"), since),
              "no picker focus on row 0")

        # A profile from a second server, whose user has the same user ID as
        # the first's: the two stay separate profiles, each on its own
        # server, and the picker names the servers. Unlinking it leaves the
        # first, back on the picker.
        token2 = http("http://127.0.0.1:%d/_fake/token?user=testuser" % FAKE2_PORT)
        server2 = "http://127.0.0.1:%d" % FAKE2_PORT
        ecp_input("masstv_server=127.0.0.1%%3A%d&masstv_token=%s" % (FAKE2_PORT, token2))
        st = wait_for(lambda s: s.get("session", {}).get("server") == server2 and s.get("screen") == "home", timeout=10)
        check("a profile linked from a second server uses that server",
              st.get("session", {}).get("server") == server2, json.dumps(st.get("session")))
        nav_to("settings")
        wait_for(lambda s: s.get("screen") == "settings", timeout=8)
        key("Down")  # from the tabs to the first row
        since = seq()
        key("Select")  # "Switch profile"
        wait_for(lambda s: s.get("screen") == "profiles", timeout=8)
        check("the picker names each profile's server when they differ",
              wait_for_log(lambda l: is_focus("rows", screen="profiles")(l)
                           and "Test User  \\u00B7  127.0.0.1:%d" % FAKE2_PORT in l, since),
              "no picker row naming the second server")
        key("Select")  # the last used profile: the second server's
        st = wait_for(lambda s: s.get("session", {}).get("server") == server2 and s.get("screen") == "home", timeout=8)
        nav_to("settings")
        wait_for(lambda s: s.get("screen") == "settings", timeout=8)
        key("Down")  # from the tabs to the first row
        key("Down")
        key("Down")
        key("Select")  # "Unlink this profile"
        since = seq()
        key("Select")  # "Yes"
        st = wait_for(lambda s: s.get("screen") == "profiles", timeout=8)
        check("unlinking one server's profile keeps the other's",
              st.get("screen") == "profiles"
              and wait_for_log(is_focus("rows", label="Test User", screen="profiles"), since),
              "screen=%r" % st.get("screen"))

        # Removing the only profile signs out (its token is revoked) and
        # opens the sign-in screen: pick the profile, then Settings >
        # Remove this profile > Yes.
        key("Select")
        wait_for(lambda s: s.get("screen") == "home", timeout=8)
        nav_to("settings")
        wait_for(lambda s: s.get("screen") == "settings", timeout=8)
        key("Down")  # from the tabs to the first row
        key("Down")
        key("Down")
        key("Select")  # "Remove this profile"
        signed_out = seq()  # the server screen's mDNS list comes after this
        key("Select")  # "Yes"
        st = wait_for(lambda s: s.get("screen") == "setup", timeout=8)
        check("removing the only profile signs out to sign-in", st.get("screen") == "setup" and not st.get("session"),
              "screen=%r session=%s" % (st.get("screen"), json.dumps(st.get("session"))))

        # Signed out: the same on the sign-in screen.
        ma_play()
        st = wait_for(lambda s: s.get("screen") == "nowplaying", timeout=10)
        check("signed-out playback shows Now Playing", st.get("screen") == "nowplaying"
              and st.get("nowplaying", {}).get("title") == "One More Time", on(st, "nowplaying")[1])
        key("Back")
        st = screen_after("setup")
        check("Back returns to sign-in and stays while the music plays", st.get("screen") == "setup"
              and st.get("nowplaying", {}).get("status") == "loading", on(st, "setup")[1])
        ma_stop()
        st = screen_after("setup")
        check("signed-out stop leaves sign-in up", *on(st, "setup"))
        # The server screen starts on Link (the last server is kept) and
        # lists what the fake announces over mDNS: itself and five made-up
        # servers, more than the list's four visible rows. Down to its Now
        # Playing button, which opens the unlinked Now Playing; that stays
        # up with nothing playing, and Back returns.
        check("the server screen lists the six servers found over mDNS",
              wait_for_log(lambda l: '"m":"servers found"' in l and '"count":6' in l and "Fake MA (test)" in l,
                           signed_out, timeout=8),
              "no 'servers found' log entry with the fake's six servers")

        def focus_logged(what, since):
            if what in ("Now Playing", "Link"):
                return wait_for_log(is_focus("buttons", label=what), since)
            if what == "address":
                return wait_for_log(is_focus("address"), since)
            # A server row reads "name · address".
            return wait_for_log(lambda l: is_focus("servers")(l)
                                and json.loads(l)["d"].get("label", "").startswith(what + " "), since)

        def step(k, what, desc):
            since = seq()
            key(k)
            check(desc, focus_logged(what, since), "no focus on %s" % what)

        step("Down", "Now Playing", "Down from Link goes to the Now Playing button")
        key("Select")
        st = screen_after("nowplaying")
        check("setup's Now Playing button opens Now Playing, which stays with nothing playing", *on(st, "nowplaying"))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "setup", timeout=8)
        check("Back from it returns to setup", *on(st, "setup"))
        # Up and Down wrap through the list, the address row, and Now
        # Playing.
        step("Down", "Fake MA (test)", "Down from Now Playing wraps to the server list")
        step("Up", "Now Playing", "Up from the list's top wraps to Now Playing")
        step("Up", "address", "Up from Now Playing goes to the address")
        step("Up", "Fake MA 6", "Up from the address goes to the list's last server")
        # The list scrolls within its rows, up to the first server.
        for n in (5, 4, 3, 2):
            step("Up", "Fake MA %d" % n, "Up in the list reaches Fake MA %d" % n)
        step("Up", "Fake MA (test)", "Up in the list scrolls back to the first server")
        # Choosing a server fills the address and moves on to Link, which
        # checks the server and opens the link screen for it; Back returns.
        since = seq()
        key("Select")
        check("choosing a server moves the cursor to Link",
              wait_for_log(lambda l: '"m":"server chosen"' in l and "127.0.0.1:%d" % FAKE_PORT in l, since)
              and focus_logged("Link", since), "no 'server chosen' and Link focus")
        key("Select")
        st = wait_for(lambda s: s.get("screen") == "link", timeout=8)
        check("Link opens the link screen", *on(st, "link"))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "setup", timeout=8)
        check("Back from the link screen returns to the server screen", *on(st, "setup"))

        # A fresh, unlinked start (a reset, like a new install) opens Now
        # Playing, with the link screen beneath it.
        ecp_input("masstv_reset=1")
        st = screen_after("nowplaying")
        check("an unlinked start opens Now Playing", *on(st, "nowplaying"))
        key("Back")
        st = wait_for(lambda s: s.get("screen") == "setup", timeout=8)
        check("Back from the unlinked start goes to the link screen", *on(st, "setup"))

        # The whole ring buffer (up to 3000 entries), a page at a time:
        # brs-cli's sockets can't send it in one reply.
        pages, since = [], 0
        while True:
            page = http(LOG_URL + "/log?since=%d&limit=500" % since, timeout=15)
            lines = [l for l in page.splitlines() if l.strip()]
            if not lines:
                break
            pages += lines
            since = json.loads(lines[-1])["s"]
        logs = "\n".join(pages) + "\n"
        check("log endpoint returns entries", logs.count("\n") > 20, "lines=%d" % logs.count("\n"))
        check("AppLaunchComplete beacon sent", '"m":"launch complete"' in logs)
        check("no token in logs", token not in logs and token.split(".")[1] not in logs)
        bad = [l for l in logs.splitlines() if '"l":"ERROR"' in l]
        check("no ERROR log entries", not bad, "\n".join(bad[:5]))
        # Every focus move is said too (speech.focused): what the tests see
        # move, the screen reader announces.
        moves = [l for l in logs.splitlines() if is_focus()(l)]
        silent = [l for l in moves if not (json.loads(l).get("d") or {}).get("said")]
        check("every focus move is said for the screen reader",
              moves and not silent, "%d of %d silent: %s" % (len(silent), len(moves), "\n".join(silent[:5])))
        signal.alarm(0)
    except StopEarly as err:
        signal.alarm(0)
        print("e2e: stopped after %r (--stop-after)" % str(err), flush=True)
    except Stalled as err:
        # Where it stuck: the screen and the app's last log lines.
        signal.alarm(0)
        where = "screen=%r" % state().get("screen")
        try:
            tail = [l for l in http(LOG_URL + "/log?since=0", timeout=3).splitlines() if '"c":"fade"' not in l][-8:]
        except Exception:  # noqa: BLE001
            tail = ["(app log unreachable)"]
        check("run finished without stalling", False, "%s; %s; last app log:\n    %s" % (err, where, "\n    ".join(tail)))
    finally:
        # Save the app's log even when a check above threw.
        try:
            with open(os.path.join(ROOT, "logs", "e2e-app.log"), "w") as f:
                f.write(http(LOG_URL + "/log?since=0"))
        except Exception:  # noqa: BLE001
            pass
        if not a.keep:
            if sim:
                sim.terminate()
            fake.terminate()
            fake2.terminate()
        fake_log.close()
        fake2_log.close()
        sim_log.close()
    failed = [r for r in results if not r[1]]
    if not failed:
        print("e2e: PASS, all %d checks passed" % len(results))
        sys.exit(0)
    kept = os.path.join(ROOT, "logs", "e2e-fail-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(kept, exist_ok=True)
    for name in ("e2e-app.log", "e2e-sim.log", "e2e-fake-ma.log"):
        src = os.path.join(ROOT, "logs", name)
        if os.path.exists(src):
            shutil.copy(src, kept)
    print("=" * 60)
    print("e2e: FAILED, %d of %d checks failed:" % (len(failed), len(results)))
    for name, _, detail in failed:
        print("  FAIL %s  -- %s" % (name, detail))
    print("logs of this run kept in %s" % os.path.relpath(kept, ROOT))
    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()
