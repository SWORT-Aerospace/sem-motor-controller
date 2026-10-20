#!/usr/bin/env python3
"""Telematics-only bill of materials: totals for the bench and configurations A and B from hardware/telematics/bom.yaml.

    python3 tools/telematics_bom.py            # write docs/TELEMATICS_BOM.md and docs/generated/telematics_bom.json
    python3 tools/telematics_bom.py --check    # fail if either is stale

Every total is the sum of its own lines (low and high ends), never a difference of other budgets. A line
without a price is excluded and listed. The recurring cost uses the live message size measured from the
telematics demonstration (docs/generated/telematics_demo/summary.json) when it is there, else the assumed size.

The file is refused (exit 2) when a line that names a firmware driver points at a file that does not exist or
does not contain the identifier it says the firmware checks, when a bench line needs the vehicle supply, or when
the supply section's rule is broken by a pair it lists as checked.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "hardware" / "telematics" / "bom.yaml"
DOC = ROOT / "docs" / "TELEMATICS_BOM.md"
JSON = ROOT / "docs" / "generated" / "telematics_bom.json"
DEMO = ROOT / "docs" / "generated" / "telematics_demo" / "summary.json"
BUDGET = (500.0, 1000.0)


def load() -> dict:
    return yaml.safe_load(SRC.read_text())


def _ext(line: dict) -> tuple[float | None, float | None]:
    if line.get("low") is None or line.get("high") is None:
        return None, None
    return line["qty"] * line["low"], line["qty"] * line["high"]


CONFIGS = (("bench", ("bench",)), ("A", ("bench", "A")), ("B", ("bench", "A", "B")),
           ("B_with_display", ("bench", "A", "B", "B_display")))


def validate(data: dict) -> list[str]:
    err = []
    for l in data["lines"]:
        if l.get("driver"):
            f = ROOT / l["driver"]
            if not f.exists():
                err.append(f"{l['id']}: driver {l['driver']} does not exist")
            elif l.get("checks") and l["checks"] not in f.read_text():
                err.append(f"{l['id']}: {l['driver']} does not contain {l['checks']!r}")
        if l["config"] == "bench" and l.get("blocked_by"):
            err.append(f"{l['id']}: a bench line cannot wait on {l['blocked_by']}")
    s = data["supply"]
    if s.get("battery_max_V") is None and s.get("vehicle_power_connection") != "blocked":
        err.append("supply: the vehicle power connection must stay blocked while battery_max_V is unknown")
    return err


def supply_verdicts(s: dict) -> list[dict]:
    """Each listed TVS / DC-DC pair against the rule: the clamp must not exceed the DC-DC input maximum, and the
    standoff must cover the pack's maximum, which is unknown until the vehicle team states it."""
    out = []
    vmax = s.get("battery_max_V")
    for p in s.get("checked_pairs", []):
        why = []
        if p["tvs_clamp_V"] > p["dcdc_input_max_V"]:
            why.append(f"clamp {p['tvs_clamp_V']:g} V at {p['tvs_clamp_at_A']:g} A above the DC-DC's "
                       f"{p['dcdc_input_max_V']:g} V input maximum")
        if vmax is None:
            why.append("standoff against V_bat,max cannot be checked: V_bat,max unknown")
        elif p["tvs_standoff_V"] < vmax:
            why.append(f"standoff {p['tvs_standoff_V']:g} V below V_bat,max {vmax:g} V")
        out.append({**p, "accepted": not why, "reasons": why})
    return out


