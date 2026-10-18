#!/usr/bin/env python3
"""Worst-case trip and release of the over-voltage comparator on sheet 02.

    python3 tools/ov_trip_worst_case.py           # write hardware/calculations/ov_trip_worst_case.md
    python3 tools/ov_trip_worst_case.py --check   # fail if that file is stale

Inputs: hardware/calculations/ov_trip_inputs.yaml (null = not known). The circuit: the divider R_top/R_bot puts
V- = V_DC x R_bot / (R_top + R_bot) on the TLV7041 inverting input; the + input sits between the TL431 node
(through R_s) and the open-drain output BRK2_N (through R_h); BRK2_N is pulled up to +3V3 through R_p. Node
equations, with I_b the + input bias current (into the pin) and I_lk the leakage drawn from BRK2_N:

    tripped  (output low, V_o = V_OL):   V+ = (V_ref / R_s + V_OL / R_h - I_b) / (1 / R_s + 1 / R_h)
    released (output open):              (V_ref - V+) / R_s + (V_o - V+) / R_h = I_b
                                         (V_3V3 - V_o) / R_p - (V_o - V+) / R_h = I_lk

Rising V_DC trips when V- > V+(released) + V_os; falling V_DC releases when V- < V+(tripped) - V_os. Referred to
the bus, both are multiples of the set point V_set = V_ref,nom x (R_top + R_bot) / R_bot. The worst case takes
every corner of every bounded input; it is reported only when no input it needs is null.
"""
from __future__ import annotations

import argparse
import itertools
import pathlib
import sys

import numpy as np
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "hardware" / "calculations" / "ov_trip_inputs.yaml"
DOC = ROOT / "hardware" / "calculations" / "ov_trip_worst_case.md"


def v_plus(v_ref, v_33, r_s, r_h, r_p, released, v_ol=0.0, i_b=0.0, i_lk=0.0):
    """The + input voltage, and the output voltage, in either output state."""
    if not released:
        return (v_ref / r_s + v_ol / r_h - i_b) / (1.0 / r_s + 1.0 / r_h), v_ol
    a = np.array([[-(1.0 / r_s + 1.0 / r_h), 1.0 / r_h], [1.0 / r_h, -(1.0 / r_p + 1.0 / r_h)]])
    b = np.array([i_b - v_ref / r_s, i_lk - v_33 / r_p])
    vp, vo = np.linalg.solve(a, b)
    return float(vp), float(vo)


def corners(bounds: dict):
    """Every combination of the (low, high) pairs in bounds."""
    keys = list(bounds)
    for combo in itertools.product(*(bounds[k] for k in keys)):
        yield dict(zip(keys, combo))


def multiples(c: dict, v_ref_nom: float):
    """Trip and release, as multiples of V_set, for one corner c."""
    vp_rel, _ = v_plus(c["v_ref"], c["v_33"], c["r_s"], c["r_h"], c["r_p"], True, i_b=c["i_b"], i_lk=c["i_lk"])
    vp_trip, _ = v_plus(c["v_ref"], c["v_33"], c["r_s"], c["r_h"], c["r_p"], False, v_ol=c["v_ol"], i_b=c["i_b"])
    k_div = c["div"]  # actual divider ratio / nominal ratio
    hys = c["v_hys"] / 2.0
    trip = (vp_rel + c["v_os"] + hys) * k_div / v_ref_nom
    rel = (vp_trip - c["v_os"] - hys) * k_div / v_ref_nom
    return trip, rel


