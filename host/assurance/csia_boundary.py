"""The CSIA shadow boundary: only qualified evidence goes in, only advisory verdicts come out.

    evidence producers -> qualified evidence (VALID only) -> CSIA vehicle adapter (frozen, shadow) -> advisory verdict

The CSIA vehicle adapter (host/csia_adapter, frozen with its evaluation; the documented result favours R3v,
docs/csia/) is research code that keeps Beta-belief "trust" values per node. This boundary decides what may cross in
each direction:

  in   a sample crosses only if its measurement is VALID (host/telematics/evidence.py); every other sample is
       withheld and counted by state. Nothing is invented for an input the unit does not have: no torque request
       (`iq_ref`: a request is propulsion authority, which this system does not hold), no road grade without a route
       map, no KCL residual from a reconstructed phase current. A relation that needs one gets no evidence and the
       core says so.
  out  the core's explanation and attribution become SUPPORTED, AMBIGUOUS or UNSUPPORTED with a plain statement. An
       attribution is "the evidence path of X", never a fault. The trust numbers (`trust`, `aggregate_trust`) do not
       cross: they are not calibrated probabilities, and a number without calibration would read as confidence.

Without the vehicle's gear ratio and wheel radius the adapter cannot be configured: the result is UNSUPPORTED for
the whole run, with that reason. Shadow mode: the output is a record for people; nothing here has a transport.
"""
from __future__ import annotations

import bisect
import math
import sqlite3
from typing import Optional

from host.telematics import evidence

# registry signal -> (CSIA input, sigma(value), clock domain)
INPUTS = {
    "ctrl.motor_speed": ("rotor", lambda v: 0.01 * abs(v) + 2.0, "controller"),
    "ctrl.phase_current_q": ("iq", lambda v: 0.15, "controller"),
    "wheel.wheel_l.speed": ("wheel_l", lambda v: 0.03 + 0.01 * abs(v), "telematics"),
    "wheel.wheel_r.speed": ("wheel_r", lambda v: 0.03 + 0.01 * abs(v), "telematics"),
    "wheel.wheel_drive.speed": ("wheel_drive", lambda v: 0.03 + 0.01 * abs(v), "telematics"),
    "imu.ax": ("imu_ax", lambda v: 0.08, "imu"),
    "imu.gz": ("imu_gz", lambda v: 0.01, "imu"),
}
NOT_PASSED = {
    "iq_ref": "a torque request is propulsion authority: the receive-only unit has none and passes none",
    "kcl": "the KCL residual is only evidence with three measured phase currents; not claimed from the broadcast",
    "grade": "no route map: road grade is unknown, so relations that need it get no evidence",
}
WITHHELD_NUMBERS = ("trust", "aggregate_trust", "lambdas")


def _seq_unwrap():
    state: dict[str, tuple[int, int]] = {}

    def f(name: str, s8: Optional[int]) -> int:
        if s8 is None:
            k = state.get(name, (0, -1))[1] + 1
            state[name] = (0, k)
            return k
        prev = state.get(name)
        if prev is None:
            state[name] = (s8, s8)
            return s8
        d = (s8 - prev[0]) & 0xFF
        if d >= 128:
            return prev[1] - (256 - d)
        state[name] = (s8, prev[1] + d)
        return prev[1] + d
    return f


