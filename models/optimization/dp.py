"""Offline spatial dynamic programming for minimum battery energy with a
finish-time constraint.

Problem (discretised in position s):
    minimise   sum_k E_batt,k
    subject to sum_k dt_k <= T_target = T_max - reserve
               0 <= v_k <= v_limit(s_k);  v_k = 0 at mandatory stops
               u_k in {coast (gates off), torque levels 0 < T_j <= T_max}
               |braking decel| <= a_brake (mechanical brakes; no energy recovered)
               longitudinal accel <= a_max (traction/comfort)
Lagrangian relaxation: J = E + lambda * t, with lambda found by bisection so
the time constraint is met. The result is optimal ONLY within this discretised
model (grid ds, dv, control set) and model parameters; grid convergence is
reported, not assumed.

Transition over one segment (length ds) at speed v_i under control u, using
the energy form of the dynamics with a midpoint predictor-corrector:
    v_{i+1}^2 = v_i^2 + 2 ds (F_drive(u) - F_res(v_mid)) / m_eff
    dt        = 2 ds / (v_i + v_{i+1})          (finite unless both are ~0)
    E         = P_batt(v_mid, u) * dt
Starts and near-zero speed: dt is only undefined when v_i + v_{i+1} == 0,
which is treated as infeasible (the vehicle cannot cross a segment at rest).
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from models.optimization.track import Track
from models.vehicle.longitudinal import VehicleParams, resistive_force_np, tractive_force
from models.vehicle.powertrain import PowerMap

INF = 1e30


@dataclasses.dataclass
class DPConfig:
    ds_m: float = 10.0
    dv_mps: float = 0.2
    n_torque: int = 10
    torque_max_Nm: float = 2.0
    v_bus: float = 46.0
    a_brake: float = 2.0
    a_max: float = 1.5
    t_max_s: float = 1000.0
    reserve_s: float = 30.0
    wind_mps: float = 0.0
    lambda_hi: float = 400.0       # upper bound for bisection [J/s]
    bisection_iters: int = 28


@dataclasses.dataclass
class DPResult:
    s: np.ndarray
    v: np.ndarray            # speed at nodes
    u_torque: np.ndarray     # per segment, motor torque [N*m] (0 with coast)
    u_coast: np.ndarray      # per segment, True = gate-off coast
    t: np.ndarray            # time at nodes
    energy_J: float
    time_s: float
    lam: float
    feasible: bool
    cfg: DPConfig
    label: str = "SYNTHETIC - optimal only within the discretised model"


class _PowerTable:
    """Tabulated P_batt(v, control) for vectorised DP."""

    def __init__(self, pmap: PowerMap, torques: np.ndarray, v_bus: float, v_max: float, dv: float = 0.02):
        self.v = np.arange(0.0, v_max + 2 * dv, dv)
        self.dv = dv
        coast = [pmap.p_batt(x, 0.0, v_bus, 25.0, "coast_gate_off") for x in self.v]
        rows = [coast, coast]  # row 0: coast, row 1: coast + mechanical brake (same electrical power)
        for T in torques:
            rows.append([pmap.p_batt(x, float(T), v_bus, 25.0, "drive") for x in self.v])
        self.p = np.array(rows)  # [n_controls, n_v]

    def __call__(self, v: np.ndarray) -> np.ndarray:
        """Return P for every control at speeds v -> shape [n_controls, len(v)]."""
        x = np.clip(v / self.dv, 0, len(self.v) - 1.000001)
        i = x.astype(int)
        f = x - i
        return self.p[:, i] * (1 - f) + self.p[:, i + 1] * f


def _setup(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig):
    s, grade, curv, vlim = track.sample(cfg.ds_m)
    v_top = float(min(track.v_max_global, vlim.max()))
    vg = np.arange(0.0, v_top + 0.5 * cfg.dv_mps, cfg.dv_mps)
    torques = np.linspace(cfg.torque_max_Nm / cfg.n_torque, cfg.torque_max_Nm, cfg.n_torque)
    ptab = _PowerTable(pmap, torques, cfg.v_bus, v_top + 1.0)
    stops = np.array([track.is_stop(x, cfg.ds_m) for x in s])
    return s, grade, curv, vlim, vg, torques, ptab, stops


def _transition(v, k, grade, curv, vlim, stops, torques, veh, cfg, ds):
    """Vectorised transitions from speeds v (shape [n]) for all controls.
    Returns v_next, dt, v_mid  each [n_controls, n] (inf/nan when infeasible)."""
    # control rows: 0 coast (gates off), 1 coast + brake, 2.. motor torque levels
    nU = len(torques) + 2
    f_drive = np.concatenate([[0.0, 0.0], [tractive_force(veh, T) for T in torques]])[:, None]
    coupled_coast = not veh.freewheel
    m_drive = veh.m_eff(coupled=True)
    m_coast = veh.m_eff(coupled=coupled_coast)
    m_eff = np.full((nU, 1), m_drive)
    m_eff[0:2, 0] = m_coast

    def fres(vv, _unused):
        out = np.empty(vv.shape)
        for r in range(nU):
            out[r] = resistive_force_np(veh, vv[r], grade[k], cfg.wind_mps, curv[k], r <= 1 and coupled_coast)
        return out

    v_b = np.broadcast_to(v[None, :], (nU, len(v)))
    v2_pred = v_b ** 2 + 2 * ds * (f_drive - fres(v_b, None)) / m_eff
    v_pred = np.sqrt(np.maximum(v2_pred, 0.0))
    v_mid = 0.5 * (v_b + v_pred)
    v2 = v_b ** 2 + 2 * ds * (f_drive - fres(v_mid, None)) / m_eff
    feasible = v2 > 0.0
    v_next = np.sqrt(np.maximum(v2, 0.0))
    # longitudinal acceleration limit (traction/comfort): cap the gain in speed
    v_next = np.minimum(v_next, np.sqrt(v_b ** 2 + 2 * cfg.a_max * ds))
    # mechanical braking to respect the next node's limit (bounded deceleration)
    limit = 0.0 if stops[k + 1] else vlim[k + 1]
    v_min_brake = np.sqrt(np.maximum(v_b ** 2 - 2 * cfg.a_brake * ds, 0.0))
    # voluntary brake control (row 1): brake down to the speed-grid point below
    # the coasting result (energy-free; models holding speed on a descent)
    v_next[1] = np.maximum(np.floor(v_next[1] / cfg.dv_mps + 1e-9) * cfg.dv_mps, v_min_brake[1])
    need_brake = v_next > limit
    v_next = np.where(need_brake, np.maximum(limit, v_min_brake), v_next)
    feasible &= v_next <= limit + 1e-9
    if stops[k + 1]:
        feasible &= v_next <= 1e-9
    v_mid = 0.5 * (v_b + v_next)
    denom = v_b + v_next
    dt = np.where(denom > 1e-9, 2 * ds / np.where(denom > 1e-9, denom, 1.0), np.inf)
    feasible &= np.isfinite(dt)
    return v_next, dt, v_mid, feasible


def _interp(Jn: np.ndarray, vg: np.ndarray, x: np.ndarray) -> np.ndarray:
    dv = vg[1] - vg[0]
    xi = x / dv
    i = np.clip(np.floor(xi).astype(int), 0, len(vg) - 2)
    f = np.clip(xi - i, 0.0, 1.0)
    a, b = Jn[i], Jn[i + 1]
    out = a * (1 - f) + b * f
    # if either neighbour is infeasible, use the feasible one only when x is on it
    out = np.where((a >= INF) | (b >= INF), np.where(f < 1e-9, a, np.where(f > 1 - 1e-9, b, INF)), out)
    out = np.where(x > vg[-1] + 1e-9, INF, out)
    return out


def _backward(lam, pre, veh, cfg):
    s, grade, curv, vlim, vg, torques, ptab, stops, trans = pre
    N = len(s) - 1
    J = np.zeros(len(vg))  # free final speed
    Js = [None] * (N + 1)
    Js[N] = J
    for k in range(N - 1, -1, -1):
        v_next, dt, v_mid, feas = trans[k]
        nC = len(torques) + 2
        P = ptab(v_mid.ravel()).reshape(nC, nC, -1)  # [control evaluated, control row of v_mid, n]
        # pick the diagonal: power for control r evaluated at v_mid[r]
        idx = np.arange(len(torques) + 2)
        Pd = P[idx, idx, :]
        dtf = np.where(feas, dt, 0.0)
        cost = Pd * dtf + lam * dtf + _interp(Js[k + 1], vg, v_next)
        cost = np.where(feas, cost, INF)
        Jk = cost.min(axis=0)
        if stops[k]:
            Jk = np.where(vg <= 1e-9, Jk, INF)
        Js[k] = np.minimum(Jk, INF)
    return Js


def _forward(lam, pre, Js, veh, cfg):
    s, grade, curv, vlim, vg, torques, ptab, stops, _trans = pre
    N = len(s) - 1
    v = np.zeros(N + 1)
    t = np.zeros(N + 1)
    uT = np.zeros(N)
    uC = np.zeros(N, bool)
    E = 0.0
    feasible = True
    for k in range(N):
        vn, dt, vm, feas = _transition(np.array([v[k]]), k, grade, curv, vlim, stops, torques, veh, cfg, cfg.ds_m)
        P = ptab(vm[:, 0])  # [ctrl, ctrl]
        Pd = np.diag(P)
        dtf = np.where(feas[:, 0], dt[:, 0], 0.0)
        cost = Pd * dtf + lam * dtf + _interp(Js[k + 1], vg, vn[:, 0])
        cost = np.where(feas[:, 0], cost, INF)
        r = int(np.argmin(cost))
        if cost[r] >= INF:
            feasible = False
            break
        v[k + 1] = vn[r, 0]
        t[k + 1] = t[k] + dt[r, 0]
        E += Pd[r] * dt[r, 0]
        uC[k] = r <= 1
        uT[k] = 0.0 if r <= 1 else torques[r - 2]
    return v, t, uT, uC, E, feasible


def precompute(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig):
    s, grade, curv, vlim, vg, torques, ptab, stops = _setup(track, veh, pmap, cfg)
    trans = [_transition(vg, k, grade, curv, vlim, stops, torques, veh, cfg, cfg.ds_m) for k in range(len(s) - 1)]
    return (s, grade, curv, vlim, vg, torques, ptab, stops, trans)


def solve_for_lambda(lam, pre, veh, cfg):
    Js = _backward(lam, pre, veh, cfg)
    return _forward(lam, pre, Js, veh, cfg)


def solve(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig) -> DPResult:
    pre = precompute(track, veh, pmap, cfg)
    t_target = cfg.t_max_s - cfg.reserve_s
    lo, hi = 0.0, cfg.lambda_hi
    best = None
    v, t, uT, uC, E, feas = solve_for_lambda(lo, pre, veh, cfg)
    if feas and t[-1] <= t_target:
        best = (lo, v, t, uT, uC, E, feas)
    else:
        for _ in range(cfg.bisection_iters):
            mid = 0.5 * (lo + hi)
            v, t, uT, uC, E, feas = solve_for_lambda(mid, pre, veh, cfg)
            if feas and t[-1] <= t_target:
                best = (mid, v, t, uT, uC, E, feas)
                hi = mid
            else:
                lo = mid
    if best is None:
        lam, (v, t, uT, uC, E, feas) = hi, solve_for_lambda(hi, pre, veh, cfg)
        return DPResult(pre[0], v, uT, uC, t, E, float(t[-1]), lam, False, cfg)
    lam, v, t, uT, uC, E, feas = best
    return DPResult(pre[0], v, uT, uC, t, E, float(t[-1]), lam, bool(feas and t[-1] <= t_target), cfg)


def export_schedule(res: DPResult, path, torque_bound_Nm: float, model_label: str) -> None:
    """Position-indexed, bounded torque/coast schedule (CSV with a metadata header)."""
    import pathlib
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        f.write(f"# SYNTHETIC schedule - {res.label}; model: {model_label}; ds={res.cfg.ds_m} m dv={res.cfg.dv_mps} "
                f"m/s; T_max={res.cfg.t_max_s} s reserve={res.cfg.reserve_s} s; torque bound {torque_bound_Nm} N*m; "
                f"energy {res.energy_J:.1f} J time {res.time_s:.1f} s\n")
        f.write("s_start_m,s_end_m,v_start_mps,v_end_mps,t_plan_s,mode,torque_Nm\n")
        for k in range(len(res.u_torque)):
            tq = min(float(res.u_torque[k]), torque_bound_Nm)
            f.write(f"{res.s[k]:.2f},{res.s[k+1]:.2f},{res.v[k]:.4f},{res.v[k+1]:.4f},{res.t[k]:.3f},"
                    f"{'coast' if res.u_coast[k] else 'drive'},{tq:.4f}\n")
