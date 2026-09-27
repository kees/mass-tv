#!/usr/bin/env python3
"""Mass TV device tools (stdlib only). The target Roku is named by $ROKU
(required, e.g. ROKU=livingroom), its address in $ROKU_<NAME>_IP; the dev
installer password from $ROKU_DEV_PASSWORD (user "rokudev").

  roku.py sideload out/masstv-debug.zip   install a dev channel (replaces the current one)
  roku.py screenshot [out.jpg]            capture the screen (dev channel must be running)
  roku.py key Up Up Select                send remote keys via ECP (Home, Rev, Fwd, Play,
                                          Select, Left, Right, Down, Up, Back, InstantReplay,
                                          Info [= Options *], ...)
  roku.py launch [k=v ...]                launch the dev channel with deep-link params
                                          (e.g. masstv_log=TRACE masstv_collector=192.168.1.5:8765)
  roku.py input k=v ...                   send /input deep-link params to the running channel
  roku.py query [media-player|active-app|device-info]
  roku.py console                         stream the BrightScript console (port 8085) to
                                          stdout and logs/console-<time>.log
  roku.py logs [--follow]                 pull the app's debug log ring buffer (port 8889)
                                          to stdout and logs/app-<time>.ndjson
  roku.py state                           print the app's /state snapshot
  roku.py genkey                          create the Roku's package signing key (once,
                                          ever: every update must be signed with it); saves
                                          ROKU_SIGN_PASSWORD and ROKU_SIGN_DEVID to .env
  roku.py package NAME [out.pkg]          sign the sideloaded channel with that key and
                                          download the .pkg (sideload the release zip first)
"""

import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PORT = 8889


def roku_ip():
    """The address of the Roku named by $ROKU: $ROKU_<NAME>_IP. There is no
    default, so a command never reaches a Roku nobody named."""
    name = os.environ.get("ROKU", "").strip()
    if not name:
        sys.exit("name the Roku: ROKU=<name> (its address in ROKU_<NAME>_IP, e.g. in .env)")
    var = "ROKU_%s_IP" % name.upper()
    ip = os.environ.get(var, "").strip()
    if not ip:
        sys.exit("set %s (e.g. in .env) for ROKU=%s" % (var, name))
    return ip


def dev_password():
    pw = os.environ.get("ROKU_DEV_PASSWORD", "")
    if not pw:
        sys.exit("set ROKU_DEV_PASSWORD (e.g. in .env)")
    return pw


def digest_header(method, path):
    """Authorization header for the dev installer.

    Fetches a fresh digest challenge with a small GET first. urllib's
    handler instead sends the full request body, gets the 401, then
    retries; the Roku often resets the connection mid-upload on that first
    attempt (BrokenPipe on sideload about one time in three).
    """
    req = urllib.request.Request("http://%s%s" % (roku_ip(), path), method="GET")
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return None
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        challenge = e.headers.get("WWW-Authenticate", "")
    fields = dict(re.findall(r'(\w+)="?([^",]*)"?', challenge))
    realm, nonce, qop = fields.get("realm", ""), fields.get("nonce", ""), fields.get("qop", "")
    ha1 = hashlib.md5(("rokudev:%s:%s" % (realm, dev_password())).encode()).hexdigest()
    ha2 = hashlib.md5(("%s:%s" % (method, path)).encode()).hexdigest()
    cnonce, nc = uuid.uuid4().hex[:16], "00000001"
    if "auth" in qop.split(","):
        resp = hashlib.md5(("%s:%s:%s:%s:auth:%s" % (ha1, nonce, nc, cnonce, ha2)).encode()).hexdigest()
        return ('Digest username="rokudev", realm="%s", nonce="%s", uri="%s", qop=auth, nc=%s, cnonce="%s", response="%s"'
                % (realm, nonce, path, nc, cnonce, resp))
    resp = hashlib.md5(("%s:%s:%s" % (ha1, nonce, ha2)).encode()).hexdigest()
    return 'Digest username="rokudev", realm="%s", nonce="%s", uri="%s", response="%s"' % (realm, nonce, path, resp)


