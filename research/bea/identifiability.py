"""Identifiability of the target hypotheses (gate 1 of research/PROTOCOL.md).

Question: on one analysis window, with a given set of records, can the
evidence separate battery-current bias (HB), a relative timing error of the
electrical records (HT) and an increased opposing force (HL) from each other
and from normal operation with bounded nuisance (H0)?

Model. Each relationship gives a residual sampled on the window: the measured
quantity minus the nominal model. Under every hypothesis the residual is

    r = sum_j c_j x_j + s(delta) + e,      e ~ N(0, Sigma)

with linear parameters x (fault sizes and nuisance terms, each a known
signature column c_j), a timing shift delta that enters through the exact
shifted power s(delta)_k = P(t_k - delta) - P(t_k), and Gaussian noise.
A hypothesis is a set of bounds on (x, delta): H0 bounds every nuisance and
fixes every fault size at 0; a fault hypothesis frees its own parameter.

Separation. With h true at size theta and every nuisance at its nominal value,
the noise-free residual is r_h. Hypothesis g is rejected by a likelihood-ratio
test when the distance

    d(h -> g) = min over (x, delta) allowed by g of || L^-1 (r_h - C x - s(delta)) ||,   Sigma = L L^T

is large against the noise: d is the expected excess of g's fit statistic in
standard deviations. This module computes d exactly (bounded least squares
plus a one-dimensional search over delta); research/IDENTIFIABILITY.md gives
the conditions under which d is zero whatever the noise or sampling rate.

Everything here is synthetic: the vehicle and motor are the repository's
SYNTHETIC parameter sets, the noise levels are assumptions listed in Study,
and no number is a measurement.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable, Optional

import numpy as np

from models.vehicle.longitudinal import (G, SYNTHETIC_VEHICLE, VehicleParams, motor_torque_for_force,
                                         resistive_force, tractive_force)
from models.vehicle.powertrain import SYNTHETIC_MOTOR, MotorParams, SyntheticPhysicsMap

TRUTH_HZ = 1000
INF = math.inf
SEPARABLE_SIGMA = 4.0   # d >= 4: one-sided test at about 1 % false rejection keeps about 95 % power (study threshold only)

# Linear parameters, in column order. Faults: bus-current bias b [A], extra opposing force dF [N]. The rest
# are nuisance: grade [rad], along-track headwind [m/s], loss-model errors (constant P0 [W], winding
# resistance [ohm], iron-loss coefficient (relative), switching loss per phase ampere [W/A], motor friction
# torque [N m]), torque constant (relative), rolling resistance, drag area [m^2], effective mass (relative),
# bus-meter zero offset [A], IMU bias after mounting calibration [m/s^2]. Motor friction and the torque
# constant appear in both the power balance and the force balance: one parameter, two relationships.
PARAMS = ("b_A", "dF_N", "grade_rad", "wind_mps", "P0_W", "dRs_ohm", "dFe_rel", "dSw_W_per_A", "dTf_Nm", "dKt_rel",
          "dCrr", "dCdA_m2", "dmeff_rel", "Ioff_A", "imu_bias_mps2")
FAULTS = ("b_A", "dF_N")


@dataclasses.dataclass(frozen=True)
class Study:
    """Synthetic plant and sensor assumptions of the study (all [A] unless noted)."""
    vehicle: VehicleParams = SYNTHETIC_VEHICLE
    motor: MotorParams = SYNTHETIC_MOTOR
    v_oc_V: float = 48.0              # team-reported nominal pack voltage, used only as an operating point
    r_src_ohm: float = 0.10           # pack and wiring resistance
    torque_slew_Nm_s: float = 20.0    # torque rise rate at a pulse edge
    sigma_ibatt_A: float = 0.02       # bus-meter current noise per 10 ms sample
    sigma_vbus_V: float = 0.01
    sigma_iq_A: float = 0.01          # reported (filtered) iq; small enough that its sharing between blocks is neglected
    sigma_v_rotor_mps: float = 0.002  # rotor-speed noise as vehicle speed
    wheel_circ_m: float = 1.50        # provisional, as host/telematics/sensors.py
    wheel_ppr: int = 32               # provisional, as host/telematics/sensors.py
    wheel_window_s: float = 0.1       # [F] wheel counting window
    sigma_imu_mps2: float = 0.05      # per 100 Hz sample, as host/telematics/sensors.py
    imu_hz: float = 100.0
    guard_s: float = 0.02             # samples this close to a drive/coast change are not used

    @property
    def sigma_x_wheel_m(self) -> float:
        """Distance quantisation of the wheel counts: one count, uniform."""
        return self.wheel_circ_m / self.wheel_ppr / math.sqrt(12.0)


# Nuisance half-widths. "known": after a calibration run; "uncertain": nominal values only.
NUISANCE = {
    "known":     {"grade_rad": 0.001, "wind_mps": 1.0, "P0_W": 2.0, "dRs_ohm": 0.01, "dFe_rel": 0.10,
                  "dSw_W_per_A": 0.05, "dTf_Nm": 0.002, "dKt_rel": 0.02,
                  "dCrr": 0.0003, "dCdA_m2": 0.003, "dmeff_rel": 0.01, "Ioff_A": 0.005, "imu_bias_mps2": 0.005},
    "uncertain": {"grade_rad": 0.005, "wind_mps": 3.0, "P0_W": 6.0, "dRs_ohm": 0.03, "dFe_rel": 0.30,
                  "dSw_W_per_A": 0.15, "dTf_Nm": 0.005, "dKt_rel": 0.05,
                  "dCrr": 0.001, "dCdA_m2": 0.010, "dmeff_rel": 0.03, "Ioff_A": 0.03, "imu_bias_mps2": 0.05},
}
TIMING = {"known": 0.005, "uncertain": 0.10}   # |delta| allowed under H0 [s]
DELTA_RANGE_S = 0.5                           # search range for delta under HT

# Hypotheses as bound changes relative to H0. HL is one class; HL_grade (grade beyond its H0 bound) and
# HL_wind are its sub-causes, separated only where the evidence supports it.
HYPOTHESES = {
    "H0": {},
    "HB": {"b_A": (-INF, INF)},
    "HT": {"delta": (-DELTA_RANGE_S, DELTA_RANGE_S)},
    "HL": {"dF_N": (0.0, INF)},
    "HL_grade": {"grade_rad": (-INF, INF)},
    "HL_wind": {"wind_mps": (-INF, INF)},
}


# ----------------------------------------------------------------------------- truth trajectories
@dataclasses.dataclass
class Truth:
    kind: str
    t: np.ndarray
    v: np.ndarray
    a: np.ndarray
    drive: np.ndarray
    torque: np.ndarray       # shaft torque [N m]
    iq: np.ndarray
    w: np.ndarray            # rotor speed when coupled [rad/s]
    P: np.ndarray            # inverter-input power [W] (the bus meter's quantity)
    V: np.ndarray
    I: np.ndarray
    F_trac: np.ndarray
    F_res: np.ndarray
    m_eff: np.ndarray

    def at(self, x: np.ndarray, times: np.ndarray) -> np.ndarray:
        return np.interp(times, self.t, x)


def _schedules(st: Study) -> dict[str, tuple[float, float, Callable[[float, float], tuple[bool, float]]]]:
    veh = st.vehicle
    t_eq = lambda v: motor_torque_for_force(veh, resistive_force(veh, v))
    t_acc = lambda a: motor_torque_for_force(veh, veh.m_eff(True) * a)
    return {
        # name: (duration s, initial speed m/s, schedule(t, v) -> (drive, commanded shaft torque))
        "cruise": (20.0, 7.0, lambda t, v: (True, t_eq(7.0))),
        "ramp": (10.0, 3.0, lambda t, v: (True, t_eq(v) + t_acc(0.6))),
        "onset": (15.0, 3.0, lambda t, v: (True, t_eq(3.0) if t < 5.0 else t_eq(v) + t_acc(0.6))),
        "pulse_coast": (24.0, 7.0, lambda t, v: (True, t_eq(v) + t_acc(0.5)) if 4.0 <= t < 10.0 else (False, 0.0)),
        "coast": (20.0, 9.0, lambda t, v: (False, 0.0)),
        "sine": (20.0, 7.0, lambda t, v: (True, t_eq(7.0) * (1.0 + 0.8 * math.sin(2 * math.pi * t / 4.0)))),
    }


CONDITIONS = ("cruise", "ramp", "onset", "pulse_coast", "coast", "sine")


def simulate(kind: str, st: Study = Study()) -> Truth:
    """Fault-free truth at 1 kHz (faults enter the residuals additively, see module docstring)."""
    veh, mot = st.vehicle, st.motor
    T, v0, sched = _schedules(st)[kind]
    pmap = SyntheticPhysicsMap(veh, motor=mot, p_aux_W=0.0)   # auxiliaries are outside the bus meter (PROTOCOL.md section 4)
    n = int(round(T * TRUTH_HZ)) + 1
    dt = 1.0 / TRUTH_HZ
    t = np.arange(n) * dt
    v = np.empty(n)
    a = np.zeros(n)
    drive = np.zeros(n, bool)
    tq = np.zeros(n)
    v[0] = v0
    tq_prev = sched(0.0, v0)[1]
    for k in range(n):
        d, cmd = sched(t[k], v[k])
        step = st.torque_slew_Nm_s * dt
        tq_k = min(max(cmd, tq_prev - step), tq_prev + step) if d else 0.0
        tq_prev = tq_k
        drive[k], tq[k] = d, tq_k
        coupled = d or not veh.freewheel
        f = tractive_force(veh, tq_k) if d else 0.0
        a[k] = (f - resistive_force(veh, v[k], motor_coupled_unpowered=not d and not veh.freewheel)) / veh.m_eff(coupled)
        if k + 1 < n:
            v[k + 1] = v[k] + a[k] * dt
    w = np.where(drive, v * veh.gear_ratio / veh.wheel_radius_m, 0.0)
    iq = np.where(drive, (tq + np.where(w > 0, mot.friction_Nm, 0.0)) / mot.kt, 0.0)
    P = np.zeros(n)
    V = np.full(n, st.v_oc_V)
    for k in range(n):
        if drive[k]:
            p = pmap.p_batt(v[k], tq[k], st.v_oc_V, 25.0, "drive")
            vb = 0.5 * (st.v_oc_V + math.sqrt(st.v_oc_V ** 2 - 4.0 * st.r_src_ohm * p))
            P[k] = pmap.p_batt(v[k], tq[k], vb, 25.0, "drive")
            V[k] = 0.5 * (st.v_oc_V + math.sqrt(st.v_oc_V ** 2 - 4.0 * st.r_src_ohm * P[k]))
    I = P / V
    F_trac = np.array([tractive_force(veh, x) for x in tq]) * drive
    F_res = np.array([resistive_force(veh, x) for x in v])
    m_eff = np.where(drive | (not veh.freewheel), veh.m_eff(True), veh.m_eff(False))
    return Truth(kind, t, v, a, drive, tq, iq, w, P, V, I, F_trac, F_res, m_eff)


# ----------------------------------------------------------------------------- relationships on a window
@dataclasses.dataclass
class Block:
    """One relationship on one window: unit-signature columns, exact timing term and noise covariance."""
    name: str
    cols: dict[str, np.ndarray]
    shift: Optional[Callable[[float], np.ndarray]]
    cov: np.ndarray            # full covariance (diagonal or banded from differencing)
    times: np.ndarray

    @property
    def n(self) -> int:
        return len(self.times)


def _steady_mask(tr: Truth, times: np.ndarray, mode_drive: bool, guard: float, span: float = 0.0) -> np.ndarray:
    """True where [t - guard, t + span + guard] lies inside one mode."""
    ok = np.ones(len(times), bool)
    lo = np.searchsorted(tr.t, times - guard)
    hi = np.searchsorted(tr.t, times + span + guard, side="right")
    for i, (a, b) in enumerate(zip(lo, hi)):
        seg = tr.drive[max(a, 0):min(b, len(tr.t))]
        ok[i] = len(seg) > 0 and bool(np.all(seg == mode_drive))
    return ok




def _interval_mean(tr: Truth, x: np.ndarray, t0: np.ndarray, t1: np.ndarray) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(0.5 * (x[1:] + x[:-1]) / TRUTH_HZ)])
    return (np.interp(t1, tr.t, c) - np.interp(t0, tr.t, c)) / (t1 - t0)


def r1_power(tr: Truth, st: Study, fs: float, steady_only: bool = False) -> Optional[Block]:
    """R1: bus-meter power against the loss model driven by iq and rotor speed (drive samples)."""
    times = np.arange(0.0, tr.t[-1] + 1e-9, 1.0 / fs)
    keep = _steady_mask(tr, times, True, st.guard_s)
    if steady_only:
        dP = np.gradient(tr.P, 1.0 / TRUTH_HZ)
        keep &= np.abs(tr.at(dP, times)) < 5.0
    times = times[keep]
    if len(times) < 3:
        return None
    V, I, iq, w = (tr.at(x, times) for x in (tr.V, tr.I, tr.iq, tr.w))
    kt = st.motor.kt
    P_k = tr.at(tr.P, times)
    var = (V * st.sigma_ibatt_A) ** 2 + (I * st.sigma_vbus_V) ** 2 + (kt * w * st.sigma_iq_A) ** 2
    cols = {"b_A": V, "P0_W": np.ones_like(V), "dRs_ohm": 1.5 * iq ** 2,
            "dFe_rel": st.motor.k_iron_W_per_rad_s15 * w ** 1.5, "dSw_W_per_A": np.abs(iq), "dTf_Nm": w,
            "dKt_rel": kt * iq * w}
    return Block("R1", cols, lambda d: tr.at(tr.P, times - d) - P_k, np.diag(var), times)


def r3_coast_current(tr: Truth, st: Study, fs: float) -> Optional[Block]:
    """R3: bus-meter current during coast with the gates off, where the true inverter input is 0."""
    times = np.arange(0.0, tr.t[-1] + 1e-9, 1.0 / fs)
    times = times[_steady_mask(tr, times, False, st.guard_s)]
    if len(times) < 3:
        return None
    one = np.ones(len(times))
    return Block("R3", {"b_A": one, "Ioff_A": one}, lambda d: tr.at(tr.I, times - d),
                 np.diag(np.full(len(times), st.sigma_ibatt_A ** 2)), times)


def _force_cols(tr: Truth, st: Study, t0, t1, accel, m_eff, grade_coef) -> dict[str, np.ndarray]:
    veh = st.vehicle
    v_air = _interval_mean(tr, tr.v, t0, t1)
    v2 = _interval_mean(tr, tr.v ** 2, t0, t1)
    one = np.ones(len(t0))
    return {"dF_N": one, "grade_rad": grade_coef * one, "wind_mps": veh.rho_air * veh.cda_m2 * v_air,
            "dCrr": veh.mass_kg * G * one, "dCdA_m2": 0.5 * veh.rho_air * v2, "dmeff_rel": m_eff * accel}


def r2_torque_motion(tr: Truth, st: Study, fs: float, torque_source: str = "iq",
                     steady_only: bool = False) -> Optional[Block]:
    """R2: tractive force from iq against resistance plus inertia from rotor speed (drive intervals).

    torque_source="ibatt" is the dependency case: torque computed from the bus
    meter's power, so the bus-current bias enters this relationship too."""
    dt = 1.0 / fs
    t0 = np.arange(0.0, tr.t[-1] - dt + 1e-9, dt)
    keep = _steady_mask(tr, t0, True, st.guard_s, span=dt)
    if steady_only:     # 2 Hz snapshots give an interval's force only while the torque is steady
        dF = np.abs(np.gradient(tr.F_trac, 1.0 / TRUTH_HZ))
        c = np.concatenate([[0.0], np.cumsum(dF[1:] / TRUTH_HZ)])
        keep &= (np.interp(t0 + dt, tr.t, c) - np.interp(t0, tr.t, c)) < 0.5
    t0 = t0[keep]
    if len(t0) < 3:
        return None
    t1 = t0 + dt
    m = tr.at(tr.m_eff, t0)
    accel = (tr.at(tr.v, t1) - tr.at(tr.v, t0)) / dt
    cols = _force_cols(tr, st, t0, t1, accel, m, st.vehicle.mass_kg * G)
    f_trac = _interval_mean(tr, tr.F_trac, t0, t1)
    cols["dKt_rel"] = f_trac
    cols["dTf_Nm"] = np.full(len(t0), -tractive_force(st.vehicle, 1.0))   # more friction, less shaft torque
    if torque_source == "ibatt":
        veh = st.vehicle
        cols["b_A"] = veh.drivetrain_eff * _interval_mean(tr, tr.V, t0, t1) / np.maximum(
            _interval_mean(tr, tr.v, t0, t1), 0.5)
    elif torque_source != "iq":
        raise ValueError(torque_source)
    # Speed differencing: every interval shares its end speeds with its neighbours (banded covariance).
    # Contiguous runs only; a gap breaks the band.
    a_white = (tractive_force(st.vehicle, st.motor.kt * st.sigma_iq_A) / math.sqrt(max(1.0, 100.0 / fs))) ** 2
    cov = _blockwise_diff_cov(t0, dt, 1, m * st.sigma_v_rotor_mps / dt, a_white)
    return Block("R2", cols, None, cov, t0)


