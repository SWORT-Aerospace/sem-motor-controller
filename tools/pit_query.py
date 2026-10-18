#!/usr/bin/env python3
"""Evidence queries on a pit database, from the command line (host/pit/queries.py).

    python3 tools/pit_query.py --db pit.sqlite runs
    python3 tools/pit_query.py --db pit.sqlite aligned --run R --signal gnss.speed --signal wheel.wheel_l.speed \
        [--from 10.0 --to 20.0 --step 0.5]
    python3 tools/pit_query.py --db pit.sqlite gaps --run R --signal ctrl.dc_voltage
    python3 tools/pit_query.py --db pit.sqlite events --run R [--verdict AMBIGUOUS]
    python3 tools/pit_query.py --db pit.sqlite window --run R --at 31.6 [--before 2 --after 2] [--signal ...]
    python3 tools/pit_query.py --db pit.sqlite prepost --run R --signal imu.ax --at 31.6

Times on the command line are seconds of the unit's clock (as in the log); output is plain text, one row per
line, with every value's evidence state. A value that was not admissible prints as its state, never as a number.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.pit import ingest, queries  # noqa: E402


def _fmt(cell: dict) -> str:
    if cell["state"] in ("VALID", "SOURCE_UNVERIFIED") and cell["value"] is not None:
        return f"{cell['value']:.4g}" + ("" if cell["state"] == "VALID" else " (unverified)")
    return cell["state"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=pathlib.Path, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("runs")
    p = sub.add_parser("aligned")
    p.add_argument("--run", required=True)
    p.add_argument("--signal", action="append", required=True)
    p.add_argument("--from", dest="t0", type=float)
    p.add_argument("--to", dest="t1", type=float)
    p.add_argument("--step", type=float, default=0.1)
    p = sub.add_parser("gaps")
    p.add_argument("--run", required=True)
    p.add_argument("--signal", required=True)
    p = sub.add_parser("events")
    p.add_argument("--run", required=True)
    p.add_argument("--verdict")
    for name in ("window", "prepost"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        p.add_argument("--at", type=float, required=True)
        p.add_argument("--before", type=float, default=2.0)
        p.add_argument("--after", type=float, default=2.0)
        p.add_argument("--signal", action="append", required=name == "prepost")
    a = ap.parse_args(argv)
    db = ingest.connect(a.db)
    us = (lambda s: None if s is None else int(round(s * 1e6)))
    if a.cmd == "runs":
        for rid, mj in db.execute("SELECT run_id, meta_json FROM runs ORDER BY run_id"):
            m = json.loads(mj)
            n = db.execute("SELECT COUNT(*) FROM measurements WHERE run_id=?", (rid,)).fetchone()[0]
            print(f"{rid}\t{m.get('kind', 'kind not stated')}\t{n} measurements")
    elif a.cmd == "aligned":
        rows = queries.aligned(db, a.run, a.signal, us(a.t0), us(a.t1), a.step)
        print("t_s\t" + "\t".join(a.signal))
        for r in rows:
            print(f"{r['t_us'] / 1e6:.3f}\t" + "\t".join(_fmt(r[s]) for s in a.signal))
    elif a.cmd == "gaps":
        iv = queries.intervals(db, a.run, a.signal)
        print("from_s\tto_s\tstate\tsamples\treason")
        for x in iv:
            print(f"{x['t0_us'] / 1e6:.3f}\t{x['t1_us'] / 1e6:.3f}\t{x['state']}\t{x.get('samples', '')}\t{x['reason']}")
        print(f"# {len(iv)} intervals in which {a.signal} was not admissible")
    elif a.cmd == "events":
        for e in queries.events(db, a.run, a.verdict):
            print(f"{e['t_us'] / 1e6:.3f}\t{e['kind']}\t{e['subject']}\t{e['verdict']}\t{e['context'] or ''}")
    elif a.cmd == "window":
        w = queries.window(db, a.run, us(a.at), a.before, a.after, a.signal)
        for r in w["evidence"]:
            t = r["t_sample_us"] if r["t_sample_us"] is not None else r["t_rx_us"]
            v = f"{r['value']:.4g}" if r["value"] is not None else "-"
            print(f"{t / 1e6:.6f}\t{r['signal']}\t{v}\t{r['state']}\t{r['reason'] or ''}")
        for e in w["receipts"]:
            print(f"# receipt {e['t_us'] / 1e6:.3f} {e['kind']} {e['subject']}: {e['verdict']}")
    elif a.cmd == "prepost":
        for s in a.signal:
            r = queries.pre_post(db, a.run, s, us(a.at), a.before, a.after)
            for side in ("before", "after"):
                x = r[side]
                mean = "-" if x["mean"] is None else f"{x['mean']:.4g}"
                print(f"{s}\t{side}\tn={x['n']}\tmean={mean}\tnot_admissible={x['not_admissible']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