def installer_request(method, path, body=None, ctype=None, retries=3):
    for attempt in range(retries):
        headers = {}
        auth = digest_header(method, path)
        if auth:
            headers["Authorization"] = auth
        if ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request("http://%s%s" % (roku_ip(), path), data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, ConnectionError) as e:
            if attempt == retries - 1:
                raise
            print("installer %s %s failed (%s); retrying" % (method, path, e), file=sys.stderr)
            time.sleep(1)
    return b""


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
    for k, (name, data) in files.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                      "Content-Type: application/zip\r\n\r\n" % (boundary, k, name)).encode() + data + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def installer_post(path, fields, files=None):
    body, ctype = multipart(fields, files or {})
    return installer_request("POST", path, body, ctype).decode("utf-8", "replace")


def cmd_sideload(args):
    path = args[0] if args else os.path.join(ROOT, "out", "masstv-debug.zip")
    with open(path, "rb") as f:
        data = f.read()
    html = installer_post("/plugin_install", {"mysubmit": "Install"}, {"archive": (os.path.basename(path), data)})
    msgs = [m for m in ("Install Success", "Identical to previous version", "Install Failure") if m in html]
    print("sideload %s: %s" % (os.path.basename(path), ", ".join(msgs) or "unknown response"))
    if "Install Failure" in html:
        sys.exit(1)


ENV_PATH = os.path.join(ROOT, ".env")
CONSOLE_PORT = 8080


def cmd_genkey(args):
    """Runs `genkey` on the Roku's developer console (port 8080).

    The key is the channel's publishing identity: every update must be
    signed with it, and a second genkey replaces it on the device. So this
    refuses when a key is already recorded, and keeps the password out of
    the terminal (it goes to .env, which git ignores).
    """
    if os.environ.get("ROKU_SIGN_PASSWORD") or os.environ.get("ROKU_SIGN_DEVID"):
        sys.exit("a signing key is already recorded (ROKU_SIGN_*); not replacing it")
    s = socket.create_connection((roku_ip(), CONSOLE_PORT), timeout=10)
    s.settimeout(1)
    out = b""
    # Let the banner arrive before sending the command.
    end = time.time() + 2
    while time.time() < end:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            out += chunk
        except socket.timeout:
            pass
    s.sendall(b"genkey\r\n")
    out = b""
    end = time.time() + 60
    while time.time() < end and not re.search(rb"DevID:\s*\S+", out):
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            out += chunk
        except socket.timeout:
            pass
    s.close()
    text = out.decode("utf-8", "replace")
    pw = re.search(r"Password:\s*(\S+)", text)
    dev = re.search(r"DevID:\s*(\S+)", text)
    if not pw or not dev:
        sys.exit("genkey output not understood (%d bytes); nothing saved" % len(text))
    with open(ENV_PATH, "a") as f:
        f.write("\n# Package signing key, from `roku.py genkey` on %s (%s).\n" % (roku_ip(), time.strftime("%Y-%m-%d")))
        f.write("# Keep with the first signed .pkg: both are needed to rekey a Roku.\n")
        f.write("ROKU_SIGN_PASSWORD=%s\nROKU_SIGN_DEVID=%s\n" % (pw.group(1), dev.group(1)))
    print("genkey: DevID %s; password saved to .env" % dev.group(1))


