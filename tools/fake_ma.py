#!/usr/bin/env python3
"""A fake Music Assistant server for Mass TV development and tests.

Speaks enough of MA's API (POST /api, GET /info, GET /login, image proxy,
stream URLs) for Mass TV's screens, and plays the role of MA's
roku_media_assistant provider: play/next/seek/stop are sent to the Roku (or
the brs-cli simulator) as ECP /launch, /input, and /keypress calls, exactly
as the real provider does.

Stdlib only. Usage:
    python3 tools/fake_ma.py --roku 127.0.0.1 [--port 8095] [--host 0.0.0.0]
        [--media test-media] [--codec flac-44k|flac-48k|mp3|aac|flac-96k24]
        [--http-profile no_content_length|chunked|forced_content_length]
        [--mdns-port 18353 [--mdns-count 6]]

Audio comes from tools/make_test_media.py output (`make test-media`); without
it, every track is a short sine tone. --http-profile mimics MA's player
setting of the same name (MA's default is no_content_length). Each stream
request is logged with its Range header and bytes sent. --mdns-port
answers _mass._tcp.local queries sent straight to that UDP port (on the
--host address) with PTR, SRV, TXT (base_url), and A, as MA does for mDNS
legacy unicast queries; tests point the app's discovery there
(masstv_mdns_to), so no real multicast or other server is involved.

Test hooks (plain HTTP, not part of MA):
    GET  /_fake/token?user=testuser   mint a long-lived token for a fake user
                                  (&days=N: expiring in N days, default 365)
    POST /_fake/play?uri=...      act like someone pressed play in MA's UI
    GET  /_fake/state             the fake queue state, revoked token ids, and
                                  items removed from recently played
"""

import argparse
import base64
import io
import json
import math
import os
import re
import socket
import struct
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROVIDER = "example_music--fake01"
SCHEMA = 77
PLAYER_ID = "ROKU_FAKE0001"

USERS = {
    "testuser": {"user_id": "u-testuser", "username": "testuser", "display_name": "Test User", "role": "user", "password": "hunter22hunter22"},
    "alex": {"user_id": "u-alex", "username": "alex", "display_name": "Alex", "role": "user", "password": "hunter22hunter22"},
}


def img(key):
    return {"type": "thumb", "path": "https://example.invalid/%s.jpg" % key, "provider": PROVIDER,
            "remotely_accessible": True, "proxy_id": "p" + key}


def sort_name(name):
    """MA's create_sort_name, simplified: lowercase, accents off, a leading
    article moved to the end."""
    s = "".join(c for c in unicodedata.normalize("NFD", name.lower().strip()) if not unicodedata.combining(c))
    for article in ("the ", "a ", "an "):
        if s.startswith(article):
            return s[len(article):] + ", " + article.strip()
    return s


# What MA's anyascii makes of the sort names this fake can't transliterate.
TRANSLITERATED = {"坂本龍一": "banbenlongyi"}


def sort_key(item):
    """MA's search_sort_name, the key its name order uses: the sort name
    transliterated to ASCII and cut to a-z and 0-9."""
    s = TRANSLITERATED.get(item["sort_name"], item["sort_name"])
    s = s.replace("æ", "ae")
    return re.sub(r"[^a-z0-9]", "", s)


def artist(aid, name):
    return {"item_id": aid, "provider": PROVIDER, "name": name, "sort_name": sort_name(name), "media_type": "artist",
            "uri": "%s://artist/%s" % (PROVIDER, aid), "metadata": {"images": [img("ar" + aid)]}}


ARTISTS = {
    "a1": artist("a1", "Daft Punk"),
    "a2": artist("a2", "Sigur Rós"),
    "a3": artist("a3", "坂本龍一"),
}


def track(tid, name, art, album, dur):
    a = ARTISTS[art]
    return {"item_id": tid, "provider": PROVIDER, "name": name, "media_type": "track", "duration": dur,
            "uri": "%s://track/%s" % (PROVIDER, tid), "favorite": False,
            "artists": [{"item_id": a["item_id"], "provider": PROVIDER, "name": a["name"], "media_type": "artist", "uri": a["uri"]}],
            "album": {"item_id": album, "provider": PROVIDER, "name": ALBUM_NAMES[album], "media_type": "album",
                      "uri": "%s://album/%s" % (PROVIDER, album), "image": img("al" + album)}}


