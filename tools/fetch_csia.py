#!/usr/bin/env python3
"""Fetch the pinned CSIA core into .deps/csia-trust-layer and verify the commit.

The CSIA repository is not modified, vendored or copied into this project; the
vehicle adapter imports it from this checkout (or from SEMMC_CSIA_PATH).
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "third_party" / "csia-trust-layer.lock"
DEST = ROOT / ".deps" / "csia-trust-layer"


def lock() -> dict:
    out = {}
    for line in LOCK.read_text().splitlines():
        m = re.match(r"^(\w+)\s*=\s*(\S+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def head(path: pathlib.Path) -> str:
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def main() -> int:
    lk = lock()
    if DEST.exists():
        h = head(DEST)
        if h != lk["commit"]:
            print(f"ERROR: {DEST} is at {h}, lock requires {lk['commit']}", file=sys.stderr)
            return 1
        print(f"CSIA already at pinned commit {h}")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(DEST)], check=True)
    subprocess.run(["git", "-C", str(DEST), "remote", "add", "origin", lk["repository"]], check=True)
    subprocess.run(["git", "-C", str(DEST), "fetch", "-q", "--depth", "1", "origin", lk["commit"]], check=True)
    subprocess.run(["git", "-C", str(DEST), "checkout", "-q", "FETCH_HEAD"], check=True)
    h = head(DEST)
    if h != lk["commit"]:
        print(f"ERROR: fetched {h}, expected {lk['commit']}", file=sys.stderr)
        return 1
    print(f"fetched CSIA {h} into {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
