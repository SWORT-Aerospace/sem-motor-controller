"""HELD-OUT synthetic evaluation set for the CSIA vehicle adapter.

The development scenarios (host/csia_adapter/synthetic.py: seed 7, one drive
profile, six faults at fixed onsets and magnitudes) were used to design and
tune the adapter. They are frozen (docs/csia/DEV_SET_FREEZE.md). This module
generates DIFFERENT scenarios, never used for tuning:

* unseen seeds (>= 1000) and randomised drive profiles: pulse bands and
  currents, standing starts after full stops, long coasts, hills of either
  sign, corners, GNSS degradation and GNSS outages;
* faults with randomised onset, duration and magnitude (including smaller
  magnitudes than the development set), slow drifts, dropouts and fault kinds
  absent from the development set.

The sensor models (rates, clocks, noise, quantisation) are the same as the
development generator, so the adapter's declared sigmas still describe them.
Everything is SYNTHETIC test data, not vehicle evidence.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from host.csia_adapter.adapter import Sample
from host.csia_adapter.synthetic import params

G = 9.80665

# kind -> (true node, magnitude range or None, is_drift)
FAULT_KINDS = {
    "wheel_l_dropout": ("wheel_l", None, False),        # in dev set (fixed onset)
    "wheel_r_dropout": ("wheel_r", None, False),        # unseen node
    "wheel_l_intermittent": ("wheel_l", (0.2, 0.5), False),  # probability of a zero window
    "rotor_stuck": ("rotor", None, False),               # in dev set
    "rotor_scale": ("rotor", (0.03, 0.12), False),       # |gain error|, sign random
    "rotor_dropout": ("rotor", None, False),             # samples stop arriving
    "gnss_offset": ("gnss", (0.4, 2.0), False),          # dev used 1.5
    "gnss_drift": ("gnss", (0.02, 0.10), True),          # m/s per s
    "imu_bias": ("imu", (0.2, 1.0), False),              # dev used 0.8
    "imu_drift": ("imu", (0.01, 0.05), True),            # m/s^2 per s
    "current_bias": ("phase_current", (0.3, 1.2), False),  # dev used 0.8
    "current_drift": ("phase_current", (0.02, 0.10), True),  # A per s on KCL
    "dc_gain": ("dc_meter", (0.10, 0.45), False),        # |gain error|, sign random; dev used +0.4
    "dc_drift": ("dc_meter", (0.005, 0.02), True),       # gain change per s
}


@dataclasses.dataclass
class EvalFault:
    kind: str
    t0: float
    t1: float
    magnitude: float = 0.0

    @property
    def node(self) -> str:
        return FAULT_KINDS[self.kind][0]


@dataclasses.dataclass
class EvalScenario:
    seed: int
    duration_s: float
    v_lo: float
    v_hi: float
    i_pulse: float
    i_start: float
    start_slip: float
    stops: tuple            # (t, decel, hold_s)
    long_coasts: tuple      # (t0, t1)
    hills: tuple            # (t0, t1, grade)
    corners: tuple          # (t0, t1, radius)
    gnss_degraded: tuple    # ((t0, t1), ...)
    gnss_outage: tuple      # ((t0, t1), ...)
    fault: EvalFault | None = None


def make_scenario(seed: int, duration_s: float, fault_kind: str | None) -> EvalScenario:
    rng = np.random.default_rng(seed)
    v_lo = float(rng.uniform(4.5, 6.0))
    v_hi = v_lo + float(rng.uniform(1.0, 3.0))
    n_stop = int(rng.integers(0, 3))
    stops = tuple(sorted((float(rng.uniform(40, duration_s - 40)), float(rng.uniform(0.8, 1.5)),
                          float(rng.uniform(2.0, 6.0))) for _ in range(n_stop)))
    coasts = []
    for _ in range(int(rng.integers(0, 3))):
        a = float(rng.uniform(20, duration_s - 70))
        coasts.append((a, a + float(rng.uniform(25, 60))))
    hills = []
    for _ in range(int(rng.integers(1, 4))):
        a = float(rng.uniform(10, duration_s - 30))
        hills.append((a, a + float(rng.uniform(8, 30)), float(rng.uniform(-0.025, 0.025))))
    corners = []
    for _ in range(int(rng.integers(2, 6))):
        a = float(rng.uniform(10, duration_s - 10))
        corners.append((a, a + float(rng.uniform(3, 8)), float(rng.uniform(20, 60))))
    deg = []
    for _ in range(int(rng.integers(0, 3))):
        a = float(rng.uniform(10, duration_s - 30))
        deg.append((a, a + float(rng.uniform(5, 25))))
    out = []
    if rng.random() < 0.3:
        a = float(rng.uniform(10, duration_s - 20))
        out.append((a, a + float(rng.uniform(3, 10))))
    fault = None
    if fault_kind:
        node, mag, _drift = FAULT_KINDS[fault_kind]
        t0 = float(rng.uniform(30, duration_s - 90))
        t1 = t0 + float(rng.uniform(20, 60))
        m = float(rng.uniform(*mag)) if mag else 0.0
        if fault_kind in ("rotor_scale", "dc_gain"):
            m = 1.0 + (m if rng.random() < 0.5 else -m)
        fault = EvalFault(fault_kind, t0, t1, m)
    return EvalScenario(seed, duration_s, v_lo, v_hi, float(rng.uniform(10, 20)), float(rng.uniform(20, 30)),
                        float(rng.uniform(0.05, 0.15)), stops, tuple(coasts), tuple(hills), tuple(corners),
                        tuple(deg), tuple(out), fault)


def build_eval_set(n_nominal: int = 24, n_per_fault: int = 5, nominal_s: float = 300.0, fault_s: float = 240.0):
    """Deterministic list of held-out scenarios. Seeds start at 1000 (the
    development set used seed 7 only)."""
    scns = [make_scenario(1000 + i, nominal_s, None) for i in range(n_nominal)]
    seed = 2000
    for kind in FAULT_KINDS:
        for _ in range(n_per_fault):
            scns.append(make_scenario(seed, fault_s, kind))
            seed += 1
    return scns


def generate(scn: EvalScenario):
    """Yield (rx_time, signal, Sample) sorted by receive time. Same sensor
    models as host/csia_adapter/synthetic.py::generate."""
    rng = np.random.default_rng(scn.seed + 7919)
    p = params()
    dt = 0.01
    k_rot = p.wheel_radius_m / p.gear_ratio
    C = 2 * math.pi * p.wheel_radius_m
    ppr, win = 32, 0.1
    v = 0.0
    w_motor = 0.0
    dist_l = dist_r = dist_d = 0.0
    last = {"l": 0.0, "r": 0.0, "d": 0.0}
    seq = {}
    pulse = True
    out = []
    f = scn.fault
    stuck_rotor = None
    start_t = 0.0          # time of the current standing start
    mode = "start"         # start | cruise | brake | hold
    hold_until = 0.0
    brake_decel = 1.0
    pending_stops = list(scn.stops)

    def emit(t, name, value, sigma, clock, flags=None, src_dt=0.0, latency=0.002):
        seq[name] = (seq.get(name, -1) + 1) & 0xFFFF
        out.append((t + latency, name, Sample(value, sigma, t + src_dt, clock, t + latency, seq[name], 1, flags or {})))

    def active(t):
        return f is not None and f.t0 <= t < f.t1

    def ramp(t):
        return (t - f.t0) * f.magnitude if active(t) else 0.0

    n = int(scn.duration_s / dt)
    for i in range(n):
        t = i * dt
        grade = next((g for a, b, g in scn.hills if a <= t < b), 0.0)
        R = next((r for a, b, r in scn.corners if a <= t < b), math.inf)
        # ---- drive profile
        if mode in ("start", "cruise") and pending_stops and t >= pending_stops[0][0]:
            _, brake_decel, hold = pending_stops.pop(0)
            mode, hold_until = "brake", math.inf
            hold_s = hold
        if mode == "brake" and v <= 0.0:
            mode, hold_until = "hold", t + hold_s
        if mode == "hold" and t >= hold_until:
            mode, start_t = "start", t
        if mode == "start" and t - start_t >= 8.0:
            mode = "cruise"
        coast_forced = any(a <= t < b for a, b in scn.long_coasts)
        if mode == "start":
            iq = scn.i_start
        elif mode in ("brake", "hold"):
            iq = 0.0
        else:
            if pulse and v >= scn.v_hi:
                pulse = False
            elif not pulse and v <= scn.v_lo:
                pulse = True
            iq = scn.i_pulse if (pulse and not coast_forced) else 0.0
        torque = p.kt_Nm_per_A * iq
        f_drive = torque * p.gear_ratio * 0.95 / p.wheel_radius_m
        f_res = 0.0025 * 100 * G + 0.5 * 1.2 * 0.035 * v * v + 100 * G * math.sin(grade) if v > 0 else 0.0
        f_brake = 101.0 * brake_decel if mode == "brake" and v > 0 else 0.0
        a = (f_drive - f_res - f_brake) / 101.0
        if mode == "hold":
            a = 0.0
        v = max(v + a * dt, 0.0)
        engaged = iq > 0.5
        ts = t - start_t
        slip = scn.start_slip * min(1.0, max(0.0, (3.5 - ts) / 0.5)) if (mode == "start" and iq > 20) else 0.0
        w_motor = v * (1 + slip) / k_rot if engaged else max(w_motor - (2.0 + 0.002 * w_motor) * dt * 10, 0.0)
        gz = v / R if math.isfinite(R) else 0.0
        v_l, v_r = v - gz * p.track_width_m / 2, v + gz * p.track_width_m / 2
        v_d = v * (1 + slip)
        dist_l += v_l * dt
        dist_r += v_r * dt
        dist_d += v_d * dt
        kcl_drift = 0.03 * math.sin(2 * math.pi * t / 120.0)
        # ---- controller samples, 100 Hz
        w_meas = w_motor * (1 + rng.normal(0, 0.003))
        if active(t) and f.kind == "rotor_stuck":
            stuck_rotor = w_meas if stuck_rotor is None else stuck_rotor
            w_meas = stuck_rotor
        if active(t) and f.kind == "rotor_scale":
            w_meas *= f.magnitude
        if not (active(t) and f.kind == "rotor_dropout"):
            emit(t, "rotor", w_meas, 0.01 * abs(w_motor) + 2.0, "controller")
        iq_meas = iq + rng.normal(0, 0.1)
        kcl = kcl_drift + rng.normal(0, 0.05)
        if active(t) and f.kind == "current_bias":
            kcl += f.magnitude
            iq_meas += f.magnitude * 0.7
        if active(t) and f.kind == "current_drift":
            kcl += ramp(t)
            iq_meas += 0.7 * ramp(t)
        emit(t, "iq", iq_meas, 0.15, "controller")
        slewing = mode == "start" and ts < 0.3 or (mode == "cruise" and 7.9 < ts < 8.3)
        emit(t, "iq_ref", iq, 0.0, "controller", {"saturated_or_slewing": slewing})
        emit(t, "kcl", kcl, 0.1, "controller", {"kcl_available": True})
        p_mech = torque * w_motor if engaged else 0.0
        p_dc = p_mech + 0.06 * abs(p_mech) + 3.0 + rng.normal(0, 1.0)
        if active(t) and f.kind == "dc_gain":
            p_dc *= f.magnitude
        if active(t) and f.kind == "dc_drift":
            p_dc *= 1.0 + ramp(t)
        if i % 2 == 0:
            emit(t, "p_dc", p_dc, 1.0, "controller")
        # ---- IMU 100 Hz
        ax = a + G * math.sin(grade) + rng.normal(0, 0.05)
        if active(t) and f.kind == "imu_bias":
            ax += f.magnitude
        if active(t) and f.kind == "imu_drift":
            ax += ramp(t)
        emit(t, "imu_ax", ax, 0.08, "imu", src_dt=1.234)
        emit(t, "imu_gz", gz + rng.normal(0, 0.005), 0.01, "imu", src_dt=1.234)
        # ---- wheels, 10 Hz edge-count windows
        if i % 10 == 0 and i > 0:
            q = C / (ppr * win)
            for key, dist in (("l", dist_l), ("r", dist_r), ("d", dist_d)):
                counts = math.floor(dist * ppr / C) - math.floor(last[key] * ppr / C)
                last[key] = dist
                name = {"l": "wheel_l", "r": "wheel_r", "d": "wheel_drive"}[key]
                if active(t) and ((key == "l" and f.kind == "wheel_l_dropout") or
                                  (key == "r" and f.kind == "wheel_r_dropout") or
                                  (key == "l" and f.kind == "wheel_l_intermittent" and rng.random() < f.magnitude)):
                    counts = 0
                emit(t, name, counts * q, q / math.sqrt(12) + 0.01 * v, "controller")
            emit(t, "grade", grade, 0.003, "map")
        # ---- GNSS 10 Hz
        if i % 10 == 5 and not any(a0 <= t < b0 for a0, b0 in scn.gnss_outage):
            deg = any(a0 <= t < b0 for a0, b0 in scn.gnss_degraded)
            sacc = 2.0 if deg else 0.08
            vg = v + rng.normal(0, 1.5 if deg else 0.05)
            if active(t) and f.kind == "gnss_offset":
                vg += f.magnitude
            if active(t) and f.kind == "gnss_drift":
                vg += ramp(t)
            emit(t, "gnss", vg, max(sacc, 0.08), "gnss", {"sacc": sacc, "num_sv": 4 if deg else 11}, src_dt=-0.08)
    out.sort(key=lambda x: x[0])
    return out
