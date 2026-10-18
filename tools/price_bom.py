#!/usr/bin/env python3
"""Price the draft BOM and compute budget scenarios.

    python3 tools/price_bom.py   -> hardware/bom/BOM_priced.csv, docs/BUDGET.md, docs/generated/budget.json

Inputs: hardware/bom/BOM_draft.csv (generated from the schematic data by
tools/gen_kicad_schematic.py) and hardware/bom/pricing.yaml (evidence, dated,
with an evidence class per line). Every total is a LOW-HIGH range. The
feasibility statement is computed from the HIGH totals, never asserted by hand.
Nothing is purchased.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOM = ROOT / "hardware" / "bom" / "BOM_draft.csv"
PRICING = ROOT / "hardware" / "bom" / "pricing.yaml"
FOOTPRINTS = ROOT / "hardware" / "footprints" / "assignments.yaml"
GEN = ROOT / "tools" / "gen_kicad_schematic.py"
BUDGETS = (500.0, 1000.0)


def match(rule, row):
    m = rule["match"]
    if "symbol" in m and not re.search(m["symbol"], row["symbol"]):
        return False
    if "value" in m and not re.search(m["value"], row["value"]):
        return False
    return True


def sheet_titles() -> dict:
    """Sheet name -> functional block title, as the schematic generator names them."""
    return dict(re.findall(r'S\.append\(\("(\w+)", "([^"]+)"', GEN.read_text()))


def price_lines():
    P = yaml.safe_load(PRICING.read_text())
    rows = list(csv.DictReader(BOM.open()))
    titles = sheet_titles()
    out = []
    fps = {e["refs"][0]: e for e in yaml.safe_load(FOOTPRINTS.read_text())["lines"]}
    for r in rows:
        fp = fps.get(r["refs"].split()[0], {})
        rule = next((x for x in P["rules"] if match(x, r)), None)
        if rule is None:
            raise SystemExit(f"no pricing rule for BOM line {r['line']} {r['symbol']} {r['value']}")
        qty = 0 if r["dnp"] else int(r["qty"])
        lo = max(qty * rule["low"], rule.get("min_line_low", 0.0) if qty else 0.0)
        hi = max(qty * rule["high"], rule.get("min_line_high", 0.0) if qty else 0.0)
        out.append({**r, "qty_per_board": qty, "mpn": rule.get("mpn", r["mpn_candidate"]) if not r["mpn_candidate"] or
                    "UNRESOLVED" in str(rule.get("mpn", "")) else r["mpn_candidate"].replace(" (verify)", ""),
                    "package": fp.get("package") or rule.get("package", ""),
                    "footprint": r["footprint"] or f"UNASSIGNED ({fp.get('disposition', 'no disposition')})",
                    "supplier": rule.get("supplier", "-"), "unit_low": rule["low"], "unit_high": rule["high"],
                    "price_date": P["retrieved"] if rule["evidence"] != "allowance" else "-",
                    "ext_low": round(lo, 2), "ext_high": round(hi, 2), "availability": rule.get("availability", ""),
                    "manufacturer": rule.get("manufacturer", "-"), "datasheet": rule.get("datasheet", "-"),
                    "function": "; ".join(titles.get(n, n) for n in r["sheets"].split()),
                    # no substitute has been checked against a primary document: alternates are leads only
                    "alternate_unchecked": rule.get("alternate", ""), "evidence": rule["evidence"],
                    "source": rule.get("source", "")})
    return P, out


def scenario(P, lines, boards, revision):
    parts_lo = sum(l["ext_low"] for l in lines) * boards
    parts_hi = sum(l["ext_high"] for l in lines) * boards
    sp_lo = sp_hi = 0.0
    for sym, n in P["spares"].items():
        cand = [l for l in lines if l["symbol"] == sym and l["qty_per_board"] > 0]
        if cand:
            sp_lo += n * min(l["unit_low"] for l in cand)
            sp_hi += n * max(l["unit_high"] for l in cand)
    ctrl_items = []
    for it in P["project_items"]["controller"]:
        k = boards if it["per"] == "board" else 1
        ctrl_items.append((it["item"], k * it["low"], k * it["high"], it["evidence"]))
    st = P["project_items"]["shipping_tax"]
    rev_lo = rev_hi = 0.0
    if revision:
        pcb = [i for i in P["project_items"]["controller"] if i["item"].startswith(("PCB", "Stencil"))]
        rev_lo = sum(i["low"] for i in pcb) + P["revision_allowance"]["parts_fraction"] * parts_lo / boards
        rev_hi = sum(i["high"] for i in pcb) + P["revision_allowance"]["parts_fraction"] * parts_hi / boards
    ctrl_lo = parts_lo + sp_lo + sum(x[1] for x in ctrl_items) + rev_lo
    ctrl_hi = parts_hi + sp_hi + sum(x[2] for x in ctrl_items) + rev_hi
    tax_lo = st["parts_tax_fraction_low"] * (parts_lo + sp_lo) + st["distributor_shipping_low"]
    tax_hi = st["parts_tax_fraction_high"] * (parts_hi + sp_hi) + st["distributor_shipping_high"]
    inc_items = []
    for it in P["project_items"]["incremental"]:
        k = boards if it["per"] == "board" else 1
        inc_items.append((it["item"], k * it["low"], k * it["high"], it["evidence"]))
    inc_lo = sum(x[1] for x in inc_items)
    inc_hi = sum(x[2] for x in inc_items)
    eq_lo = sum(e["low"] for e in P["equipment"])
    eq_hi = sum(e["high"] for e in P["equipment"])
    return {"boards": boards, "revision": revision, "parts": (parts_lo, parts_hi), "spares": (sp_lo, sp_hi),
            "controller_items": ctrl_items, "revision_allowance": (rev_lo, rev_hi),
            "controller_only": (ctrl_lo + tax_lo, ctrl_hi + tax_hi), "shipping_tax": (tax_lo, tax_hi),
            "incremental_items": inc_items, "incremental": (inc_lo, inc_hi), "equipment_if_not_owned": (eq_lo, eq_hi),
            "complete_owned_equipment": (ctrl_lo + tax_lo + inc_lo, ctrl_hi + tax_hi + inc_hi),
            "complete_buying_equipment": (ctrl_lo + tax_lo + inc_lo + eq_lo, ctrl_hi + tax_hi + inc_hi + eq_hi)}


def main() -> int:
    P, lines = price_lines()
    out_csv = ROOT / "hardware" / "bom" / "BOM_priced.csv"
    cols = ["line", "refs", "qty_per_board", "manufacturer", "mpn", "value", "package", "footprint", "function",
            "rating_basis", "datasheet", "supplier", "unit_low", "unit_high", "price_date", "ext_low", "ext_high",
            "availability", "selection_status", "alternate_unchecked", "evidence", "source", "pin_check"]
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for l in lines:
            w.writerow(l)
    by_ev = {}
    for l in lines:
        e = by_ev.setdefault(l["evidence"], [0.0, 0.0, 0])
        e[0] += l["ext_low"]
        e[1] += l["ext_high"]
        e[2] += 1
    scen = {"S1 one functional prototype": scenario(P, lines, 1, False),
            "S1R one prototype + one revision": scenario(P, lines, 1, True),
            "S2 two assembled boards": scenario(P, lines, 2, False),
            "S2R two boards + one revision": scenario(P, lines, 2, True)}
    (ROOT / "docs" / "generated" / "budget.json").write_text(json.dumps(
        {"by_evidence": by_ev, "scenarios": scen}, indent=1, default=list))
    f = lambda t: f"${t[0]:,.0f} – ${t[1]:,.0f}"  # noqa: E731
    L = ["# Budget decision: priced draft design (provisional)", "",
         "> Generated by `tools/price_bom.py` from the schematic-derived BOM (`hardware/bom/BOM_draft.csv`) and the "
         "pricing evidence in `hardware/bom/pricing.yaml`. **Nothing has been purchased.**", "",
         "> **Price quality.** No supplier quote has been obtained yet. Prices come from web-search "
         "snapshots of distributor pages (undated caches, retrieved 2026-10-15), from **representative** candidates "
         "for the rating-dependent parts (not selections), or from stated **allowances**. Every number is a range. "
         "Re-quote on live pages before deciding anything.", "",
         "## 1. One board's parts by evidence class", "",
         "| evidence | BOM lines | parts cost per board |", "|---|---|---|"]
    for k, (lo, hi, n) in sorted(by_ev.items()):
        L.append(f"| {k} | {n} | ${lo:,.2f} – ${hi:,.2f} |")
    tot_lo = sum(v[0] for v in by_ev.values())
    tot_hi = sum(v[1] for v in by_ev.values())
    L += [f"| **total** | {len(lines)} | **${tot_lo:,.2f} – ${tot_hi:,.2f}** |", "",
          "The rating-dependent lines (MOSFETs, shunts, bulk capacitors, fuse, TVS, P-FET, connectors) are priced as "
          "representatives. Their real cost moves with the motor and battery ratings.", "",
          "## 2. Scenarios (low – high)", "",
          "| scenario | A. controller only | B. A + vehicle integration | C. B + bring-up equipment if not owned | $500 − B (low / high end) | $1,000 − C (low / high end) |",
          "|---|---|---|---|---|---|"]
    for name, s in scen.items():
        co, cp, ce = s["controller_only"], s["complete_owned_equipment"], s["complete_buying_equipment"]
        m = lambda x: f"${x:,.0f}" if x >= 0 else f"−${-x:,.0f}"  # noqa: E731
        L.append(f"| {name} | {f(co)} | {f(cp)} | {f(ce)} | {m(BUDGETS[0] - cp[0])} / {m(BUDGETS[0] - cp[1])} | "
                 f"{m(BUDGETS[1] - ce[0])} / {m(BUDGETS[1] - ce[1])} |")
    L += ["", "A = board parts, spares, PCB, shipping, stencil, consumables, heatsink, tax/shipping on parts, and the "
          "revision allowance where named. B adds connectors, harness, enclosure and bench load. C adds the bring-up "
          "tools the team may not own; an oscilloscope and a differential probe are NOT included and must be "
          "borrowed. A negative remainder means over budget at that end of the range.", ""]
    s1 = scen["S1 one functional prototype"]
    L += ["", "Contingency = budget minus the HIGH end of the range. The vs-$500 column assumes the team already owns "
          "the bring-up equipment; the vs-$1,000 column assumes it buys the listed items (an oscilloscope and a "
          "differential probe are NOT included: they must be borrowed).", "",
          "## 3. Line items of scenario S1 (one prototype)", "",
          f"* Parts for one board: {f(s1['parts'])}; spares (6 MOSFETs, gate driver, 2 shunts, TVS, 2 fuses, CAN "
          f"transceiver, MCU): {f(s1['spares'])}; tax and shipping on parts: {f(s1['shipping_tax'])}."]
    for it, lo, hi, ev in s1["controller_items"]:
        L.append(f"* {it}: ${lo:,.0f} – ${hi:,.0f} ({ev})")
    for it, lo, hi, ev in s1["incremental_items"]:
        L.append(f"* [integration] {it}: ${lo:,.0f} – ${hi:,.0f} ({ev})")
    for e in P["equipment"]:
        L.append(f"* [equipment, only if not owned] {e['item']}: ${e['low']:,.0f} – ${e['high']:,.0f} ({e['evidence']}: {e['source']})")
    def verdict(rng, budget):
        lo, hi = rng
        if hi <= budget:
            return f"within ${budget:,.0f} even at the high end ({f(rng)})"
        if lo <= budget:
            return f"STRADDLES ${budget:,.0f} ({f(rng)}): within only if prices land in the lower part of the range"
        return f"OVER ${budget:,.0f} even at the low end ({f(rng)})"
    all_within = all(scen[k]["complete_owned_equipment"][1] <= BUDGETS[0] for k in scen if k.startswith("S1")) and \
        scen["S2R two boards + one revision"]["complete_buying_equipment"][1] <= BUDGETS[1]
    spread = sorted([(it, hi - lo) for it, lo, hi, _e in s1["controller_items"] + s1["incremental_items"]] +
                    [("board parts (allowance + representative + snippet)", s1["parts"][1] - s1["parts"][0]),
                     ("spares", s1["spares"][1] - s1["spares"][0]),
                     ("tax and shipping on parts", s1["shipping_tax"][1] - s1["shipping_tax"][0])],
                    key=lambda x: -x[1])[:5]
    L += ["", "## 4. Decision statement (computed, not asserted)", "",
          f"* One prototype, controller only (A): {verdict(scen['S1 one functional prototype']['controller_only'], BUDGETS[0])}.",
          f"* One prototype with vehicle integration, equipment owned (B): {verdict(scen['S1 one functional prototype']['complete_owned_equipment'], BUDGETS[0])}.",
          f"* One prototype + one revision + integration, equipment owned (B): {verdict(scen['S1R one prototype + one revision']['complete_owned_equipment'], BUDGETS[0])}.",
          f"* Two boards + integration, equipment owned (B): {verdict(scen['S2 two assembled boards']['complete_owned_equipment'], BUDGETS[1])}.",
          f"* Two boards + one revision + integration + equipment (C): {verdict(scen['S2R two boards + one revision']['complete_buying_equipment'], BUDGETS[1])}.",
          "", "Largest contributors to the low–high spread (scenario S1): " +
          "; ".join(f"{n} (${d:,.0f})" for n, d in spread) + ".", "",
          ("**Conclusion: within budget at the high end of every listed scenario, under the conditions below.**"
           if all_within else
           "**Conclusion: the budget is not shown to be feasible.** At least one range reaches past its limit, so "
           "feasibility cannot be claimed until the spread is closed.") + " Closing the spread takes: a live PCB quote for the actual board size "
          "and copper weight; live distributor quotes for the snippet lines; the motor and battery ratings (they fix "
          "the representative power-stage lines and the heatsink); and an inventory check of the passives and "
          "equipment the team already owns. Each of these narrows the range, and `tools/price_bom.py` recomputes the "
          "statement.", "",
          "Conditions behind all the ranges:",
          "  1. rating-dependent parts stay in the representative class (100 V D2PAK MOSFETs, 2512 shunts, "
          "~220 µF bulk); ≥ 80 A peak or a battery above ~60 V changes the power stage, heatsink and copper weight;",
          "  2. stock gaps seen in the snapshots are resolved (INA228 in the US, DRV8353SRTAR at Digi-Key, the 1 mΩ "
          "Kelvin shunt at 38 weeks);",
          "  3. hand assembly by the vehicle team with the stencil (no PCBA service);",
          "  4. an oscilloscope, a differential probe, a rework station and a reflow method are available.", ""]
    (ROOT / "docs" / "BUDGET.md").write_text("\n".join(L))
    print("\n".join(x for x in L if x.startswith(("| S", "* One", "* Two", "Largest", "**Conclusion"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
