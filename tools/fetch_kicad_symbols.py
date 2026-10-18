#!/usr/bin/env python3
"""Fetch the KiCad symbol libraries the schematic uses, at the project's KiCad release, SHA-256 checked.

    python3 tools/fetch_kicad_symbols.py                 # into build/kicad-symbols-8.0.9/
    python3 tools/fetch_kicad_symbols.py --dest DIR

The project's KiCad release is 8.0.9: the CI ERC runs KiCad 8.0.9, and the schematic generator
(tools/gen_kicad_schematic.py) and the ERC (tools/run_kicad_erc.sh) both read symbols from this pinned
copy, so the symbols embedded in the schematic are the ones the ERC compares them with. Source: the KiCad
project's kicad-symbols repository, tag 8.0.9 (CC-BY-SA-4.0 with the KiCad libraries' exception for
designs that use them). Only the 17 libraries the generator uses are fetched; a file whose hash differs
from the pinned one is rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TAG = "8.0.9"
URL = "https://gitlab.com/kicad/libraries/kicad-symbols/-/raw/{tag}/{lib}.kicad_sym"
DEFAULT_DEST = ROOT / "build" / f"kicad-symbols-{TAG}"
SHA256 = {
    "74xGxx": "0dd6f82d04b470fba4f6430dcbb2db12beca539a00eaafb1861eff671445175d",
    "Comparator": "79c68b16ff7e82e115c81d8e2aafd4345ae18ef60c9ce22f30528524a85de016",
    "Connector": "d3c305337940d2048a7281674c3976ac6d7f2d5cce9b4065d835e007aac5826c",
    "Connector_Generic": "9fbb70b9dcdb4121384821b18901229300c0cc64f19b26c43e4f7d384609b709",
    "Device": "7503ada06c4fa226c51fd81f7069aa5b19233d0e44fbf71e93cd0776849ec142",
    "Diode": "25a4a6cadc3f1fab7cf1fd60c236494b3a044102ebc027895b1b7542d77419d3",
    "Interface_CAN_LIN": "c38fb427b68e72910f8742540fd24d9c65990b21713ab851aac5387e12267d1e",
    "Isolator": "d2afa6c9c3e4177c3b7f5688d05527f4c6a48120e6d40fa1e5176b5ac4be2b75",
    "Jumper": "f2fdc83abc164c28c2244d868d43d74907d383104f68dd4a85453ab91eb9d1dd",
    "MCU_ST_STM32G4": "012873cbe844ab27e6436dd2728758d4d0b2cc1f6a1404cb50379245e540bfec",
    "Power_Protection": "7621f2131aa3949a103715754de589df3e76ad16829555c62837b3af1346c36b",
    "Power_Supervisor": "d92e210c0e362a183a5512521d8a3e9728c6db9dd27435e7ca16d04a4c5a6641",
    "Reference_Voltage": "bd5484da5bf30302a3324a2cd2274ef28ea3875eb6fac5396dd62ebd36fcea14",
    "Regulator_Linear": "880d91706546291b97777bf3d1bb3bd121b028e34e3badfc7aa0d09a65062904",
    "Regulator_Switching": "0a842b6361bb47f93a7d248f437f7c0a494dfef92ea24bef6d09d02a7096d6ae",
    "Switch": "369914c93a68e40e2ac22f35ee338043f26e84fa0407339f23fe8d9639433191",
    "power": "e56d8bf205f7927dbbd1b309a9d12a706e30a33c7689eb168d131f9e6b598435",
}


def ok(path: pathlib.Path, lib: str) -> bool:
    return path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256[lib]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=pathlib.Path, default=DEFAULT_DEST)
    a = ap.parse_args()
    a.dest.mkdir(parents=True, exist_ok=True)
    for lib in sorted(SHA256):
        path = a.dest / f"{lib}.kicad_sym"
        if ok(path, lib):
            continue
        data = urllib.request.urlopen(URL.format(tag=TAG, lib=lib), timeout=120).read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != SHA256[lib]:
            print(f"{lib}: SHA-256 {digest} does not match the pinned {SHA256[lib]}", file=sys.stderr)
            return 1
        path.write_bytes(data)
    print(f"KiCad symbols {TAG}: {len(SHA256)} libraries in {a.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
