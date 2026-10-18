"""Advisory energy figures for the pit and the driver's coach (ADVISORY ONLY: nothing here reaches the vehicle).

    rolling(db, run, channel, window_s, step_s)   rolling Wh/km at the controller input over a sliding window; a
                                                  window with a missing interval of power, an unverified distance or
                                                  too little distance gives no number, only the reason
    speed_table(db, run, channel, bins)           energy per distance by speed band, from admissible speed only
    remaining(used_Wh)                            what is left of the NOMINAL pack energy (48 V x 10 Ah, team-reported;
                                                  usable energy not measured), and the distance at a stated Wh/km
    cruise_advice(table, min_km)                  the speed band with the lowest observed Wh/km, with the conditions
                                                  that limit it; a suggestion to people, not a setpoint

Energy is at the controller input (ctrl.dc_voltage x ctrl.dc_current, the controller's own sensors; host/pit/
energy.py), not at the battery or the joulemeter. Distance is one wheel channel's counted edges x pitch, so it
needs the circumference and pulses per revolution; a lower-bound distance (lost edges, suspect channel) gives no
Wh/km. The receive-only boundary holds: this module reads the database and returns numbers for people. It has no
transport and no output to the controller, and its results carry `advisory_only: True`.
"""
from __future__ import annotations

import bisect
import sqlite3
from typing import Optional

from host.pit import energy

NOMINAL_V = 48.0            # team-reported (docs/BATTERY.md); not a measured or rated usable value
NOMINAL_AH = 10.0
ADVISORY = {"advisory_only": True, "boundary": "controller input (the controller's own V and I sensors)"}


def _power_pairs(db: sqlite3.Connection, run_id: str, align_tol_us: int = 20_000) -> list[tuple[int, float]]:
    V = energy.series(db, run_id, "ctrl.dc_voltage")
    I = energy.series(db, run_id, "ctrl.dc_current")
    vt = [r[0] for r in V]
    out = []
    for t, i, _u, _q in I:
        k = bisect.bisect_left(vt, t)
        j = min((x for x in (k - 1, k) if 0 <= x < len(V)), key=lambda x: abs(vt[x] - t), default=None)
        if j is not None and abs(vt[j] - t) <= align_tol_us:
            out.append((t, V[j][1] * i))
    return out


def _energy_between(pairs, ts, a: int, b: int, max_gap_us: int) -> tuple[Optional[float], str]:
    i, j = bisect.bisect_left(ts, a), bisect.bisect_right(ts, b)
    seg = pairs[i:j]
    if len(seg) < 2:
        return None, "no aligned valid voltage and current"
    if seg[0][0] - a > max_gap_us or b - seg[-1][0] > max_gap_us:
        return None, "power missing at the window edge"
    e = 0.0
    for (t0, p0), (t1, p1) in zip(seg, seg[1:]):
        if t1 - t0 > max_gap_us:
            return None, f"power missing for {(t1 - t0) / 1e6:.2f} s"
        e += 0.5 * (p0 + p1) * (t1 - t0) / 1e6
    return e, ""


def _distance_at(db, run_id, channel):
    rows = db.execute("SELECT t_rx_us, value, validity FROM measurements WHERE run_id=? AND signal=? AND value IS NOT "
                      "NULL ORDER BY t_rx_us", (run_id, f"wheel.{channel}.distance")).fetchall()
    return [r[0] for r in rows], rows


def rolling(db: sqlite3.Connection, run_id: str, channel: str, window_s: float = 30.0, step_s: float = 5.0,
            min_distance_m: float = 20.0, max_gap_us: int = 100_000) -> list[dict]:
    pairs = _power_pairs(db, run_id)
    ts = [p[0] for p in pairs]
    dts, drows = _distance_at(db, run_id, channel)
    span = db.execute("SELECT MIN(t_local_us), MAX(t_local_us) FROM records WHERE run_id=?", (run_id,)).fetchone()
    if span[0] is None:
        return []
    out, w, step = [], int(window_s * 1e6), int(step_s * 1e6)
    b = span[0] + w
    while b <= span[1]:
        a = b - w
        row = {"t0_us": a, "t1_us": b, "Wh_per_km": None, "energy_Wh": None, "distance_m": None, "reason": "",
               **ADVISORY}
        e, why = _energy_between(pairs, ts, a, b, max_gap_us)
        ia, ib = bisect.bisect_right(dts, a) - 1, bisect.bisect_right(dts, b) - 1
        if e is None:
            row["reason"] = why
        elif ia < 0 or ib < 0:
            row["reason"] = f"no distance of {channel} at the window edges"
        elif drows[ib][2] != "valid" or drows[ia][2] != "valid":
            row["reason"] = f"distance of {channel} is a lower bound (lost edges or suspect channel)"
        else:
            d = drows[ib][1] - drows[ia][1]
            row.update(energy_Wh=e / 3600.0, distance_m=d)
            if d < min_distance_m:
                row["reason"] = f"distance {d:.1f} m < {min_distance_m} m: Wh/km not meaningful"
            else:
                row["Wh_per_km"] = (e / 3600.0) / (d / 1000.0)
        out.append(row)
        b += step
    return out


