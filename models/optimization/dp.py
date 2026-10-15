"""Offline spatial dynamic programming for minimum battery-terminal energy with
a finish-time constraint and an EXPLICIT actuator model.

Actuators (one per segment; never mixed within a segment):
    COAST         motor gates off, no brake. Electrical power = auxiliary only.
    PROPEL(T)     motor torque T > 0 (controller-commanded), no brake.
    DRIVER_BRAKE  friction brake applied by the DRIVER at a nominal deceleration
                  level, motor gates off. The controller cannot command it: a
                  plan that uses it is driver GUIDANCE (export_guidance) with
                  stated reaction and tracking assumptions.
Policies:
    "propulsion_coast_brake"  all three (first vehicle version: braking = guidance)
    "propulsion_coast"        torque-only, no braking of any kind (no hidden
                              assistance): corner limits and stops must be met by
                              coasting alone, or the problem is reported infeasible.

Problem (discretised in position s):
    minimise   sum_k E_batt,k                  (battery terminal energy, see
                                                docs/ENERGY_ACCOUNTING.md)
    subject to sum_k dt_k <= T_target = T_max - reserve
               0 <= v_k <= v_limit(s_k)        (violations are infeasible; nothing
                                                brakes implicitly)
               v_k = 0 at mandatory stops       (vehicle at rest within
                                                stop_zone_m before the stop line)
               (F_drive - F_res)/m <= a_max     (a torque level that would exceed
                                                it is infeasible; the energy charged
                                                is always that of the torque applied)
Lagrangian relaxation J = E + lambda * t; lambda by bisection. Optimal ONLY
within this discretised model (grid ds, dv, control set) and its parameters.

Transition over one segment (length ds) at speed v_i:
    v_{i+1}^2 = v_i^2 + 2 ds (F_drive - F_res(v_mid) - F_brake) / m_eff
    dt        = 2 ds / (v_i + v_{i+1})
    E_batt    = P_batt(v_mid, action) * dt ;  E_brake = F_brake * distance
"""
from __future__ import annotations

import dataclasses

import numpy as np

from models.optimization.track import Track
from models.vehicle.longitudinal import VehicleParams, resistive_force_np, tractive_force
from models.vehicle.powertrain import PowerMap

INF = 1e30
COAST, PROPEL, BRAKE = 0, 1, 2
KIND_NAME = {COAST: "coast", PROPEL: "propel", BRAKE: "driver_brake"}
POLICIES = ("propulsion_coast_brake", "propulsion_coast")


@dataclasses.dataclass
class DPConfig:
    ds_m: float = 10.0
    dv_mps: float = 0.2
    n_torque: int = 10
    torque_max_Nm: float = 2.0
    v_bus: float = 46.0
    policy: str = "propulsion_coast_brake"
    brake_decel_levels: tuple = (0.5, 1.0, 1.5, 2.0)   # nominal driver brake decel [m/s^2] (synthetic)
    a_max: float = 1.5                                 # traction/comfort acceleration bound
    stop_zone_m: float = 2.0                           # ASSUMPTION: rest within this distance before a stop line
    v_margin_mps: float = 0.0                          # plan this far below every corner limit (guidance margin)
    t_max_s: float = 1000.0
    reserve_s: float = 30.0
    wind_mps: float = 0.0
    lambda_hi: float = 400.0
    bisection_iters: int = 28


@dataclasses.dataclass
class DPResult:
    s: np.ndarray
    v: np.ndarray            # speed at nodes
    kind: np.ndarray         # per segment: COAST / PROPEL / BRAKE
    u_torque: np.ndarray     # per segment motor torque [N*m] (0 unless PROPEL)
    u_brake_N: np.ndarray    # per segment driver brake force at the wheel [N] (0 unless BRAKE)
    e_batt_J: np.ndarray     # per segment battery-terminal energy
    e_brake_J: np.ndarray    # per segment energy dissipated in the friction brake
    t: np.ndarray            # time at nodes
    energy_J: float
    brake_energy_J: float
    time_s: float
    lam: float
    feasible: bool
    cfg: DPConfig
    infeasible_reason: str = ""
    label: str = "SYNTHETIC - optimal only within the discretised model"

    @property
    def u_coast(self) -> np.ndarray:
        """Gate-off segments WITHOUT braking (braking segments are not coast)."""
        return self.kind == COAST