def totals(data: dict) -> dict:
    lines = data["lines"]
    unpriced = [l["id"] for l in lines if l["config"] != "tax" and (l.get("low") is None or l.get("high") is None)]
    priced = lambda l: l.get("low") is not None and l.get("high") is not None  # noqa: E731

    def s(configs):
        lo = sum(_ext(l)[0] for l in lines if l["config"] in configs and priced(l))
        hi = sum(_ext(l)[1] for l in lines if l["config"] in configs and priced(l))
        return lo, hi

    tax = next(l for l in lines if l["config"] == "tax")
    out = {}
    for name, configs in CONFIGS:
        parts = [l for l in lines if l["config"] in configs and l["id"] != "shipping"]
        plo = sum(_ext(l)[0] for l in parts if priced(l))
        phi = sum(_ext(l)[1] for l in parts if priced(l))
        lo, hi = s(configs)
        lo += plo * tax["percent_low"] / 100.0
        hi += phi * tax["percent_high"] / 100.0
        out[name] = {"low": round(lo, 2), "high": round(hi, 2), "parts_low": round(plo, 2), "parts_high": round(phi, 2)}
    eq = s(("equipment",))
    out["equipment_if_not_owned"] = {"low": round(eq[0], 2), "high": round(eq[1], 2)}
    u = data["usage"]
    msg, measured = u["message_bytes_assumed"], False
    if DEMO.exists():
        d = json.loads(DEMO.read_text())
        if d.get("live_message_bytes_mean"):
            msg, measured = d["live_message_bytes_mean"], True
    mb_per_hour = (msg + u["mqtt_overhead_bytes"]) * u["rate_hz"] * 3600 / 1e6
    once = next(l for l in lines if l["id"] == "sim_once")
    month = next(l for l in lines if l["id"] == "sim_month")
    per_mb = next(l for l in lines if l["id"] == "data_mb")
    h = u["running_hours_per_month"]
    out["recurring"] = {
        "message_bytes": msg, "message_size_measured": measured, "mb_per_running_hour": round(mb_per_hour, 2),
        "one_time": once["low"],
        "per_month_low": round(month["low"] + per_mb["low"] * mb_per_hour * h["low"], 2),
        "per_month_high": round(month["high"] + per_mb["high"] * mb_per_hour * h["high"], 2),
        "running_hours_per_month": h,
    }
    out["unpriced_lines"] = unpriced
    out["blocked_lines"] = sorted(l["id"] for l in lines if l.get("blocked_by"))
    out["options_not_counted"] = sorted(l["id"] for l in lines if l["config"] == "option")
    out["supply"] = {"vehicle_power_connection": data["supply"]["vehicle_power_connection"],
                     "battery_max_V": data["supply"]["battery_max_V"],
                     "pairs": [{"tvs": v["tvs"], "dcdc": v["dcdc"], "accepted": v["accepted"], "reasons": v["reasons"]}
                               for v in supply_verdicts(data["supply"])]}
    return out


