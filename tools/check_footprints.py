#!/usr/bin/env python3
"""Footprint assignment check: every BOM line has a disposition, every assigned footprint matches its symbol.

    python3 tools/check_footprints.py --fetch         # download the pinned KiCad 8.0.9 footprints (SHA-256 checked)
    python3 tools/check_footprints.py                 # check and write hardware/footprints/FOOTPRINT_CHECK.md
    python3 tools/check_footprints.py --check         # fail on a failed check or a stale report
    python3 tools/check_footprints.py --fetch --pin   # record the hash of newly assigned footprints

Inputs: hardware/footprints/assignments.yaml (one entry per BOM line, hand-maintained), hardware/bom/BOM_draft.csv,
the generated schematic sheets (the symbols embedded in them give each reference's pin numbers) and the footprint
files from the KiCad project's kicad-footprints repository, tag 8.0.9, pinned in library_pins.yaml.

Per assigned footprint it checks: the file is the pinned one; the set of numbered pads equals the symbol's set of
pin numbers (an exposed pad must carry a symbol pin number, extra numbered pads fail); a courtyard and a
fabrication outline exist (solder jumpers and net ties are copper only and have no body to outline; a net tie
also has no courtyard); the mounting type is SMD or through-hole; the package named in the assignment appears
in the footprint name for chip parts; the footprint passes the symbol's footprint filters (as KiCad's ERC
footprint check does); two-terminal diodes and LEDs have pin 1 = K on the symbol, matching the
library's pad 1 = cathode convention. It records the footprint's own description as the land-pattern source,
because some library footprints are drawn from another manufacturer's drawing than the selected part's.
"""
from __future__ import annotations

import argparse
import collections
import csv
import fnmatch
import hashlib
import pathlib
import re
import sys
import urllib.request

import yaml
from kiutils.footprint import Footprint
from kiutils.schematic import Schematic

ROOT = pathlib.Path(__file__).resolve().parent.parent
FPDIR = ROOT / "hardware" / "footprints"
SRC = FPDIR / "assignments.yaml"
PINS = FPDIR / "library_pins.yaml"
DOC = FPDIR / "FOOTPRINT_CHECK.md"
TABLE = ROOT / "hardware" / "kicad" / "fp-lib-table"
BOM = ROOT / "hardware" / "bom" / "BOM_draft.csv"
KICAD = ROOT / "hardware" / "kicad"
TAG = "8.0.9"
LIB = ROOT / "build" / f"kicad-footprints-{TAG}"
URL = "https://gitlab.com/kicad/libraries/kicad-footprints/-/raw/{tag}/{lib}.pretty/{name}.kicad_mod"
ASSIGNED = ("verified", "assigned_drawing_pending")
ORDER = ["verified", "assigned_drawing_pending", "rating_dependent", "datasheet_dependent", "connector_dependent",
         "pinout_blocked"]


def load():
    return yaml.safe_load(SRC.read_text())


def fp_path(lib_id: str) -> pathlib.Path:
    lib, name = lib_id.split(":", 1)
    return LIB / f"{lib}.pretty" / f"{name}.kicad_mod"


def used_footprints(a: dict) -> list[str]:
    return sorted({e["footprint"] for e in a["lines"] if e.get("footprint")})


def fetch(a: dict, pin: bool) -> int:
    pins = yaml.safe_load(PINS.read_text()) if PINS.exists() else {}
    pins = pins or {}
    bad = 0
    for fid in used_footprints(a):
        p = fp_path(fid)
        if not p.exists():
            lib, name = fid.split(":", 1)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(urllib.request.urlopen(URL.format(tag=TAG, lib=lib, name=name), timeout=120).read())
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if fid not in pins and pin:
            pins[fid] = digest
        elif pins.get(fid) != digest:
            print(f"{fid}: SHA-256 {digest} is not the pinned {pins.get(fid)}", file=sys.stderr)
            bad += 1
    if pin:
        PINS.write_text("# SHA-256 of each KiCad footprint file used, tag " + TAG + "; written by\n"
                        "# tools/check_footprints.py --fetch --pin after the file has been reviewed.\n"
                        + yaml.safe_dump(dict(sorted(pins.items())), sort_keys=False))
    print(f"KiCad footprints {TAG}: {len(used_footprints(a))} files in {LIB}")
    return 1 if bad else 0