class _PowerTable:
    """Tabulated P_batt(v) per control row for vectorised DP."""

    def __init__(self, pmap: PowerMap, kinds, torques_row, v_bus: float, v_max: float, dv: float = 0.02):
        self.v = np.arange(0.0, v_max + 2 * dv, dv)
        self.dv = dv
        rows = []
        for kd, T in zip(kinds, torques_row):
            if kd == PROPEL:
                rows.append([pmap.p_batt(x, float(T), v_bus, 25.0, "drive") for x in self.v])
            else:  # coast and driver braking: gates off, electronics only
                rows.append([pmap.p_batt(x, 0.0, v_bus, 25.0, "coast_gate_off") for x in self.v])
        self.p = np.array(rows)

    def diag(self, v_mid: np.ndarray) -> np.ndarray:
        """v_mid [n_controls, n] -> P[r, j] for control r at speed v_mid[r, j]."""
        x = np.clip(v_mid / self.dv, 0, len(self.v) - 1.000001)
        i = x.astype(int)
        f = x - i
        r = np.arange(self.p.shape[0])[:, None]
        return self.p[r, i] * (1 - f) + self.p[r, i + 1] * f


def _controls(cfg: DPConfig, veh: VehicleParams):
    if cfg.policy not in POLICIES:
        raise ValueError(cfg.policy)
    torques = np.linspace(cfg.torque_max_Nm / cfg.n_torque, cfg.torque_max_Nm, cfg.n_torque)
    m_coast = veh.m_eff(coupled=not veh.freewheel)
    kinds, tq, fb = [COAST], [0.0], [0.0]
    if cfg.policy == "propulsion_coast_brake":
        for a in cfg.brake_decel_levels:
            kinds.append(BRAKE)
            tq.append(0.0)
            fb.append(m_coast * a)
    for T in torques:
        kinds.append(PROPEL)
        tq.append(float(T))
        fb.append(0.0)
    return np.array(kinds), np.array(tq), np.array(fb)


def _setup(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig):
    s, grade, curv, vlim = track.sample(cfg.ds_m)
    # A corner can begin or end between nodes. Speed is monotone within a
    # segment (constant-force approximation), so requiring each node to be at
    # or below the lowest limit on BOTH adjacent segments keeps the whole
    # segment compliant. v0.1 checked the limit at nodes only and could enter
    # a corner between nodes above its limit (found by an execution test).
    dense = 1.0
    seg_min = np.empty(len(s) - 1)
    for k in range(len(s) - 1):
        xs = np.arange(s[k], s[k + 1] + 1e-9, dense)
        seg_min[k] = min(track.v_limit(x) for x in np.append(xs, s[k + 1] - 1e-6))
    vlim = vlim.copy()
    vlim[:-1] = np.minimum(vlim[:-1], seg_min)
    vlim[1:] = np.minimum(vlim[1:], seg_min)
    vlim = np.maximum(vlim - cfg.v_margin_mps, 0.0)
    v_top = float(min(track.v_max_global, vlim.max()))
    vg = np.arange(0.0, v_top + 0.5 * cfg.dv_mps, cfg.dv_mps)
    kinds, tq, fb = _controls(cfg, veh)
    ptab = _PowerTable(pmap, kinds, tq, cfg.v_bus, v_top + 1.0)
    stops = np.array([track.is_stop(x, cfg.ds_m) for x in s])
    vstar = _upper_envelope(s, grade, curv, vlim, stops, float(fb.max()), veh, cfg)
    return s, grade, curv, (vlim, vstar), vg, (kinds, tq, fb), ptab, stops