def qualified_samples(db: sqlite3.Connection, run_id: str) -> tuple[list, dict]:
    """(time-ordered [(t_s, csia_input, Sample)], {"passed": {...}, "withheld": {signal: {state: n}}})."""
    from host.csia_adapter.adapter import Sample
    rows = db.execute("SELECT signal, value, t_rx_us, t_sample_us, source_seq, validity FROM measurements WHERE "
                      "run_id=? AND (signal IN (%s) OR signal IN ('gnss.speed','gnss.speed_acc','gnss.num_sv',"
                      "'ctrl.dc_voltage','ctrl.dc_current')) ORDER BY COALESCE(t_sample_us, t_rx_us), record_id"
                      % ",".join("?" * len(INPUTS)), (run_id, *INPUTS)).fetchall()
    useq = _seq_unwrap()
    out, passed, withheld = [], {}, {}
    latest: dict[str, float] = {}
    volt: list[tuple[int, float]] = []
    for sig, v, t_rx, t_s, seq, val in rows:
        st = evidence.state_of(val)
        if st != "VALID":
            withheld.setdefault(sig, {}).setdefault(st, 0)
            withheld[sig][st] += 1
            continue
        t_ref = t_s if t_s is not None else t_rx
        t = t_ref / 1e6
        latest[sig] = v
        if sig in INPUTS:
            name, sigma, clock = INPUTS[sig]
            out.append((t, name, Sample(v, sigma(v), t, clock, t_rx / 1e6, useq(name, seq), 1, {})))
        elif sig == "gnss.num_sv":
            g, sacc = latest.get("gnss.speed"), latest.get("gnss.speed_acc")
            if g is not None and sacc is not None:
                out.append((t, "gnss", Sample(g, max(sacc, 0.08), t, "gnss", t_rx / 1e6, useq("gnss", None), 1,
                                              {"sacc": sacc, "num_sv": int(v)})))
                name = "gnss"
            else:
                continue
        elif sig == "ctrl.dc_voltage":
            volt.append((t_ref, v))
            continue
        elif sig == "ctrl.dc_current":
            k = bisect.bisect_left(volt, (t_ref, -math.inf))
            near = [volt[j] for j in (k - 1, k) if 0 <= j < len(volt) and abs(volt[j][0] - t_ref) <= 20_000]
            if not near:
                withheld.setdefault("p_dc", {}).setdefault("no aligned voltage", 0)
                withheld["p_dc"]["no aligned voltage"] += 1
                continue
            name = "p_dc"
            out.append((t, name, Sample(near[-1][1] * v, 1.0, t, "controller", t_rx / 1e6, useq(name, seq), 1, {})))
        else:
            continue
        passed[name] = passed.get(name, 0) + 1
    return out, {"passed": passed, "withheld": withheld, "not_passed": NOT_PASSED}


def _verdict(st, p) -> tuple[str, str]:
    from host.csia_adapter.adapter import Explain
    e = Explain(int(st.explanation))
    if not st.monitor_ok or e == Explain.MONITOR_UNHEALTHY:
        return "UNSUPPORTED", "the shadow monitor reports itself unhealthy: no conclusion"
    if e == Explain.OK_CONSISTENT:
        return "SUPPORTED", "the active relations agree"
    if e in (Explain.NO_EVIDENCE, Explain.STALE_INPUTS, Explain.REGIME_GATED):
        return "UNSUPPORTED", {Explain.NO_EVIDENCE: "no relation had admissible evidence",
                               Explain.STALE_INPUTS: "inputs not fresh",
                               Explain.REGIME_GATED: "no relation applies in this regime"}[e]
    if e == Explain.DISAGREE_AMBIGUOUS or not st.suspects:
        return "AMBIGUOUS", "a relation disagrees and the evidence does not attribute it: cause not isolated"
    return "AMBIGUOUS", ("the core attributes the disagreement to the evidence path of " + ", ".join(st.suspects) +
                         ": the cause on that path (sensor, wiring, parameter, a real local effect) is not isolated")


def run(db: sqlite3.Connection, run_id: str, wheel_radius_m: Optional[float], gear_ratio: Optional[float],
        freewheel: Optional[bool] = None, tick_s: float = 0.1) -> dict:
    res = {"run_id": run_id, "advisory_only": True, "verdicts": {}, "transitions": [],
           "withheld_numbers": {k: "not reported: not a calibrated probability" for k in WITHHELD_NUMBERS}}
    missing = [n for n, v in (("wheel radius", wheel_radius_m), ("gear ratio", gear_ratio),
                              ("freewheel", freewheel)) if v is None]
    if missing:
        res.update(verdict="UNSUPPORTED", reason="the CSIA vehicle adapter needs " + ", ".join(missing) +
                   ", which this configuration does not state")
        return res
    from host.csia_adapter.adapter import AdapterParams, VehicleCsiaAdapter
    data, gate = qualified_samples(db, run_id)
    res["gate"] = gate
    if not data:
        res.update(verdict="UNSUPPORTED", reason="no admissible evidence crossed the boundary")
        return res
    ad = VehicleCsiaAdapter(AdapterParams(wheel_radius_m=wheel_radius_m, gear_ratio=gear_ratio, freewheel=freewheel))
    res["csia_version"] = ad.csia_version
    k, last = 0, None
    t, t1 = data[0][0] + tick_s, data[-1][0]
    while t <= t1:
        while k < len(data) and data[k][0] <= t:
            ad.ingest(data[k][1], data[k][2])
            k += 1
        st = ad.tick(t)
        verdict, why = _verdict(st, ad.p)
        res["verdicts"][verdict] = res["verdicts"].get(verdict, 0) + 1
        if (verdict, why) != last:
            res["transitions"].append({"t_s": round(t, 3), "verdict": verdict, "statement": why,
                                       "explanation": int(st.explanation), "observability": st.observability,
                                       "active_relations": bin(st.evidence_mask & 0xFF).count("1")})
            last = (verdict, why)
        t = round(t + tick_s, 6)
    res["verdict"] = "see transitions"
    return res
