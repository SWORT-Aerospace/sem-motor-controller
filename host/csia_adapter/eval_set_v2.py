"""Synthetic scenario generator v2 for the CSIA v2 evaluation (SYNTHETIC test data).

Starts from the v1 held-out generator (eval_set.py, frozen) and changes the
two things the host end-to-end demonstration showed v1 could not test:

1. DC power physics. v1 generated p_dc = p_mech + 6 % |p_mech| + 3 W, the same
   form the v1 adapter assumes. v2 generates
       p_dc = p_mech + 1.5 R(T) iq^2 + k_sw |iq| + P_fixed + noise
   with, per scenario, R0 within +/-10 % of 0.10 ohm, R(T) following a
   first-order winding-temperature model (tau 240-480 s, 0.393 %/K), k_sw in
   0.05-0.15 W/A and P_fixed in 2-5 W. p_dc is sent at 10 Hz, the ctrl_energy
   rate of protocol 1.1 (v1 used 50 Hz).
2. Current profile. Part of each cruise is a speed hold: a proportional
   controller with filtered command noise, so iq varies between p_dc samples,
   as with the host supervisor's speed-hold policy. The rest is v1's
   pulse-and-glide.

Scenario structure, faults, sensors, clocks and noise are otherwise v1's.
The adapter's E6 calibration is fitted on development seeds only; evaluation
seeds are generated only after docs/csia/V2_FREEZE.json is committed.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from host.csia_adapter.adapter import Sample
from host.csia_adapter.eval_set import FAULT_KINDS, EvalScenario, make_scenario
from host.csia_adapter.synthetic import params

G = 9.80665
DEV_NOMINAL_SEEDS = tuple(range(3000, 3008))      # 8 x 300 s
DEV_FAULT_SEED0 = 3100                            # 14 kinds x 2
EVAL_NOMINAL_SEEDS = tuple(range(6000, 6024))     # 24 x 300 s, generated only after the freeze
EVAL_FAULT_SEED0 = 7000                           # 14 kinds x 5


@dataclasses.dataclass
class ScenarioV2(EvalScenario):
    hold_segments: tuple = ()     # (t0, t1, v_set)
    R0_ohm: float = 0.10
    tau_th_s: float = 360.0
    k_sw_W_per_A: float = 0.1
    p_fixed_W: float = 3.0


def make_scenario_v2(seed: int, duration_s: float, fault_kind: str | None) -> ScenarioV2:
    base = make_scenario(seed, duration_s, fault_kind)
    rng = np.random.default_rng(seed + 104729)
    holds = []
    t = float(rng.uniform(15, 40))
    while t < duration_s - 20:
        t1 = min(t + float(rng.uniform(20, 50)), duration_s - 5)
        holds.append((t, t1, float(rng.uniform(base.v_lo, base.v_hi))))
        t = t1 + float(rng.uniform(20, 50))
    return ScenarioV2(**dataclasses.asdict(base) | {"fault": base.fault}, hold_segments=tuple(holds),
                      R0_ohm=float(0.10 * rng.uniform(0.9, 1.1)), tau_th_s=float(rng.uniform(240, 480)),
                      k_sw_W_per_A=float(rng.uniform(0.05, 0.15)), p_fixed_W=float(rng.uniform(2.0, 5.0)))


def dev_set():
    scns = [make_scenario_v2(s, 300.0, None) for s in DEV_NOMINAL_SEEDS]
    seed = DEV_FAULT_SEED0
    for kind in FAULT_KINDS:
        for _ in range(2):
            scns.append(make_scenario_v2(seed, 240.0, kind))
            seed += 1
    return scns


def eval_set():
    scns = [make_scenario_v2(s, 300.0, None) for s in EVAL_NOMINAL_SEEDS]
    seed = EVAL_FAULT_SEED0
    for kind in FAULT_KINDS:
        for _ in range(5):
            scns.append(make_scenario_v2(seed, 240.0, kind))
            seed += 1
    return scns


def generate(scn: ScenarioV2):
    """(rx_time, signal, Sample) sorted by receive time."""
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
    start_t = 0.0
    mode = "start"
    hold_until = 0.0
    brake_decel = 1.0
    hold_s = 0.0
    pending_stops = list(scn.stops)
    T_w = 25.0                      # winding temperature, degC
    k_heat = 30.0 / (1.5 * scn.R0_ohm * 15.0 ** 2)   # 30 K rise at 15 A continuous
    noise_f = 0.0

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
        seg = next((h for h in scn.hold_segments if h[0] <= t < h[1]), None)
        noise_f += (rng.normal(0.0, 1.5) - noise_f) * dt / 0.2      # 0.8 Hz filtered command noise
        if mode == "start":
            iq = scn.i_start
        elif mode in ("brake", "hold"):
            iq = 0.0
        elif seg is not None and not coast_forced:
            iq = min(max(8.0 * (seg[2] - v) + 4.0 + noise_f, 0.0), 30.0)   # speed hold
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
        R_w = scn.R0_ohm * (1.0 + 0.00393 * (T_w - 25.0))
        T_w += dt * (k_heat * 1.5 * R_w * iq * iq - (T_w - 25.0)) / scn.tau_th_s
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
        p_dc = p_mech + 1.5 * R_w * iq * iq + scn.k_sw_W_per_A * abs(iq) + scn.p_fixed_W + rng.normal(0, 1.0)
        if active(t) and f.kind == "dc_gain":
            p_dc *= f.magnitude
        if active(t) and f.kind == "dc_drift":
            p_dc *= 1.0 + ramp(t)
        if i % 10 == 3:
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
