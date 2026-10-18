#!/usr/bin/env python3
"""Cross-check the draft hardware against itself: netlist, pin allocation, BOM,
platform notes, timing budget and configuration.

    python3 tools/hw_consistency.py    -> hardware/review/CONSISTENCY_CHECK.md (exit 1 on any FAIL)

Source of truth for connectivity is the netlist KiCad itself exports from the
committed schematic (hardware/kicad/semmc.net, written by
tools/gen_kicad_schematic.py --check), not the generator's intent. Results:
  PASS   the property holds in the exported design
  FAIL   a contradiction between two artefacts (must be fixed)
  OPEN   cannot be decided without a part datasheet, a measurement or a vehicle decision
This is a consistency check of a DRAFT; it is not a design review and not an ERC.
"""
from __future__ import annotations

import ast
import collections
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NET = ROOT / "hardware" / "kicad" / "semmc.net"
PINS = ROOT / "hardware" / "interfaces" / "pin_allocation_STM32G474VBCETx.csv"   # LQFP100, as in the schematic
BOM = ROOT / "hardware" / "bom" / "BOM_draft.csv"
GEN = ROOT / "tools" / "gen_kicad_schematic.py"
PLATFORM = ROOT / "firmware" / "platform" / "stm32g4" / "src" / "pwm.h"
OUT = ROOT / "hardware" / "review" / "CONSISTENCY_CHECK.md"


def short(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def parse_netlist(path: pathlib.Path):
    t = path.read_text()
    comps = {}
    for m in re.finditer(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)(.*?)\(libsource \(lib "([^"]*)"\) \(part "([^"]*)"\)'
                         r'(.*?)\(sheetpath', t, re.S):
        sheet = re.search(r'\(property \(name "Sheetname"\) \(value "([^"]*)"\)\)', m.group(6))
        fp = re.search(r'\(footprint "([^"]*)"\)', m.group(3))
        comps[m.group(1)] = {"value": m.group(2), "lib": m.group(4), "part": m.group(5),
                             "sheet": sheet.group(1) if sheet else "", "footprint": fp.group(1) if fp else ""}
    nets = {}
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]+)"\)(.*?)\)\)\n(?=    \(net|  \)\))', t, re.S):
        nodes = re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)(?: \(pinfunction "([^"]*)"\))? '
                           r'\(pintype "([^"]+)"\)', m.group(2))
        nets[short(m.group(1))] = [{"ref": r, "pin": p, "fn": f, "type": ty} for r, p, f, ty in nodes]
    pin_net = {(n["ref"], n["pin"]): name for name, nodes in nets.items() for n in nodes}
    return comps, nets, pin_net


