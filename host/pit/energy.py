"""Energy per distance at the pit (README section D, docs/MATH_SPEC.md section 8).

    v      = C * counts / (N * window)            wheel speed [m/s] from one counting window
    E_Wh   = E_J / 3600                           the controller integrates E_J = sum(V * I * dt)
    Wh/km  = E_Wh / (distance_m / 1000)
    E_nom  = V_nom * Q_rated                      nominal pack energy [Wh]; not measured usable energy

`run_summary` reads one run from the pit database (signals imported by
host/pit/ingest.py import_log). It uses the controller's own energy counter
(`ctrl_energy.energy_J`, integrated over valid samples only) and its gap time
(`ctrl_energy_quality.gap_s`), and the distance of one wheel channel as the sum
of speed x window. It reports what is missing instead of filling it in. The
result is the energy at the controller input, not the joulemeter's figure
(docs/ENERGY_METHODS.md 2.1).
"""
from __future__ import annotations

import sqlite3


def wheel_speed_mps(counts: int, circumference_m: float, pulses_per_rev: int, window_s: float) -> float:
    """v = C * f / N with f = counts / window."""
    return circumference_m * (counts / window_s) / pulses_per_rev


def energy_wh(energy_J: float) -> float:
    return energy_J / 3600.0


def wh_per_km(energy_J: float, distance_m: float) -> float:
    return energy_wh(energy_J) / (distance_m / 1000.0)


def nominal_pack_wh(nominal_V: float, capacity_Ah: float) -> float:
    """Nominal energy label value. Usable energy depends on the voltage limits, current and temperature."""
    return nominal_V * capacity_Ah


def run_summary(db: sqlite3.Connection, run_id: str, channel: str, window_s: float | None) -> dict:
    notes = []
    rows = db.execute("SELECT name, t_local_us, value FROM signals WHERE run_id=? AND name IN "
                      "('energy_J','energy_gap_s',?) ORDER BY t_local_us", (run_id, channel)).fetchall()
    e = [(t, v) for n, t, v in rows if n == "energy_J" and v is not None]
    g = [(t, v) for n, t, v in rows if n == "energy_gap_s" and v is not None]
    w = [(t, v) for n, t, v in rows if n == channel]
    res = {"run_id": run_id, "channel": channel, "energy_Wh": None, "distance_m": None, "Wh_per_km": None,
           "energy_gap_s": None, "notes": notes}
    if len(e) < 2:
        notes.append("fewer than two controller energy samples: no energy over the run")
    if not w:
        notes.append(f"no samples of wheel channel {channel}: no distance")
    if window_s is None:
        notes.append("wheel counting window not in the run metadata: no distance")
    if len(e) < 2 or not w or window_s is None:
        return res
    t0, t1 = e[0][0], e[-1][0]
    dE = e[-1][1] - e[0][1]
    inside = [v for t, v in w if t0 < t <= t1]
    missing = sum(1 for v in inside if v is None)
    dist = sum(v * window_s for v in inside if v is not None)
    res.update(energy_Wh=energy_wh(dE), distance_m=dist, t_span_s=(t1 - t0) / 1e6)
    if g:
        gaps = [v for t, v in g if t0 <= t <= t1]
        res["energy_gap_s"] = (gaps[-1] - gaps[0]) if len(gaps) >= 2 else None
        if res["energy_gap_s"]:
            notes.append(f"controller energy has {res['energy_gap_s']:.3f} s of gaps in this span: energy is a lower "
                         "bound")
    else:
        notes.append("no energy gap counter: completeness of the energy figure unknown")
    if missing:
        notes.append(f"{missing} wheel windows without a value: distance is a lower bound")
    if dist > 0:
        res["Wh_per_km"] = wh_per_km(dE, dist)
    else:
        notes.append("zero distance on this channel: no energy per distance")
    notes.append("energy at the controller input; the official joulemeter also counts the telemetry unit, sensors, "
                 "display and wiring downstream of it")
    notes.append("a wheel dropout reads as zero counts and shortens the distance; compare with rotor speed or GNSS")
    return res


