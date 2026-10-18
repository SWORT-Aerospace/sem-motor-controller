#!/usr/bin/env python3
"""Fabrication release gate for the motor-controller board.

    python3 tools/release_gate.py                 # evaluate; write docs/generated/release_gate.md
    python3 tools/release_gate.py --package DIR   # also build the release package, only if every gate passes

The gate conditions are listed in hardware/layout/PRE_LAYOUT.md section 5. Each is checked from the files in
the repository; none is assumed. The package (sources, PDFs, Gerbers, drill, BOM, placement, notes, firmware
revision, configuration, checklists, limitations, SHA-256 checksums, manifest) is produced only when all pass:
a failing gate never produces fabrication outputs, so nothing incomplete can be mistaken for a release.
Exit status: 0 when the gate passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOM = ROOT / "hardware/bom/BOM_draft.csv"
REGISTER = ROOT / "hardware/selection/DATASHEET_REGISTER.md"
KICAD = ROOT / "hardware/kicad"
PCB = KICAD / "semmc.kicad_pcb"
REVIEW = ROOT / "hardware/review/REVIEW_CHECKLIST.md"
LAYOUT_REVIEW = ROOT / "hardware/review/LAYOUT_REVIEW.md"
ERC_JSON = KICAD / "ERC_REPORT.json"
REPORT = ROOT / "docs/generated/release_gate.md"


def _rows():
    return list(csv.DictReader(BOM.open()))


def gate_bom_resolved():
    bad = [r["line"] for r in _rows() if r["selection_status"].startswith("UNRESOLVED") or "UNRESOLVED" in r["value"]]
    return not bad, f"{len(bad)} UNRESOLVED BOM lines" if bad else "every BOM line resolved"


def gate_footprints_and_pins():
    priced = list(csv.DictReader((ROOT / "hardware/bom/BOM_priced.csv").open()))
    fp_empty = sum(1 for r in priced if not r["footprint"] or "UNASSIGNED" in r["footprint"])
    placeholders = len(re.findall(r'UNVERIFIED|placeholder', (KICAD / "semmc.kicad_sym").read_text(), re.I))
    ics = [r for r in _rows() if r["refs"].split()[0].startswith("U")]
    no_primary = [r["refs"] for r in ics if "PRIMARY" not in r["pin_check"].upper() or "NOT read" in r["pin_check"]]
    ok = fp_empty == 0 and placeholders == 0 and not no_primary
    return ok, (f"{fp_empty} of {len(priced)} BOM lines without a footprint; {placeholders} placeholder marks in the project symbols; "
                f"{len(no_primary)} ICs without a primary pin check")


def gate_datasheets():
    n_open = REGISTER.read_text().count("**open**")
    return n_open == 0, f"{n_open} datasheet register rows open"


def gate_pcb_drc():
    if not PCB.exists():
        return False, "no PCB file (hardware/kicad/semmc.kicad_pcb)"
    if shutil.which("kicad-cli") is None:
        return False, "kicad-cli not available to run the DRC"
    out = KICAD / "DRC_REPORT.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(out), str(PCB)],
                   capture_output=True)
    if not out.exists():
        return False, "DRC did not produce a report"
    rep = json.loads(out.read_text())
    n = len(rep.get("violations", [])) + len(rep.get("unconnected_items", []))
    return n == 0, f"DRC: {n} violations or unconnected items"


def gate_erc():
    """The committed ERC record (tools/erc_record.py) for the current schematic inputs, from the CI KiCad 8.0.9
    ERC; every warning type it lists must be discussed in the design review."""
    sys.path.insert(0, str(ROOT))
    from tools import erc_record  # noqa: E402
    ok, text = erc_record.status()
    r = erc_record.load() or {}
    reviewed = (ROOT / "hardware/review/DESIGN_REVIEW.md").read_text()
    unreviewed = [t for t in r.get("warning_types", []) if t not in reviewed]
    if ERC_JSON.exists():  # in the CI ERC job the fresh report is also present: it must agree
        _, err, warn, _ = erc_record.report_counts(ERC_JSON)
        if (err, warn) != (r.get("errors"), r.get("warnings")):
            return False, f"{text}; this tree's ERC_REPORT.json has {err} errors, {warn} warnings"
    return ok and not unreviewed, f"{text}; {len(unreviewed)} warning types not reviewed"


def gate_signed_reviews():
    def signed(p: pathlib.Path) -> bool:
        return p.exists() and re.search(r"^Signed:\s*\S+.*\d{4}-\d{2}-\d{2}", p.read_text(), re.M) is not None
    checklist_open = REVIEW.read_text().count("- [ ]")
    ok = signed(REVIEW) and checklist_open == 0 and signed(LAYOUT_REVIEW)
    return ok, (f"design review: {checklist_open} unchecked items, signed: {signed(REVIEW)}; "
                f"schematic-to-layout review signed: {signed(LAYOUT_REVIEW)}")


def gate_release_config():
    cfgs = [p for p in (ROOT / "config").glob("vehicle.*.yaml") if p.name not in ("vehicle.synthetic.yaml",
                                                                                   "vehicle.unconfigured.yaml")]
    for p in cfgs:
        r = subprocess.run([sys.executable, str(ROOT / "tools/config_tool.py"), "validate", str(p), "--mode", "hw"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return True, f"{p.relative_to(ROOT)} is hardware-valid"
    return False, "no hardware-valid vehicle configuration (config/vehicle.<car>.yaml)"


GATES = [
    ("G1", "BOM fully resolved", gate_bom_resolved),
    ("G2", "Footprints assigned, pinouts primary-checked, no placeholder symbol", gate_footprints_and_pins),
    ("G3", "Datasheet register complete", gate_datasheets),
    ("G4", "PCB exists and passes DRC", gate_pcb_drc),
    ("G5", "ERC on the current schematic: no error, every warning reviewed", gate_erc),
    ("G6", "Design review and schematic-to-layout review signed", gate_signed_reviews),
    ("G7", "Hardware-valid vehicle configuration for the release", gate_release_config),
]


def evaluate():
    return [(gid, title, *fn()) for gid, title, fn in GATES]


def report(results) -> str:
    passed = all(ok for _, _, ok, _ in results)
    L = ["# Fabrication release gate", "", "Generated by `tools/release_gate.py`; do not edit.", "",
         f"**Result: {'PASS' if passed else 'FAIL'}.** "
         + ("The release package may be built." if passed else
            "No fabrication outputs are produced; the board is not fabrication-ready."), "",
         "| Gate | Condition | Result | Detail |", "|---|---|---|---|"]
    for gid, title, ok, detail in results:
        L.append(f"| {gid} | {title} | {'PASS' if ok else 'FAIL'} | {detail} |")
    return "\n".join(L) + "\n"


def build_package(dest: pathlib.Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(list(a), check=True, cwd=ROOT)  # noqa: E731
    run("kicad-cli", "sch", "export", "pdf", "--output", str(dest / "schematic.pdf"), str(KICAD / "semmc.kicad_sch"))
    (dest / "gerbers").mkdir(exist_ok=True)
    run("kicad-cli", "pcb", "export", "gerbers", "--output", str(dest / "gerbers"), str(PCB))
    run("kicad-cli", "pcb", "export", "drill", "--output", str(dest / "gerbers"), str(PCB))
    run("kicad-cli", "pcb", "export", "pos", "--output", str(dest / "placement.csv"), "--format", "csv", str(PCB))
    shutil.copytree(KICAD, dest / "sources", dirs_exist_ok=True)
    for f in (BOM, REVIEW, LAYOUT_REVIEW, ROOT / "hardware/layout/PRE_LAYOUT.md", ROOT / "docs/BLOCKERS.md"):
        shutil.copy(f, dest / f.name)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    sums = {str(p.relative_to(dest)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(dest.rglob("*")) if p.is_file()}
    (dest / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()))
    (dest / "manifest.json").write_text(json.dumps({"revision": rev, "files": sums}, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--package", type=pathlib.Path)
    a = ap.parse_args()
    results = evaluate()
    REPORT.write_text(report(results))
    for gid, title, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {gid} {title}: {detail}")
    passed = all(ok for _, _, ok, _ in results)
    if a.package:
        if not passed:
            print("release package NOT built: the gate fails")
            return 1
        build_package(a.package)
        print(f"release package in {a.package}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
