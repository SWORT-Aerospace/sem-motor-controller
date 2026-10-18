#!/usr/bin/env python3
"""Pin-type rule check on the netlist KiCad exported (NOT a KiCad ERC).

    python3 tools/pin_type_check.py   -> hardware/kicad/PIN_TYPE_CHECK.md

KiCad 7 has no command-line ERC; the real ERC runs with KiCad 8 or newer
(`tools/run_kicad_erc.sh`, the CI `erc` job). This tool applies a subset of ERC-style pin-type rules to
`hardware/kicad/semmc.net`, which KiCad itself exported (so connectivity and
pin types are KiCad's, not the generator's). It does not replace a real ERC:
KiCad's ERC also checks label/sheet-pin consistency, the full pin-conflict
matrix, power flags, off-grid and duplicate references. Run
`tools/run_kicad_erc.sh` with KiCad 8 or newer for that.

Rules (KiCad ERC equivalent in brackets):
  R1 two or more output / power_out pins on one net            [pin conflict: output-output]
  R2 power_in pins on a net with no power_out pin               [power pin not driven] (KiCad needs a PWR_FLAG
     where a rail is driven through passives or a connector)
  R3 input pins on a net with nothing that can drive it         [input pin not driven]
  R4 a pin alone on its net and not marked no-connect           [pin not connected]
  R5 open-collector pins on a net with no passive (pull-up)     [design check, not in KiCad ERC]
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
NET = ROOT / "hardware" / "kicad" / "semmc.net"
OUT = ROOT / "hardware" / "kicad" / "PIN_TYPE_CHECK.md"

DRIVERS = {"output", "power_out", "bidirectional", "tri_state", "passive", "open_collector", "open_emitter"}


def parse(text: str):
    nets = []
    for m in re.finditer(r'\(net \(code "?(\d+)"?\) \(name "([^"]*)"\)(.*?)\)\s*(?=\(net \(code|\)\s*\)\s*$)', text, re.S):
        nodes = [(r, p, t, (fn.group(1) if (fn := re.search(r'\(pinfunction "([^"]*)"\)', body)) else ""))
                 for r, p, body, t in [(a, b, c, d) for a, b, c, d in
                                       re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)((?:\s*\(pinfunction "[^"]*"\))?)\s*\(pintype "([^"]+)"\)', m.group(3))]]
        nets.append((m.group(2), nodes))
    return nets


def power_flags(sch_dir: pathlib.Path) -> set[str]:
    """Nets carrying a PWR_FLAG. KiCad leaves power symbols out of netlists, so read them from the sheets:
    the flag's pin sits at the symbol origin, where the generator places the rail's global label."""
    flagged = set()
    for f in sorted(sch_dir.glob("*.kicad_sch")):
        t = f.read_text()
        pos = {(round(float(m.group(1)), 3), round(float(m.group(2)), 3)) for m in re.finditer(r'\(symbol \(lib_id "power:PWR_FLAG"\) \(at ([\d.\-]+) ([\d.\-]+)', t)}
        for m in re.finditer(r'\(global_label "([^"]+)" \(shape [a-z_]+\) \(at ([\d.\-]+) ([\d.\-]+)', t):
            if (round(float(m.group(2)), 3), round(float(m.group(3)), 3)) in pos:
                flagged.add(m.group(1))
    return flagged


def check(nets, flagged=frozenset()):
    findings = []
    for name, nodes in nets:
        types = [n[2] for n in nodes]
        base = [t.split("+")[0] for t in types]
        outs = [n for n in nodes if n[2].split("+")[0] in ("output", "power_out")]
        if len(outs) >= 2:
            findings.append(("R1", "error", name, ", ".join(f"{r}.{p}" for r, p, *_ in outs)))
        if "power_in" in base and "power_out" not in base and name.lstrip("/") not in flagged:
            findings.append(("R2", "error (KiCad ERC)", name,
                             ", ".join(f"{r}.{p}" for r, p, t, _ in nodes if t.startswith("power_in"))))
        if "input" in base and not any(b in DRIVERS for b in base):
            findings.append(("R3", "error", name, ", ".join(f"{r}.{p}" for r, p, t, _ in nodes if t.startswith("input"))))
        if len(nodes) == 1 and "no_connect" not in types[0]:
            r, p, t, _ = nodes[0]
            findings.append(("R4", "error", name, f"{r}.{p} ({t})"))
        if "open_collector" in base and "passive" not in base:
            findings.append(("R5", "warning", name, ", ".join(f"{r}.{p}" for r, p, t, _ in nodes if "open_collector" in t)))
    return findings


def main() -> int:
    nets = parse(NET.read_text())
    flagged = power_flags(NET.parent)
    f = check(nets, flagged)
    counts = {}
    for rule, sev, *_ in f:
        counts[rule] = counts.get(rule, 0) + 1
    L = ["# Pin-type rule check on the KiCad-exported netlist (generated; NOT a KiCad ERC)", "",
         "> `tools/pin_type_check.py` on `hardware/kicad/semmc.net` (exported by `kicad-cli` from the draft). "
         "Connectivity and pin types are KiCad's. **This is not an ERC**: the KiCad ERC runs separately with KiCad 8 "
         "or newer (`tools/run_kicad_erc.sh`, the CI `erc` job; results in `docs/VERIFICATION_REPORT.md`). "
         "Neither check shows that the circuit is electrically correct; that needs review and measurement.", "",
         f"Nets checked: {len(nets)}. Rails with a PWR_FLAG (read from the sheets): "
         f"{', '.join(f'`{n}`' for n in sorted(flagged)) or 'none'}. Findings: {len(f)} "
         f"({', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) or 'none'}).", "",
         "| Rule | Severity | Net | Pins |", "|---|---|---|---|"]
    for rule, sev, net, pins in sorted(f):
        L.append(f"| {rule} | {sev} | `{net}` | {pins} |")
    L += ["", "Rules: R1 output-output conflict; R2 power input with no power output on the net (KiCad reports this "
          "unless a PWR_FLAG marks the rail as driven); R3 input with nothing able to drive it; R4 pin alone on its net "
          "without a no-connect marker; R5 open-drain without a pull-up (design rule, not in KiCad ERC).", ""]
    OUT.write_text("\n".join(L))
    print(f"{len(nets)} nets, {len(f)} findings -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