def compare_channels(summaries: list[dict], tolerance: float = 0.02) -> list[str]:
    """Distances of the instrumented wheels should agree; a shorter one points at missed pulses."""
    d = {s["channel"]: s["distance_m"] for s in summaries if s.get("distance_m")}
    if len(d) < 2:
        return ["only one wheel channel with a distance: no cross-check between wheels"]
    hi = max(d.values())
    short = {c: v for c, v in d.items() if v < (1 - tolerance) * hi}
    return [f"wheel channel {c} covers {v:.1f} m, {100 * (1 - v / hi):.1f} % less than the longest "
            f"({hi:.1f} m): missed pulses or a dropout on that channel" for c, v in sorted(short.items())]


# ---------------------------------------------------------------- energy from measured V and I (v0.7)
# Measurement boundaries. Controller input energy is what the external controller's own sensors see at its DC
# terminals; total battery energy needs the battery-side monitor (optional telematics hardware) and also
# contains the telematics unit, sensors, display and every other auxiliary load downstream of that monitor.
BOUNDARIES = {
    "controller_input": ("ctrl.dc_voltage", "ctrl.dc_current",
                         "DC input terminals of the external controller, measured by the controller's own sensors; "
                         "excludes the telematics unit, sensors, display and other auxiliary loads"),
    "battery": ("batt.voltage", "batt.current",
                "battery terminals, measured by the battery-side monitor; includes the controller, the telematics "
                "unit and every auxiliary load downstream of the monitor"),
}


def series(db: sqlite3.Connection, run_id: str, signal: str, usable_only: bool = True) -> list[tuple]:
    """[(t_ref_us, value, t_unc_us, validity)] of one signal from the `measurements` table, in time order.
    t_ref is the sample time when the source gave one, else the receive time."""
    rows = db.execute("SELECT COALESCE(t_sample_us, t_rx_us), value, t_unc_us, validity FROM measurements "
                      "WHERE run_id=? AND signal=? ORDER BY COALESCE(t_sample_us, t_rx_us)", (run_id, signal)).fetchall()
    return [r for r in rows if r[3] == "valid"] if usable_only else rows


def _span(db: sqlite3.Connection, run_id: str) -> tuple[int, int] | None:
    r = db.execute("SELECT MIN(t_local_us), MAX(t_local_us) FROM records WHERE run_id=?", (run_id,)).fetchone()
    return None if r[0] is None else (r[0], r[1])


