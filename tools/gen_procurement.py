#!/usr/bin/env python3
"""Generate the project procurement tables from hardware/bom/procurement.yaml.

    python3 tools/gen_procurement.py           -> docs/PROCUREMENT.md
    python3 tools/gen_procurement.py --check   (exit 1 if it is not current)

This is the v0.6 combined procurement table (controller and telemetry). Since v0.7 the root README shows the
telematics bill of materials instead (tools/telematics_bom.py), so this tool no longer writes a README block;
`render_readme` stays for a document that still carries the markers.

The YAML file is the only source of lines. Estimated lines take their low-high
range from the motor-controller pricing (docs/generated/budget.json, written by
tools/price_bom.py; bring-up equipment from hardware/bom/pricing.yaml), so each
number exists once. The generator refuses the file (exit 2) when a price has no
dated source, when an estimate reference does not resolve, when Ordered or
Received has no order evidence, or when a status is not one of Candidate /
Selected / Ordered / Received / Blocked. Unknown quantities and costs print as
TBD, never as zero. Subtotals leave out optional lines, lines marked not
budgeted and lines inside the telematics PCB assembly; no total is printed while
any counted line is unpriced.

`builds` (controller only, minimum, full scope) are evaluated against the $500 and
$1,000 budget with and without the development equipment. Every build must
contain every line of the controller category, so a build can defer features
but never protection.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "hardware" / "bom" / "procurement.yaml"
BUDGET = ROOT / "docs" / "generated" / "budget.json"
PRICING = ROOT / "hardware" / "bom" / "pricing.yaml"
README = ROOT / "README.md"
DOC = ROOT / "docs" / "PROCUREMENT.md"
BEGIN, END = "<!-- procurement-table:begin -->", "<!-- procurement-table:end -->"
STATUSES = ("Candidate", "Selected", "Ordered", "Received", "Blocked")


def load_refs() -> tuple[dict, dict]:
    return json.loads(BUDGET.read_text()), yaml.safe_load(PRICING.read_text())


def resolve(est: dict, d: dict, budget: dict, pricing: dict):
    """(low, high, evidence) for an estimate reference; raises KeyError or ValueError when it does not resolve."""
    if "pricing" in est:
        field, _, prefix = est["pricing"].partition("/")
        for e in pricing[field]:
            if e["item"].startswith(prefix):
                return float(e["low"]), float(e["high"]), f"{e['evidence']} (hardware/bom/pricing.yaml {field})"
        raise KeyError(f"pricing {est['pricing']!r}")
    ref = est["budget"]
    ref, _, scen = ref.partition("@")
    scen = scen or d["estimate_scenario"]
    s = budget["scenarios"][scen]
    field, _, prefix = ref.partition("/")
    where = f"docs/generated/budget.json, {scen.split()[0]}"
    if prefix:
        for label, lo, hi, ev in s[field]:
            if label.startswith(prefix):
                return float(lo), float(hi), f"{ev} ({where}: {field})"
        raise KeyError(f"budget {est['budget']!r}")
    lo, hi = s[field]
    if field == "parts":
        mix = ", ".join(f"{v[2]} {k}" for k, v in budget["by_evidence"].items())
        return float(lo), float(hi), f"BOM lines by evidence: {mix} ({where}: parts)"
    return float(lo), float(hi), f"computed by tools/price_bom.py ({where}: {field})"


def validate(d: dict, budget: dict | None = None, pricing: dict | None = None) -> list[str]:
    if budget is None or pricing is None:
        budget, pricing = load_refs()
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
        if not it.get("purpose"):
            err.append(f"{i}: purpose missing")
        q = it.get("qty")
        if q is not None and (not isinstance(q, int) or isinstance(q, bool) or q <= 0):
            err.append(f"{i}: qty must be a positive integer or null")
        c = it.get("unit_cost_usd")
        kinds = [k for k in ("unit_cost_usd", "estimate", "not_budgeted") if it.get(k) is not None]
        if len(kinds) > 1:
            err.append(f"{i}: only one of unit_cost_usd, estimate, not_budgeted may be set (has {', '.join(kinds)})")
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
        if it.get("estimate") is not None:
            try:
                lo, hi, _ = resolve(it["estimate"], d, budget, pricing)
                if hi <= 0 or lo > hi:
                    err.append(f"{i}: estimate {lo}-{hi} is empty or inverted; use not_budgeted for a zero line")
            except (KeyError, ValueError, TypeError) as e:
                err.append(f"{i}: estimate does not resolve: {e}")
            if q is None:
                err.append(f"{i}: an estimate needs a quantity")
        if it.get("status") in ("Ordered", "Received") and not it.get("order_evidence"):
            err.append(f"{i}: status {it['status']} needs order_evidence")
    ctrl = [it["id"] for it in d.get("items", []) if it.get("category") == "controller"]
    for b in d.get("builds", []):
        inc = b["includes"] if b["includes"] != "all" else []
        dfr = [x for g in b.get("deferred", []) for x in g["lines"]]
        for x in inc + b.get("equipment_if_not_owned", []) + dfr:
            if x not in seen:
                err.append(f"build {b['id']}: unknown line {x}")
        if b["includes"] != "all":
            err += [f"build {b['id']}: controller line {x} left out (protection is never deferred)"
                    for x in ctrl if x not in inc]
        err += [f"build {b['id']}: {x} both included and deferred" for x in set(inc) & set(dfr)]
    return err


def money(x: float) -> str:
    return f"{x:,.2f}"


def dollars(x: float) -> str:
    return f"{x:,.0f}"


def cost(it: dict, d: dict, budget: dict, pricing: dict) -> dict:
    """kind: quote | estimate | not_budgeted | assembly | tbd, with unit and line ranges where known."""
    if it.get("in_assembly") is True:
        return {"kind": "assembly"}
    if it.get("not_budgeted"):
        return {"kind": "not_budgeted"}
    q, c = it.get("qty"), it.get("unit_cost_usd")
    if c is not None:
        return {"kind": "quote", "unit": (c, c), "line": (q * c, q * c) if q is not None else None}
    if it.get("estimate") is not None:
        lo, hi, ev = resolve(it["estimate"], d, budget, pricing)
        return {"kind": "estimate", "unit": (lo, hi), "line": (q * lo, q * hi), "evidence": ev}
    return {"kind": "tbd"}


def counted(it: dict, k: dict) -> bool:
    return not it.get("optional") and k["kind"] not in ("assembly", "not_budgeted")


def summary(d: dict, budget: dict | None = None, pricing: dict | None = None) -> dict:
    if budget is None or pricing is None:
        budget, pricing = load_refs()
    cats = {}
    for key in d["categories"]:
        cats[key] = {"lines": 0, "counted": 0, "quoted": 0.0, "n_quoted": 0, "est": [0.0, 0.0], "n_est": 0,
                     "unpriced": 0, "not_counted": 0}
    for it in d["items"]:
        k = cost(it, d, budget, pricing)
        c = cats[it["category"]]
        c["lines"] += 1
        if not counted(it, k):
            c["not_counted"] += 1
            continue
        c["counted"] += 1
        if k["kind"] == "quote" and k["line"] is not None:
            c["n_quoted"] += 1
            c["quoted"] += k["line"][0]
            c["est"][0] += k["line"][0]
            c["est"][1] += k["line"][1]
        elif k["kind"] == "estimate":
            c["n_est"] += 1
            c["est"][0] += k["line"][0]
            c["est"][1] += k["line"][1]
        else:
            c["unpriced"] += 1
    tot = {f: sum(c[f] for c in cats.values()) for f in ("lines", "counted", "n_quoted", "n_est", "unpriced",
                                                          "not_counted", "quoted")}
    tot["est"] = [sum(c["est"][0] for c in cats.values()), sum(c["est"][1] for c in cats.values())]
    tot["status"] = {s: sum(1 for it in d["items"] if it["status"] == s) for s in STATUSES}
    return {"categories": cats, "total": tot}


def item_label(it: dict) -> str:
    lab = it["item"]
    if it.get("optional") and "optional" not in lab.lower():
        lab += " (optional)"
    if it.get("in_assembly") is True:
        lab += " (in the PCB assembly line; not counted again)"
    return lab


def cells(it: dict, k: dict) -> tuple[str, str, str]:
    q = it.get("qty")
    qty = "TBD" if q is None else f"{q} {it['unit']}" if it.get("unit") else str(q)
    if k["kind"] == "quote":
        unit = money(k["unit"][0])
        line = money(k["line"][0]) if k["line"] else "TBD"
    elif k["kind"] == "estimate":
        unit = f"est. {dollars(k['unit'][0])} to {dollars(k['unit'][1])}"
        line = f"est. {dollars(k['line'][0])} to {dollars(k['line'][1])}"
    elif k["kind"] == "not_budgeted":
        unit = line = "not budgeted"
    elif k["kind"] == "assembly":
        unit, line = "in assembly", "-"
    else:
        unit = line = "TBD"
    return qty, unit, line


def table(d: dict, budget: dict, pricing: dict) -> list[str]:
    L = ["| Item | Purpose | Qty | Unit cost (USD) | Total (USD) | Status |", "|---|---|---|---|---|---|"]
    for key, title in d["categories"].items():
        rows = [it for it in d["items"] if it["category"] == key]
        if not rows:
            continue
        L.append(f"| **{title}** | | | | | |")
        for it in rows:
            qty, unit, line = cells(it, cost(it, d, budget, pricing))
            L.append(f"| {item_label(it)} | {' '.join(it['purpose'].split())} | {qty} | {unit} | {line} | "
                     f"{it['status']} |")
    return L


def range_text(lo: float, hi: float, sign: str = "") -> str:
    return f"{sign}{dollars(lo)} to {sign}{dollars(hi)}" if hi > 0 else "none priced"


def subtotal_table(d: dict, s: dict) -> list[str]:
    L = ["| Category | Lines | Estimated (USD) | Dated quotes | Unpriced (TBD) | Not counted |",
         "|---|---|---|---|---|---|"]
    for key, title in d["categories"].items():
        c = s["categories"][key]
        if not c["lines"]:
            continue
        L.append(f"| {title} | {c['lines']} | {range_text(*c['est'])} ({c['n_est'] + c['n_quoted']} lines) | "
                 f"{c['n_quoted']} | {c['unpriced']} | {c['not_counted']} |")
    t = s["total"]
    L.append(f"| **All categories** | {t['lines']} | **{range_text(*t['est'])}** ({t['n_est'] + t['n_quoted']} lines) "
             f"| {t['n_quoted']} | **{t['unpriced']}** | {t['not_counted']} |")
    return L


def totals_lines(d: dict, s: dict, budget: dict, pricing: dict) -> list[str]:
    t = s["total"]
    lo, hi = d["budget"]["overall_usd"]
    # the equipment the team may already own: the builds' equipment lines (the bench load is built, not owned)
    eq = {i for b in d.get("builds", []) for i in b.get("equipment_if_not_owned", [])}
    ks = [cost(it, d, budget, pricing) for it in d["items"] if it["id"] in eq]
    e_lo = sum(k["line"][0] for k in ks if k.get("line"))
    e_hi = sum(k["line"][1] for k in ks if k.get("line"))
    owned = (t["est"][0] - e_lo, t["est"][1] - e_hi)
    quotes = (f"**${money(t['quoted'])}** from {t['n_quoted']} of {t['counted']} counted lines"
              if t["n_quoted"] else f"**none**: none of the {t['counted']} counted lines has a dated quote")
    if t["est"][0] > hi:
        fit = f"the estimated lines alone are above ${hi:,} even at the low end"
    elif t["unpriced"]:
        fit = (f"with {t['unpriced']} lines unpriced, a fit within ${lo:,} to ${hi:,} is **not established**")
    else:
        fit = f"the range above is the whole estimate; compare it with ${lo:,} to ${hi:,}"
    return [f"* Priced subtotal from dated quotes: {quotes}.",
            f"* Estimated lines: **{range_text(*t['est'], sign='$')}** over {t['n_est']} lines "
            f"({range_text(*owned, sign='$')} if the development equipment is already owned). These ranges come from the "
            "draft controller BOM pricing ([`docs/BUDGET.md`](docs/BUDGET.md)); they are estimates, not quotes.",
            "* Estimates are summed before rounding to whole dollars, so adding the rounded rows can differ from a "
            "subtotal by a few dollars.",
            f"* Unpriced lines: **{t['unpriced']}** (TBD). They come on top of the estimated range, so the complete "
            "cost is not known.",
            f"* Not counted: {t['not_counted']} lines (optional lines, the borrowed oscilloscope, and parts inside the "
            "telematics PCB assembly line).",
            f"* Budget: the project budget is about ${lo:,} to ${hi:,}; which lines it must cover is "
            f"**{d['budget']['scope']}**. {fit[0].upper() + fit[1:]}.",
            "* Status: " + ", ".join(f"{k} {v}" for k, v in t["status"].items()) + ". Nothing has been ordered.",
            "* A separate battery for the driver display is not an approved purchase: Article 57i allows built-in "
            "batteries only in unmodified, self-contained display or communication devices, and Article 57b allows "
            "no accessory battery on a Battery Electric vehicle."]


def build_sums(b: dict, d: dict, budget: dict, pricing: dict) -> dict:
    """Estimated range and unpriced lines of a build, without and with the development equipment."""
    items = {it["id"]: it for it in d["items"]}
    eq = list(b.get("equipment_if_not_owned", []))
    if b["includes"] == "all":
        ids = [i for i, it in items.items() if counted(it, cost(it, d, budget, pricing)) and i not in eq]
    else:
        ids = list(b["includes"])

    def acc(idlist):
        lo = hi = 0.0
        tbd = []
        for i in idlist:
            k = cost(items[i], d, budget, pricing)
            if not counted(items[i], k):
                continue
            if k["kind"] in ("quote", "estimate") and k.get("line"):
                lo, hi = lo + k["line"][0], hi + k["line"][1]
            else:
                tbd.append(i)
        return lo, hi, tbd
    lo, hi, tbd = acc(ids)
    elo, ehi, etbd = acc(eq)
    return {"ids": ids, "owned": (lo, hi, tbd), "bought": (lo + elo, hi + ehi, tbd + etbd)}


def verdict(lo: float, hi: float, tbd: list, limit: float) -> str:
    if lo > limit:
        return f"over: above ${limit:,.0f} even at the low end"
    if tbd:
        return (f"not established: {len(tbd)} lines unpriced"
                + (f"; the priced lines alone straddle ${limit:,.0f}" if hi > limit else ""))
    if hi <= limit:
        return f"high end of the estimate below ${limit:,.0f} (estimates, not quotes)"
    return f"straddles ${limit:,.0f}: within only if prices land in the lower part of the range"


def builds_table(d: dict, budget: dict, pricing: dict) -> list[str]:
    lo_b, hi_b = d["budget"]["overall_usd"]
    L = [f"| Build | Development equipment | Estimated (USD) | Unpriced lines | Against ${lo_b:,} | Against ${hi_b:,} |",
         "|---|---|---|---|---|---|"]
    for b in d.get("builds", []):
        s = build_sums(b, d, budget, pricing)
        for label, key in (("owned", "owned"), ("bought", "bought")):
            lo, hi, tbd = s[key]
            L.append(f"| {b['title']} | {label} | {range_text(lo, hi)} | {len(tbd)} | {verdict(lo, hi, tbd, lo_b)} | "
                     f"{verdict(lo, hi, tbd, hi_b)} |")
    return L


def group_cost(ids: list, d: dict, budget: dict, pricing: dict):
    """Estimated range and unpriced lines of a group of items, optional lines included (adding one back is the
    point); lines inside the PCB assembly or not budgeted are skipped."""
    items = {it["id"]: it for it in d["items"]}
    lo = hi = 0.0
    tbd = []
    for i in ids:
        k = cost(items[i], d, budget, pricing)
        if k["kind"] in ("assembly", "not_budgeted"):
            continue
        if k["kind"] in ("quote", "estimate") and k.get("line"):
            lo, hi = lo + k["line"][0], hi + k["line"][1]
        else:
            tbd.append(i)
    return lo, hi, tbd


def builds_detail(d: dict, budget: dict, pricing: dict) -> list[str]:
    items = {it["id"]: it for it in d["items"]}
    L = []
    for b in d.get("builds", []):
        s = build_sums(b, d, budget, pricing)
        L += [f"**{b['title']}.** {' '.join(b['goal'].split())}", ""]
        if b.get("capability"):
            L.append(f"* Capability: {' '.join(b['capability'].split())}")
        unp = s["bought"][2]
        L.append("* Lines: " + "; ".join(items[i]["item"] for i in s["ids"]) + ".")
        if unp:
            L.append("* Unpriced (TBD): " + "; ".join(items[i]["item"] for i in unp) + ".")
        for g in b.get("deferred", []):
            glo, ghi, gtbd = group_cost(g["lines"], d, budget, pricing)
            price = (f"adds {range_text(glo, ghi)} USD" + (f" plus {len(gtbd)} unpriced" if gtbd else "")
                     if glo or ghi else ("unpriced" if gtbd else "nothing counted"))
            L.append("* Deferred: " + "; ".join(items[i]["item"] for i in g["lines"])
                     + f". Effect: {g['effect']}. To add back: {price}.")
        L.append("")
    return L


def readme_block(d: dict, budget: dict | None = None, pricing: dict | None = None) -> str:
    if budget is None or pricing is None:
        budget, pricing = load_refs()
    s = summary(d, budget, pricing)
    return "\n".join([BEGIN, "Generated from [`hardware/bom/procurement.yaml`](hardware/bom/procurement.yaml) "
                      f"(updated {d['updated']}) by `tools/gen_procurement.py`; edit the YAML file, not this table. "
                      "Requirements, candidates, cost sources and what blocks each line: "
                      "[`docs/PROCUREMENT.md`](docs/PROCUREMENT.md).", "", "**Subtotals**", "",
                      *subtotal_table(d, s), "", *totals_lines(d, s, budget, pricing), "",
                      "**Builds against the budget** (every build keeps the whole controller, protection included; "
                      "what each build defers: [`docs/PROCUREMENT.md`](docs/PROCUREMENT.md#builds-against-the-budget))",
                      "", *builds_table(d, budget, pricing), "",
                      "Every line with its requirement, candidate, cost source and blocker: "
                      "[`docs/PROCUREMENT.md`](docs/PROCUREMENT.md#lines).", END])


def to_docs(line: str) -> str:
    """Rewrite repository-root links for a page in docs/."""
    return re.sub(r"\]\((?!https?:|#)([^)]+)\)",
                  lambda m: "](" + (m.group(1)[5:] if m.group(1).startswith("docs/") else "../" + m.group(1)) + ")",
                  line)


def doc(d: dict, budget: dict | None = None, pricing: dict | None = None) -> str:
    if budget is None or pricing is None:
        budget, pricing = load_refs()
    s = summary(d, budget, pricing)
    L = ["# Project procurement", "",
         f"Generated by `tools/gen_procurement.py` from `hardware/bom/procurement.yaml` (updated {d['updated']}); edit "
         "the YAML file, not this page. Nothing has been ordered. No line has a dated quote yet; a quote enters only "
         "with its supplier, date and reference. "
         "Estimated lines take their range from the draft controller BOM pricing "
         f"(`docs/generated/budget.json`, scenario \"{d['estimate_scenario']}\"), which `tools/price_bom.py` writes "
         "from `hardware/bom/BOM_draft.csv` and `hardware/bom/pricing.yaml`.", "",
         "Statuses: **Candidate** (named, requirements not yet confirmed), **Selected** (requirements and "
         "compatibility checked), **Ordered** and **Received** (only with order evidence), **Blocked** (an input is "
         "missing; the detail table says which).", "", "## Subtotals", "", *subtotal_table(d, s), "",
         *[to_docs(x) for x in totals_lines(d, s, budget, pricing)], "", "## Builds against the budget", "",
         "Every build contains every line of the controller category: features are deferred, protection is not. "
         "\"Owned\" assumes the team already has the development equipment; \"bought\" adds it (an oscilloscope "
         "and differential probe are not budgeted in either: they must be borrowed). A build with unpriced lines "
         "cannot be shown to fit.", "", *builds_table(d, budget, pricing), "", *builds_detail(d, budget, pricing),
         "## Lines", "", *table(d, budget, pricing), "",
         "## Lines in detail", "",
         "| Item | Category | Candidate | Requirement | Blocked by | Cost source | Evidence |",
         "|---|---|---|---|---|---|---|"]
    for it in d["items"]:
        ev = it.get("evidence")
        evl = "-"
        if ev:
            path, _, anchor = ev.partition("#")
            rel = path[len("docs/"):] if path.startswith("docs/") else "../" + path
            evl = f"[`{path}{'#' + anchor if anchor else ''}`]({rel}{'#' + anchor if anchor else ''})"
        k = cost(it, d, budget, pricing)
        src = {"quote": lambda: f"quote: {it['price']['supplier']}, {it['price']['reference']}, {it['price']['date']}",
               "estimate": lambda: f"estimate, {k['evidence']}",
               "not_budgeted": lambda: f"not budgeted: {it['not_budgeted']}",
               "assembly": lambda: "inside the telematics PCB assembly line",
               "tbd": lambda: "none yet"}[k["kind"]]()
        L.append(f"| {item_label(it)} | {d['categories'][it['category']]} | {it.get('candidate') or '-'} | "
                 f"{' '.join(str(it.get('requirement') or '-').split())} | {it.get('blocked_by') or '-'} | {src} | "
                 f"{evl} |")
    L += ["", "## Related", "",
          "* Candidate research and sources: [`TELEMETRY_CANDIDATES.md`](TELEMETRY_CANDIDATES.md).",
          "* Battery facts and what they do not establish: [`BATTERY.md`](BATTERY.md).",
          "* Rules read for these lines: [`RULES_COMPLIANCE.md`](RULES_COMPLIANCE.md).",
          "* Motor-controller BOM, pricing evidence and budget scenarios: "
          "[`../hardware/bom/README.md`](../hardware/bom/README.md), [`BUDGET.md`](BUDGET.md).", ""]
    return "\n".join(L)


def render_readme(d: dict, text: str, budget: dict | None = None, pricing: dict | None = None) -> str:
    if BEGIN not in text or END not in text:
        raise SystemExit(f"README.md has no {BEGIN} ... {END} markers")
    block = readme_block(d, budget, pricing)
    return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _m: block, text, flags=re.S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    d = yaml.safe_load(SRC.read_text())
    budget, pricing = load_refs()
    err = validate(d, budget, pricing)
    if err:
        print("procurement file refused:\n  " + "\n  ".join(err))
        return 2
    new_doc = doc(d, budget, pricing)
    t = summary(d, budget, pricing)["total"]
    if a.check:
        stale = [p.name for p, x in ((DOC, new_doc),) if not p.exists() or p.read_text() != x]
        if stale:
            print("not current: " + ", ".join(stale) + " (run tools/gen_procurement.py)")
            return 1
        print(f"procurement tables current: {t['lines']} lines, {t['n_quoted']} quoted, {t['n_est']} estimated, "
              f"{t['unpriced']} unpriced, {t['not_counted']} not counted")
        return 0
    DOC.write_text(new_doc)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
