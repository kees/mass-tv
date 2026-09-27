#!/usr/bin/env python3
"""Set bs_const values in a *staged* manifest (build output, not src/).

BrighterScript applies bsconfig's manifest.bs_const only to its in-memory
manifest; the staged manifest file is copied unchanged, and Roku evaluates
`#if DEBUG` on the device from that file. This makes the staged file match.

Usage: python3 tools/set_bs_const.py build/release/manifest DEBUG=false
"""

import sys


def main():
    path, assigns = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
    lines = open(path, encoding="utf-8").read().splitlines()
    out, found = [], False
    for line in lines:
        if line.startswith("bs_const="):
            found = True
            consts = dict(p.split("=", 1) for p in line[len("bs_const="):].split(";") if "=" in p)
            consts.update(assigns)
            line = "bs_const=" + ";".join("%s=%s" % kv for kv in consts.items())
        out.append(line)
    if not found:
        out.append("bs_const=" + ";".join("%s=%s" % kv for kv in assigns.items()))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("%s: %s" % (path, [l for l in out if l.startswith("bs_const=")][0]))


if __name__ == "__main__":
    main()