ALBUM_NAMES = {"al1": "Discovery", "al2": "Ágætis byrjun", "al3": "async"}
TRACKS = [
    track("t1", "One More Time", "a1", "al1", 320),
    track("t2", "Aerodynamic", "a1", "al1", 212),
    track("t3", "Digital Love", "a1", "al1", 301),
    track("t4", "Svefn-g-englar", "a2", "al2", 604),
    track("t5", "Starálfur", "a2", "al2", 407),
    track("t6", "andata", "a3", "al3", 285),
]
# Invented lyrics (MA's metadata.lrc_lyrics and lyrics) for the Lyrics
# screen: synced for t2, plain for t1.
TRACKS[1]["metadata"] = {
    "lrc_lyrics": "\n".join("[00:%02d.00]Invented line %d" % (i * 4, i + 1) for i in range(20)),
    "lyrics": "\n".join("Invented line %d" % (i + 1) for i in range(20)),
}
TRACKS[0]["metadata"] = {"lyrics": "An invented verse\nwith a second line\n\nand a second verse"}

# Drone pitch (Hz) per track in the synthetic test media, so a track change
# is audible (tools/make_test_media.py).
TONES = {"t1": 165.0, "t2": 220.0, "t3": 294.0, "t4": 392.0, "t5": 523.0, "t6": 131.0}

# Invented album descriptions (MA's metadata.description), one long
# enough that the app's text panel has to scroll.
ALBUM_TEXTS = {
    "al1": " ".join("Paragraph %d of an invented description for a test album, long enough to wrap." % i
                    for i in range(1, 41)),
    "al2": "An invented description for a test album.",
    "al3": "An invented description for a test album.",
}
ALBUMS = {}
for aid, name in ALBUM_NAMES.items():
    ts = [t for t in TRACKS if t["album"]["item_id"] == aid]
    ALBUMS[aid] = {"item_id": aid, "provider": PROVIDER, "name": name, "sort_name": sort_name(name), "media_type": "album", "year": 2001,
                   "uri": "%s://album/%s" % (PROVIDER, aid), "artists": ts[0]["artists"], "favorite": False,
                   "metadata": {"images": [img("al" + aid)], "description": ALBUM_TEXTS[aid]}}
PLAYLISTS = {
    "flow": {"item_id": "flow", "provider": PROVIDER, "name": "Flow", "media_type": "playlist", "is_dynamic": True,
             "uri": "%s://playlist/flow" % PROVIDER, "owner": "Example Music", "metadata": {"images": [img("flow")]}},
    "pl1": {"item_id": "pl1", "provider": PROVIDER, "name": "Late Night", "media_type": "playlist",
            "uri": "%s://playlist/pl1" % PROVIDER, "owner": "testuser", "metadata": {"images": [img("pl1")]}},
}
PLAYLIST_TRACKS = {"flow": ["t1", "t4", "t6", "t2"], "pl1": ["t6", "t5", "t3"]}


def make_token(user, days, long_lived):
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = {"sub": user["user_id"], "username": user["username"], "exp": int(time.time()) + days * 86400,
               "jti": uuid.uuid4().hex, "is_long_lived": long_lived}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return "%s.%s.fakesig" % (header, body)


def token_id(token):
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).get("jti")