def r4_coast_decel(tr: Truth, st: Study, fs: float) -> Optional[Block]:
    """R4: coast deceleration from the wheel counts against resistance (coast intervals).

    At 10 Hz the speeds come from cumulative counts (second difference of a
    quantised distance); at lower rates from single 0.1 s count windows, as the
    live summary reports them."""
    if fs > 1.0 / st.wheel_window_s + 1e-9:
        return None                                   # the wheel counts exist only in 0.1 s windows
    dt = 1.0 / fs
    t0 = np.arange(0.0, tr.t[-1] - dt + 1e-9, dt)
    t0 = t0[_steady_mask(tr, t0, False, st.guard_s, span=dt)]
    if len(t0) < 3:
        return None
    t1 = t0 + dt
    m = tr.at(tr.m_eff, t0)
    accel = (tr.at(tr.v, t1) - tr.at(tr.v, t0)) / dt
    cols = _force_cols(tr, st, t0, t1, accel, m, st.vehicle.mass_kg * G)
    if abs(dt - st.wheel_window_s) < 1e-9:
        cov = _blockwise_diff_cov(t0, dt, 2, m * st.sigma_x_wheel_m / dt ** 2, np.zeros(len(t0)))
    else:
        sv = math.sqrt(2.0) * st.sigma_x_wheel_m / st.wheel_window_s
        cov = _blockwise_diff_cov(t0, dt, 1, m * sv / dt, np.zeros(len(t0)))
    return Block("R4", cols, None, cov, t0)