def _upper_envelope(s, grade, curv, vlim, stops, f_brake_max, veh, cfg):
    """Exact (continuous) upper feasibility bound per node: the highest speed
    from which the most decelerating available action (strongest driver brake,
    or coasting for the torque-only policy) still meets every downstream
    limit. NaN where no speed (not even rest) can: the problem is infeasible
    there. Used to prune dead ends exactly instead of by grid interpolation."""
    n = len(s)
    vs = np.empty(n)
    vs[-1] = 0.0 if stops[-1] else vlim[-1]
    m = veh.m_eff(coupled=not veh.freewheel)
    ds = cfg.ds_m
    for k in range(n - 2, -1, -1):
        if np.isnan(vs[k + 1]):
            vs[k] = np.nan
            continue
        f = resistive_force_np(veh, np.array([max(vs[k + 1], 0.0)]), grade[k], cfg.wind_mps, curv[k],
                               not veh.freewheel)[0] + f_brake_max
        if stops[k + 1]:
            v2 = 2 * ds * f / m          # bring it to rest at the stop line
        else:
            v2 = vs[k + 1] ** 2 + 2 * ds * f / m
        if v2 < 0.0:
            vs[k] = np.nan if not stops[k] else 0.0
        else:
            vs[k] = min(vlim[k], float(np.sqrt(v2)))
        if stops[k]:
            vs[k] = 0.0 if not np.isnan(vs[k]) else np.nan
    return vs


def _transition(v, k, grade, curv, vlim, stops, ctl, veh, cfg, ds):
    """Vectorised transitions from speeds v (shape [n]) for every control row.
    Returns v_next, dt, v_mid, dist, feasible, each [n_controls, n]."""
    kinds, tq, fb = ctl
    nU = len(kinds)
    f_drive = np.array([tractive_force(veh, T) for T in tq])[:, None]
    f_brake = fb[:, None]
    propel = (kinds == PROPEL)[:, None]
    coupled_unpowered = not veh.freewheel
    m_eff = np.where(propel, veh.m_eff(coupled=True), veh.m_eff(coupled=not veh.freewheel))

    def fres(vv):
        out = np.empty(vv.shape)
        for r in range(nU):
            out[r] = resistive_force_np(veh, vv[r], grade[k], cfg.wind_mps, curv[k],
                                        kinds[r] != PROPEL and coupled_unpowered)
        return out

    v_b = np.broadcast_to(v[None, :], (nU, len(v)))
    f_net0 = f_drive - fres(v_b) - f_brake
    v2_pred = v_b ** 2 + 2 * ds * f_net0 / m_eff
    v_pred = np.sqrt(np.maximum(v2_pred, 0.0))
    v_mid = 0.5 * (v_b + v_pred)
    v2 = v_b ** 2 + 2 * ds * (f_drive - fres(v_mid) - f_brake) / m_eff
    feasible = np.ones_like(v2, dtype=bool)
    # acceleration bound: a torque level that would exceed a_max is not
    # available at this state (it is never clipped after the fact)
    feasible &= ~(propel & (f_net0 / m_eff > cfg.a_max + 1e-9))
    dist = np.full(v2.shape, ds)
    v_next = np.sqrt(np.maximum(v2, 0.0))
    vlim, vstar = vlim
    vs_next = vstar[k + 1]
    limit = 0.0 if stops[k + 1] else (min(vlim[k + 1], vs_next) if np.isfinite(vs_next) else -1.0)
    if stops[k + 1]:
        # the vehicle must come to rest within stop_zone_m before the line
        drop = np.maximum(v_b ** 2 - v2, 1e-12)
        d_stop = np.where(v2 <= 0.0, ds * v_b ** 2 / drop, np.inf)
        ok = (v2 <= 0.0) & (d_stop >= ds - cfg.stop_zone_m) & (v_b > 0.0)
        feasible &= ok
        dist = np.where(ok, d_stop, ds)
        v_next = np.where(ok, 0.0, v_next)
    else:
        feasible &= v2 > 0.0            # stalling before the node is infeasible
        feasible &= v_next <= limit + 1e-9  # NO implicit braking: overspeed is infeasible
    v_mid = 0.5 * (v_b + v_next)
    denom = v_b + v_next
    dt = np.where(denom > 1e-9, 2 * dist / np.where(denom > 1e-9, denom, 1.0), np.inf)
    feasible &= np.isfinite(dt)
    return v_next, dt, v_mid, dist, feasible