def vi_energy(db: sqlite3.Connection, run_id: str, boundary: str = "controller_input", align_tol_us: int = 20_000,
              max_gap_us: int | None = None) -> dict:
    """Energy = integral of V x I over the intervals where both are valid and time-aligned.

    Each current sample is paired with the nearest voltage sample no more than `align_tol_us` away (both
    times are telematics-clock references; the result reports the larger of their uncertainties). Consecutive
    pairs no more than `max_gap_us` apart are integrated with the trapezoid rule; a longer gap, and the time
    before the first and after the last pair, is a missing interval, reported with its cause and never
    filled in. The missing energy is bounded only roughly, by the largest observed power times the missing
    time. The accuracy of the V and I sensors themselves is not known here and is not included."""
    v_sig, i_sig, where = BOUNDARIES[boundary]
    V = series(db, run_id, v_sig)
    I = series(db, run_id, i_sig)
    res = {"run_id": run_id, "boundary": boundary, "boundary_text": where, "signals": [v_sig, i_sig],
           "energy_J": None, "energy_Wh": None, "covered_s": 0.0, "missing_s": None, "missing_intervals": [],
           "p_max_W": None, "missing_energy_bound_J": None, "discretisation_J": None, "pairs": 0,
           "unpaired_current_samples": 0, "timestamp_uncertainty_us": None,
           "notes": ["sensor accuracy of V and I not stated by their source: not included in any bound"]}
    span = _span(db, run_id)
    if span is None:
        res["notes"].append("run has no records")
        return res
    import bisect
    vt = [r[0] for r in V]
    pairs, unc = [], 0
    for t, i, ui, _q in I:
        k = bisect.bisect_left(vt, t)
        best = min((j for j in (k - 1, k) if 0 <= j < len(V)), key=lambda j: abs(vt[j] - t), default=None)
        if best is None or abs(vt[best] - t) > align_tol_us:
            res["unpaired_current_samples"] += 1
            continue
        pairs.append((t, V[best][1] * i))
        unc = max(unc, ui or 0, V[best][2] or 0)
    res["pairs"] = len(pairs)
    if max_gap_us is None:
        d = sorted(b[0] - a[0] for a, b in zip(I, I[1:]))
        max_gap_us = 3 * d[len(d) // 2] if d else 0
    res["max_gap_us"] = max_gap_us
    res["timestamp_uncertainty_us"] = unc if pairs else None
    if not pairs:
        res["missing_s"] = (span[1] - span[0]) / 1e6
        res["missing_intervals"] = [[span[0] / 1e6, span[1] / 1e6, _cause(db, run_id, v_sig, i_sig, *span)]]
        res["notes"].append(f"no time-aligned valid {v_sig} and {i_sig}: no energy at this boundary")
        return res
    e = rect = covered = 0.0
    gaps = []
    if pairs[0][0] - span[0] > max_gap_us:
        gaps.append((span[0], pairs[0][0]))
    for (t0, p0), (t1, p1) in zip(pairs, pairs[1:]):
        if t1 - t0 > max_gap_us:
            gaps.append((t0, t1))
            continue
        dt = (t1 - t0) / 1e6
        e += 0.5 * (p0 + p1) * dt
        rect += p0 * dt
        covered += dt
    if span[1] - pairs[-1][0] > max_gap_us:
        gaps.append((pairs[-1][0], span[1]))
    p_max = max(abs(p) for _t, p in pairs)
    missing = sum(b - a for a, b in gaps) / 1e6
    res.update(energy_J=e, energy_Wh=e / 3600.0, covered_s=covered, missing_s=missing, p_max_W=p_max,
               missing_energy_bound_J=p_max * missing, discretisation_J=abs(e - rect),
               missing_intervals=[[a / 1e6, b / 1e6, _cause(db, run_id, v_sig, i_sig, a, b)] for a, b in gaps])
    if gaps:
        res["notes"].append(f"{len(gaps)} missing interval(s), {missing:.2f} s: the energy covers only the valid "
                            "intervals and is not extrapolated")
    return res


def _cause(db, run_id, v_sig, i_sig, a_us, b_us) -> str:
    """Why an interval has no valid aligned V and I: the validities seen in it, or no measurement at all."""
    rows = db.execute("SELECT signal, validity, COUNT(*) FROM measurements WHERE run_id=? AND signal IN (?,?) AND "
                      "COALESCE(t_sample_us, t_rx_us) > ? AND COALESCE(t_sample_us, t_rx_us) < ? GROUP BY signal, "
                      "validity", (run_id, v_sig, i_sig, a_us, b_us)).fetchall()
    bad = sorted(f"{s} {q} x{n}" for s, q, n in rows if q != "valid")
    have = {s for s, q, _n in rows if q == "valid"}
    lost = [s for s in (v_sig, i_sig) if s not in have]
    if not rows:
        return "no measurement of either signal"
    parts = bad + [f"no valid {s}" for s in lost if not any(x.startswith(s) for x in bad)]
    return "; ".join(parts) or "samples too far apart to pair"


def wheel_distance(db: sqlite3.Connection, run_id: str, channel: str) -> dict:
    """Distance of one wheel channel: the last distance measurement (counted edges x pitch). After lost edges,
    or once the channel was suspect (silent while another channel moved), the value is a lower bound (validity
    unverified). Also counts the channel's speed records without evidence and those found suspect."""
    r = db.execute("SELECT value, validity, t_rx_us FROM measurements WHERE run_id=? AND signal=? AND value IS NOT "
                   "NULL ORDER BY t_rx_us DESC LIMIT 1", (run_id, f"wheel.{channel}.distance")).fetchone()
    no_ev, susp = db.execute("SELECT SUM(validity='no_evidence'), SUM(validity='invalid') FROM measurements WHERE "
                             "run_id=? AND signal=?", (run_id, f"wheel.{channel}.speed")).fetchone()
    no_ev, susp = no_ev or 0, susp or 0
    if r is None:
        return {"channel": channel, "distance_m": None, "lower_bound": None, "no_evidence_records": no_ev,
                "suspect_records": susp, "t_us": None}
    return {"channel": channel, "distance_m": r[0], "lower_bound": r[1] != "valid", "no_evidence_records": no_ev,
            "suspect_records": susp, "t_us": r[2]}
