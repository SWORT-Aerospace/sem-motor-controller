"""Strategy evaluation on a common forward simulator (SYNTHETIC models).

All strategies are executed by the SAME time-domain simulator, which applies
the controller's torque slew limits, a traction/comfort acceleration cap and
mechanical braking to a precomputed braking envelope for corner limits. This
is how strategies are compared at matched finish time; the DP's internal
(spatially discretised) energy is not used for comparison.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable

import numpy as np

from models.optimization.track import Track
from models.vehicle.longitudinal import VehicleParams, resistive_force, tractive_force
from models.vehicle.powertrain import PowerMap

Controller = Callable[[float, float, float], tuple[float, bool]]  # (s, v, t) -> (torque_cmd, coast)


@dataclasses.dataclass
class SimConfig:
    dt: float = 0.05
    v_bus: float = 46.0
    torque_max_Nm: float = 2.0
    slew_up_Nm_s: float = 5.0
    slew_down_Nm_s: float = 10.0
    a_max: float = 1.5
    a_brake: float = 2.0
    wind_mps: float = 0.0
    t_limit_s: float = 3000.0


@dataclasses.dataclass
class SimResult:
    energy_J: float
    time_s: float
    finished: bool
    n_accel_events: int
    brake_energy_J: float
    trace: dict

    @property
    def km_per_kWh(self) -> float:
        return float("nan")


def braking_envelope(track: Track, a_brake: float, ds: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    s = np.arange(0.0, track.length_m + ds, ds)
    vl = np.array([track.v_limit(x) for x in s])
    env = vl.copy()
    for i in range(len(s) - 2, -1, -1):
        env[i] = min(vl[i], math.sqrt(env[i + 1] ** 2 + 2 * a_brake * ds))
    return s, env


def simulate(track: Track, veh: VehicleParams, pmap: PowerMap, ctrl: Controller, cfg: SimConfig,
             record: bool = False) -> SimResult:
    s_env, v_env = braking_envelope(track, cfg.a_brake)
    s = v = t = E = E_brake = 0.0
    torque = 0.0
    accel_events = 0
    driving_prev = False
    tr = {"t": [], "s": [], "v": [], "torque": [], "p": []} if record else {}
    m_drive = veh.m_eff(coupled=True)
    m_coast = veh.m_eff(coupled=not veh.freewheel)
    while s < track.length_m and t < cfg.t_limit_s:
        T_cmd, coast = ctrl(s, v, t)
        T_cmd = min(max(T_cmd, 0.0), cfg.torque_max_Nm) if not coast else 0.0
        if T_cmd > torque:
            torque = min(T_cmd, torque + cfg.slew_up_Nm_s * cfg.dt)
        else:
            torque = max(T_cmd, torque - cfg.slew_down_Nm_s * cfg.dt)
        mode = "coast_gate_off" if (coast and torque == 0.0) else "drive"
        driving = torque > 0.0
        if driving and not driving_prev:
            accel_events += 1
        driving_prev = driving
        g, kappa = track.grade(s), track.curvature(s)
        f_res = resistive_force(veh, v, g, cfg.wind_mps, kappa, motor_coupled_unpowered=(mode != "drive") and not veh.freewheel)
        m_eff = m_drive if mode == "drive" else m_coast
        a = (tractive_force(veh, torque) - f_res) / m_eff
        a = min(a, cfg.a_max)
        v_new = max(v + a * cfg.dt, 0.0)
        s_new = s + 0.5 * (v + v_new) * cfg.dt
        v_cap = float(np.interp(s_new, s_env, v_env))
        if v_new > v_cap:
            E_brake += 0.5 * m_eff * (v_new ** 2 - v_cap ** 2)
            v_new = v_cap
            s_new = s + 0.5 * (v + v_new) * cfg.dt
        v_mid = 0.5 * (v + v_new)
        p = pmap.p_batt(v_mid, torque, cfg.v_bus, 25.0, mode)
        E += p * cfg.dt
        if record:
            tr["t"].append(t); tr["s"].append(s); tr["v"].append(v); tr["torque"].append(torque); tr["p"].append(p)
        s, v, t = s_new, v_new, t + cfg.dt
        if v == 0.0 and torque == 0.0 and T_cmd == 0.0 and s < track.length_m and t > 1.0:
            break  # stopped short of the finish
    return SimResult(E, t, s >= track.length_m, accel_events, E_brake, {k: np.array(x) for k, x in tr.items()})


# ----------------------------------------------------------------- controllers
def constant_speed(v_set: float, veh: VehicleParams, kp: float = 2.0) -> Controller:
    def c(s, v, t):
        f_ff = resistive_force(veh, v_set) / max(veh.drivetrain_eff, 1e-6)
        t_ff = f_ff * veh.wheel_radius_m / veh.gear_ratio
        T = t_ff + kp * (v_set - v)
        return (max(T, 0.0), T <= 0.0)
    return c


def pulse_and_coast(v_lo: float, v_hi: float, torque_Nm: float) -> Controller:
    state = {"pulse": True}

    def c(s, v, t):
        if state["pulse"] and v >= v_hi:
            state["pulse"] = False
        elif not state["pulse"] and v <= v_lo:
            state["pulse"] = True
        return (torque_Nm, False) if state["pulse"] else (0.0, True)
    return c


@dataclasses.dataclass
class PaceCorrector:
    """Bounded pace correction: delta_T = clip(k * (t - t_plan(s)), -bound, +bound).
    Positive when behind schedule. The corrected command is clipped to
    [0, torque_max]. No other online adaptation is performed."""
    k_Nm_per_s: float = 0.05
    bound_Nm: float = 0.3

    def delta(self, t: float, t_plan: float) -> float:
        return max(-self.bound_Nm, min(self.bound_Nm, self.k_Nm_per_s * (t - t_plan)))


def schedule_follower(s_nodes: np.ndarray, torque: np.ndarray, coast: np.ndarray, t_plan: np.ndarray,
                      torque_max: float, pace: PaceCorrector | None = None) -> Controller:
    def c(s, v, t):
        k = min(int(np.searchsorted(s_nodes, s, side="right") - 1), len(torque) - 1)
        k = max(k, 0)
        T, cst = float(torque[k]), bool(coast[k])
        if pace is not None:
            tp = float(np.interp(s, s_nodes, t_plan))
            d = pace.delta(t, tp)
            if cst and d > 0:
                cst, T = False, 0.0
            T = min(max(T + d, 0.0), torque_max)
            if T == 0.0 and d <= 0:
                cst = True
        return (T, cst)
    return c


def bisect_param(f_time: Callable[[float], float], lo: float, hi: float, t_target: float, iters: int = 30) -> float:
    """Find x in [lo, hi] with f_time(x) <= t_target, minimal x-effort (time decreasing in x)."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if f_time(mid) <= t_target:
            hi = mid
        else:
            lo = mid
    return hi