class Queue:
    def __init__(self):
        self.items = []
        self.index = 0
        self.state = "idle"
        self.shuffle = False
        self.repeat = "off"
        self.elapsed = 0.0
        self.anchor = time.time()
        self.session = uuid.uuid4().hex[:8]
        self.user = None

    def current(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def queue_item(self, i):
        if not (0 <= i < len(self.items)):
            return None
        t = self.items[i]["track"]
        return {"queue_item_id": self.items[i]["qid"], "name": t["name"], "duration": t["duration"],
                "media_item": t, "image": t["album"]["image"], "index": i}

    def as_dict(self):
        # The next track is handed to the Roku with the current one (send_current).
        buffered = min(self.index + 1, len(self.items) - 1) if self.items else None
        return {"queue_id": PLAYER_ID, "state": self.state, "current_index": self.index, "items": len(self.items),
                "index_in_buffer": buffered,
                "shuffle_enabled": self.shuffle, "repeat_mode": self.repeat, "elapsed_time": self.elapsed,
                "elapsed_time_last_updated": self.anchor, "playback_speed": 1.0,
                "current_item": self.streamed_item(self.index), "next_item": self.queue_item(self.index + 1)}

    def streamed_item(self, i):
        # MA fills in stream details for the item it streams: the source's
        # format (a streaming service's FLAC 16/44.1).
        qi = self.queue_item(i)
        if qi is not None:
            qi["streamdetails"] = {"provider": PROVIDER, "item_id": qi["media_item"]["item_id"],
                                   "audio_format": {"content_type": "flac", "codec_type": "flac", "sample_rate": 44100,
                                                    "bit_depth": 16, "channels": 2, "bit_rate": None}}
        return qi


CODEC_EXT = {"flac-44k": "flac", "flac-48k": "flac", "flac-96k24": "flac", "mp3": "mp3", "aac": "aac"}


class FakeMA:
    def __init__(self, roku, public_host, port, app_id, media_dir=None, codec="flac-44k", http_profile="no_content_length"):
        self.roku = roku
        self.public_host = public_host
        self.port = port
        self.app_id = app_id
        self.media_dir = media_dir
        self.codec = codec
        self.http_profile = http_profile
        self.api_delay = 0.0
        self.tokens = {}
        self.revoked = []  # token ids revoked via auth/token/revoke
        self.unplayed = []  # (provider, item_id, media_type) removed via music/mark_unplayed
        self.queue = Queue()
        self.lock = threading.RLock()
        self.log = []
        self.seeks = {}  # stream session -> start offset in seconds

    # --- ECP, as the roku_media_assistant provider does it ---

    def ecp(self, path, params=None):
        url = "http://%s:8060/%s" % (self.roku, path)
        if params is not None:
            url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        self.log.append(path)
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=5).read()
        except Exception as e:  # noqa: BLE001
            print("[fake_ma] ECP %s failed: %s" % (path, e))

    def media_file(self, track_id):
        """(path, codec) for a track in the configured codec, falling back to
        flac-44k, or (None, "wav") for the built-in tone."""
        if not self.media_dir:
            return None, "wav"
        for codec in (self.codec, "flac-44k"):
            path = os.path.join(self.media_dir, codec, "%s.%s" % (track_id, CODEC_EXT[codec]))
            if os.path.exists(path):
                if codec != self.codec:
                    print("[fake_ma] no %s file for %s; using flac-44k" % (self.codec, track_id))
                return path, codec
        return None, "wav"

    def track_for_queue_item(self, qid):
        for it in self.queue.items:
            if it["qid"] == qid:
                return it["track"]
        return None

    def stream_params(self, i, enqueue=False):
        qi = self.queue.queue_item(i)
        t = qi["media_item"]
        _, codec = self.media_file(t["item_id"])
        ext = CODEC_EXT.get(codec, "wav")
        url = "http://%s:%d/single/%s/%s/%s/%s.%s" % (self.public_host, self.port, self.queue.session, PLAYER_ID,
                                                       qi["queue_item_id"], PLAYER_ID, ext)
        p = {"u": url, "t": "a", "songName": t["name"], "artistName": t["artists"][0]["name"],
             "albumName": t["album"]["name"],
             "albumArt": "http://%s:%d/imageproxy/%s?size=512" % (self.public_host, self.port, t["album"]["image"]["proxy_id"]),
             "songFormat": "flac", "duration": str(t["duration"]), "isLive": "false"}
        if enqueue:
            # The real provider leaks Python None as "None" here; mimic it.
            p.update({"enqueue": "true", "albumName": "None"})
        return p

    def send_current(self):
        if self.queue.current() is None:
            return
        self.queue.state = "playing"
        self.queue.elapsed = 0.0
        self.queue.anchor = time.time()
        self.ecp("input", self.stream_params(self.queue.index))
        if self.queue.index + 1 < len(self.queue.items):
            self.ecp("input", self.stream_params(self.queue.index + 1, enqueue=True))

    # --- commands ---

    def resolve_tracks(self, media):
        uris = media if isinstance(media, list) else [media]
        out = []
        for uri in uris:
            if isinstance(uri, dict):
                uri = uri.get("uri", "")
            kind, _, ident = uri.partition("://")[2].partition("/")
            if kind == "track":
                out += [t for t in TRACKS if t["item_id"] == ident]
            elif kind == "album":
                out += [t for t in TRACKS if t["album"]["item_id"] == ident]
            elif kind == "playlist":
                out += [t for i in PLAYLIST_TRACKS.get(ident, []) for t in TRACKS if t["item_id"] == i]
            elif kind == "artist":
                out += [t for t in TRACKS if t["artists"][0]["item_id"] == ident]
        return out

    def play_media(self, args, user):
        tracks = self.resolve_tracks(args.get("media"))
        if not tracks:
            raise KeyError("media not found")
        q = self.queue
        start_item = args.get("start_item")
        if start_item:
            # As MA does: the collection from start_item on, the tracks
            # before it dropped (moved behind the rest when shuffle is on).
            at = next((i for i, t in enumerate(tracks) if start_item in (t["uri"], t["item_id"])), None)
            if at is None:
                raise KeyError("start_item not found")
            tracks = tracks[at:] + (tracks[:at] if q.shuffle else [])
        option = args.get("option", "play")
        items = [{"qid": uuid.uuid4().hex[:12], "track": t} for t in tracks]
        q.user = user
        if option in ("replace", "play") or not q.items:
            q.items = items
            q.index = 0
            q.session = uuid.uuid4().hex[:8]
            self.send_current()
        elif option == "next":
            q.items[q.index + 1:q.index + 1] = items
        else:
            q.items += items
        return None

    def api(self, cmd, args, user):
        q = self.queue
        if cmd == "auth/me":
            return {k: v for k, v in user.items() if k != "password"}
        if cmd == "auth/token/create":
            tok = make_token(user, 365, True)
            self.tokens[tok] = user
            return tok
        if cmd == "auth/token/revoke":
            for tok in [t for t in self.tokens if token_id(t) == args.get("token_id")]:
                del self.tokens[tok]
                self.revoked.append(args.get("token_id"))
            return None
        if cmd == "auth/logout":
            return None
        if cmd == "providers":
            return [{"instance_id": PROVIDER, "domain": "example_music", "name": "Example Music", "type": "music",
                     "available": True}]
        if cmd == "players/all":
            return [{"player_id": "sonos1", "provider": "sonos", "name": "Kitchen", "available": True},
                    {"player_id": PLAYER_ID, "provider": "roku_media_assistant", "name": "Living Room", "available": True,
                     "device_info": {"identifiers": {"ip_address": self.roku}}}]
        if cmd == "music/recently_played_items":
            played = [ALBUMS["al2"], TRACKS[0], PLAYLISTS["pl1"]]
            return [i for i in played
                    if (i["provider"], i["item_id"], i["media_type"]) not in self.unplayed][:args.get("limit", 10)]
        if cmd == "music/mark_unplayed":
            # MA deletes the play log rows of the identity it's given.
            mi = args.get("media_item") or {}
            self.unplayed.append((mi.get("provider"), mi.get("item_id"), mi.get("media_type")))
            return None
        if cmd == "music/recommendations":
            return [{"item_id": "made_for_you", "provider": PROVIDER, "name": "Made for you", "media_type": "folder", "items": []},
                    {"item_id": "top", "provider": PROVIDER, "name": "Top albums", "media_type": "folder", "items": []},
                    {"item_id": "empty", "provider": PROVIDER, "name": "Nothing here", "media_type": "folder", "items": []}]
        if cmd == "music/recommendations/items":
            return {"made_for_you": [PLAYLISTS["flow"], PLAYLISTS["pl1"]], "top": list(ALBUMS.values())}.get(args.get("item_id"), [])
        if cmd.startswith("music/") and cmd.endswith("/library_items"):
            kind = cmd.split("/")[1]
            data = {"albums": list(ALBUMS.values()), "artists": list(ARTISTS.values()), "tracks": TRACKS,
                    "playlists": list(PLAYLISTS.values())}.get(kind, [])
            if args.get("favorite"):
                data = [d for d in data if d.get("favorite")]
            # MA's name order, for the kinds whose items have sort names.
            order = args.get("order_by", "sort_name")
            if kind in ("albums", "artists") and order in ("sort_name", "sort_name_desc"):
                data = sorted(data, key=sort_key, reverse=order == "sort_name_desc")
            off, lim = int(args.get("offset", 0)), int(args.get("limit", 500))
            return data[off:off + lim]
        if cmd.startswith("music/") and cmd.endswith("/count"):
            kind = cmd.split("/")[1]
            data = {"albums": list(ALBUMS.values()), "artists": list(ARTISTS.values()), "tracks": TRACKS,
                    "playlists": list(PLAYLISTS.values())}.get(kind, [])
            if args.get("favorite_only"):
                data = [d for d in data if d.get("favorite")]
            return len(data)
        if cmd == "music/browse":
            path = args.get("path") or ""
            if not path or path == "root":
                return [{"item_id": PROVIDER, "provider": PROVIDER, "name": "Example Music", "media_type": "folder", "path": PROVIDER + "://"}]
            if path == PROVIDER + "://":
                return [{"item_id": "back", "name": "..", "media_type": "folder", "path": "root"},
                        {"item_id": "mfy", "provider": PROVIDER, "name": "Made For You", "media_type": "folder", "path": PROVIDER + "://Made For You"}]
            return [PLAYLISTS["flow"], PLAYLISTS["pl1"]]
        if cmd == "music/search":
            s = args.get("search_query", "").lower()
            return {"artists": [a for a in ARTISTS.values() if s in a["name"].lower()],
                    "albums": [a for a in ALBUMS.values() if s in a["name"].lower()],
                    "tracks": [t for t in TRACKS if s in t["name"].lower()],
                    "playlists": [p for p in PLAYLISTS.values() if s in p["name"].lower()]}
        if cmd == "music/item_by_uri":
            uri = args.get("uri", "")
            for coll in (ALBUMS.values(), PLAYLISTS.values(), ARTISTS.values(), TRACKS):
                for it in coll:
                    if it["uri"] == uri:
                        return it
            raise KeyError(uri)
        if cmd == "metadata/get_track_lyrics":
            # Like MA: [lyrics, lrc_lyrics] for the track given (by its uri
            # here; MA also looks lyrics up for a library track without).
            uri = (args.get("track") or {}).get("uri", "")
            md = next((t.get("metadata") or {} for t in TRACKS if t["uri"] == uri), {})
            return [md.get("lyrics"), md.get("lrc_lyrics")]
        if cmd in ("music/albums/album_tracks", "music/playlists/playlist_tracks", "music/artists/top_tracks",
                   "music/artists/artist_tracks"):
            kind = {"music/albums/album_tracks": "album", "music/playlists/playlist_tracks": "playlist",
                    "music/artists/top_tracks": "artist", "music/artists/artist_tracks": "artist"}[cmd]
            return self.resolve_tracks("%s://%s/%s" % (PROVIDER, kind, args.get("item_id")))
        if cmd == "music/artists/artist_albums":
            return [a for a in ALBUMS.values() if a["artists"][0]["item_id"] == args.get("item_id")]
        if cmd == "music/artists/similar_artists":
            return [a for k, a in ARTISTS.items() if k != args.get("item_id")]
        if cmd == "music/favorites/add_item":
            uri = args.get("item")
            for coll in (ALBUMS.values(), PLAYLISTS.values(), TRACKS):
                for it in coll:
                    if it["uri"] == uri:
                        it["favorite"] = True
            return None
        if cmd == "music/get_library_item":
            return {"item_id": "lib-" + str(args.get("item_id")), "provider": "library"}
        if cmd == "music/favorites/remove_item":
            return None
        if cmd == "player_queues/get" or cmd == "player_queues/get_active_queue":
            return q.as_dict()
        if cmd == "player_queues/items":
            off, lim = int(args.get("offset", 0)), int(args.get("limit", 500))
            return [q.queue_item(i) for i in range(off, min(len(q.items), off + lim))]
        if cmd == "player_queues/play_media":
            return self.play_media(args, user)
        if cmd == "player_queues/next":
            if q.index + 1 < len(q.items):
                q.index += 1
                self.send_current()
            return None
        if cmd == "player_queues/previous":
            if q.index > 0:
                q.index -= 1
            self.send_current()
            return None
        if cmd == "player_queues/play_index":
            idx = args.get("index")
            for i, it in enumerate(q.items):
                if it["qid"] == idx or i == idx:
                    q.index = i
            self.send_current()
            return None
        if cmd == "player_queues/seek":
            # Real MA: play_index(current, seek_position) -> a new stream URL
            # for the same queue item, starting at the offset, sent as a
            # fresh /input.
            q.session = uuid.uuid4().hex[:8]
            self.seeks[q.session] = float(args.get("position", 0))
            self.ecp("input", self.stream_params(q.index))
            q.elapsed = float(args.get("position", 0))
            q.anchor = time.time()
            return None
        if cmd == "player_queues/play_pause" or cmd == "player_queues/play" or cmd == "player_queues/pause":
            # As MA does: an idle queue starts again with a new stream (none
            # when it's empty); pause and resume are the Roku's Play key.
            if q.state == "idle":
                if cmd != "player_queues/pause" and q.items:
                    q.session = uuid.uuid4().hex[:8]
                    self.send_current()
                return None
            self.ecp("keypress/Play")
            q.state = "paused" if q.state == "playing" else "playing"
            return None
        if cmd == "player_queues/stop":
            self.ecp("input", {"u": " ", "t": "a", "songName": "Music Assistant", "artistName": "Waiting for Playback..."})
            q.state = "idle"
            return None
        if cmd == "player_queues/shuffle":
            q.shuffle = bool(args.get("shuffle_enabled"))
            return None
        if cmd == "player_queues/repeat":
            q.repeat = args.get("repeat_mode", "off")
            return None
        if cmd in ("player_queues/move_item", "player_queues/delete_item"):
            key = args.get("queue_item_id") or args.get("item_id_or_index")
            i = next((n for n, it in enumerate(q.items) if it["qid"] == key), None)
            if i is None:
                raise KeyError("Item %s not found in queue" % key)
            # As MA: nothing up to what the Roku already has moves or goes.
            if i <= min(q.index + 1, len(q.items) - 1):
                if cmd == "player_queues/move_item":
                    raise IndexError("%d is already played/buffered" % i)
                return None
            item = q.items.pop(i)
            if cmd == "player_queues/move_item":
                q.items.insert(min(q.index + 2, len(q.items)), item)
            return None
        if cmd == "player_queues/clear":
            q.items = []
            q.index = 0
            q.state = "idle"
            return None
        raise LookupError("Invalid Command: " + cmd)


