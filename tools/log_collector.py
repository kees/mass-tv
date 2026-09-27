#!/usr/bin/env python3
"""Receives Mass TV debug logs pushed from a Roku (debug builds only).

Run this on a host the Roku can reach, then point the app at it with a deep
link: `tools/roku.py launch masstv_collector=<this-host>:8765`. Entries are
printed and appended to logs/collector-<time>.ndjson. Useful when the pull
endpoint (`tools/roku.py logs`) isn't reachable, or to capture logs across
app restarts.

Usage: python3 tools/log_collector.py [--port 8765]
"""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    path = os.path.join(ROOT, "logs", "collector-%s.ndjson" % time.strftime("%Y%m%d-%H%M%S"))
    out = open(path, "a", encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode("utf-8", "replace")
            device = self.headers.get("X-MassTV-Device", "?")
            for line in body.splitlines():
                if not line.strip():
                    continue
                out.write(line + "\n")
                try:
                    e = json.loads(line)
                    d = (" " + json.dumps(e["d"])) if "d" in e else ""
                    print("[%s] %6d %-5s %s@%s %s%s" % (device, e.get("s", 0), e.get("l"), e.get("c"), e.get("th"), e.get("m"), d))
                except ValueError:
                    print("[%s] %s" % (device, line))
            out.flush()
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    print("collecting on :%d -> %s" % (a.port, path))
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
