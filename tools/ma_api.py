#!/usr/bin/env python3
"""Call a Music Assistant server's JSON-RPC API (POST /api).

Server from $MA_URL (default http://127.0.0.1:8095), token from $MA_TOKEN
(both can live in .env). Prints the JSON result.

Usage:
  tools/ma_api.py <command> ['<json args>']
  tools/ma_api.py config/core/get_entries '{"domain": "streams"}'
  tools/ma_api.py players/all
"""

import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


def call(command, args=None):
    url = os.environ.get("MA_URL", "http://127.0.0.1:8095").rstrip("/") + "/api"
    token = os.environ.get("MA_TOKEN", "")
    body = json.dumps({"message_id": "cli", "command": command, "args": args or {}}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %d: %s" % (e.code, e.read().decode(errors="replace")[:500]))


def main():
    load_env()
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(call(sys.argv[1], args), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
