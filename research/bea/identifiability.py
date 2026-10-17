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
from typing import Callable

import numpy as np

from models.vehicle.longitudinal import G, motor_torque_for_force, resistive_force, tractive_force
from models.vehicle.powertrain import SyntheticPhysicsMap
from research.bea.relations import (DELTA_RANGE_S, FAULTS, HYPOTHESES, INF, NUISANCE, PARAMS, TIMING, Block,  # noqa: F401
                                    Signals, Study, Whitened, _whitener, bounds_for, build_window, bvls, fit,
                                    r1_power, whiten)

TRUTH_HZ = 1000
SEPARABLE_SIGMA = 4.0   # d >= 4: one-sided test at about 1 % false rejection keeps about 95 % power (study threshold only)
Truth = Signals


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


def simulate(kind: str, st: Study = Study()) -> Signals:
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
    x = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * dt)])
    edges = np.arange(0.0, t[-1] + 1e-9, st.wheel_window_s)
    wx = np.interp(edges, t, x)
    wheel_t, wheel_v = 0.5 * (edges[1:] + edges[:-1]), np.diff(wx) / st.wheel_window_s
    # The truth is nominal: the bus meter's power equals the model's, and the IMU reads the acceleration.
    return Signals(t, float(TRUTH_HZ), v, drive, iq, w, P, V, I, P.copy(), F_trac, F_res, m_eff, f_imu=a,
                   wheel_t=wheel_t, wheel_v=wheel_v, kind=kind)




# ----------------------------------------------------------------------------- evidence sets
EVIDENCE = {
    # name: (relationships with their rates, note)
    "summary_2Hz": ({"R1s": 2.0, "R2s": 2.0, "R3": 2.0, "R4": 2.0}, "the live 2 Hz summary (steady intervals only)"),
    "frames_100Hz": ({"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0}, "full-rate controller frames and wheel counts from the local log"),
    "frames_imu": ({"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0, "R5": 10.0}, "as frames_100Hz plus the IMU records"),
}


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


COLLINEAR_REL = 1e-5   # d below this fraction of ||r_h|| is round-off (the solver resolves about 1e-6): g reproduces h exactly


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
