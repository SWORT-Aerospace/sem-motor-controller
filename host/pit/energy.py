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