def _interp(Jn: np.ndarray, vg: np.ndarray, x: np.ndarray, v_bound: float = np.inf) -> np.ndarray:
    """Cost-to-go at off-grid speeds. Between a feasible grid point and an
    infeasible one, a speed at or below the exact feasibility bound v_bound
    takes the feasible neighbour's value (feasibility itself is decided
    exactly by the transition's v_next <= v_bound check); above it, INF."""
    dv = vg[1] - vg[0]
    xi = x / dv
    i = np.clip(np.floor(xi).astype(int), 0, len(vg) - 2)
    f = np.clip(xi - i, 0.0, 1.0)
    a, b = Jn[i], Jn[i + 1]
    out = a * (1 - f) + b * f
    edge = np.where(f < 1e-9, a, np.where(f > 1 - 1e-9, b, INF))
    edge = np.where((a < INF) & (b >= INF) & (x <= v_bound + 1e-9), a, edge)
    out = np.where((a >= INF) | (b >= INF), edge, out)
    out = np.where(x > vg[-1] + 1e-9, INF, out)
    return out


def _backward(lam, pre, veh, cfg):
    s, grade, curv, vlim, vg, ctl, ptab, stops, trans = pre
    N = len(s) - 1
    Js = [None] * (N + 1)
    Js[N] = np.zeros(len(vg))  # free final speed (identical terminal condition for every strategy)
    for k in range(N - 1, -1, -1):
        v_next, dt, v_mid, _dist, feas = trans[k]
        Pd = ptab.diag(v_mid)
        dtf = np.where(feas, dt, 0.0)
        cost = Pd * dtf + lam * dtf + _interp(Js[k + 1], vg, v_next, _vb(vlim, k + 1))
        cost = np.where(feas, cost, INF)
        Jk = cost.min(axis=0)
        if stops[k]:
            Jk = np.where(vg <= 1e-9, Jk, INF)
        Js[k] = np.minimum(Jk, INF)
    return Js


def _forward(lam, pre, Js, veh, cfg):
    s, grade, curv, vlim, vg, ctl, ptab, stops, _trans = pre
    kinds, tq, fb = ctl
    N = len(s) - 1
    v = np.zeros(N + 1)
    t = np.zeros(N + 1)
    kind = np.zeros(N, int)
    uT = np.zeros(N)
    uB = np.zeros(N)
    eB = np.zeros(N)
    eE = np.zeros(N)
    feasible = True
    for k in range(N):
        vn, dt, vm, dist, feas = _transition(np.array([v[k]]), k, grade, curv, vlim, stops, ctl, veh, cfg, cfg.ds_m)
        Pd = ptab.diag(vm)[:, 0]
        dtf = np.where(feas[:, 0], dt[:, 0], 0.0)
        cost = Pd * dtf + lam * dtf + _interp(Js[k + 1], vg, vn[:, 0], _vb(vlim, k + 1))
        cost = np.where(feas[:, 0], cost, INF)
        r = int(np.argmin(cost))
        if cost[r] >= INF:
            feasible = False
            break
        v[k + 1] = vn[r, 0]
        t[k + 1] = t[k] + dt[r, 0]
        kind[k] = kinds[r]
        uT[k] = tq[r]
        uB[k] = fb[r]
        eE[k] = Pd[r] * dt[r, 0]
        eB[k] = fb[r] * dist[r, 0]
    return v, t, kind, uT, uB, eE, eB, feasible


def _vb(vlim, k):
    v = vlim[1][k]
    return float(v) if np.isfinite(v) else -1.0


def precompute(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig):
    s, grade, curv, vlim, vg, ctl, ptab, stops = _setup(track, veh, pmap, cfg)
    trans = [_transition(vg, k, grade, curv, vlim, stops, ctl, veh, cfg, cfg.ds_m) for k in range(len(s) - 1)]
    return (s, grade, curv, vlim, vg, ctl, ptab, stops, trans)


