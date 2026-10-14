"""SYNTHETIC multi-sensor scenarios for the CSIA vehicle adapter.

Normal events that must NOT be reported as sensor faults: standing-start
traction slip of the driven wheel, freewheel decoupling while coasting,
cornering (front wheels differ by yaw x track), grade, GNSS degradation,
low-speed wheel-pulse quantisation, slow thermal drift of the current offset.
Faults are injected on top. Everything is invented test data.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from host.csia_adapter.adapter import AdapterParams, Sample

G = 9.80665


@dataclasses.dataclass
class Fault:
    kind: str           # wheel_l_dropout | rotor_stuck | gnss_offset | imu_bias | current_bias | dc_gain | repeat_rotor
    t0: float
    t1: float
    magnitude: float = 0.0


@dataclasses.dataclass
class Scenario:
    duration_s: float = 120.0
    seed: int = 7
    gnss_degraded: tuple = (60.0, 80.0)
    corners: tuple = ((20.0, 26.0, 25.0), (45.0, 50.0, 35.0), (95.0, 101.0, 25.0))  # (t0, t1, radius)
    grade_segments: tuple = ((30.0, 40.0, 0.01), (70.0, 78.0, -0.01))
    faults: tuple = ()
    gnss_available: bool = True
    imu_available: bool = True


def params() -> AdapterParams:
    return AdapterParams(wheel_radius_m=1.5 / (2 * math.pi), gear_ratio=10.0, track_width_m=0.5, freewheel=True,
                         kt_Nm_per_A=0.06)


def generate(scn: Scenario):
    """Yield (t, signal_name, Sample) in receive order, 100 Hz base rate."""
    rng = np.random.default_rng(scn.seed)
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
    kcl_drift = 0.0
    out = []

    def emit(t, name, value, sigma, clock, flags=None, src_dt=0.0, latency=0.002):
        seq[name] = (seq.get(name, -1) + 1) & 0xFFFF
        out.append((t + latency, name, Sample(value, sigma, t + src_dt, clock, t + latency, seq[name], 1, flags or {})))

    def fault(kind, t):
        return next((f for f in scn.faults if f.kind == kind and f.t0 <= t < f.t1), None)

    stuck_rotor = None
    n = int(scn.duration_s / dt)
    for i in range(n):
        t = i * dt
        grade = next((g for a, b, g in scn.grade_segments if a <= t < b), 0.0)
        R = next((r for a, b, r in scn.corners if a <= t < b), math.inf)
        # strategy: standing start at high current, then pulse-and-coast 5.5..7.5 m/s
        if t < 8.0:
            iq = 25.0
        else:
            if pulse and v >= 7.5:
                pulse = False
            elif not pulse and v <= 5.5:
                pulse = True
            iq = 15.0 if pulse else 0.0
        torque = p.kt_Nm_per_A * iq
        f_drive = torque * p.gear_ratio * 0.95 / p.wheel_radius_m
        f_res = 0.0025 * 100 * G + 0.5 * 1.2 * 0.035 * v * v + 100 * G * math.sin(grade) if v > 0 else 0.0
        a = (f_drive - f_res) / 101.0
        v = max(v + a * dt, 0.0)
        engaged = iq > 0.5
        slip = 0.12 * min(1.0, max(0.0, (3.5 - t) / 0.5)) if iq > 20 else 0.0  # start slip, fades 3.0-3.5 s
        # The rotor is geared to the DRIVEN wheel (so it slips with it); with the
        # freewheel open it spins down on its own friction.
        w_motor = v * (1 + slip) / k_rot if engaged else max(w_motor - (2.0 + 0.002 * w_motor) * dt * 10, 0.0)
        gz = v / R if math.isfinite(R) else 0.0
        v_l, v_r = v - gz * p.track_width_m / 2, v + gz * p.track_width_m / 2
        v_d = v * (1 + slip)
        dist_l += v_l * dt
        dist_r += v_r * dt
        dist_d += v_d * dt
        kcl_drift = 0.03 * math.sin(2 * math.pi * t / 120.0)  # slow thermal drift, within tolerance
        # ---- controller samples, 100 Hz (clock "controller") ----
        w_meas = w_motor * (1 + rng.normal(0, 0.003))
        f = fault("rotor_stuck", t)
        if f:
            stuck_rotor = w_meas if stuck_rotor is None else stuck_rotor
            w_meas = stuck_rotor
        if not fault("repeat_rotor", t):
            emit(t, "rotor", w_meas, 0.01 * abs(w_motor) + 2.0, "controller")
        iq_meas = iq + rng.normal(0, 0.1)
        kcl = kcl_drift + rng.normal(0, 0.05)
        fb = fault("current_bias", t)
        if fb:
            kcl += fb.magnitude
            iq_meas += fb.magnitude * 0.7
        emit(t, "iq", iq_meas, 0.15, "controller")
        slewing = (7.9 < t < 8.3) or any(abs(t - tt) < 0.25 for tt in ())
        emit(t, "iq_ref", iq, 0.0, "controller", {"saturated_or_slewing": slewing})
        emit(t, "kcl", kcl, 0.1, "controller", {"kcl_available": True})
        p_mech = torque * w_motor if engaged else 0.0
        p_dc = p_mech + 0.06 * abs(p_mech) + 3.0 + rng.normal(0, 1.0)
        fg = fault("dc_gain", t)
        if fg:
            p_dc *= fg.magnitude
        if i % 2 == 0:
            emit(t, "p_dc", p_dc, 1.0, "controller")
        # ---- IMU, 100 Hz (own clock with offset) ----
        if scn.imu_available:
            bias = fault("imu_bias", t)
            ax = a + G * math.sin(grade) + rng.normal(0, 0.05) + (bias.magnitude if bias else 0.0)
            emit(t, "imu_ax", ax, 0.08, "imu", src_dt=1.234)
            emit(t, "imu_gz", gz + rng.normal(0, 0.005), 0.01, "imu", src_dt=1.234)
        # ---- wheels: edge counts per 100 ms window ----
        if i % 10 == 0 and i > 0:
            q = C / (ppr * win)
            for key, dist in (("l", dist_l), ("r", dist_r), ("d", dist_d)):
                counts = math.floor(dist * ppr / C) - math.floor(last[key] * ppr / C)
                last[key] = dist
                name = {"l": "wheel_l", "r": "wheel_r", "d": "wheel_drive"}[key]
                if key == "l" and fault("wheel_l_dropout", t):
                    counts = 0
                emit(t, name, counts * q, q / math.sqrt(12) + 0.01 * v, "controller")
            emit(t, "grade", grade, 0.003, "map")
        # ---- GNSS 10 Hz ----
        if scn.gnss_available and i % 10 == 5:
            deg = scn.gnss_degraded[0] <= t < scn.gnss_degraded[1]
            sacc = 2.0 if deg else 0.08
            off = fault("gnss_offset", t)
            vg = v + rng.normal(0, 1.5 if deg else 0.05) + (off.magnitude if off else 0.0)
            emit(t, "gnss", vg, max(sacc, 0.08), "gnss", {"sacc": sacc, "num_sv": 4 if deg else 11}, src_dt=-0.08)
    out.sort(key=lambda x: x[0])
    return out


def run(adapter_factory, scn: Scenario):
    """Feed a scenario to an adapter and tick it at 10 Hz. Returns list of states."""
    ad = adapter_factory()
    states = []
    data = generate(scn)
    k = 0
    for j in range(1, int(scn.duration_s * 10)):
        t = j * 0.1
        while k < len(data) and data[k][0] <= t:
            _, name, s = data[k]
            ad.ingest(name, s)
            k += 1
        states.append(ad.tick(t))
    return states