def cmd_package(args):
    """Signs the sideloaded channel and downloads the .pkg."""
    if not args:
        sys.exit("usage: roku.py package NAME [out.pkg]")
    pw = os.environ.get("ROKU_SIGN_PASSWORD", "")
    if not pw:
        sys.exit("set ROKU_SIGN_PASSWORD (from roku.py genkey)")
    name = args[0]
    out = args[1] if len(args) > 1 else os.path.join(ROOT, "out", name.replace("/", "-") + ".pkg")
    html = installer_post("/plugin_package", {"mysubmit": "Package", "app_name": name, "passwd": pw,
                                              "pkg_time": str(int(time.time() * 1000))})
    m = re.search(r'"pkgPath"\s*:\s*"([^"]+)"', html) or re.search(r'href="(pkgs[/\\]+[^"]+\.pkg)"', html)
    if not m:
        msg = re.search(r"(Failed[^<\"]*|Invalid[^<\"]*|Error[^<\"]*)", html)
        sys.exit("packaging failed: %s" % (msg.group(1) if msg else "no package link in the response"))
    path = "/" + m.group(1).replace("\\", "/").lstrip("/")
    path = re.sub(r"/+", "/", path)
    data = installer_request("GET", path)
    if len(data) < 1024 or data.lstrip()[:1] == b"<":
        sys.exit("download of %s doesn't look like a package (%d bytes)" % (path, len(data)))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    print("package: %s (%d bytes) from %s" % (out, len(data), path))


def cmd_screenshot(args):
    out = args[0] if args else os.path.join(ROOT, "logs", "screenshot-%s.jpg" % time.strftime("%Y%m%d-%H%M%S"))
    installer_post("/plugin_inspect", {"mysubmit": "Screenshot"})
    data = installer_request("GET", "/pkgs/dev.jpg?time=%d" % time.time())
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    print(out)


def ecp(path, params=None, method="POST"):
    url = "http://%s:8060/%s" % (roku_ip(), path)
    if params:
        url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, data=b"" if method == "POST" else None, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def kv(args):
    out = {}
    for a in args:
        k, _, v = a.partition("=")
        out[k] = v
    return out


def cmd_key(args):
    for k in args:
        ecp("keypress/" + urllib.parse.quote(k))
        time.sleep(0.25)


def cmd_launch(args):
    print(ecp("launch/dev", kv(args)) or "launched")


def cmd_input(args):
    print(ecp("input", kv(args)) or "sent")


def cmd_query(args):
    print(ecp("query/" + (args[0] if args else "media-player"), method="GET"))


def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def cmd_console(args):
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    path = os.path.join(ROOT, "logs", "console-%s.log" % stamp())
    s = socket.create_connection((roku_ip(), 8085), timeout=10)
    s.settimeout(None)
    print("console -> %s (Ctrl-C to stop)" % path, file=sys.stderr)
    buf = b""
    with open(path, "a", encoding="utf-8") as f:
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = time.strftime("%H:%M:%S ") + line.decode("utf-8", "replace").rstrip("\r")
                    print(text)
                    f.write(text + "\n")
                    f.flush()
        except KeyboardInterrupt:
            pass


def app_get(path):
    with urllib.request.urlopen("http://%s:%d%s" % (roku_ip(), LOG_PORT, path), timeout=10) as r:
        return r.read().decode("utf-8", "replace"), r.headers


def cmd_logs(args):
    follow = "--follow" in args or "-f" in args
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    path = os.path.join(ROOT, "logs", "app-%s.ndjson" % stamp())
    since = 0
    with open(path, "a", encoding="utf-8") as f:
        while True:
            body, _ = app_get("/log?since=%d" % since)
            for line in body.splitlines():
                if not line.strip():
                    continue
                f.write(line + "\n")
                e = json.loads(line)
                since = max(since, e.get("s", since))
                d = (" " + json.dumps(e["d"])) if "d" in e else ""
                print("%6d %s %-5s %s@%s %s%s" % (e["s"], time.strftime("%H:%M:%S", time.gmtime(e["t"] / 1000)),
                                                  e["l"], e["c"], e["th"], e["m"], d))
            f.flush()
            if not follow:
                break
            time.sleep(1)
    print("saved %s" % path, file=sys.stderr)


def cmd_state(args):
    body, _ = app_get("/state")
    print(json.dumps(json.loads(body), indent=2))


COMMANDS = {
    "sideload": cmd_sideload, "screenshot": cmd_screenshot, "key": cmd_key, "launch": cmd_launch,
    "input": cmd_input, "query": cmd_query, "console": cmd_console, "logs": cmd_logs, "state": cmd_state,
    "genkey": cmd_genkey, "package": cmd_package,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