def evaluate(inp: dict) -> dict:
    res, dev, sup = inp["resistors"], inp["devices"], inp["supply"]
    net = inp["network"]

    def r(name):
        x = res[net[name]]
        return x["nominal_ohm"], x["tolerance"]

    v_ref_nom = dev["V_ref_V"]["nominal"]
    nominal = dict(v_ref=v_ref_nom, v_33=sup["V_3V3_V"]["nominal"], r_s=r("R_s")[0], r_h=r("R_h")[0],
                   r_p=r("R_p")[0], v_ol=0.0, i_b=0.0, i_lk=0.0, v_os=0.0, v_hys=0.0, div=1.0)
    out = {"nominal": multiples(nominal, v_ref_nom)}

    def rb(name):
        n, t = r(name)
        return (n * (1 - t), n * (1 + t))

    t_top, t_bot = res[net["R_top"]]["tolerance"], res[net["R_bot"]]["tolerance"]
    div_b = (1.0 - t_top - t_bot, 1.0 + t_top + t_bot)  # bound on (R_top + R_bot) / R_bot over its nominal
    res_only = dict(nominal, r_s=rb("R_s"), r_h=rb("R_h"), r_p=rb("R_p"), div=div_b)
    res_only = {k: v if isinstance(v, tuple) else (v,) for k, v in res_only.items()}
    ks = [multiples(c, v_ref_nom) for c in corners(res_only)]
    out["resistors_only"] = (min(k[0] for k in ks), max(k[0] for k in ks), min(k[1] for k in ks),
                             max(k[1] for k in ks))

    need = {"V_ref_V min/max": (dev["V_ref_V"]["min"], dev["V_ref_V"]["max"]),
            "V_3V3_V min/max": (sup["V_3V3_V"]["min"], sup["V_3V3_V"]["max"]),
            "V_os_V max": (dev["V_os_V"]["max"],), "V_hys_internal_V": (dev["V_hys_internal_V"]["nominal"],),
            "I_bias_A max": (dev["I_bias_A"]["max"],), "V_OL_V max": (dev["V_OL_V"]["max"],),
            "I_leak_out_A max": (dev["I_leak_out_A"]["max"],), "I_leak_pin_A max": (dev["I_leak_pin_A"]["max"],)}
    out["missing"] = [k for k, v in need.items() if any(x is None for x in v)]
    if not out["missing"]:
        i_lk = dev["I_leak_out_A"]["max"] + dev["I_leak_pin_A"]["max"]
        full = dict(res_only, v_ref=(dev["V_ref_V"]["min"], dev["V_ref_V"]["max"]),
                    v_33=(sup["V_3V3_V"]["min"], sup["V_3V3_V"]["max"]), v_ol=(0.0, dev["V_OL_V"]["max"]),
                    i_b=(-dev["I_bias_A"]["max"], dev["I_bias_A"]["max"]), i_lk=(0.0, i_lk),
                    v_os=(-dev["V_os_V"]["max"], dev["V_os_V"]["max"]), v_hys=(dev["V_hys_internal_V"]["nominal"],))
        ks = [multiples(c, v_ref_nom) for c in corners(full)]
        out["worst_case"] = (min(k[0] for k in ks), max(k[0] for k in ks), min(k[1] for k in ks),
                             max(k[1] for k in ks))
    # TL431 cathode current: what R_bias supplies minus what leaves the node through R_s. In the tripped state
    # V+ is below V_ref, so current leaves the node and the cathode current is at its lowest.
    i_s = max((v_ref_nom - out_vp(nominal, st)) / nominal["r_s"] for st in (True, False))
    r_bias, t_bias = r("R_bias")
    out["i_k_nominal_A"] = (nominal["v_33"] - v_ref_nom) / r_bias - i_s
    out["i_k_low_A"] = (nominal["v_33"] - v_ref_nom) / (r_bias * (1 + t_bias)) - i_s  # nominal supply and V_ref
    lim = inp["limits"]
    out["criteria_missing"] = [k for k in ("V_bat_max_V", "V_regen_margin_V", "V_stress_max_V") if lim[k] is None]
    return out


def out_vp(c: dict, released: bool) -> float:
    return v_plus(c["v_ref"], c["v_33"], c["r_s"], c["r_h"], c["r_p"], released)[0]


def pct(x: float) -> str:
    return f"{(x - 1.0) * 100.0:+.2f} %"