def solve_for_lambda(lam, pre, veh, cfg):
    Js = _backward(lam, pre, veh, cfg)
    return _forward(lam, pre, Js, veh, cfg), Js


def coast_envelope(track: Track, veh: VehicleParams, ds: float = 1.0, wind_mps: float = 0.0):
    """Highest speed at each position from which COASTING ALONE (no brake, no
    regen) keeps the vehicle at or under every downstream corner limit.
    Returns (s, v_env, first_infeasible_s or None). Where gravity on a descent
    accelerates the coasting vehicle into a corner, v_env can drop to zero: no
    torque-only plan exists through that point."""
    s = np.arange(0.0, track.length_m + ds, ds)
    vl = np.array([track.v_limit(x) for x in s])
    env = vl.copy()
    m = veh.m_eff(coupled=not veh.freewheel)
    first_bad = None
    for i in range(len(s) - 2, -1, -1):
        g, kap = track.grade(s[i]), track.curvature(s[i])
        # speed-squared change while coasting over ds (evaluated at the downstream speed)
        f_res = resistive_force_np(veh, np.array([env[i + 1]]), g, wind_mps, kap, not veh.freewheel)[0]
        v2 = env[i + 1] ** 2 + 2 * ds * f_res / m   # going backwards: v_i^2 = v_{i+1}^2 + 2 ds F_res/m
        if v2 < 0.0:
            env[i] = 0.0
            first_bad = s[i]
        else:
            env[i] = min(vl[i], float(np.sqrt(v2)))
    return s, env, first_bad


def solve(track: Track, veh: VehicleParams, pmap: PowerMap, cfg: DPConfig) -> DPResult:
    pre = precompute(track, veh, pmap, cfg)
    t_target = cfg.t_max_s - cfg.reserve_s
    n = len(pre[0]) - 1

    def pack(lam, res, ok, reason=""):
        v, t, kind, uT, uB, eE, eB, feas = res
        return DPResult(pre[0], v, kind, uT, uB, eE, eB, t, float(eE.sum()), float(eB.sum()), float(t[-1]),
                        lam, ok, cfg, reason)

    res0, Js0 = solve_for_lambda(0.0, pre, veh, cfg)
    if Js0[0][0] >= INF or not res0[-1]:
        reason = "no feasible path for this actuator set"
        if cfg.policy == "propulsion_coast":
            _, env, bad = coast_envelope(track, veh, wind_mps=cfg.wind_mps)
            if bad is not None:
                reason += (f"; coasting alone cannot meet the downstream corner limit from s = {bad:.0f} m "
                           f"(gravity/descent accelerates the vehicle above the limit even from rest)")
        return pack(0.0, res0, False, reason)
    if res0[1][-1] <= t_target:
        return pack(0.0, res0, True)
    lo, hi, best = 0.0, cfg.lambda_hi, None
    for _ in range(cfg.bisection_iters):
        mid = 0.5 * (lo + hi)
        res, _ = solve_for_lambda(mid, pre, veh, cfg)
        if res[-1] and res[1][-1] <= t_target:
            best, hi = (mid, res), mid
        else:
            lo = mid
    if best is None:
        res, _ = solve_for_lambda(hi, pre, veh, cfg)
        return pack(hi, res, False, f"finish-time target {t_target:.0f} s not reachable (fastest found "
                                    f"{res[1][-1]:.1f} s over {n} segments)")
    return pack(best[0], best[1], True)