def render(data: dict, t: dict) -> str:
    L = ["# Telematics bill of materials (bench, configurations A and B)", "",
         "Generated by `tools/telematics_bom.py` from [`hardware/telematics/bom.yaml`](../hardware/telematics/bom.yaml); "
         "do not edit. **Nothing has been ordered and no price is a quote.** Every price is a search-result snapshot "
         f"retrieved {data['retrieved']} (no live distributor page could be read from this environment) or a stated "
         "allowance; re-check every line on the live page before ordering.", "",
         "Scope: the telematics unit only. The motor controller is another team's; none of its parts are here. These "
         "totals are the sums of their own lines, not the old combined budget minus a controller subtotal; the old "
         "budget ([`BUDGET.md`](BUDGET.md), [`hardware/bom/`](../hardware/bom/README.md)) stays as the record of the deferred "
         "controller development. Battery: 48 V nominal, 10 Ah, as the vehicle team reports it; the maximum pack voltage "
         "is not known, so no supply-protection part is selected and **the vehicle power connection is blocked** "
         "(section Vehicle supply). The bench runs from USB and needs none of it.", "",
         "## Totals", "",
         "| Configuration | Contents | Low | High | Within $500? | Within $1,000? |", "|---|---|---|---|---|---|"]

    def fit(lo, hi, cap):
        return "yes" if hi <= cap else ("no" if lo > cap else "only at the low end")
    rows = [("bench", "first bench, USB-powered: the parts the firmware drives (BENCH.md B1 to B12)"),
            ("A", "bench + vehicle logging (supply lines are blocked placeholders)"), ("B", "A + LTE uplink"),
            ("B_with_display", "B + driver display")]
    for k, what in rows:
        v = t[k]
        L.append(f"| {k.replace('_', ' ')} | {what} | ${v['low']:,.2f} | ${v['high']:,.2f} | {fit(v['low'], v['high'], BUDGET[0])} | "
                 f"{fit(v['low'], v['high'], BUDGET[1])} |")
    e = t["equipment_if_not_owned"]
    r = t["recurring"]
    L += ["", "Each configuration includes the one before it. "
          f"A and B include spares, shipping and the vehicle-supply placeholders ({', '.join(f'`{x}`' for x in t['blocked_lines'])}: "
          "priced from candidates, none selected); every total includes 0 to 10 % sales tax on its parts. Options, in no "
          f"total: {', '.join(f'`{x}`' for x in t['options_not_counted'])}. Equipment, only if not owned and never "
          f"in A or B: ${e['low']:,.2f} to ${e['high']:,.2f} (two USB-CAN adapters and a generic crimp tool; the genuine "
          "Deutsch HDT-48-00 is $427.05, so borrow one). An oscilloscope, a multimeter and a function generator are assumed "
          "borrowed.", "",
          f"Recurring (B): SIM ${r['one_time']:.2f} once, then ${r['per_month_low']:.2f} to ${r['per_month_high']:.2f} per month for "
          f"{r['running_hours_per_month']['low']} to {r['running_hours_per_month']['high']} running hours a month at "
          f"{r['mb_per_running_hour']:.1f} MB per running hour (live message of {r['message_bytes']:.0f} bytes"
          f"{' measured from the telematics demonstration' if r['message_size_measured'] else ' (assumed)'} at 2 Hz plus MQTT "
          "overhead). The running hours are an assumption to replace with the team's test plan.", ""]
    if t["unpriced_lines"]:
        L += [f"Lines without a price, excluded from the totals: {', '.join(f'`{x}`' for x in t['unpriced_lines'])}.", ""]
    s = t["supply"]
    L += ["## Vehicle supply: blocked", "",
          f"V_bat,max: {'unknown' if s['battery_max_V'] is None else s['battery_max_V']} ({data['supply']['battery_source']}). "
          f"Vehicle power connection: **{s['vehicle_power_connection']}**. Bench: {data['supply']['bench_power']}.", "",
          "Selection rule (checked by `tools/telematics_bom.py` for every pair listed in `supply.checked_pairs`):", ""]
    L += [f"* {r}" for r in data["supply"]["rule"]]
    L += ["", "| TVS | DC-DC | Verdict |", "|---|---|---|"]
    for p in s["pairs"]:
        L.append(f"| {p['tvs']} | {p['dcdc']} | {'accepted' if p['accepted'] else 'rejected: ' + '; '.join(p['reasons'])} |")
    L += ["", "What resolves it: the vehicle team's V_bat,max (B-BAT-V), then either a TVS whose clamp stays below the "
          "chosen DC-DC's absolute maximum input or a DC-DC (or a surge stopper ahead of it) rated above the TVS clamp, "
          "each checked against its own data sheet.", ""]
    L += ["## Lines", "", "| Config | Item | Part | Qty | Unit low | Unit high | Evidence | Source |", "|---|---|---|---|---|---|---|---|"]
    for l in data["lines"]:
        if l["config"] == "tax":
            lo, hi = f"{l['percent_low']:g} %", f"{l['percent_high']:g} %"
        else:
            lo = "unknown" if l.get("low") is None else f"${l['low']:,.2f}"
            hi = "unknown" if l.get("high") is None else f"${l['high']:,.2f}"
        note = f" {l['notes']}" if l.get("notes") else ""
        if l.get("blocked_by"):
            note += f" **Selection blocked by {l['blocked_by']}.**"
        if l.get("driver"):
            note += f" Driver: `{l['driver']}`."
        L.append(f"| {l['config']} | {l['item']} | {l.get('part') or '-'} | {l['qty']} | {lo} | {hi} | {l['evidence']} | "
                 f"{l['source']}.{note} |".replace("\n", " "))
    L += ["", "## Decisions this list depends on", "",
          "* **Pack maximum voltage** (vehicle team): fixes the TVS, the DC-DC, the fuse and the reverse diode "
          "(section Vehicle supply); until then the vehicle power connection is blocked.",
          "* **Event country**: fixes the LTE bands and so the modem board (A7670E for Europe/Asia, a North American "
          "module otherwise); no A7672-family board is sold at a retail USD price.",
          "* **Log rate and attempt length**: the 16 MiB NOR holds 138 min at the bench rates and 27 min at full rate with "
          "the fixture's controller broadcast, then sparse logging (docs/generated/telematics_storage.md); the real "
          "controller's rate decides whether a larger NOR or microSD (driver to write) is needed.",
          "* **The controller interface** ([`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md)): "
          "connector, tap point and termination fix the CAN cable, the connector count and whether the transceiver's "
          "terminator stays off.",
          "* **Wheel geometry**: fixes the Hall switch, the magnet count and the mounting.", "",
          "## Spares rule", "", data["spares_rule"].strip(), ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    data = load()
    err = validate(data)
    if err:
        print("bom refused:\n  " + "\n  ".join(err), file=sys.stderr)
        return 2
    t = totals(data)
    text = render(data, t)
    js = json.dumps(t, indent=1, sort_keys=True) + "\n"
    if a.check:
        stale = [p for p, c in ((DOC, text), (JSON, js)) if not p.exists() or p.read_text() != c]
        if stale:
            print(f"stale: {[str(p.relative_to(ROOT)) for p in stale]}: run python3 tools/telematics_bom.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(text)
    JSON.write_text(js)
    print(f"wrote {DOC.relative_to(ROOT)} and {JSON.relative_to(ROOT)}: bench ${t['bench']['low']:.2f}-"
          f"{t['bench']['high']:.2f}, A ${t['A']['low']:.2f}-{t['A']['high']:.2f}, B ${t['B']['low']:.2f}-{t['B']['high']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