def r5_imu_force(tr: Truth, st: Study, fs: float) -> Optional[Block]:
    """R5: force balance with the IMU's specific force (a + g sin(grade)) in place of the wheel acceleration.

    Grade cancels except for the rotating-inertia share, so R5 sees the extra
    force but almost no grade. Needs the IMU records from the local log."""
    dt = 1.0 / fs
    t0 = np.arange(0.0, tr.t[-1] - dt + 1e-9, dt)
    t0 = t0[_steady_mask(tr, t0, True, st.guard_s, span=dt) | _steady_mask(tr, t0, False, st.guard_s, span=dt)]
    if len(t0) < 3:
        return None
    t1 = t0 + dt
    m = tr.at(tr.m_eff, t0)
    f_mean = _interval_mean(tr, tr.a, t0, t1)
    cols = _force_cols(tr, st, t0, t1, f_mean, m, (st.vehicle.mass_kg - m) * G)
    cols["dKt_rel"] = _interval_mean(tr, tr.F_trac, t0, t1)
    drive_frac = _interval_mean(tr, tr.drive.astype(float), t0, t1)
    cols["dTf_Nm"] = -tractive_force(st.vehicle, 1.0) * drive_frac
    cols["imu_bias_mps2"] = m
    n_avg = max(1.0, st.imu_hz * dt)
    var = (m * st.sigma_imu_mps2) ** 2 / n_avg
    return Block("R5", cols, None, np.diag(var), t0)