def export_schedule(res: DPResult, path, torque_bound_Nm: float, model_label: str) -> None:
    """Position-indexed schedule (CSV with a metadata header). The controller
    executes only PROPEL torque (bounded) and COAST; DRIVER_BRAKE rows are for
    the driver display (export_guidance), never a controller command."""
    import pathlib
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    m = res.cfg
    with p.open("w") as f:
        f.write(f"# SYNTHETIC schedule - {res.label}; policy {m.policy}; model: {model_label}; ds={m.ds_m} m "
                f"dv={m.dv_mps} m/s; T_max={m.t_max_s} s reserve={m.reserve_s} s; torque bound {torque_bound_Nm} "
                f"N*m; battery energy {res.energy_J:.1f} J; friction-brake energy {res.brake_energy_J:.1f} J; "
                f"time {res.time_s:.1f} s\n")
        f.write("s_start_m,s_end_m,v_start_mps,v_end_mps,t_plan_s,action,controller_torque_Nm,"
                "driver_brake_force_N,battery_energy_J,brake_energy_J\n")
        for k in range(len(res.kind)):
            tq = min(float(res.u_torque[k]), torque_bound_Nm) if res.kind[k] == PROPEL else 0.0
            f.write(f"{res.s[k]:.2f},{res.s[k+1]:.2f},{res.v[k]:.4f},{res.v[k+1]:.4f},{res.t[k]:.3f},"
                    f"{KIND_NAME[int(res.kind[k])]},{tq:.4f},{res.u_brake_N[k]:.2f},{res.e_batt_J[k]:.2f},"
                    f"{res.e_brake_J[k]:.2f}\n")


@dataclasses.dataclass(frozen=True)
class GuidanceAssumptions:
    """Assumptions under which a braking plan is issued as driver guidance.
    All SYNTHETIC placeholders until measured with the team's drivers."""
    reaction_s: float = 1.0          # cue -> brake application
    release_reaction_s: float = 0.7  # release cue -> brake released
    decel_tracking: float = 0.20     # achieved decel within +/- this fraction of nominal
    speed_margin_mps: float = 0.0    # extra margin the plan keeps below corner limits


def brake_blocks(res: DPResult) -> list[dict]:
    """Contiguous DRIVER_BRAKE segments."""
    out, k = [], 0
    m = None
    while k < len(res.kind):
        if res.kind[k] == BRAKE:
            j = k
            while j + 1 < len(res.kind) and res.kind[j + 1] == BRAKE:
                j += 1
            m = m or res.cfg
            dist = res.s[j + 1] - res.s[k]
            out.append({"s_from_m": float(res.s[k]), "s_to_m": float(res.s[j + 1]), "v_entry_mps": float(res.v[k]),
                        "v_exit_mps": float(res.v[j + 1]), "force_N_max": float(res.u_brake_N[k:j + 1].max()),
                        "mean_decel_mps2": float((res.v[k] ** 2 - res.v[j + 1] ** 2) / (2 * dist)) if dist > 0 else 0.0,
                        "energy_J": float(res.e_brake_J[k:j + 1].sum()), "t_from_s": float(res.t[k])})
            k = j + 1
        else:
            k += 1
    return out


def export_guidance(res: DPResult, path, a: GuidanceAssumptions) -> list[dict]:
    """Driver braking guidance: cue positions are advanced by the assumed
    reaction distance (v * reaction_s). Written as CSV with the assumptions in
    the header; returns the blocks."""
    import pathlib
    blocks = brake_blocks(res)
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        f.write(f"# SYNTHETIC driver braking guidance (controller never brakes); reaction {a.reaction_s} s, "
                f"release reaction {a.release_reaction_s} s, decel tracking +/-{100*a.decel_tracking:.0f} %, "
                f"speed margin {a.speed_margin_mps} m/s; {len(blocks)} blocks, "
                f"{sum(b['energy_J'] for b in blocks):.0f} J dissipated\n")
        f.write("cue_on_m,brake_from_m,brake_to_m,v_entry_mps,target_exit_mps,release_at_mps,mean_decel_mps2,"
                "brake_force_max_N,brake_energy_J\n")
        for b in blocks:
            cue_on = b["s_from_m"] - b["v_entry_mps"] * a.reaction_s
            release_at = b["v_exit_mps"] + b["mean_decel_mps2"] * a.release_reaction_s
            f.write(f"{cue_on:.1f},{b['s_from_m']:.1f},{b['s_to_m']:.1f},{b['v_entry_mps']:.3f},"
                    f"{b['v_exit_mps']:.3f},{release_at:.3f},{b['mean_decel_mps2']:.3f},{b['force_N_max']:.1f},"
                    f"{b['energy_J']:.1f}\n")
    return blocks