def mcu_net_map() -> dict:
    tree = ast.parse(GEN.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MCU_NET" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("MCU_NET not found in the generator")


def run():
    comps, nets, pin_net = parse_netlist(NET)
    R = []

    def rec(cid, status, detail):
        R.append((cid, status, detail))

    def find(pred):
        return [r for r, c in comps.items() if pred(c)]

    def other_end(ref, net):
        """Net at the other pin of a two-terminal part connected to `net`."""
        ends = [n for (r, _p), n in pin_net.items() if r == ref]
        rest = [n for n in ends if n != net]
        return rest[0] if len(ends) == 2 and rest else None

    def resistors_to(net, target):
        return [n["ref"] for n in nets.get(net, []) if n["ref"].startswith("R") and other_end(n["ref"], net) == target]

    drv = find(lambda c: c["value"].startswith("DRV8353S"))
    andg = find(lambda c: c["part"] == "74LVC1G08")
    mcu = find(lambda c: c["value"].startswith("STM32G474"))
    wdg = find(lambda c: c["part"] == "MAX6369")
    cmpov = find(lambda c: c["part"].startswith("TLV7041"))
    opto = find(lambda c: c["part"] == "PC817")
    assert len(drv) == len(andg) == len(mcu) == len(wdg) == len(cmpov) == len(opto) == 1, "expected one of each"
    drv, andg, mcu, wdg, cmpov, opto = drv[0], andg[0], mcu[0], wdg[0], cmpov[0], opto[0]
    pins = {row["function"]: row for row in csv.DictReader(PINS.open())}
    mnet = mcu_net_map()

    def net_of_fn(ref, fn):
        return next((name for name, nodes in nets.items() for n in nodes if n["ref"] == ref and n["fn"] == fn), None)

    # ---- protection ---------------------------------------------------------------
    en = net_of_fn(drv, "ENABLE")
    drivers = [n for n in nets[en] if n["type"] in ("output", "power_out", "open_collector")]
    mcu_on_en = [n for n in nets[en] if n["ref"] == mcu]
    fb_pin = pins["OUTPUT_ENABLE_FEEDBACK"]["position"]
    ok = (len(drivers) == 1 and drivers[0]["ref"] == andg and drivers[0]["pin"] == "4" and
          all(n["pin"] == fb_pin for n in mcu_on_en) and resistors_to(en, "GND"))
    rec("PR1 driver ENABLE has one driver: the AND gate", "PASS" if ok else "FAIL",
        f"{drv}.ENABLE on {en}: driven by {[(d['ref'], d['pin']) for d in drivers]}; MCU only on pin "
        f"{[n['pin'] for n in mcu_on_en]} (OUTPUT_ENABLE_FEEDBACK = pin {fb_pin}); pull-down "
        f"{resistors_to(en, 'GND')}")
    a1, a2 = pin_net.get((andg, "1")), pin_net.get((andg, "2"))
    rec("PR2 AND inputs are the MCU enable and HW_PERMIT", "PASS" if {a1, a2} == {"MCU_DRV_EN", "HW_PERMIT"} else "FAIL",
        f"{andg} inputs: pin 1 {a1}, pin 2 {a2}")
    pd = {n: resistors_to(n, "GND") for n in ("MCU_DRV_EN", "DRV_EN_GATED", "HW_PERMIT", "PRECHG_EN")}
    rec("PR3 every enable defaults off (pull-down to GND)", "PASS" if all(pd.values()) else "FAIL",
        "; ".join(f"{k}: {v or 'NONE'}" for k, v in pd.items()))
    nf = net_of_fn(drv, "nFAULT")
    bk = pins["PWM_BREAK"]
    on_bk = pin_net.get((mcu, bk["position"]))
    rec("PR4 driver nFAULT reaches TIM1_BKIN, with a pull-up", "PASS" if on_bk == nf and resistors_to(nf, "+3V3") else "FAIL",
        f"{drv}.nFAULT on {nf}; MCU pin {bk['position']} ({bk['pin']}, {bk['signal']}) on {on_bk}; pull-up "
        f"{resistors_to(nf, '+3V3')}")
    ov = pin_net.get((cmpov, "1"))
    bk2 = pins["PWM_BREAK2"]
    on_bk2 = pin_net.get((mcu, bk2["position"]))
    rec("PR5 over-voltage comparator reaches TIM1_BKIN2, with a pull-up",
        "PASS" if on_bk2 == ov and resistors_to(ov, "+3V3") else "FAIL",
        f"{cmpov} output on {ov}; MCU pin {bk2['position']} ({bk2['pin']}) on {on_bk2}; pull-up {resistors_to(ov, '+3V3')}")
    wdo = next((pin_net[(r, p)] for (r, p), _n in pin_net.items() if r == wdg and p == "7"), None)
    diodes = [n["ref"] for n in nets.get(wdo, []) if n["ref"].startswith("D") and other_end(n["ref"], wdo) == "HW_PERMIT"]
    k_side = [n for n in nets.get(wdo, []) if n["ref"] in diodes and n["fn"] == "K"]
    to_nrst = [n["ref"] for n in nets.get(wdo, []) if n["ref"].startswith("R") and other_end(n["ref"], wdo) == "NRST"]
    rec("PR6 watchdog timeout pulls HW_PERMIT low and resets the MCU",
        "PASS" if diodes and len(k_side) == len(diodes) and to_nrst else "FAIL",
        f"{wdg} WDO on {wdo}; diode(s) {diodes} with cathode on WDO (wired pull-down of HW_PERMIT); to NRST via {to_nrst}")
    hp_drivers = [n for n in nets["HW_PERMIT"] if n["type"] in ("output", "power_out") or n["ref"] == mcu]
    es = pins["ESTOP_CHAIN_SENSE"]["position"]
    opto_on = [n for n in nets["HW_PERMIT"] if n["ref"] == opto]
    rec("PR7 HW_PERMIT comes from the safety loop; the MCU only senses it",
        "PASS" if opto_on and all(n["ref"] == mcu and n["pin"] == es for n in hp_drivers) else "FAIL",
        f"{opto} on HW_PERMIT pin {[n['pin'] for n in opto_on]}; MCU on pin {[n['pin'] for n in hp_drivers]} "
        f"(ESTOP_CHAIN_SENSE = pin {es})")
    rec("PR8 independent over-current comparator on BKIN2", "OPEN",
        "none in the draft: hardware over-current shutdown is the gate driver's VDS monitoring through nFAULT -> BKIN "
        "(threshold depends on the MOSFET R_DS(on), i.e. on the motor current); BKIN2 carries the over-voltage trip only. "
        "Decide after the motor peak current is known.")

    # ---- pins -----------------------------------------------------------------------
    bad = []
    for fn, row in pins.items():
        want = mnet.get(fn, fn)
        got = pin_net.get((mcu, row["position"]))
        if got != want:
            bad.append(f"{fn} pin {row['position']} ({row['pin']}): netlist {got}, expected {want}")
    rec("PN1 every allocated MCU pin carries the intended net", "FAIL" if bad else "PASS",
        "; ".join(bad) or f"{len(pins)} allocated functions match the netlist")
    txt = PLATFORM.read_text()
    m1 = re.search(r"\bBKIN\s+\((P[A-G]\d+)", txt)
    m2 = re.search(r"\bBKIN2\s+\((P[A-G]\d+)", txt)
    plat = (m1.group(1) if m1 else None, m2.group(1) if m2 else None)
    want = (pins["PWM_BREAK"]["pin"], pins["PWM_BREAK2"]["pin"])
    rec("PN2 target PWM driver (pwm.h) names the same break pins as the allocation", "PASS" if plat == want else "FAIL",
        f"pwm.h BKIN/BKIN2 {plat}; pin allocation {want}")
    desc = pins["PWM_BREAK2"]["note"]
    rec("PN3 BKIN2 description matches the schematic (over-voltage)",
        "PASS" if "over-voltage" in desc and "over-current comparator\"" not in desc else "FAIL", desc)

    # ---- BOM --------------------------------------------------------------------------
    rows = list(csv.DictReader(BOM.open()))
    bom_refs = collections.Counter()
    val_bad, qty_bad, fp_bad = [], [], []
    for r in rows:
        refs = [x.strip() for x in r["refs"].split() if x.strip()] if " " in r["refs"] else \
            [x.strip() for x in r["refs"].split(",") if x.strip()]
        bom_refs.update(refs)
        if int(r["qty"]) != len(refs):
            qty_bad.append(r["line"])
        for ref in refs:
            if ref in comps and comps[ref]["value"] != r["value"]:
                val_bad.append(f"{ref}: BOM '{r['value']}' vs schematic '{comps[ref]['value']}'")
            if ref in comps and comps[ref]["footprint"] != r.get("footprint", ""):
                fp_bad.append(f"{ref}: BOM '{r.get('footprint', '')}' vs netlist '{comps[ref]['footprint']}'")
    real = {r for r in comps if not r.startswith("#")}
    missing = sorted(real - set(bom_refs))
    extra = sorted(set(bom_refs) - real)
    dup = sorted(r for r, n in bom_refs.items() if n > 1)
    rec("BM1 BOM lines cover every schematic component exactly once",
        "PASS" if not (missing or extra or dup or qty_bad or val_bad) else "FAIL",
        f"{len(real)} components, {len(rows)} BOM lines; missing {missing[:8]}, extra {extra[:8]}, duplicated {dup[:8]}, "
        f"qty mismatches {qty_bad[:8]}, value mismatches {val_bad[:4]}")
    with_fp = sum(1 for r in rows if r.get("footprint"))
    rec("BM3 every netlist footprint equals its BOM line's footprint", "FAIL" if fp_bad else "PASS",
        "; ".join(fp_bad[:6]) or f"{with_fp} of {len(rows)} BOM lines have a footprint, all identical in the netlist "
        "(assignment and its checks: hardware/footprints/FOOTPRINT_CHECK.md)")
    unresolved = sum(1 for r in rows if r["selection_status"].startswith("UNRESOLVED"))
    rec("BM2 motor/battery-dependent parts stay unresolved", "OPEN",
        f"{unresolved} BOM lines are UNRESOLVED (ratings depend on the motor, battery, harness or rules); no fabrication "
        "release while any remains")

    # ---- timing / configuration --------------------------------------------------------
    sys.path.insert(0, str(ROOT))
    import yaml  # noqa: E402

    from tools import timing_budget as TB  # noqa: E402
    cfg = yaml.safe_load((ROOT / "config" / "vehicle.synthetic.yaml").read_text())
    settle_cfg = cfg["inverter"]["current_sample_settle_s"]
    settle_tb = TB.v("t_ring_s") + TB.v("t_csa_settle_s")
    rec("TM1 configured current-sample settle equals the timing budget's assumption",
        "PASS" if abs(settle_cfg - settle_tb) < 1e-12 else "FAIL",
        f"config {settle_cfg * 1e6:.2f} us; timing budget ringing {TB.v('t_ring_s') * 1e6:.2f} + CSA settle "
        f"{TB.v('t_csa_settle_s') * 1e6:.2f} us (both ASSUMED, to measure at bench stage 3/4)")
    cbad = [k for k, (val, tag, path) in TB.K.items() if tag == "C" and
            abs(val - float(_get(cfg, path.split(" ")[0]))) > 1e-12]
    rec("TM2 timing budget inputs tagged [C] equal the configuration", "FAIL" if cbad else "PASS",
        f"mismatched: {cbad}" if cbad else "pwm frequency, dead time, duty_max, voltage-limit fraction read from config")
    rec("TM3 dead time and PWM frequency", "OPEN",
        f"synthetic {cfg['inverter']['deadtime_s'] * 1e9:.0f} ns at {cfg['inverter']['pwm_frequency_Hz'] / 1e3:.0f} kHz; "
        "dead time depends on the selected MOSFETs' switching times, PWM frequency on the motor inductance")

    # ---- power rails --------------------------------------------------------------------
    # Power-path tracing: series passives and jumpers are two-terminal; a power-path IC
    # passes OUT -> IN; a FET passes S <-> D. Sources: a regulator's power output pin or
    # a connector (J<n>, not a jumper JP<n>).
    two_term = {r for r in comps if r[0] in "LRDF" or r.startswith(("FB", "JP"))}
    by_ref = collections.defaultdict(dict)
    for (r, p), n in pin_net.items():
        fn = next((x["fn"] for x in nets[n] if x["ref"] == r and x["pin"] == p), "")
        by_ref[r][fn or p] = n

    def neighbours(net):
        out = []
        for x in nets[net]:
            r = x["ref"]
            if comps.get(r, {}).get("part") == "R_Shunt":          # four-terminal shunt: force pins 1-2
                ends = {by_ref[r].get("1"), by_ref[r].get("2")}
                out += [(r, v) for v in ends if v and v != net and net in ends]
            elif r in two_term:
                o = other_end(r, net)
                if o:
                    out.append((r, o))
            elif r.startswith("U") and {"IN", "OUT"} <= set(by_ref[r]) and by_ref[r]["OUT"] == net:
                out.append((r, by_ref[r]["IN"]))
            elif r.startswith("Q") and comps[r]["sheet"] == "power_input":   # precharge/bypass path, not the bridge
                ends = {k: v for k, v in by_ref[r].items() if k in ("D", "S", "2", "3")}
                out += [(r, v) for v in ends.values() if v != net]
        return out

    def is_source_connector(ref):
        return bool(re.match(r"^J\d", ref)) and comps.get(ref, {}).get("sheet") == "power_input"
    rails = [n for n in nets if any(x["type"] == "power_in" for x in nets[n]) and n not in ("GND", "PGND")]
    lines = []
    fails = []
    for rail in sorted(rails):
        loads = sorted({x["ref"] for x in nets[rail] if x["type"] == "power_in"})
        # breadth-first over the power path; a regulator output beats a connector at any depth
        seen, frontier, reach = {rail}, [(rail, [])], []
        while frontier:
            net, hops = frontier.pop(0)
            reach.append((net, hops))
            for ref, o in neighbours(net):
                if o not in seen and o not in ("GND", "PGND"):
                    seen.add(o)
                    frontier.append((o, hops + [ref]))
        src = next(((net, hops, x["ref"]) for net, hops in reach for x in nets[net] if x["type"] == "power_out"), None) \
            or next(((net, hops, x["ref"]) for net, hops in reach for x in nets[net] if is_source_connector(x["ref"])), None)
        if src is None:
            fails.append(rail)
            lines.append(f"{rail}: loads {loads}; NO SOURCE FOUND")
        else:
            lines.append(f"{rail}: loads {loads}; source {src[2]} on {src[0]} via {src[1] or 'direct'}")
    rec("PW1 every powered rail traces to a regulator output or the battery connector",
        "FAIL" if fails else "PASS", " | ".join(lines))
    rec("PW2 rail current budgets", "OPEN",
        "supply currents of the candidate ICs were not read from primary datasheets; regulator ratings vs loads to be "
        "checked when the parts are chosen (input sheet)")
    return R


def _get(cfg, path):
    node = cfg
    for part in path.split("."):
        node = node[part]
    return node


def main() -> int:
    R = run()
    n = collections.Counter(s for _c, s, _d in R)
    L = ["# Hardware consistency check (draft)", "",
         "Generated by `tools/hw_consistency.py` from the netlist KiCad exports (`hardware/kicad/semmc.net`), "
         "the pin allocation, the draft BOM, the STM32G4 platform notes, the timing budget and the configuration. "
         "PASS: holds in the exported design. FAIL: two artefacts contradict each other. OPEN: needs a datasheet, a "
         "measurement or a vehicle decision. A consistency check of a draft, not a design review and not an ERC.", "",
         f"Totals: {n.get('PASS', 0)} PASS, {n.get('FAIL', 0)} FAIL, {n.get('OPEN', 0)} OPEN.", "",
         "| Check | Result | Detail |", "|---|---|---|"]
    L += [f"| {c} | **{s}** | {d.replace('|', '/')} |" for c, s, d in R]
    OUT.write_text("\n".join(L) + "\n")
    for c, s, d in R:
        print(f"{s:5s} {c}: {d[:160]}")
    print(f"wrote {OUT.relative_to(ROOT)}: {dict(n)}")
    return 1 if n.get("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
