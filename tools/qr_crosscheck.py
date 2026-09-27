#!/usr/bin/env python3
"""Cross-check Mass TV's BrightScript QR encoder against Nayuki's qrcodegen.

Runs the compiled encoder (build/unit, from `make unit`) under brs-cli for
several texts, every mask (0-7), and compares each module with qrcodegen's
output for the same version, error level M, byte mode, and mask.

qrcodegen is used because it follows the spec byte-for-byte. segno is not a
usable reference: it appends an extra 0x00 codeword whenever the terminator
ends on a byte boundary (always, in byte mode for versions 1-9), which
decoders tolerate but which changes the matrix.

Usage: python3 tools/qr_crosscheck.py   (needs `pip install qrcodegen`)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build", "unit")
BRS = os.path.join(ROOT, "node_modules", ".bin", "brs-cli")

TEXTS = [
    "HELLO",
    "http://192.168.1.23:8888/s/0123456789abcdef",
    "http://192.168.100.200:8888/s/fedcba9876543210?x=1",
    "x" * 90,
    "https://example.invalid/" + "a" * 150,
]

DRIVER = """
sub main()
    texts = %s
    for each text in texts
        for mask = 0 to 7
            mods = qr_encode(text, mask)
            lines = []
            for each row in mods
                s = ""
                for each cell in row
                    if cell then s = s + "1" else s = s + "0"
                end for
                lines.Push(s)
            end for
            print "QR|" + mask.ToStr() + "|" + lines.Join(",")
        end for
    end for
end sub
"""


def brs_matrices():
    texts = "[" + ", ".join(json.dumps(t) for t in TEXTS) + "]"
    lib = os.path.join(BUILD, "source", "lib")
    with tempfile.TemporaryDirectory() as tmp:
        driver = os.path.join(tmp, "driver.brs")
        with open(driver, "w") as f:
            f.write(DRIVER % texts)
        files = [os.path.join(BUILD, "source", "bslib.brs")]
        files += sorted(os.path.join(lib, n) for n in os.listdir(lib))
        files.append(driver)
        out = subprocess.run([BRS] + files, capture_output=True, text=True, cwd=tmp).stdout
    result = []
    for line in out.splitlines():
        if line.startswith("QR|"):
            _, mask, rows = line.split("|", 2)
            result.append((int(mask), rows.split(",")))
    return result


def reference_matrix(text, version, mask):
    from qrcodegen import QrCode, QrSegment

    seg = QrSegment.make_bytes(text.encode("utf-8"))
    q = QrCode.encode_segments([seg], QrCode.Ecc.MEDIUM, version, version, mask, False)
    size = q.get_size()
    return ["".join("1" if q.get_module(x, y) else "0" for x in range(size)) for y in range(size)]


def main():
    try:
        import qrcodegen  # noqa: F401
    except ImportError:
        sys.exit("qrcodegen is not installed for this Python (pip install qrcodegen)")
    got = brs_matrices()
    if len(got) != len(TEXTS) * 8:
        sys.exit("expected %d matrices from brs-cli, got %d" % (len(TEXTS) * 8, len(got)))
    failures = 0
    for i, text in enumerate(TEXTS):
        for mask in range(8):
            m, rows = got[i * 8 + mask]
            version = (len(rows) - 17) // 4
            want = reference_matrix(text, version, mask)
            if rows != want:
                failures += 1
                diff = sum(a != b for r1, r2 in zip(rows, want) for a, b in zip(r1, r2))
                print("MISMATCH text#%d mask %d version %d: %d modules differ" % (i, mask, version, diff))
    total = len(TEXTS) * 8
    print("qr crosscheck: %d/%d matrices identical" % (total - failures, total))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