def transcode_from(path, codec, offset):
    """The file re-encoded from `offset` seconds, as MA does for a seek."""
    import subprocess

    fmt = {"flac": ["-c:a", "flac", "-f", "flac"], "mp3": ["-c:a", "libmp3lame", "-b:a", "320k", "-f", "mp3"],
           "aac": ["-c:a", "aac", "-b:a", "256k", "-f", "adts"]}[CODEC_EXT[codec]]
    if codec == "flac-96k24":
        fmt = ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"] + fmt
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % offset, "-i", path] + fmt + ["-"],
                       capture_output=True)
    return r.stdout


def tone_wav(seconds=5):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        frames = b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 22050))) for i in range(22050 * seconds))
        w.writeframes(frames)
    return buf.getvalue()


def tiny_png():
    # 1x1 grey PNG.
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNoaAAAAYIBAKN0Vl4AAAAASUVORK5CYII=")


def make_handler(fake):
    audio = tone_wav()
    png = tiny_png()

    class Handler(BaseHTTPRequestHandler):
        # MA's server (aiohttp) speaks HTTP/1.1; chunked encoding requires it.
        # Range requests are ignored (always 200 with the whole stream).
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):
            print("[fake_ma] " + (fmt % a))

        def send(self, code, body, ctype="application/json", headers=None):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def stream(self, path):
            # /single/<session>/<queue>/<queue_item_id>/<player>.<ext>
            parts = path.strip("/").split("/")
            session = parts[1] if len(parts) >= 5 else ""
            qid = parts[3] if len(parts) >= 5 else ""
            with fake.lock:
                track = fake.track_for_queue_item(qid)
                offset = fake.seeks.get(session, 0.0)
            file_path, codec = (None, "wav")
            if track:
                file_path, codec = fake.media_file(track["item_id"])
            if file_path and offset > 0:
                data = transcode_from(file_path, codec, offset)
                print("[fake_ma] seek stream from %.1fs" % offset)
            elif file_path:
                with open(file_path, "rb") as f:
                    data = f.read()
            else:
                data = audio
            ctype = {"flac": "audio/flac", "mp3": "audio/mpeg", "aac": "audio/aac"}.get(CODEC_EXT.get(codec, ""), "audio/wav")
            profile = fake.http_profile
            print("[fake_ma] stream %s track=%s codec=%s profile=%s range=%r ua=%r" % (
                self.command, track["item_id"] if track else "?", codec, profile,
                self.headers.get("Range"), self.headers.get("User-Agent")))
            sent = 0
            try:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                if profile == "forced_content_length":
                    self.send_header("Content-Length", str(len(data)))
                elif profile == "chunked":
                    self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command == "HEAD":
                    return
                step = 64 * 1024
                for off in range(0, len(data), step):
                    chunk = data[off:off + step]
                    if profile == "chunked":
                        self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                    else:
                        self.wfile.write(chunk)
                    sent += len(chunk)
                if profile == "chunked":
                    self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self.close_connection = True
                print("[fake_ma] stream end track=%s sent=%d/%d bytes" % (track["item_id"] if track else "?", sent, len(data)))

        def do_HEAD(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith("/single/") or u.path.startswith("/flow/"):
                return self.stream(u.path)
            return self.send(404, "", "text/plain")

        def user_for(self):
            auth = self.headers.get("Authorization", "")
            if not auth.lower().startswith("bearer "):
                return None
            return fake.tokens.get(auth[7:].strip())

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = dict(urllib.parse.parse_qsl(u.query))
            if u.path == "/info":
                return self.send(200, json.dumps({"server_id": "fake", "server_version": "2.9.0-fake",
                                                  "schema_version": SCHEMA, "min_supported_schema_version": 28,
                                                  "base_url": "http://%s:%d" % (fake.public_host, fake.port),
                                                  "onboard_done": True}))
            if u.path == "/login":
                # Real MA shows a form; the fake signs in as ?user= (default testuser).
                user = USERS[qs.get("user", "testuser")]
                tok = make_token(user, 90, False)
                fake.tokens[tok] = user
                ret = qs.get("return_url", "")
                sep = "&" if "?" in ret else "?"
                return self.send(302, "", "text/plain", {"Location": ret + sep + "code=" + tok})
            if u.path.startswith("/imageproxy/"):
                pid = u.path.rsplit("/", 1)[-1]
                art = os.path.join(fake.media_dir or "", "art", pid + ".jpg")
                if fake.media_dir and os.path.exists(art):
                    with open(art, "rb") as f:
                        return self.send(200, f.read(), "image/jpeg")
                return self.send(200, png, "image/png")
            if u.path.startswith("/single/") or u.path.startswith("/flow/"):
                return self.stream(u.path)
            if u.path == "/_fake/token":
                user = USERS[qs.get("user", "testuser")]
                tok = make_token(user, int(qs.get("days", 365)), True)
                fake.tokens[tok] = user
                return self.send(200, tok, "text/plain")
            if u.path == "/_fake/state":
                with fake.lock:
                    return self.send(200, json.dumps({"queue": fake.queue.as_dict(), "ecp": fake.log[-20:],
                                                      "revoked": fake.revoked, "unplayed": fake.unplayed}))
            return self.send(404, "not found", "text/plain")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            if u.path == "/_fake/play":
                qs = dict(urllib.parse.parse_qsl(u.query))
                with fake.lock:
                    fake.play_media({"media": qs.get("uri"), "option": "replace"}, USERS["testuser"])
                return self.send(200, "ok", "text/plain")
            if u.path != "/api":
                return self.send(404, "not found", "text/plain")
            try:
                msg = json.loads(raw or b"{}")
            except ValueError:
                return self.send(400, "Invalid JSON", "text/plain")
            cmd = msg.get("command", "")
            args = msg.get("args") or {}
            if cmd == "time":
                return self.send(200, json.dumps(time.time()))
            if cmd == "auth/login":
                user = USERS.get(args.get("username"))
                if not user or user["password"] != args.get("password"):
                    return self.send(200, json.dumps({"success": False, "error": "Invalid credentials"}))
                tok = make_token(user, 90, False)
                fake.tokens[tok] = user
                return self.send(200, json.dumps({"success": True, "access_token": tok,
                                                  "user": {k: v for k, v in user.items() if k != "password"}}))
            user = self.user_for()
            if user is None:
                return self.send(401, "Authentication required", "text/plain")
            if fake.api_delay and cmd.startswith("music/"):
                time.sleep(fake.api_delay)
            try:
                with fake.lock:
                    result = fake.api(cmd, args, user)
            except LookupError as e:
                return self.send(400, str(e), "text/plain")
            except Exception as e:  # noqa: BLE001
                print("[fake_ma] %s failed: %r" % (cmd, e))
                return self.send(500, "Internal server error", "text/plain")
            return self.send(200, json.dumps(result))

    return Handler


MDNS_SERVICE = "_mass._tcp.local"
MDNS_NAME = "Fake MA (test)"


def dns_name(name):
    out = b""
    for part in name.strip(".").split("."):
        raw = part.encode()
        out += bytes([len(raw)]) + raw
    return out + b"\0"


def dns_record(name, rtype, ttl, rdata):
    return dns_name(name) + struct.pack(">HHIH", rtype, 1, ttl, len(rdata)) + rdata


def mdns_question(packet):
    """The first question's name and type in a query, or None."""
    if len(packet) < 12 or packet[2] & 0x80 or struct.unpack(">H", packet[4:6])[0] < 1:
        return None
    labels, off = [], 12
    while off < len(packet) and packet[off]:
        n = packet[off]
        if n & 0xC0:
            return None
        labels.append(packet[off + 1:off + 1 + n].decode("ascii", "replace"))
        off += 1 + n
    if off + 5 > len(packet):
        return None
    return ".".join(labels), struct.unpack(">H", packet[off + 1:off + 3])[0]


def mdns_answer(qid, public, port, count=1):
    """This fake as "Fake MA (test)", plus count - 1 made-up servers ("Fake
    MA 2", ...) on the following ports, which nothing answers."""
    service = MDNS_SERVICE
    host = "fake-ma.local"
    records = []
    for i in range(count):
        instance = "fake%d.%s" % (port + i, service)
        name = MDNS_NAME if i == 0 else "Fake MA %d" % (i + 1)
        txt = b"".join(bytes([len(s)]) + s for s in (("server_id=fake%d" % (i + 1)).encode(), b"name=" + name.encode(),
                                                     ("base_url=http://%s:%d" % (public, port + i)).encode()))
        records += [
            dns_record(service, 12, 4500, dns_name(instance)),
            dns_record(instance, 33, 120, struct.pack(">HHH", 0, 0, port + i) + dns_name(host)),
            dns_record(instance, 16, 4500, txt),
        ]
    records.append(dns_record(host, 1, 120, bytes(int(x) for x in public.split("."))))
    return struct.pack(">HHHHHH", qid, 0x8400, 0, len(records), 0, 0) + b"".join(records)


def serve_mdns(sock, public, port, count):
    """Answers _mass._tcp.local queries arriving on sock straight back to
    the asker, as MA's zeroconf answers legacy unicast queries."""
    while True:
        packet, peer = sock.recvfrom(9000)
        q = mdns_question(packet)
        if q is None or q[0].lower() != MDNS_SERVICE or q[1] not in (12, 255):
            continue
        print("[fake_ma] mDNS query for %s from %s:%d" % (q[0], peer[0], peer[1]))
        sock.sendto(mdns_answer(struct.unpack(">H", packet[:2])[0], public, port, count), peer)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roku", required=True, help="Roku (or simulator) IP for ECP")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--host", default="0.0.0.0", help="bind address")
    ap.add_argument("--public-host", default=None, help="address the Roku uses to reach this server")
    ap.add_argument("--app-id", default="dev")
    default_media = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test-media")
    ap.add_argument("--media", default=default_media, help="output of tools/make_test_media.py")
    ap.add_argument("--codec", default="flac-44k", choices=sorted(CODEC_EXT))
    ap.add_argument("--http-profile", default="no_content_length",
                    choices=["no_content_length", "chunked", "forced_content_length"])
    ap.add_argument("--api-delay", type=float, default=0.0,
                    help="seconds to hold each music/* API reply (slow-MA testing)")
    ap.add_argument("--mdns-port", type=int, default=0,
                    help="answer _mass._tcp.local queries sent to this UDP port (tests; see masstv_mdns_to)")
    ap.add_argument("--mdns-count", type=int, default=1,
                    help="servers in each mDNS answer: this one plus made-up ones (list scrolling)")
    a = ap.parse_args()
    public = a.public_host or local_address_toward(a.roku)
    media = a.media if os.path.isdir(a.media) else None
    fake = FakeMA(a.roku, public, a.port, a.app_id, media, a.codec, a.http_profile)
    fake.api_delay = a.api_delay
    if a.mdns_port:
        # Bound here, so a busy port fails at startup rather than silently.
        msock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        msock.bind((a.host, a.mdns_port))
        print("[fake_ma] answering mDNS queries on %s:%d" % (a.host, a.mdns_port))
        threading.Thread(target=serve_mdns, args=(msock, public, a.port, a.mdns_count), daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(fake))
    print("[fake_ma] listening on %s:%d (public %s), Roku ECP at %s:8060" % (a.host, a.port, public, a.roku))
    print("[fake_ma] media: %s, codec %s, http profile %s" % (media or "built-in tone", a.codec, a.http_profile))
    srv.serve_forever()


def local_address_toward(host):
    """The local IP the OS would use to reach host (what the Roku must call)."""
    if host in ("127.0.0.1", "localhost"):
        return "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 8060))
        return s.getsockname()[0]
    finally:
        s.close()


if __name__ == "__main__":
    main()
