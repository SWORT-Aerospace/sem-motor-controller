#!/usr/bin/env python3
"""Generate the telemetry procurement tables from hardware/bom/telemetry_procurement.yaml.

    python3 tools/gen_procurement.py           -> README.md (budget table between markers), docs/PROCUREMENT.md
    python3 tools/gen_procurement.py --check   (exit 1 if either is not current)

The YAML file is the only source. The generator refuses it (exit 2) when a price
has no dated source, when Ordered or Received has no order evidence, or when a
status is not one of Candidate / Selected / Ordered / Received / Blocked. Unknown
quantities and costs print as TBD; a line total is printed only when both are
known; the subtotal counts priced lines only and never lines inside the PCB
assembly; no estimated total is printed while any line is unpriced.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "hardware" / "bom" / "telemetry_procurement.yaml"
README = ROOT / "README.md"
DOC = ROOT / "docs" / "PROCUREMENT.md"
BEGIN, END = "<!-- procurement-table:begin -->", "<!-- procurement-table:end -->"
STATUSES = ("Candidate", "Selected", "Ordered", "Received", "Blocked")


def validate(d: dict) -> list[str]:
    err = []
    cats = d.get("categories", {})
    seen = set()
    for it in d.get("items", []):
        i = it.get("id", "?")
        if i in seen:
            err.append(f"{i}: duplicate id")
        seen.add(i)
        if it.get("status") not in STATUSES:
            err.append(f"{i}: status {it.get('status')!r} not one of {', '.join(STATUSES)}")
        if it.get("category") not in cats:
            err.append(f"{i}: unknown category {it.get('category')!r}")
        q = it.get("qty")
        if q is not None and (not isinstance(q, int) or isinstance(q, bool) or q <= 0):
            err.append(f"{i}: qty must be a positive integer or null")
        c = it.get("unit_cost_usd")
        if c is not None:
            pr = it.get("price") or {}
            if not isinstance(c, (int, float)) or isinstance(c, bool) or c < 0:
                err.append(f"{i}: unit_cost_usd must be a non-negative number or null")
            if not (pr.get("supplier") and pr.get("reference") and pr.get("date")):
                err.append(f"{i}: a unit cost needs price.supplier, price.reference and price.date")
            else:
                try:
                    datetime.date.fromisoformat(str(pr["date"]))
                except ValueError:
                    err.append(f"{i}: price.date {pr['date']!r} is not YYYY-MM-DD")
        if it.get("status") in ("Ordered", "Received") and not it.get("order_evidence"):
            err.append(f"{i}: status {it['status']} needs order_evidence")
    return err


def money(x: float) -> str:
    return f"{x:,.2f}"


def line_total(it: dict):
    if it.get("in_assembly") is True:
        return None
    q, c = it.get("qty"), it.get("unit_cost_usd")
    return q * c if q is not None and c is not None else None


def summary(d: dict) -> dict:
    items = d["items"]
    counted = [it for it in items if it.get("in_assembly") is not True]
    priced = [it for it in counted if line_total(it) is not None]
    return {"lines": len(items), "counted": len(counted), "priced": len(priced),
            "unpriced": len(counted) - len(priced), "subtotal": sum(line_total(it) for it in priced),
            "status": {s: sum(1 for it in items if it["status"] == s) for s in STATUSES}}


def item_label(it: dict) -> str:
    lab = it["item"]
    if it.get("optional") and "optional" not in lab.lower():
        lab += " (optional)"
    if it.get("in_assembly") is True:
        lab += " (in the PCB assembly line; not counted again)"
    return lab


def table(d: dict) -> list[str]:
    L = ["| Item | Qty | Unit cost (USD) | Total (USD) | Status |", "|---|---|---|---|---|"]
    for key, title in d["categories"].items():
        rows = [it for it in d["items"] if it["category"] == key]
        if not rows:
            continue
        L.append(f"| **{title}** | | | | |")
        for it in rows:
            q = it.get("qty")
            c = it.get("unit_cost_usd")
            t = line_total(it)
            L.append(f"| {item_label(it)} | {q if q is not None else 'TBD'} | {money(c) if c is not None else 'TBD'} | "
                     f"{money(t) if t is not None else 'TBD'} | {it['status']} |")
    return L


def totals_lines(d: dict) -> list[str]:
    s = summary(d)
    lo, hi = d["budget"]["overall_usd"]
    sub = (f"**${money(s['subtotal'])}** from {s['priced']} of {s['counted']} lines with a dated price"
           if s["priced"] else f"**none**: none of the {s['counted']} lines has a dated price")
    share = d["budget"]["telemetry_share"]
    return [f"* Known priced subtotal: {sub}.",
            f"* Unpriced lines: **{s['unpriced']}** (shown as TBD).",
            "* Estimated total: **not stated**. It needs a dated price for every counted line and an agreed scope "
            "(which lines, how many units, shipping and tax, contingency).",
            f"* Budget: the project budget is about ${lo:,} to ${hi:,}. Whether the telemetry lines share it with the "
            f"motor-controller BOM ([`docs/BUDGET.md`](docs/BUDGET.md)) is **{share}**.",
            "* Status: " + ", ".join(f"{k} {v}" for k, v in s["status"].items()) + ". Nothing has been ordered.",
            "* A separate battery for the driver display is not an approved purchase: Article 57i allows built-in "
            "batteries only in unmodified, self-contained display or communication devices, and Article 57b allows "
            "no accessory battery on a Battery Electric vehicle."]


def readme_block(d: dict) -> str:
    return "\n".join([BEGIN, f"Telemetry procurement, generated from "
                      "[`hardware/bom/telemetry_procurement.yaml`](hardware/bom/telemetry_procurement.yaml) "
                      f"(updated {d['updated']}). Requirements, candidates and what blocks each line: "
                      "[`docs/PROCUREMENT.md`](docs/PROCUREMENT.md). The motor-controller BOM is separate: "
                      "[`hardware/bom/README.md`](hardware/bom/README.md).", "", *table(d), "", *totals_lines(d), END])


def doc(d: dict) -> str:
    L = ["# Telemetry procurement", "",
         f"Generated by `tools/gen_procurement.py` from `hardware/bom/telemetry_procurement.yaml` (updated "
         f"{d['updated']}); edit the YAML file, not this page. Nothing has been ordered. Prices: no line has a dated "
         "quote yet (distributor sites were unreachable from the build environment); a price enters only with its "
         "supplier, date and reference.", "",
         "Statuses: **Candidate** (named, requirements not yet confirmed), **Selected** (requirements and "
         "compatibility checked), **Ordered** and **Received** (only with order evidence), **Blocked** (an input is "
         "missing; the column says which).", "", "## Summary", "", *table(d), "",
         *[x.replace("](docs/", "](") for x in totals_lines(d)], "", "## Lines in detail", "",
         "| Item | Category | Candidate | Requirement | Blocked by | Evidence |", "|---|---|---|---|---|---|"]
    for it in d["items"]:
        ev = it.get("evidence")
        evl = "-"
        if ev:
            path, _, anchor = ev.partition("#")
            rel = path[len("docs/"):] if path.startswith("docs/") else "../" + path
            evl = f"[`{path}{'#' + anchor if anchor else ''}`]({rel}{'#' + anchor if anchor else ''})"
        L.append(f"| {item_label(it)} | {d['categories'][it['category']]} | {it.get('candidate') or '-'} | "
                 f"{' '.join(str(it.get('requirement') or '-').split())} | {it.get('blocked_by') or '-'} | {evl} |")
    L += ["", "## Related", "",
          "* Candidate research and sources: [`TELEMETRY_CANDIDATES.md`](TELEMETRY_CANDIDATES.md).",
          "* Battery facts and what they do not establish: [`BATTERY.md`](BATTERY.md).",
          "* Rules read for these lines: [`RULES_COMPLIANCE.md`](RULES_COMPLIANCE.md).",
          "* Motor-controller BOM and budget scenarios: [`../hardware/bom/README.md`](../hardware/bom/README.md), "
          "[`BUDGET.md`](BUDGET.md).", ""]
    return "\n".join(L)


def render_readme(d: dict, text: str) -> str:
    if BEGIN not in text or END not in text:
        raise SystemExit(f"README.md has no {BEGIN} ... {END} markers")
    return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _m: readme_block(d), text, flags=re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    d = yaml.safe_load(SRC.read_text())
    err = validate(d)
    if err:
        print("procurement file refused:\n  " + "\n  ".join(err))
        return 2
    new_readme = render_readme(d, README.read_text())
    new_doc = doc(d)
    if a.check:
        stale = [p.name for p, t in ((README, new_readme), (DOC, new_doc)) if not p.exists() or p.read_text() != t]
        if stale:
            print("not current: " + ", ".join(stale) + " (run tools/gen_procurement.py)")
            return 1
        s = summary(d)
        print(f"procurement tables current: {s['lines']} lines, {s['priced']} priced, {s['unpriced']} unpriced")
        return 0
    README.write_text(new_readme)
    DOC.write_text(new_doc)
    print(f"wrote README.md (budget table) and {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
