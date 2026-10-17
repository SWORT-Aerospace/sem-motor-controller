"""Pit-side CSIA replay over an imported run (SHADOW: it reports, it never commands).

Reads the decoded signals of one run from the pit database, rebuilds the
adapter's Samples in the telematics clock domain (every receive time is the
telematics unit's timestamp), ticks the frozen vehicle adapter at 10 Hz and
returns the advisory timeline plus host runtime and memory figures.

Mapping (docs/ICD.md, CSIA inputs):
  rotor, iq, kcl (+kcl_available), p_dc       controller frames
  iq_ref = accepted_Nm / kt, flagged saturated_or_slewing when the command
           trace carries SLEW or any CLAMP reason
  wheel_l, wheel_r, wheel_drive               telematics hall inputs (counts -> m/s)
  gnss (+sacc, num_sv), imu_ax, imu_gz        telematics GNSS / IMU
  grade                                       route map; a flat synthetic track here (0 rad, sigma 0.003)
Controller frames carry an 8-bit sequence; it is unwrapped per signal so the
adapter's 16-bit ordering check is not defeated by the wrap.
"""
from __future__ import annotations

import math
import sqlite3
import time
import tracemalloc

from host.csia_adapter.adapter import AdapterParams, Sample, VehicleCsiaAdapter

SLEW_OR_CLAMP = 0x1000 | 0x0100 | 0x0200 | 0x0400 | 0x0800 | 0x2000


def build_samples(db: sqlite3.Connection, run_id: str, kt: float, wheel_q_mps: float):
    rows = db.execute("SELECT name, t_local_us, value, seq FROM signals WHERE run_id=? ORDER BY t_local_us, block, idx",
                      (run_id,)).fetchall()
    unwrap: dict[str, tuple[int, int]] = {}
    latest: dict[str, float] = {}
    out: list[tuple[float, str, Sample]] = []

    def useq(name, s8):
        if s8 is None:
            k = unwrap.get(name, (0, -1))[1] + 1
            unwrap[name] = (0, k)
            return k
        prev = unwrap.get(name)
        if prev is None:
            unwrap[name] = (s8, s8)
            return s8
        p8, full = prev
        d = (s8 - p8) & 0xFF
        if d >= 128:                       # older than the newest seen: a smaller number, state unchanged
            return full - (256 - d)
        unwrap[name] = (s8, full + d)      # d == 0 (duplicate) keeps the same number
        return full + d

    def emit(t, name, v, sigma, clock, flags=None, seq=None):
        if v is None:
            return
        out.append((t, name, Sample(v, sigma, t, clock, t, useq(name, seq), 1, flags or {})))

    for name, t_us, v, seq in rows:
        t = t_us / 1e6
        latest[name] = v
        if name == "rotor":
            emit(t, "rotor", v, 0.01 * abs(v or 0.0) + 2.0, "controller", seq=seq)
        elif name == "iq":
            emit(t, "iq", v, 0.15, "controller", seq=seq)
        elif name == "kcl":
            emit(t, "kcl", v, 0.1, "controller", {"kcl_available": bool(latest.get("kcl_available"))}, seq=seq)
        elif name == "p_dc":
            emit(t, "p_dc", v, 1.0, "controller", seq=seq)
        elif name == "reason":
            acc = latest.get("accepted_Nm")
            if acc is not None and v is not None:
                emit(t, "iq_ref", acc / kt, 0.0, "controller",
                     {"saturated_or_slewing": bool(int(v) & SLEW_OR_CLAMP)}, seq=seq)
        elif name in ("wheel_l", "wheel_r", "wheel_drive"):
            emit(t, name, v, wheel_q_mps / math.sqrt(12) + 0.01 * (v or 0.0), "telematics")
        elif name == "gnss_num_sv":
            g = latest.get("gnss")
            sacc = latest.get("gnss_sacc")
            if g is not None and sacc is not None:
                emit(t, "gnss", g, max(sacc, 0.08), "gnss", {"sacc": sacc, "num_sv": int(v)})
                emit(t, "grade", 0.0, 0.003, "map")
        elif name == "imu_ax":
            emit(t, "imu_ax", v, 0.08, "imu")
        elif name == "imu_gz":
            emit(t, "imu_gz", v, 0.01, "imu")
    return out


def replay(db: sqlite3.Connection, run_id: str, params: AdapterParams, kt: float, wheel_q_mps: float) -> dict:
    data = build_samples(db, run_id, kt, wheel_q_mps)
    if not data:
        return {"ticks": 0, "timeline": []}
    tracemalloc.start()
    ad = VehicleCsiaAdapter(params)
    t0, t1 = data[0][0], data[-1][0]
    k = 0
    timeline = []
    tick_ms = []
    t = t0 + 0.1
    while t <= t1:
        while k < len(data) and data[k][0] <= t:
            ad.ingest(data[k][1], data[k][2])
            k += 1
        c0 = time.perf_counter()
        st = ad.tick(t)
        tick_ms.append((time.perf_counter() - c0) * 1e3)
        timeline.append({"t_local_s": round(t, 3), "observability": st.observability,
                         "explanation": int(st.explanation), "suspects": list(st.suspects),
                         "ambiguous": list(st.ambiguous), "aggregate_trust": st.aggregate_trust,
                         "monitor_ok": st.monitor_ok, "evidence_mask": st.evidence_mask,
                         "failing": sorted(r for r, lv in st.lambdas.items()
                                           if isinstance(lv, float) and math.isfinite(lv) and lv > params.lam_fail),
                         "trust": {n: round(v, 4) for n, v in st.trust.items()}})
        t = round(t + 0.1, 6)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    tick_ms.sort()
    return {"ticks": len(timeline), "timeline": timeline, "csia_version": ad.csia_version,
            "tick_ms_mean": sum(tick_ms) / len(tick_ms), "tick_ms_p99": tick_ms[int(0.99 * (len(tick_ms) - 1))],
            "tick_ms_max": tick_ms[-1], "peak_traced_kib": peak / 1024, "samples": len(data)}
