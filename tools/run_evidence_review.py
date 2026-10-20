#!/usr/bin/env python3
"""Shadow evidence review of a stored run: context, cross-domain witnesses, advisory conclusions, receipts.

    python3 tools/run_evidence_review.py --db pit.sqlite --run <run_id> --out build/evidence_review \
        [--param drivetrain.gear_ratio=10.0 --param drivetrain.freewheel=true] [--pair wheel_l:wheel_r]

Writes OUT/<run_id>_evidence_review.json (the full result) and .md (a summary for people), and stores receipts in
the database (`receipts`). Parameters the run's log does not carry (gear ratio, freewheel, coast-down
deceleration) are UNSUPPORTED unless given here with their source; the relations that need them then report
insufficient evidence. Advisory only: nothing here can command the motor controller.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.assurance import review  # noqa: E402
from host.pit import ingest  # noqa: E402


def _value(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return float(v)
    except ValueError:
        return v


def render(res: dict) -> str:
    L = [f"# Evidence review: {res['run_id']}", "",
         f"Data class **{res['data_class']}**. Shadow and advisory only. Relation set `{res['relation_set']}`, schema "
         f"v{res['schema_version']}, {res['ticks']} ticks of {res['tick_s']} s. Every tolerance is PROVISIONAL.", "",
         "## Contexts", "", "| Context | Ticks |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(res["counts"]["context"].items())]
    L += ["", "## Witness results", "", "| Result | Count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(res["counts"]["results"].items())]
    L += ["", "## Ambiguous conclusions (observed inconsistencies)", ""]
    if not res["ambiguous"]:
        L.append("None.")
    for k, a in sorted(res["ambiguous"].items()):
        L.append(f"* `{k}` from {a['first_s']:.1f} s to {a['last_s']:.1f} s ({a['ticks']} ticks): {a['statement']}. "
                 f"Open candidates: {'; '.join(a['candidates'])}.")
    L += ["", "## Common-cause checks", ""]
    L += [f"* {c['verdict']}: {c['statement']}" for c in res["common_cause"]] or ["No simultaneous loss across sources."]
    L += ["", "## Not supported by this configuration", "", ", ".join(f"`{s}`" for s in res["unsupported_wanted"]) or
          "none", "", f"Parameters: " + ", ".join(f"`{k}` = {v}" for k, v in res["parameters"].items()), ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=pathlib.Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "evidence_review")
    ap.add_argument("--param", action="append", default=[], help="name=value (with its source in the run notes)")
    ap.add_argument("--pair", action="append", default=[], help="two wheel channels expected to agree, a:b")
    ap.add_argument("--tick", type=float, default=0.1)
    a = ap.parse_args()
    db = ingest.connect(a.db)
    params = {k: _value(v) for k, v in (p.split("=", 1) for p in a.param)}
    pairs = tuple(tuple(p.split(":", 1)) for p in a.pair)
    res = review.run(db, a.run, params, a.tick, pairs)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{a.run}_evidence_review.json").write_text(json.dumps(res, indent=2, sort_keys=True, default=str) + "\n")
    (a.out / f"{a.run}_evidence_review.md").write_text(render(res))
    print(f"EVIDENCE REVIEW {a.run} ({res['data_class']}): {res['ticks']} ticks, contexts {res['counts']['context']}, "
          f"results {res['counts']['results']}, {len(res['ambiguous'])} ambiguous, {res['receipts']} receipts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