def render(inp: dict) -> str:
    e = evaluate(inp)
    t, rl = e["nominal"]
    a, b, c, d = e["resistors_only"]
    net = inp["network"]
    L = ["# Over-voltage trip: worst case", "",
         "Generated by `tools/ov_trip_worst_case.py` from `ov_trip_inputs.yaml`; do not edit. The circuit and the node "
         "equations are in the tool's docstring; the design is `hardware/review/DESIGN_REVIEW.md` item 6. Thresholds "
         "are given at the bus as multiples of the set point V_set = 2.495 V x (R_top + R_bot) / R_bot, so they hold "
         "for whatever divider the battery decision sets.", "",
         f"Network: R_s = {net['R_s']}, R_h = {net['R_h']}, R_p = {net['R_p']}, R_bias = {net['R_bias']}, "
         f"R_top = {net['R_top']}, R_bot = {net['R_bot']}. Resistor tolerances: {inp['tolerance_basis']}.", "",
         "| Case | Trip (rising), x V_set | Release (falling), x V_set | Status |", "|---|---|---|---|",
         f"| Nominal, ideal comparator and reference | {t:.4f} ({pct(t)}) | {rl:.4f} ({pct(rl)}) | calculation |",
         f"| Resistor tolerances only (all corners) | {a:.4f} to {b:.4f} | {c:.4f} to {d:.4f} | calculation; device terms excluded |"]
    if "worst_case" in e:
        a, b, c, d = e["worst_case"]
        L.append(f"| Full worst case | {a:.4f} to {b:.4f} | {c:.4f} to {d:.4f} | all inputs bounded |")
    else:
        L.append("| Full worst case | pending | pending | missing: " + ", ".join(e["missing"]) + " |")
    L += ["",
          f"TL431 cathode current at nominal values: {e['i_k_nominal_A'] * 1e3:.2f} mA; with R_bias 1 % high: "
          f"{e['i_k_low_A'] * 1e3:.2f} mA. Against the minimum for regulation: "
          + ("pending (`I_k_min_A`, TL431 data sheet)" if inp["devices"]["I_k_min_A"]["max"] is None else
             f"{inp['devices']['I_k_min_A']['max'] * 1e3:.2f} mA") + "; the supply's lower bound is also needed.", "",
          "## Acceptance criteria", "",
          "1. Lowest trip above V_bat,max plus the regeneration margin (no nuisance trip at full charge).",
          "2. Highest trip below the lowest stress rating (MOSFET V_DS, link capacitors, DRV8353 VM) minus the "
          "measured switching overshoot.",
          "3. Lowest release above V_bat,max, so the comparator releases once the bus is back in its normal range "
          "(otherwise the break cannot be cleared at full charge: safe, but the controller stays unavailable).", "",
          "Status: " + ("pending; missing " + ", ".join(e["criteria_missing"]) if e["criteria_missing"] else "evaluable")
          + ". Until the device terms and these limits exist, the trip is not verified: blocker B-OVTRIP.", "",
          "## Power-up and loading, to check against the data sheets", "",
          "* The logic rail comes up from the battery side, before the precharge, so the link may already be charged "
          "while +3V3 rises. Below the comparator's minimum supply its output is not specified; the MCU is in reset "
          "then and TIM1 is not configured, so the gate outputs are off whatever BRK2_N does. Until the TL431 "
          "regulates, its node follows +3V3 through R_bias; the trip is defined only once +3V3 and V_ref are both "
          "in range. The firmware arms the break input when it configures TIM1 (`pwm_init`), after the clock and "
          "supply are up.",
          "* BRK2_N is loaded by R_h, the PC3 input and the test point; the released level and the trip use the "
          "leakage terms above. ADC sampling on VBUS_SENSE draws charge from the divider node through 1 k; C207 "
          "holds the node, and the size of that dip against the hysteresis is to be checked once C207 and the ADC "
          "sampling time are fixed.",
          "* The comparator has no other supply decoupling requirement recorded here; follow its data sheet.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = render(yaml.safe_load(SRC.read_text()))
    if a.check:
        if not DOC.exists() or DOC.read_text() != text:
            print(f"{DOC.relative_to(ROOT)} is stale: run python3 tools/ov_trip_worst_case.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(text)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
