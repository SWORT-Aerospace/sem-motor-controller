"""Comparison monitors for evaluating CSIA's incremental value.

B1 SimpleChecks: freshness + range + NaN per signal (what any controller
   should do anyway).
B2 ResidualThreshold: conventional pairwise residuals with fixed thresholds
   and a debounce counter, WITHOUT regime gating or yaw/slip/freewheel
   awareness - the naive version of the same physics.
Both consume the same samples as the adapter and report alarms per tick.
"""
from __future__ import annotations

import math

from host.csia_adapter.adapter import AdapterParams, Sample, SignalTracker

RANGES = {"rotor": (-50.0, 2000.0), "wheel_l": (0.0, 30.0), "wheel_r": (0.0, 30.0), "wheel_drive": (0.0, 30.0),
          "gnss": (0.0, 30.0), "imu_ax": (-30.0, 30.0), "imu_gz": (-5.0, 5.0), "iq": (-100.0, 100.0),
          "iq_ref": (-100.0, 100.0), "kcl": (-10.0, 10.0), "p_dc": (-100.0, 5000.0), "grade": (-0.2, 0.2)}


class SimpleChecks:
    def __init__(self, p: AdapterParams):
        self.sig = {k: SignalTracker(w) for k, w in p.windows.items()}
        self.bad = set()

    def ingest(self, name, s: Sample):
        lo, hi = RANGES[name]
        if not (math.isfinite(s.value) and lo <= s.value <= hi):
            self.bad.add(name)
        self.sig[name].update(s)

    def tick(self, t):
        alarms = {n for n, tr in self.sig.items() if tr.last is not None and not tr.fresh(t) and n != "grade"}
        alarms |= self.bad
        self.bad = set()
        return sorted(alarms)


class ResidualThreshold:
    def __init__(self, p: AdapterParams, k_sigma: float = 3.0, debounce: int = 3):
        self.p, self.k, self.deb = p, k_sigma, debounce
        self.sig = {k: SignalTracker(w) for k, w in p.windows.items()}
        self.count = {}

    def ingest(self, name, s: Sample):
        self.sig[name].update(s)

    def tick(self, t):
        S, p = self.sig, self.p
        v = {k: S[k].value() for k in S}
        s = {k: S[k].sigma() for k in S}
        k_rot = p.wheel_radius_m / p.gear_ratio
        res = {
            "rotor_vs_wheel_drive": (v["rotor"] * k_rot - v["wheel_drive"], math.hypot(s["rotor"] * k_rot, s["wheel_drive"])),
            "wheel_l_vs_r": (v["wheel_l"] - v["wheel_r"], math.hypot(s["wheel_l"], s["wheel_r"])),
            "gnss_vs_wheel_l": (v["gnss"] - v["wheel_l"], math.hypot(0.1, s["wheel_l"])),
            "gnss_vs_wheel_drive": (v["gnss"] - v["wheel_drive"], math.hypot(0.1, s["wheel_drive"])),
            "kcl": (v["kcl"], 0.1),
            "power": (v["p_dc"] - (p.kt_Nm_per_A * v["iq"] * v["rotor"] + p.p_aux_W), 6.0),
        }
        alarms = []
        for name, (r, sig) in res.items():
            if not (math.isfinite(r) and math.isfinite(sig)):
                continue
            if abs(r) > self.k * sig:
                self.count[name] = self.count.get(name, 0) + 1
            else:
                self.count[name] = 0
            if self.count[name] >= self.deb:
                alarms.append(name)
        return alarms
