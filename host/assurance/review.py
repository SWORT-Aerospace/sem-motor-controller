"""Shadow evidence review of one stored run (pit database): context, witnesses, conclusions, receipts.

    python3 tools/run_evidence_review.py --db pit.sqlite --run <run_id> --out build/evidence_review

At every tick (10 Hz by default) the latest measurement of each signal becomes an evidence assessment
(host/telematics/evidence.py) against the run's own configuration: a signal its adapter does not map, or a wheel
speed without circumference and pulses per revolution, is UNSUPPORTED, not MISSING. The context comes from the
admissible evidence only; each witness relation is evaluated in its declared contexts; conclusions are SUPPORTED,
AMBIGUOUS or UNSUPPORTED. A receipt is stored whenever a conclusion changes (table `receipts`), so the report can
answer "why did the system say this" with the values, times, states, context, witness results and rejections of
that moment. Simultaneous loss of admissible evidence across sources is checked against the shared paths of the
schema (family C). The evidence rows get the context of their time (`evidence.context`).

Shadow mode: this reads the database and writes records for people. It has no CAN, MQTT or controller interface.
The data class (SIMULATED, BENCH, HIL, VEHICLE) is taken from the log's own `kind`; a log that does not state one is
UNKNOWN, never VEHICLE.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from typing import Optional

from host.assurance import verdicts, witnesses
from host.telematics import context as C
from host.telematics import evidence, lineage, signals
from host.telematics.evidence import Evidence
from host.telematics.measurement import Measurement


def data_class(meta: dict) -> str:
    k = str(meta.get("kind", "")).upper()
    if "SIMULATION" in k or k.startswith("HOST"):
        return "SIMULATED"
    for word in ("VEHICLE", "HIL", "BENCH"):
        if k.startswith(word):
            return word
    return "UNKNOWN"


def supported(db: sqlite3.Connection, run_id: str, meta: dict) -> set[str]:
    sens = meta.get("sensors") or {}
    adapter_id = (meta.get("controller_adapter") or {}).get("id", "semmc-sim-fixture")
    from host.telematics import controller_adapter as CA
    adapter_sigs = evidence.adapter_signals(CA.SimFixtureAdapter()) if adapter_id == CA.SimFixtureAdapter.id else \
        set(r[0] for r in db.execute("SELECT DISTINCT signal FROM measurements WHERE run_id=? AND source='controller'",
                                     (run_id,)))
    present = {r[0] for r in db.execute("SELECT DISTINCT source FROM measurements WHERE run_id=?", (run_id,))}
    chans = list((sens.get("wheel_channels") or {}).values())
    temps = [r[0].split(".", 1)[1] for r in db.execute(
        "SELECT DISTINCT signal FROM measurements WHERE run_id=? AND source='temp'", (run_id,))]
    return evidence.supported_signals(adapter_sigs, bool(sens.get("wheel_circumference_m") and sens.get("wheel_ppr")),
                                      chans, battery_monitor=bool(sens.get("battery_monitor")),
                                      gnss="gnss" in present, imu="imu" in present, temp_channels=temps)


class _Series:
    def __init__(self):
        self.t: list[int] = []
        self.m: list[Measurement] = []
        self.t_valid: list[int] = []

    def fresh_valid(self, a_us: int, b_us: int) -> bool:
        """An admissible sample was received in (a, b]."""
        i = bisect.bisect_right(self.t_valid, a_us)
        return i < len(self.t_valid) and self.t_valid[i] <= b_us

    def at(self, t_us: int) -> Optional[Measurement]:
        i = bisect.bisect_right(self.t, t_us) - 1
        return self.m[i] if i >= 0 else None


def _load(db, run_id) -> dict[str, _Series]:
    out: dict[str, _Series] = {}
    q = ("SELECT record_id, source, signal, value, unit, t_rx_us, t_sample_us, t_unc_us, source_seq, validity, "
         "provenance, upper FROM measurements WHERE run_id=? ORDER BY COALESCE(t_sample_us, t_rx_us), record_id")
    for row in db.execute(q, (run_id,)):
        m = Measurement(*row)
        s = out.setdefault(m.signal, _Series())
        s.t.append(m.t_ref_us)
        s.m.append(m)
        if m.validity == "valid":
            s.t_valid.append(m.t_ref_us)
    return out


def _wheel_speed(ev: dict) -> Optional[float]:
    w = sorted(e.value for s, e in ev.items() if s.startswith("wheel.") and s.endswith(".speed") and e.admissible)
    return w[len(w) // 2] if w else None


def _speed_now(ev: dict) -> Optional[float]:
    g = ev.get("gnss.speed")
    return g.value if g is not None and g.admissible else _wheel_speed(ev)


class _Derivative:
    """dv/dt over about 1 s from admissible speeds only: (value, window start); None after a gap."""

    def __init__(self):
        self.hist: list[tuple[int, float]] = []

    def __call__(self, t: int, v: Optional[float]) -> Optional[tuple[float, int]]:
        if v is None:
            self.hist.clear()
            return None
        self.hist.append((t, v))
        while self.hist and t - self.hist[0][0] > 1_500_000:
            self.hist.pop(0)
        old = next(((tp, vp) for tp, vp in reversed(self.hist) if t - tp >= 800_000), None)
        return None if old is None else ((v - old[1]) / ((t - old[0]) / 1e6), old[0])


def _mean_valid(ser: Optional[_Series], a_us: int, b_us: int) -> Optional[tuple[float, int]]:
    """Mean of the admissible samples received in (a, b], and how many; None when there are none."""
    if ser is None:
        return None
    i, j = bisect.bisect_right(ser.t, a_us), bisect.bisect_right(ser.t, b_us)
    vals = [m.value for m in ser.m[i:j] if m.validity == "valid"]
    return (sum(vals) / len(vals), len(vals)) if vals else None


def run(db: sqlite3.Connection, run_id: str, params: Optional[dict] = None, tick_s: float = 0.1,
        wheel_pairs: tuple = (), ctx_cfg: C.ContextConfig = C.ContextConfig(), write: bool = True,
        onset_window_s: float = 1.0) -> dict:
    meta = json.loads(db.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
    sens = meta.get("sensors") or {}
    params = {"wheel.circumference_m": sens.get("wheel_circumference_m"), "wheel.ppr": sens.get("wheel_ppr"),
              "drivetrain.gear_ratio": None, "drivetrain.freewheel": None, "vehicle.coast_decel_mps2": None,
              **(params or {})}
    sup = supported(db, run_id, meta)
    series = _load(db, run_id)
    chans = list((sens.get("wheel_channels") or {}).values())
    temps = sorted(s for s in sup if s.startswith("temp."))
    rels = witnesses.relation_set(chans, temps, wheel_pairs)
    rel_hash = witnesses.set_hash(rels)
    wanted = sorted(sup | {s for s in series if s.startswith("ctrl.")} |
                    {"ctrl.dc_voltage", "ctrl.dc_current", "ctrl.motor_speed", "ctrl.torque_reference", "gnss.speed",
                     "gnss.speed_acc", "imu.ax", "imu.gz"} | {f"wheel.{c}.speed" for c in chans})
    times = [t for s in series.values() for t in (s.t[:1] + s.t[-1:])]
    if not times:
        return {"run_id": run_id, "ticks": 0, "note": "no measurements"}
    boot = db.execute("SELECT MIN(t_local_us) FROM records WHERE run_id=? AND rtype=12", (run_id,)).fetchone()[0]
    t0, t1, tick = min(times), max(times), int(tick_s * 1e6)
    meta_r = {"schema_version": evidence.schema()["schema_version"], "relation_set": rel_hash,
              "data_class": data_class(meta), "run_id": run_id}
    # direct evidence of a disturbance on a shared path
    disturb = []
    for t, status in db.execute("SELECT t_local_us, status FROM records WHERE run_id=? AND rtype=8", (run_id,)):
        if status == "bus_error":
            disturb.append((t, "bus:i2c1", f"TEMP read bus error at {t / 1e6:.3f} s"))
    power = ("BOR", "POR", "BROWN", "POWER")

    def reset_cause(rid: str, m: dict) -> str:
        r = db.execute("SELECT report_json FROM imports WHERE run_id=? ORDER BY rowid DESC", (rid,)).fetchone()
        boot_rec = (json.loads(r[0]).get("boot") or {}) if r else {}
        return str(boot_rec.get("cause") or (m.get("reset") or {}).get("cause", ""))

    cause = reset_cause(run_id, meta)
    if any(w in cause.upper() for w in power) and boot is not None:
        disturb.append((boot, "power:unit_supply", f"reset cause '{cause}' at the start of this session"))
    # the end of this session: no final counters record, and the unit's next session starts after a power reset
    rep = db.execute("SELECT report_json FROM imports WHERE run_id=? ORDER BY rowid DESC", (run_id,)).fetchone()
    prev_drop = 0.0
    t_end = db.execute("SELECT MAX(t_local_us) FROM records WHERE run_id=?", (run_id,)).fetchone()[0]
    for t_c, dq, ds, cn in db.execute(
            "SELECT t_local_us, MAX(CASE WHEN name='cnt_log_dropped_queue' THEN value END), "
            "MAX(CASE WHEN name='cnt_log_dropped_storage' THEN value END), "
            "MAX(CASE WHEN name='cnt_can_not_logged' THEN value END) FROM signals WHERE run_id=? AND "
            "name IN ('cnt_log_dropped_queue','cnt_log_dropped_storage','cnt_can_not_logged') GROUP BY t_local_us "
            "ORDER BY t_local_us", (run_id,)):
        tot = (dq or 0) + (ds or 0) + (cn or 0)
        if tot > prev_drop:
            disturb.append((t_c, "unit:recorder", f"the unit counted {int(tot - prev_drop)} records or frames it "
                                                  "could not log, by this counters record"))
        prev_drop = max(prev_drop, tot)
    if rep and not json.loads(rep[0]).get("final_counters") and t_end is not None:
        nxt = None
        if meta.get("unit_id") and isinstance(meta.get("boot"), int):
            for rid2, mj in db.execute("SELECT run_id, meta_json FROM runs"):
                m2 = json.loads(mj)
                if m2.get("unit_id") == meta["unit_id"] and m2.get("boot") == meta["boot"] + 1:
                    nxt = reset_cause(rid2, m2)
        what = "the session ended without a final counters record" + \
            (f"; the next session's reset cause is '{nxt}'" if nxt else "")
        if nxt is None or any(w in nxt.upper() for w in power):
            disturb.append((t_end, "unit:recorder", what))
    last_verdict: dict[tuple, str] = {}
    timeline: dict[str, list] = {}           # relation or conclusion -> [[t_s, result or verdict], ...] at changes
    counts = {"context": {}, "results": {}, "verdicts": {}}
    ambiguous: dict[str, dict] = {}
    receipts, snapshots, ctx_rows, onsets = [], [], [], []
    admissible_prev: dict[str, bool] = {}
    d_speed, d_wheel = _Derivative(), _Derivative()
    prev_temp: dict[str, tuple[float, float]] = {}
    # run on past the last record by the longest freshness threshold, so every stream that stopped is seen to stop
    t_last = t1
    t1 = t1 + int(max(sg.stale_s for sg in signals.REGISTRY) * 1e6)
    t = t0 + tick
    while t <= t1:
        ev: dict[str, Evidence] = {}
        for s in wanted:
            ser = series.get(s)
            m = ser.at(t) if ser else None
            ev[s] = evidence.assess(s, m, t, supported=s in sup)
        # accelerations from admissible speeds about 1 s earlier: for the context, from the best speed (GNSS, else
        # the wheels); as the witness accel.from_wheel, from the wheels only, so its lineage is what it says, and
        # accel.from_imu, the mean of the admissible IMU samples over the same window, timed like it
        d1 = d_speed(t, _speed_now(ev))
        accel = d1[0] if d1 else None
        dw = d_wheel(t, _wheel_speed(ev))
        for sig, src, ok in (("accel.from_wheel", "wheel", dw is not None), ("accel.from_imu", "imu", dw is not None)):
            lin = tuple(sorted(lineage.raw_sources(sig)))
            val, why = None, "no admissible wheel speed about 1 s earlier"
            if ok:
                if sig == "accel.from_wheel":
                    val, why = dw[0], None
                else:
                    mv = _mean_valid(series.get("imu.ax"), dw[1], t)
                    val, why = (mv[0], None) if mv else (None, "no admissible imu.ax sample in the window")
            mid, half = ((t + dw[1]) // 2, (t - dw[1]) // 2) if ok else (None, None)
            ev[sig] = Evidence(sig, "VALID" if val is not None else "UNKNOWN", val, "m/s^2", why, t_ref_us=mid,
                               t_unc_us=half if val is not None else None, age_us=0 if val is not None else None,
                               source=src, provenance=("speed derivative" if src == "wheel" else "mean of imu.ax") +
                               " over the window" if val is not None else None, seq=None, lineage=lin)
        since_boot = (t - (boot if boot is not None else t0)) / 1e6
        ctx = C.classify({s: e for s, e in ev.items() if not s.startswith("accel.")}, since_boot, accel,
                         ctx_cfg if params.get("drivetrain.freewheel") is None else
                         C.ContextConfig(**{**ctx_cfg.__dict__, "freewheel": params["drivetrain.freewheel"]}))
        counts["context"][ctx.mode] = counts["context"].get(ctx.mode, 0) + 1
        ctx_rows.append((ctx.mode, run_id, t - tick, t))
        p = {**params, "_now_s": t / 1e6, "_prev": prev_temp}
        obs = [witnesses.evaluate(r, ev, ctx, p) for r in rels]
        for s in temps:
            if ev[s].admissible:
                prev_temp.setdefault(s, (t / 1e6, ev[s].value))
                if t / 1e6 - prev_temp[s][0] >= 1.0:
                    prev_temp[s] = (t / 1e6, ev[s].value)
        concl = [verdicts.from_observation(o) for o in obs] + verdicts.localize(obs)
        for s, e in ev.items():
            was = admissible_prev.get(s)
            if was and not e.admissible and e.state not in ("UNSUPPORTED",) and s in series:
                # a stream that stopped is dated by its first missed sample (last sample + expected period), not by
                # when it was declared stale
                per = evidence.expected_period_us(s) or 0
                t_on = min(t, t - e.age_us + per) if e.state == "STALE" and e.age_us is not None else t
                onsets.append((t_on, e.source or s.split(".")[0], s, f"{e.state}: {e.reason}"))
            admissible_prev[s] = e.admissible
        for o in obs:
            counts["results"][o.result] = counts["results"].get(o.result, 0) + 1
            tl = timeline.setdefault(o.relation, [])
            if not tl or tl[-1][1] != o.result:
                tl.append([round(t / 1e6, 3), o.result])
        changed = []
        for c in concl:
            counts["verdicts"][c.verdict] = counts["verdicts"].get(c.verdict, 0) + 1
            key = (c.kind, c.subject)
            if last_verdict.get(key) != c.verdict:
                changed.append(c)
                last_verdict[key] = c.verdict
                if c.kind == "localization":
                    timeline.setdefault(f"localization:{c.subject}", []).append([round(t / 1e6, 3), c.verdict])
            if c.verdict == "AMBIGUOUS":
                a = ambiguous.setdefault(f"{c.kind}:{c.subject}", {"first_s": t / 1e6, "last_s": t / 1e6, "ticks": 0,
                                                                   "statement": c.statement,
                                                                   "candidates": list(c.candidates)})
                a["last_s"], a["ticks"] = t / 1e6, a["ticks"] + 1
        for key in [k for k in last_verdict if k[0] == "localization"]:
            if not any(c.kind == "localization" and c.subject == key[1] for c in concl):
                del last_verdict[key]                 # the localization no longer holds
                timeline[f"localization:{key[1]}"].append([round(t / 1e6, 3), "none"])
        if changed:
            evd = {s: e.as_dict() for s, e in ev.items()}
            rc = verdicts.receipt(t, ctx.as_dict(), evd, obs, concl, meta_r)
            snapshots.append((run_id, t, json.dumps(rc, sort_keys=True, default=str)))
            for c in changed:
                basis = [o.as_dict() for o in obs if o.relation in c.basis]
                receipts.append((run_id, t, c.kind, c.subject, c.verdict, ctx.mode,
                                 json.dumps({"changed": c.as_dict(), "observations": basis, "snapshot_t_us": t},
                                            sort_keys=True, default=str)))
        t += tick
    def still_admissible(a_us: int, b_us: int) -> set[str]:
        """Signals with fresh admissible evidence received in (a, b]: positive evidence that their paths worked."""
        return {s for s, ser in series.items() if ser.fresh_valid(a_us, b_us)}

    # an orderly end of the log (a final counters record) is the end of the recording, not a loss of evidence
    orderly = bool(rep and json.loads(rep[0]).get("final_counters"))
    if orderly:
        onsets = [o for o in onsets if o[0] < t_last - int(onset_window_s * 1e6)]
    cc = verdicts.common_cause(onsets, int(onset_window_s * 1e6), disturb, still_admissible)
    for c in cc:
        t_c = c.t_us
        receipts.append((run_id, t_c, c.kind, c.subject, c.verdict, None,
                         json.dumps({**meta_r, "advisory_only": True, "t_us": t_c, "conclusions": [c.as_dict()],
                                     "disturbances": [d for d in disturb], "reason": c.statement}, default=str)))
    if write:
        db.executemany("UPDATE evidence SET context=? WHERE run_id=? AND t_ref_us>? AND t_ref_us<=?", ctx_rows)
        db.executemany("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?,?,?,?)", receipts)
        db.executemany("INSERT OR REPLACE INTO receipt_snapshots VALUES (?,?,?)", snapshots)
        db.commit()
    return {"run_id": run_id, "data_class": meta_r["data_class"], "relation_set": rel_hash,
            "schema_version": meta_r["schema_version"], "ticks": len(ctx_rows), "tick_s": tick_s,
            "supported": sorted(sup), "unsupported_wanted": sorted(set(wanted) - sup),
            "relations": [r.definition() for r in rels], "parameters": {k: v for k, v in params.items()},
            "counts": counts, "ambiguous": ambiguous, "common_cause": [c.as_dict() for c in cc],
            "timeline": timeline, "t_first_s": round(t0 / 1e6, 3), "t_last_s": round(t_last / 1e6, 3),
            "receipts": len(receipts)}
