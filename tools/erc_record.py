#!/usr/bin/env python3
"""ERC record: a KiCad ERC result tied to the exact schematic inputs it was run on.

    python3 tools/erc_record.py hash                       # print the SHA-256 of the current schematic inputs
    python3 tools/erc_record.py record --kicad 8.0.9 --errors 0 --warnings 0 --run URL [--artifact TEXT]
    python3 tools/erc_record.py record --report hardware/kicad/ERC_REPORT.json --run URL
    python3 tools/erc_record.py check [--report hardware/kicad/ERC_REPORT.json]

The ERC runs in CI (job `erc`, KiCad 8.0.9 from the KiCad PPA, symbols and footprints pinned by SHA-256); this
environment has KiCad 7, which has no command-line ERC. hardware/kicad/ERC_RECORD.yaml stores the result of one
CI run together with the SHA-256 of everything that run checked: the schematic sheets, the project symbol
library, the library tables, the project file, and the pinned hashes of the KiCad symbol and footprint files. The
release gate (tools/release_gate.py, G5) accepts the record only while that hash equals the current one, so any
schematic or library change invalidates it until a new CI ERC is recorded.

`check` (run by the CI ERC job after the ERC) fails when the record matches the current inputs but this run's
report disagrees with it. A record for other inputs is reported as stale, without failing the job: the release
gate is where it blocks.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
KICAD = ROOT / "hardware" / "kicad"
RECORD = KICAD / "ERC_RECORD.yaml"
FP_PINS = ROOT / "hardware" / "footprints" / "library_pins.yaml"


def inputs() -> list[pathlib.Path]:
    files = sorted(KICAD.glob("*.kicad_sch")) + [KICAD / n for n in ("semmc.kicad_sym", "sym-lib-table",
                                                                     "fp-lib-table", "semmc.kicad_pro")]
    return files + [FP_PINS]


def inputs_hash() -> str:
    sys.path.insert(0, str(ROOT))
    from tools.fetch_kicad_symbols import SHA256 as SYMBOL_PINS, TAG  # noqa: E402
    h = hashlib.sha256()
    for p in inputs():
        h.update(f"{p.parent.name}/{p.name}".encode() + b"\0" + p.read_bytes() + b"\0")
    h.update(f"kicad-symbols {TAG}\0".encode())
    for lib, digest in sorted(SYMBOL_PINS.items()):
        h.update(f"{lib}={digest}\0".encode())
    return h.hexdigest()


def report_counts(path: pathlib.Path) -> tuple[str, int, int, list[str]]:
    rep = json.loads(path.read_text())
    vs = [v for s in rep.get("sheets", []) for v in s.get("violations", [])]
    errors = sum(1 for v in vs if v.get("severity") == "error")
    warn = [v.get("type", "?") for v in vs if v.get("severity") == "warning"]
    return str(rep.get("kicad_version", "?")), errors, len(warn), sorted(set(warn))


def load() -> dict | None:
    return yaml.safe_load(RECORD.read_text()) if RECORD.exists() else None


def status() -> tuple[bool, str]:
    """(valid, text) for the release gate: a record for the current inputs with no error."""
    r = load()
    if r is None:
        return False, "no ERC record (hardware/kicad/ERC_RECORD.yaml)"
    if r["schematic_inputs_sha256"] != inputs_hash():
        return False, f"ERC record is for other schematic inputs (recorded {r['schematic_inputs_sha256'][:12]}, now {inputs_hash()[:12]})"
    return r["errors"] == 0, (f"KiCad {r['kicad_version']} ERC on the current inputs: {r['errors']} errors, "
                              f"{r['warnings']} warnings ({r['run']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hash")
    rec = sub.add_parser("record")
    rec.add_argument("--report", type=pathlib.Path)
    rec.add_argument("--kicad")
    rec.add_argument("--errors", type=int)
    rec.add_argument("--warnings", type=int)
    rec.add_argument("--warning-types", nargs="*", default=[])
    rec.add_argument("--run", required=True, help="URL of the CI run whose ERC this is")
    rec.add_argument("--artifact", default="", help="the run's report artifact and its digest")
    chk = sub.add_parser("check")
    chk.add_argument("--report", type=pathlib.Path)
    a = ap.parse_args()

    if a.cmd == "hash":
        print(inputs_hash())
        return 0
    if a.cmd == "record":
        if a.report:
            ver, err, warn, types = report_counts(a.report)
            digest = hashlib.sha256(a.report.read_bytes()).hexdigest()
        else:
            if a.kicad is None or a.errors is None or a.warnings is None:
                ap.error("record needs --report, or --kicad, --errors and --warnings from the CI run")
            ver, err, warn, types, digest = a.kicad, a.errors, a.warnings, sorted(set(a.warning_types)), None
        out = {"schematic_inputs_sha256": inputs_hash(), "kicad_version": ver, "errors": err, "warnings": warn,
               "warning_types": types, "run": a.run, "artifact": a.artifact or None, "report_sha256": digest,
               "recorded": datetime.date.today().isoformat(),
               "inputs": [f"{p.parent.parent.name}/{p.parent.name}/{p.name}" for p in inputs()] + ["tools/fetch_kicad_symbols.py SHA256 table"]}
        RECORD.write_text("# KiCad ERC result tied to the schematic inputs it checked; written by tools/erc_record.py.\n"
                          "# Valid only while schematic_inputs_sha256 equals `python3 tools/erc_record.py hash`.\n"
                          + yaml.safe_dump(out, sort_keys=False, width=110))
        print(f"wrote {RECORD.relative_to(ROOT)}: {err} errors, {warn} warnings")
        return 0
    r = load()
    if r is None:
        print("no ERC record", file=sys.stderr)
        return 1
    cur = inputs_hash()
    if r["schematic_inputs_sha256"] != cur:
        print(f"ERC record stale: recorded for {r['schematic_inputs_sha256'][:12]}, inputs now {cur[:12]}. "
              "Record this run's ERC with tools/erc_record.py record (the release gate stays failed until then).")
        return 0
    if a.report:
        ver, err, warn, _ = report_counts(a.report)
        if (ver, err, warn) != (r["kicad_version"], r["errors"], r["warnings"]):
            print(f"this run's ERC ({ver}: {err} errors, {warn} warnings) differs from the record "
                  f"({r['kicad_version']}: {r['errors']} errors, {r['warnings']} warnings) for the same inputs",
                  file=sys.stderr)
            return 1
        print(f"ERC record confirmed by this run: KiCad {ver}, {err} errors, {warn} warnings")
    else:
        print(f"ERC record matches the current inputs ({r['run']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