def speed_table(db: sqlite3.Connection, run_id: str, channel: str,
                bins: tuple = (0.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0), max_gap_us: int = 100_000) -> list[dict]:
    """Energy and distance per speed band: each power interval is assigned the admissible wheel speed at its start
    (an interval without one is counted as unassigned, not guessed)."""
    pairs = _power_pairs(db, run_id)
    sp = energy.series(db, run_id, f"wheel.{channel}.speed")
    st = [r[0] for r in sp]
    acc = {k: [0.0, 0.0, 0.0] for k in range(len(bins) - 1)}      # energy J, distance m, time s
    unassigned = 0.0
    for (t0, p0), (t1, p1) in zip(pairs, pairs[1:]):
        if t1 - t0 > max_gap_us:
            continue
        dt = (t1 - t0) / 1e6
        i = bisect.bisect_right(st, t0) - 1
        if i < 0 or t0 - st[i] > 300_000:
            unassigned += dt
            continue
        v = sp[i][1]
        k = bisect.bisect_right(bins, v) - 1
        if 0 <= k < len(bins) - 1:
            acc[k][0] += 0.5 * (p0 + p1) * dt
            acc[k][1] += v * dt
            acc[k][2] += dt
    out = []
    for k, (e, d, t) in acc.items():
        out.append({"band_mps": [bins[k], bins[k + 1]], "time_s": t, "distance_m": d, "energy_Wh": e / 3600.0,
                    "Wh_per_km": (e / 3600.0) / (d / 1000.0) if d > 1.0 else None, **ADVISORY})
    if out:
        out[-1]["unassigned_s"] = unassigned
    return out


def remaining(used_Wh: float, wh_per_km: Optional[float] = None, nominal_V: float = NOMINAL_V,
              capacity_Ah: float = NOMINAL_AH) -> dict:
    nominal = energy.nominal_pack_wh(nominal_V, capacity_Ah)
    left = nominal - used_Wh
    return {"nominal_Wh": nominal, "used_Wh": used_Wh, "remaining_nominal_Wh": left,
            "distance_at_rate_km": (left / wh_per_km) if wh_per_km else None,
            "basis": f"NOMINAL {nominal_V:g} V x {capacity_Ah:g} Ah (team-reported, docs/BATTERY.md); usable energy "
                     "depends on voltage limits, current and temperature and is not measured; energy used is at the "
                     "controller input, so the auxiliary loads are not in it", **ADVISORY}


def cruise_advice(table: list[dict], min_distance_m: float = 200.0) -> dict:
    cands = [r for r in table if r["Wh_per_km"] is not None and r["distance_m"] >= min_distance_m]
    if not cands:
        return {"band_mps": None, "reason": f"no speed band with at least {min_distance_m:.0f} m of admissible "
                                            "evidence", **ADVISORY}
    best = min(cands, key=lambda r: r["Wh_per_km"])
    return {"band_mps": best["band_mps"], "Wh_per_km": best["Wh_per_km"], "distance_m": best["distance_m"],
            "reason": "the lowest Wh/km observed in this run, among bands with enough distance; it is not a setpoint: "
                      "the event's minimum average speed (docs/RULES_COMPLIANCE.md), the track, wind, grade and the "
                      "driver decide", "conditions": ["only this run's data", "controller-input energy",
                                                      "speed bands with fewer than " + f"{min_distance_m:.0f} m left out"],
            **ADVISORY}