def symbol_pins() -> dict[str, tuple[str, dict[str, str], list[str]]]:
    """reference -> (lib_id, {pin number: pin name}, footprint filters) from the symbols embedded in the sheets."""
    out = {}
    for f in sorted(KICAD.glob("*.kicad_sch")):
        sch = Schematic.from_file(str(f))
        libs = {}
        for s in sch.libSymbols:
            pins = {}
            for unit in [s] + list(s.units):
                for p in unit.pins:
                    pins[p.number] = p.name
            filters = next((p.value.split() for p in s.properties if p.key == "ki_fp_filters"), [])
            libs[s.libId] = (pins, filters)
        for ss in sch.schematicSymbols:
            ref = next(p.value for p in ss.properties if p.key == "Reference")
            if ref.startswith("#"):
                continue
            lib_id = f"{ss.libraryNickname}:{ss.entryName}" if ss.libraryNickname else ss.entryName
            out[ref] = (lib_id, *libs.get(lib_id, libs.get(ss.libId, ({}, []))))
    return out


def filters_match(fid: str, filters: list[str]) -> bool:
    """KiCad's footprint filters: a filter with ':' matches library:name, otherwise the name; no filter matches all."""
    name = fid.split(":", 1)[1]
    return not filters or any(fnmatch.fnmatch((fid if ":" in f else name).lower(), f.lower()) for f in filters)


def check_footprint(fid: str, pins: dict[str, str], package: str | None, lib_id: str,
                    filters: list[str]) -> tuple[list[str], dict]:
    p = fp_path(fid)
    problems = []
    if not p.exists():
        return [f"{fid} not fetched (run --fetch)"], {}
    f = Footprint.from_file(str(p))
    pads = collections.Counter(pd.number for pd in f.pads if pd.number)
    layers = {g.layer for g in f.graphicItems if hasattr(g, "layer")}
    info = {"pads": sum(pads.values()), "numbers": len(pads), "descr": (f.description or "").strip(),
            "type": f.attributes.type if f.attributes and f.attributes.type else "unspecified",
            "shared": sorted(n for n, k in pads.items() if k > 1)}  # exposed pad with vias, or a switch's pad pairs
    if set(pads) != set(pins):
        miss, extra = sorted(set(pins) - set(pads)), sorted(set(pads) - set(pins))
        problems.append(f"pads differ from symbol pins (no pad for {miss}, no pin for {extra})")
    copper_only = fid.startswith(("NetTie:", "Jumper:SolderJumper"))  # no body: placed copper, not a part
    if not layers & {"F.CrtYd", "B.CrtYd"} and not fid.startswith("NetTie:"):
        problems.append("no courtyard")
    if "F.Fab" not in layers and not copper_only:
        problems.append("no fabrication outline")
    if info["type"] not in ("smd", "through_hole") and not fid.startswith(("NetTie:", "TestPoint:", "Jumper:")):
        problems.append(f"mounting type {info['type']}")
    if package and re.fullmatch(r"0[0-9]{3}|1[0-9]{3}", package) and package not in fid:
        problems.append(f"package {package} not in the footprint name")
    if not filters_match(fid, filters):
        problems.append(f"footprint outside the symbol's filters {filters}")
    if lib_id in ("Device:LED", "Device:D_Zener", "Device:D_Schottky") and pins.get("1") != "K":
        problems.append("symbol pin 1 is not the cathode")
    return problems, info


def evaluate(a: dict) -> dict:
    bom = list(csv.DictReader(BOM.open()))
    by_first = {}
    seen = collections.Counter()
    problems = []
    for e in a["lines"]:
        for r in e["refs"]:
            seen[r] += 1
        by_first[e["refs"][0]] = e
        if e["disposition"] not in ORDER:
            problems.append(f"{e['refs'][0]}: unknown disposition {e['disposition']}")
        if (e["disposition"] in ASSIGNED) != bool(e.get("footprint")):
            problems.append(f"{e['refs'][0]}: disposition {e['disposition']} and footprint {e.get('footprint')}")
    bom_refs = [r for row in bom for r in row["refs"].split()]
    for r in set(bom_refs) - set(seen):
        problems.append(f"{r}: in the BOM, no footprint disposition")
    for r in set(seen) - set(bom_refs):
        problems.append(f"{r}: has a disposition, not in the BOM")
    for r, n in seen.items():
        if n > 1:
            problems.append(f"{r}: {n} dispositions")
    sym = symbol_pins()
    rows = []
    for row in bom:
        refs = row["refs"].split()
        e = by_first.get(refs[0])
        if e is None or sorted(e["refs"]) != sorted(refs):
            problems.append(f"BOM line {row['line']}: refs {refs} not one assignment entry")
            continue
        res = {"line": int(row["line"]), "refs": refs, "e": e, "info": {}, "problems": []}
        if e.get("footprint"):
            for r in refs:
                lib_id, pins, filters = sym.get(r, ("?", {}, []))
                pr, info = check_footprint(e["footprint"], pins, e.get("package"), lib_id, filters)
                res["problems"] += [f"{r}: {x}" for x in pr]
                res["info"] = info
        problems += res["problems"]
        rows.append(res)
    counts = collections.Counter(r["e"]["disposition"] for r in rows)
    tps = sum(1 for r in rows if r["refs"][0].startswith("TP"))
    return {"rows": rows, "problems": problems, "counts": counts, "tp": tps}