def _blockwise_diff_cov(t0: np.ndarray, dt: float, order: int, scale, white_var) -> np.ndarray:
    """Covariance of scale_k * (difference of order `order` of iid unit noise) plus white noise.

    Differences share samples with their neighbours inside a run of contiguous
    intervals; a gap in t0 starts a new, independent run."""
    n = len(t0)
    cov = np.diag(np.broadcast_to(np.asarray(white_var, float), (n,))).copy()
    scale = np.broadcast_to(np.asarray(scale, float), (n,))
    breaks = np.flatnonzero(np.diff(t0) > dt * 1.5) + 1
    for idx in np.split(np.arange(n), breaks):
        D = np.eye(len(idx) + order)
        for _ in range(order):
            D = D[1:] - D[:-1]
        S = np.diag(scale[idx])
        cov[np.ix_(idx, idx)] += S @ (D @ D.T) @ S
    return cov


# ----------------------------------------------------------------------------- evidence sets
EVIDENCE = {
    # name: (relationships with their rates, timing bound key, note)
    "summary_2Hz": ({"R1s": 2.0, "R2s": 2.0, "R3": 2.0, "R4": 2.0}, "the live 2 Hz summary (steady intervals only)"),
    "frames_100Hz": ({"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0}, "full-rate controller frames and wheel counts from the local log"),
    "frames_imu": ({"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0, "R5": 10.0}, "as frames_100Hz plus the IMU records"),
}


def build_window(tr: Truth, st: Study, rels: dict[str, float], torque_source: str = "iq") -> list[Block]:
    out = []
    for name, fs in rels.items():
        if name == "R1" and torque_source == "ibatt":
            continue                         # R1 would be circular: the torque already comes from the bus power
        b = {"R1": lambda: r1_power(tr, st, fs), "R1s": lambda: r1_power(tr, st, fs, steady_only=True),
             "R2": lambda: r2_torque_motion(tr, st, fs, torque_source),
             "R2s": lambda: r2_torque_motion(tr, st, fs, torque_source, steady_only=True), "R3": lambda: r3_coast_current(tr, st, fs),
             "R4": lambda: r4_coast_decel(tr, st, fs), "R5": lambda: r5_imu_force(tr, st, fs)}[name]()
        if b is not None:
            out.append(b)
    return out


@dataclasses.dataclass
class Whitened:
    """Stacked, whitened problem: columns C (n x p), timing term, parameter names."""
    C: np.ndarray
    names: list[str]
    shift: Callable[[float], np.ndarray]
    n: int
    blocks: list[str]


def _whitener(cov: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    if np.count_nonzero(cov - np.diag(np.diag(cov))) == 0:
        inv_sd = 1.0 / np.sqrt(np.diag(cov))
        return lambda x: x * inv_sd
    L = np.linalg.cholesky(cov)
    return lambda x: np.linalg.solve(L, x)


def whiten(blocks: list[Block]) -> Whitened:
    ws = [_whitener(b.cov) for b in blocks]
    C = np.column_stack([np.concatenate([w(b.cols.get(p, np.zeros(b.n))) for b, w in zip(blocks, ws)])
                         for p in PARAMS]) if blocks else np.zeros((0, len(PARAMS)))
    keep = [i for i in range(len(PARAMS)) if np.any(C[:, i] != 0)]
    with_shift = [(b, w) for b, w in zip(blocks, ws)]

    def shift(d: float) -> np.ndarray:
        return np.concatenate([w(b.shift(d)) if b.shift else np.zeros(b.n) for b, w in with_shift])

    return Whitened(C[:, keep], [PARAMS[i] for i in keep], shift, sum(b.n for b in blocks), [b.name for b in blocks])


# ----------------------------------------------------------------------------- bounded least squares
def bvls(A: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, max_iter: Optional[int] = None):
    """min ||A x - y||^2 subject to lo <= x <= hi (bounds may be infinite; lo == hi fixes a variable).

    Active-set method in the form of Stark and Parker's BVLS: solve on the free
    set, step back into the box when the solution leaves it, free the bound
    variable whose gradient points most into the box, stop at a KKT point. A
    freed variable whose solve does not lower the objective is blocked until
    the objective next decreases, which prevents cycling on collinear columns.
    Returns (x, ||A x - y||^2)."""
    n = A.shape[1]
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    if n == 0:
        return np.zeros(0), float(y @ y)
    # Unit-norm columns: the study's columns differ by five orders of magnitude.
    cn = np.linalg.norm(A, axis=0)
    cn[cn == 0] = 1.0
    xs, J = _bvls_scaled(A / cn, y, lo * cn, hi * cn, max_iter)
    return xs / cn, J


def _bvls_scaled(A, y, lo, hi, max_iter):
    n = A.shape[1]
    max_iter = max_iter or 20 * n + 20
    tol_g = 1e-10 * (1.0 + np.linalg.norm(A) * (1.0 + np.linalg.norm(y)))
    fixed = lo == hi
    obj = lambda z: float(np.sum((A @ z - y) ** 2))

    def settle(x, free):
        for _ in range(n + 1):
            if not free.any():
                break
            z = np.linalg.lstsq(A[:, free], y - A[:, ~free] @ x[~free], rcond=None)[0]
            xf, lf, hf = x[free], lo[free], hi[free]
            if np.all(z >= lf) and np.all(z <= hf):
                x[free] = z
                break
            step = z - xf
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(z < lf, (lf - xf) / step, np.where(z > hf, (hf - xf) / step, np.inf))
            alpha = float(np.clip(np.nanmin(r), 0.0, 1.0))
            x[free] = np.clip(xf + alpha * step, lf, hf)
            idx = np.flatnonzero(free)
            with np.errstate(invalid="ignore"):
                hit = (r <= alpha * (1 + 1e-9) + 1e-15) & np.isfinite(r)
            hit[int(np.nanargmin(r))] = True            # the variable that limited the step always stops at its bound
            k = idx[hit]
            x[k] = np.where(z[hit] < lf[hit], lo[k], hi[k])
            free[k] = False
        return x, free

    x = np.clip(np.zeros(n), lo, hi)
    x, free = settle(x, (x > lo) & (x < hi) & ~fixed)
    best = obj(x)
    blocked = np.zeros(n, bool)
    unblocked_once = False
    for _ in range(max_iter):
        g = A.T @ (y - A @ x)
        push = np.full(n, -np.inf)
        cand = ~free & ~blocked & ~fixed
        push[cand & (x <= lo)] = g[cand & (x <= lo)]
        push[cand & (x >= hi)] = -g[cand & (x >= hi)]
        j = int(np.argmax(push))
        if push[j] <= tol_g:
            if blocked.any():                        # a blocked variable may still violate KKT: retry it once more
                gb = np.where(~free & blocked & ~fixed & (x <= lo), g, np.where(~free & blocked & ~fixed & (x >= hi), -g, -np.inf))
                if np.max(gb) > tol_g and not unblocked_once:
                    blocked[:] = False
                    unblocked_once = True
                    continue
            return x, obj(x)
        f_try = free.copy()
        f_try[j] = True
        x_try, f_try = settle(x.copy(), f_try)
        cur = obj(x_try)
        if cur < best - 1e-13 * (1.0 + best):
            x, free, best = x_try, f_try, cur
            blocked[:] = False
            unblocked_once = False
        else:
            blocked[j] = True
    raise RuntimeError("bvls did not reach a KKT point")


# ----------------------------------------------------------------------------- hypothesis fits
def bounds_for(hyp: str, names: list[str], level: str) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    nb = NUISANCE[level]
    lo = np.array([0.0 if p in FAULTS else -nb[p] for p in names])
    hi = np.array([0.0 if p in FAULTS else nb[p] for p in names])
    dt0 = TIMING[level]
    delta = (-dt0, dt0)
    for p, (a, b) in HYPOTHESES[hyp].items():
        if p == "delta":
            delta = (a, b)
        elif p in names:
            i = names.index(p)
            lo[i], hi[i] = a, b
    return lo, hi, delta


def fit(W: Whitened, y: np.ndarray, hyp: str, level: str, n_grid: int = 41) -> tuple[float, dict]:
    """Smallest whitened squared residual of y under hypothesis hyp; returns (J, estimate)."""
    lo, hi, (d_lo, d_hi) = bounds_for(hyp, W.names, level)

    def J(d):
        x, j = bvls(W.C, y - W.shift(d), lo, hi)
        return j, x

    grid = np.unique(np.concatenate([np.linspace(d_lo, d_hi, n_grid if d_hi - d_lo > 0.05 else 5), [0.0]]))
    grid = grid[(grid >= d_lo) & (grid <= d_hi)]
    vals = [J(d)[0] for d in grid]
    i = int(np.argmin(vals))
    a, b = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = J(c)[0], J(d)[0]
    for _ in range(30):
        if b - a < 1e-5:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = J(c)[0]
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = J(d)[0]
    cands = [(vals[i], grid[i]), (fc, c), (fd, d)]
    jbest, dbest = min(cands)
    jx, x = J(dbest)
    return jx, {"delta_s": float(dbest), **{n: float(v) for n, v in zip(W.names, x)}}


def truth_residual(W: Whitened, hyp: str, size: float) -> np.ndarray:
    """Noise-free whitened residual with hypothesis hyp at the given size and every nuisance at 0."""
    if hyp == "H0":
        return np.zeros(W.n)
    if hyp == "HT":
        return W.shift(size)
    p = {"HB": "b_A", "HL": "dF_N", "HL_grade": "grade_rad", "HL_wind": "wind_mps"}[hyp]
    if p not in W.names:
        return np.zeros(W.n)
    return W.C[:, W.names.index(p)] * size


def separation(W: Whitened, h: str, size: float, g: str, level: str) -> float:
    """d(h -> g) in noise standard deviations."""
    j, _ = fit(W, truth_residual(W, h, size), g, level)
    return math.sqrt(max(j, 0.0))


COLLINEAR_REL = 1e-6   # d below this fraction of ||r_h|| is round-off: g reproduces h exactly


def is_collinear(W: Whitened, h: str, size: float, g: str, level: str) -> bool:
    """True when g reproduces h's residual exactly (to round-off), so no amount of data separates them."""
    norm = float(np.linalg.norm(truth_residual(W, h, size)))
    return norm == 0.0 or separation(W, h, size, g, level) <= COLLINEAR_REL * norm


def principal_cosine(W: Whitened, h: str, size: float, g: str, level: str) -> float:
    """cos of the angle between h's residual and the span of the columns g may use (bounds ignored).

    1 means h's signature lies inside what g can explain by direction alone; then
    only the nuisance bounds can separate them."""
    r = truth_residual(W, h, size)
    if not np.any(r):
        return float("nan")
    lo, hi, (d_lo, d_hi) = bounds_for(g, W.names, level)
    use = [i for i in range(len(W.names)) if lo[i] != hi[i]]
    M = W.C[:, use]
    if d_hi > d_lo:
        eps = 1e-3
        M = np.column_stack([M, (W.shift(eps) - W.shift(-eps)) / (2 * eps)]) if M.size else \
            ((W.shift(eps) - W.shift(-eps)) / (2 * eps))[:, None]
    if M.size == 0:
        return 0.0
    proj = M @ np.linalg.lstsq(M, r, rcond=None)[0]
    return float(np.linalg.norm(proj) / np.linalg.norm(r))


# ----------------------------------------------------------------------------- timing kinds
def _lag(tr: Truth, tau: float) -> np.ndarray:
    """First-order response of the measured power to the true power (a sensor or filter time constant)."""
    if tau <= 0:
        return tr.P.copy()
    a = 1.0 / (TRUTH_HZ * tau)
    y = np.empty_like(tr.P)
    y[0] = tr.P[0]
    for k in range(1, len(y)):
        y[k] = y[k - 1] + min(a, 1.0) * (tr.P[k] - y[k - 1])
    return y


def _boxcar(tr: Truth, width: float) -> np.ndarray:
    """Mean of the true power over the preceding `width` seconds (an averaging converter)."""
    n = max(1, int(round(width * TRUTH_HZ)))
    c = np.concatenate([[0.0], np.cumsum(tr.P)])
    k = np.arange(len(tr.P))
    lo = np.maximum(k + 1 - n, 0)
    return (c[k + 1] - c[lo]) / (k + 1 - lo)


TIMING_KINDS = {
    # name: (measured power as a function of the parameter, parameter grid for fitting it)
    "delay": (lambda tr, p: np.interp(tr.t - p, tr.t, tr.P), np.linspace(0.0, 0.2, 81)),
    "lag": (lambda tr, p: _lag(tr, p), np.linspace(0.0, 0.2, 81)),
    "boxcar": (lambda tr, p: _boxcar(tr, p), np.linspace(0.0, 0.4, 81)),
}


def timing_kind_distance(tr: Truth, st: Study, fs: float, true_kind: str, true_param: float, alt_kind: str,
                         level: str = "known") -> float:
    """d(true kind -> best member of the alternative kind) on R1 alone, with R1's loss-model nuisance.

    Shows whether a pure delay, a first-order response and an averaging window
    can be told apart from the electrical records at a given rate."""
    b = r1_power(tr, st, fs)
    if b is None:
        return float("nan")
    w = _whitener(b.cov)
    names = [p for p in PARAMS if p in b.cols and p not in FAULTS]
    C = np.column_stack([w(b.cols[p]) for p in names])
    nb = NUISANCE[level]
    lo, hi = np.array([-nb[p] for p in names]), np.array([nb[p] for p in names])
    P_k = tr.at(tr.P, b.times)
    meas = lambda kind, p: w(tr.at(TIMING_KINDS[kind][0](tr, p), b.times) - P_k)
    y = meas(true_kind, true_param)
    best = min(bvls(C, y - meas(alt_kind, p), lo, hi)[1] for p in TIMING_KINDS[alt_kind][1])
    return math.sqrt(max(best, 0.0))
