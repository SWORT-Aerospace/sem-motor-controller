"""Evidence queries on the pit database (host/pit/ingest.py): what was known, when, and how well.

    aligned(db, run, signals, t0, t1, step_s)   one row per step: each signal's value and evidence state at that
                                                time, from its latest measurement (a stale or missing value is
                                                null with its state, never 0 or the last good value), with the
                                                basis of its timestamp bound and whether its sample age is known
    intervals(db, run, signal)                  the intervals in which a signal was not admissible (MISSING before
                                                its first sample, STALE in a silence longer than its freshness
                                                threshold, and the import state of any non-VALID sample)
    window(db, run, t_us, before_s, after_s)    the evidence, receipts and source timing around one event
    pre_post(db, run, signal, t_us, before_s, after_s)
                                                the admissible values just before and just after an event (count,
                                                mean, min, max) with the non-admissible samples counted, not used
    events(db, run)                             conclusions the evidence review stored (receipts), to pick windows

All times are the unit's clock (microseconds), as in the log. The states come from host/telematics/evidence.py
against the schema; nothing here fills a gap.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from typing import Iterable, Optional

from host.telematics import evidence, signals
from host.telematics.measurement import ROW_COLUMNS, Measurement, from_row

_Q = (f"SELECT {ROW_COLUMNS} FROM measurements WHERE run_id=? AND signal=? ORDER BY COALESCE(t_sample_us, t_rx_us), "
      "record_id")


def _series(db: sqlite3.Connection, run_id: str, signal: str) -> tuple[list[int], list[Measurement]]:
    ms = [from_row(r) for r in db.execute(_Q, (run_id, signal))]
    return [m.t_ref_us for m in ms], ms


def session_span(db: sqlite3.Connection, run_id: str) -> tuple[Optional[int], Optional[int]]:
    return db.execute("SELECT MIN(t_local_us), MAX(t_local_us) FROM records WHERE run_id=?", (run_id,)).fetchone()


def aligned(db: sqlite3.Connection, run_id: str, sigs: Iterable[str], t0_us: Optional[int] = None,
            t1_us: Optional[int] = None, step_s: float = 0.1) -> list[dict]:
    sigs = list(sigs)
    a, b = session_span(db, run_id)
    t0_us, t1_us = t0_us if t0_us is not None else a, t1_us if t1_us is not None else b
    if t0_us is None or t1_us is None:
        return []
    ser = {s: _series(db, run_id, s) for s in sigs}
    out, t, step = [], t0_us, int(step_s * 1e6)
    while t <= t1_us:
        row = {"t_us": t}
        for s in sigs:
            ts, ms = ser[s]
            i = bisect.bisect_right(ts, t) - 1
            e = evidence.assess(s, ms[i] if i >= 0 else None, t)
            row[s] = {"value": e.value, "state": e.state, "age_ms": None if e.age_us is None else e.age_us // 1000,
                      "t_unc_basis": e.t_unc_basis, "sample_age_known": e.sample_age_known}
        out.append(row)
        t += step
    return out


def intervals(db: sqlite3.Connection, run_id: str, signal: str) -> list[dict]:
    reg = signals.lookup(signal)
    if reg is None:
        raise ValueError(f"unknown signal {signal!r}")
    stale = int(reg.stale_s * 1e6)
    a, b = session_span(db, run_id)
    ts, ms = _series(db, run_id, signal)
    raw: list[tuple[int, int, str, str]] = []
    if a is None:
        return []
    if not ms:
        return [{"t0_us": a, "t1_us": b, "state": "MISSING", "reason": "never received in this session"}]
    if ts[0] > a:
        raw.append((a, ts[0], "MISSING", "not received yet"))
    for i, m in enumerate(ms):
        nxt = ts[i + 1] if i + 1 < len(ms) else b
        st = evidence.state_of(m.validity)
        if st != "VALID":
            raw.append((ts[i], nxt, st, f"{m.validity}: {m.provenance}"))
        elif nxt - ts[i] > stale:
            raw.append((ts[i] + stale, nxt, "STALE", f"no sample for {(nxt - ts[i]) / 1e6:.3f} s"))
    out: list[dict] = []
    for t0, t1, st, why in raw:
        if t1 <= t0:
            continue
        if out and out[-1]["state"] == st and out[-1]["t1_us"] >= t0:
            out[-1]["t1_us"] = max(out[-1]["t1_us"], t1)
            out[-1]["samples"] += 1
        else:
            out.append({"t0_us": t0, "t1_us": t1, "state": st, "reason": why, "samples": 1})
    return out


def window(db: sqlite3.Connection, run_id: str, t_us: int, before_s: float = 2.0, after_s: float = 2.0,
           sigs: Optional[Iterable[str]] = None) -> dict:
    a, b = t_us - int(before_s * 1e6), t_us + int(after_s * 1e6)
    q = ("SELECT t_rx_us, t_sample_us, signal, value, unit, state, reason, source, seq, raw, t_unc_us, t_unc_basis "
         "FROM evidence_records WHERE run_id=? AND COALESCE(t_sample_us, t_rx_us) BETWEEN ? AND ?")
    args: list = [run_id, a, b]
    if sigs:
        sigs = list(sigs)
        q += " AND signal IN (%s)" % ",".join("?" * len(sigs))
        args += sigs
    rows = [dict(zip(("t_rx_us", "t_sample_us", "signal", "value", "unit", "state", "reason", "source", "seq", "raw",
                      "t_unc_us", "t_unc_basis"), r))
            for r in db.execute(q + " ORDER BY COALESCE(t_sample_us, t_rx_us), record_id", args)]
    rec = [{"t_us": t, "kind": k, "subject": s, "verdict": v, "context": c}
           for t, k, s, v, c in db.execute("SELECT t_us, kind, subject, verdict, context FROM receipts WHERE run_id=? "
                                           "AND t_us BETWEEN ? AND ? ORDER BY t_us", (run_id, a, b))]
    timing = {s: json.loads(j) for s, j in db.execute("SELECT stream, report_json FROM source_timing WHERE run_id=?",
                                                       (run_id,))}
    return {"run_id": run_id, "t_us": t_us, "from_us": a, "to_us": b, "evidence": rows, "receipts": rec,
            "source_timing": timing}


def pre_post(db: sqlite3.Connection, run_id: str, signal: str, t_us: int, before_s: float = 2.0,
             after_s: float = 2.0) -> dict:
    ts, ms = _series(db, run_id, signal)

    def stats(lo: int, hi: int) -> dict:
        i, j = bisect.bisect_left(ts, lo), bisect.bisect_right(ts, hi)
        vals = [m.value for m in ms[i:j] if m.validity == "valid"]
        rej = sum(1 for m in ms[i:j] if m.validity != "valid")
        if not vals:
            return {"n": 0, "not_admissible": rej, "mean": None, "min": None, "max": None}
        return {"n": len(vals), "not_admissible": rej, "mean": sum(vals) / len(vals), "min": min(vals),
                "max": max(vals)}
    return {"signal": signal, "t_us": t_us, "before": stats(t_us - int(before_s * 1e6), t_us - 1),
            "after": stats(t_us, t_us + int(after_s * 1e6))}


def events(db: sqlite3.Connection, run_id: str, verdict: Optional[str] = None) -> list[dict]:
    q = "SELECT t_us, kind, subject, verdict, context FROM receipts WHERE run_id=?"
    args: list = [run_id]
    if verdict:
        q += " AND verdict=?"
        args.append(verdict)
    return [{"t_us": t, "kind": k, "subject": s, "verdict": v, "context": c}
            for t, k, s, v, c in db.execute(q + " ORDER BY t_us", args)]