def lib_table(a: dict) -> str:
    """Project footprint table: the libraries the assignment uses, from ${KICAD8_FOOTPRINT_DIR} (the pinned copy in
    CI, tools/run_kicad_erc.sh; an installed KiCad 8 library otherwise)."""
    libs = sorted({f.split(":", 1)[0] for f in used_footprints(a)})
    rows = "".join(f'  (lib (name "{n}")(type "KiCad")(uri "${{KICAD8_FOOTPRINT_DIR}}/{n}.pretty")(options "")'
                   f'(descr "KiCad {TAG}"))\n' for n in libs)
    return "(fp_lib_table\n  (version 7)\n" + rows + ")\n"


def render(a: dict, ev: dict) -> str:
    c, rows = ev["counts"], ev["rows"]
    n = len(rows)
    parts = lambda d: sum(len(r["refs"]) for r in rows if r["e"]["disposition"] == d)  # noqa: E731
    L = ["# Footprint check", "",
         "Generated by `tools/check_footprints.py` from `assignments.yaml`, `hardware/bom/BOM_draft.csv`, the "
         f"generated schematic and the KiCad footprints {TAG} pinned in `library_pins.yaml`; do not edit.", "",
         "## Summary", "",
         f"Before this revision: 0 of {n} BOM lines had a footprint. Now:", "",
         "| Disposition | BOM lines | Parts | Meaning |", "|---|---|---|---|"]
    meaning = {"verified": "assigned, every check below passed; generic part defined by value and package",
               "assigned_drawing_pending": "assigned, checks passed; the manufacturer's package drawing is not read",
               "rating_dependent": "waits for a rating (battery, motor)",
               "datasheet_dependent": "waits for a value or pin voltage from an unread data sheet",
               "connector_dependent": "waits for the harness connector family",
               "pinout_blocked": "symbol pins are placeholders"}
    for d in ORDER:
        L.append(f"| {d} | {c.get(d, 0)} | {parts(d)} | {meaning[d]} |")
    L += ["", f"Verified: {c.get('verified', 0)} lines ({c.get('verified', 0) - ev['tp']} without the {ev['tp']} "
          f"test-point lines). Checks failed: {len(ev['problems'])}.", ""]
    if ev["problems"]:
        L += ["## Failures", ""] + [f"* {p}" for p in ev["problems"]] + [""]
    tht = [r for r in rows if r["info"].get("type") == "through_hole"]
    L += ["## Assembly", "",
          "Through-hole parts among the assigned footprints (hand soldering or a mixed process): "
          + (", ".join(f"{' '.join(r['refs'])} ({r['e']['footprint'].split(':')[1]})" for r in tht) or "none")
          + ". Everything else assigned is SMD on the top side.", "",
          "## Per line", "",
          "| Line | Refs | Disposition | Footprint | Pads (numbers) | Land-pattern source (library description) | Basis | Blocker |",
          "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (ORDER.index(x["e"]["disposition"]), x["line"])):
        e, i = r["e"], r["info"]
        refs = " ".join(r["refs"]) if len(r["refs"]) <= 6 else " ".join(r["refs"][:6]) + f" (+{len(r['refs']) - 6})"
        pads = f"{i['pads']} ({i['numbers']})" + (f", several pads numbered {','.join(i['shared'])}" if i.get("shared") else "") if i else "-"
        descr = i.get("descr", "-").replace("|", "/")[:110] if i else "-"
        L.append(f"| {r['line']} | {refs} | {e['disposition']} | {e.get('footprint', '-')} | {pads} | {descr} | "
                 f"{e['basis'].replace('|', '/')} | {e.get('blocker', '')} |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--pin", action="store_true")
    ap.add_argument("--check", action="store_true")
    o = ap.parse_args()
    a = load()
    if o.fetch:
        return fetch(a, o.pin)
    ev = evaluate(a)
    text, table = render(a, ev), lib_table(a)
    if o.check:
        for p in ev["problems"]:
            print(p, file=sys.stderr)
        stale = not DOC.exists() or DOC.read_text() != text or not TABLE.exists() or TABLE.read_text() != table
        if stale:
            print(f"{DOC.relative_to(ROOT)} is stale: run python3 tools/check_footprints.py", file=sys.stderr)
        return 1 if ev["problems"] or stale else 0
    DOC.write_text(text)
    TABLE.write_text(table)
    print(f"wrote {DOC.relative_to(ROOT)} and {TABLE.relative_to(ROOT)}: {len(ev['problems'])} problems")
    return 1 if ev["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
