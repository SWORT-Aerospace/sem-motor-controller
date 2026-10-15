"""Strategy evaluation on a common forward simulator (SYNTHETIC models).

Every strategy runs on the SAME time-domain simulator with the same route,
start (rest at s = 0), terminal condition (cross the finish line; final speed
free), finish-time target, actuator constraints and auxiliary load:

* Motor torque is the only controller actuator: slew-limited, bounded by
  torque_max, and limited so that the longitudinal acceleration stays within
  a_max. The torque REDUCED by that limit is the torque whose power is charged
  (force, torque, electrical power and energy stay consistent).
* Braking exists only as the DRIVER's friction brake, driven by a strategy's
  braking guidance through a driver model: reaction delay, release delay and a
  deceleration tracking error. While the brake is applied the controller holds
  zero torque (brake override, CONTROL_CONTRACT.md L1). Nothing brakes
  automatically: a corner limit exceeded or a stop missed is recorded as a
  violation, never silently corrected.
* An energy reconciliation is accumulated per run:
      tractive work at the wheel = delta kinetic energy + resistive work + brake work
  (exact for the update used here). A non-zero residual would mean that a
  force was applied without being charged, or the reverse.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable, NamedTuple

import numpy as np

from models.optimization.track import Track
from models.vehicle.longitudinal import VehicleParams, motor_torque_for_force, resistive_force, tractive_force
from models.vehicle.powertrain import PowerMap


class Command(NamedTuple):
    torque_Nm: float          # controller propulsion torque request (>= 0)
    coast: bool               # gate-off when torque has reached zero
    brake_cue_N: float = 0.0  # DRIVER guidance: requested friction-brake force at the wheel (0 = none)


Controller = Callable[[float, float, float], Command]  # (s, v, t) -> Command


@dataclasses.dataclass
class DriverModel:
    """How the driver executes braking guidance (SYNTHETIC assumptions)."""
    reaction_s: float = 1.0          # cue on -> brake applied
    release_s: float = 0.7           # cue off -> brake released
    decel_gain: float = 1.0          # achieved / requested brake force (tracking error)


@dataclasses.dataclass
class SimConfig:
    dt: float = 0.05
    v_bus: float = 46.0
    torque_max_Nm: float = 2.0
    slew_up_Nm_s: float = 5.0
    slew_down_Nm_s: float = 10.0
    a_max: float = 1.5
    wind_mps: float = 0.0
    t_limit_s: float = 3000.0
    overspeed_tol_mps: float = 0.05
    driver: DriverModel = dataclasses.field(default_factory=DriverModel)


@dataclasses.dataclass
class SimResult:
    energy_J: float            # battery-terminal energy (incl. auxiliary load)
    time_s: float
    finished: bool
    n_accel_events: int
    brake_energy_J: float      # dissipated in the friction brake (vehicle KE, not battery energy)
    trace: dict
    aux_energy_J: float = 0.0
    final_speed_mps: float = 0.0
    overspeed_events: int = 0
    max_overspeed_mps: float = 0.0
    stop_violations: int = 0
    accel_limited_steps: int = 0
    brake_applications: int = 0
    reconciliation: dict = dataclasses.field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """Finished, no corner overspeed and no missed stop."""
        return self.finished and self.overspeed_events == 0 and self.stop_violations == 0


def braking_envelope(track: Track, a_brake: float, ds: float = 1.0, margin_mps: float = 0.0):
    """Highest speed from which braking at a_brake meets every downstream limit."""
    s = np.arange(0.0, track.length_m + ds, ds)
    vl = np.array([max(track.v_limit(x) - margin_mps, 0.0) for x in s])
    env = vl.copy()
    for i in range(len(s) - 2, -1, -1):
        env[i] = min(vl[i], math.sqrt(env[i + 1] ** 2 + 2 * a_brake * ds))
    return s, env


def simulate(track: Track, veh: VehicleParams, pmap: PowerMap, ctrl: Controller, cfg: SimConfig,
             record: bool = False) -> SimResult:
    s = v = t = E = E_brake = E_aux = 0.0
    W_trac = W_res = W_brake = dKE = 0.0
    torque = 0.0
    accel_events = brake_apps = n_alim = 0
    over_n, over_max, stop_viol = 0, 0.0, 0
    driving_prev = braking_prev = over_prev = False
    cue_prev, cue_force, t_apply, t_release = False, 0.0, math.inf, math.inf
    tr = {"t": [], "s": [], "v": [], "torque": [], "brake_N": [], "p": []} if record else {}
    m_drive = veh.m_eff(coupled=True)
    m_coast = veh.m_eff(coupled=not veh.freewheel)
    p_aux = pmap.p_batt(0.0, 0.0, cfg.v_bus, 25.0, "coast_gate_off")
    stops = sorted(p + k * track.lap_length_m for k in range(track.laps) for p in track.stop_positions_m)
    dm = cfg.driver
    while s < track.length_m and t < cfg.t_limit_s:
        cmd = ctrl(s, v, t)
        # ---- driver: brake applied reaction_s after the cue comes on, released
        # release_s after it goes off; force = decel_gain x cued force
        cue = max(cmd.brake_cue_N, 0.0)
        if cue > 0.0 and not cue_prev:
            t_apply, t_release = t + dm.reaction_s, math.inf
        elif cue == 0.0 and cue_prev:
            t_release = t + dm.release_s
        if cue > 0.0:
            cue_force = cue
        cue_prev = cue > 0.0
        f_brake = dm.decel_gain * cue_force if (t >= t_apply and t < t_release) else 0.0
        braking = f_brake > 0.0
        if braking and not braking_prev:
            brake_apps += 1
        braking_prev = braking
        # ---- controller torque: brake override, bound, slew, acceleration limit
        T_cmd = 0.0 if (cmd.coast or braking) else min(max(cmd.torque_Nm, 0.0), cfg.torque_max_Nm)
        g, kappa = track.grade(s), track.curvature(s)
        if braking:
            torque = 0.0                       # brake override: immediate (L1)
        elif T_cmd > torque:
            torque = min(T_cmd, torque + cfg.slew_up_Nm_s * cfg.dt)
        else:
            torque = max(T_cmd, torque - cfg.slew_down_Nm_s * cfg.dt)
        mode = "drive" if torque > 0.0 else "coast_gate_off"
        f_res = resistive_force(veh, v, g, cfg.wind_mps, kappa,
                                motor_coupled_unpowered=(mode != "drive") and not veh.freewheel)
        m_eff = m_drive if mode == "drive" else m_coast
        if mode == "drive":
            t_amax = motor_torque_for_force(veh, f_res + m_eff * cfg.a_max)
            if torque > t_amax:
                torque = t_amax
                n_alim += 1
        driving = torque > 0.0
        if driving and not driving_prev:
            accel_events += 1
        driving_prev = driving
        f_trac = tractive_force(veh, torque)
        f_br = f_brake if v > 0.0 else 0.0
        a = (f_trac - f_res - f_br) / m_eff
        v_new = v + a * cfg.dt
        if v_new < 0.0:                        # brake/resistance cannot reverse the vehicle
            v_new = 0.0
        v_mid = 0.5 * (v + v_new)
        ds = v_mid * cfg.dt
        # work terms consistent with the update actually taken
        if v + a * cfg.dt >= 0.0:
            W_trac += f_trac * ds
            W_res += f_res * ds
            W_brake += f_br * ds
        else:                                  # came to rest inside the step: friction absorbs the rest
            W_trac += f_trac * ds
            W_res += f_res * ds
            W_brake += 0.5 * m_eff * (v * v - v_new * v_new) + (f_trac - f_res) * ds
        dKE += 0.5 * m_eff * (v_new * v_new - v * v)
        E_brake = W_brake
        p = pmap.p_batt(v_mid, torque, cfg.v_bus, 25.0, mode)
        E += p * cfg.dt
        E_aux += p_aux * cfg.dt
        s_new = s + ds
        vl = track.v_limit(s_new)
        over = v_new > vl + cfg.overspeed_tol_mps
        if over and not over_prev:
            over_n += 1
        over_prev = over
        if over:
            over_max = max(over_max, v_new - vl)
        for sp in stops:
            if s < sp <= s_new and v_mid > 0.2:
                stop_viol += 1
        if record:
            tr["t"].append(t); tr["s"].append(s); tr["v"].append(v); tr["torque"].append(torque)
            tr["brake_N"].append(f_br); tr["p"].append(p)
        s, v, t = s_new, v_new, t + cfg.dt
        if v == 0.0 and torque == 0.0 and T_cmd == 0.0 and not braking and s < track.length_m and t > 1.0 \
                and not any(abs(s - sp) < 3.0 for sp in stops):
            break  # stopped short of the finish
    resid = W_trac - (dKE + W_res + W_brake)
    rec = {"tractive_work_J": W_trac, "delta_ke_J": dKE, "resistive_work_J": W_res, "brake_work_J": W_brake,
           "residual_J": resid, "battery_minus_tractive_J": E - W_trac}
    return SimResult(E, t, s >= track.length_m, accel_events, E_brake, {k: np.array(x) for k, x in tr.items()},
                     E_aux, v, over_n, over_max, stop_viol, n_alim, brake_apps, rec)


# ----------------------------------------------------------------- controllers
class EnvelopeBrakeCue:
    """Baseline driver braking guidance for non-optimised strategies. The
    envelope is planned with a deceleration below the one the driver is asked
    for (a_plan_fraction), plus a speed margin, and the cue looks ahead by the
    assumed reaction distance. The cue is on while the speed is above the
    planning envelope at the look-ahead point."""

    def __init__(self, track: Track, veh: VehicleParams, a_nominal: float = 1.0, reaction_assumed_s: float = 1.0,
                 margin_mps: float = 0.3, a_plan_fraction: float = 0.7):
        self.s_env, self.v_env = braking_envelope(track, a_nominal * a_plan_fraction, margin_mps=margin_mps)
        self.f = veh.m_eff(coupled=not veh.freewheel) * a_nominal
        self.tau = reaction_assumed_s

    def __call__(self, s: float, v: float) -> float:
        look = s + v * self.tau
        return self.f if v > float(np.interp(look, self.s_env, self.v_env)) else 0.0


def constant_speed(v_set: float, veh: VehicleParams, kp: float = 2.0, brake: EnvelopeBrakeCue | None = None,
                   v_cap: Callable[[float], float] | None = None) -> Controller:
    """Cruise at v_set. With `brake`, corners are taken with driver braking
    guidance; with `v_cap` (torque-only), the set speed is lowered ahead of
    corners to a coast envelope so that no braking is needed."""
    def c(s, v, t):
        vs = min(v_set, v_cap(s)) if v_cap else v_set
        f_ff = resistive_force(veh, vs) / max(veh.drivetrain_eff, 1e-6)
        t_ff = f_ff * veh.wheel_radius_m / veh.gear_ratio
        T = t_ff + kp * (vs - v)
        cue = brake(s, v) if brake else 0.0
        return Command(max(T, 0.0), T <= 0.0, cue)
    return c


def pulse_and_coast(v_lo: float, v_hi: float, torque_Nm: float, brake: EnvelopeBrakeCue | None = None,
                    v_cap: Callable[[float], float] | None = None) -> Controller:
    state = {"pulse": True}

    def c(s, v, t):
        hi = min(v_hi, v_cap(s)) if v_cap else v_hi
        lo = min(v_lo, hi - 0.05)
        if state["pulse"] and v >= hi:
            state["pulse"] = False
        elif not state["pulse"] and v <= lo:
            state["pulse"] = True
        cue = brake(s, v) if brake else 0.0
        return Command(torque_Nm, False, cue) if state["pulse"] else Command(0.0, True, cue)
    return c


@dataclasses.dataclass
class PaceCorrector:
    """Bounded pace correction: delta_T = clip(k * (t - t_plan(s)), -bound, +bound).
    Positive when behind schedule. Acts on propulsion torque only; it never
    changes braking guidance. No other online adaptation is performed."""
    k_Nm_per_s: float = 0.05
    bound_Nm: float = 0.3

    def delta(self, t: float, t_plan: float) -> float:
        return max(-self.bound_Nm, min(self.bound_Nm, self.k_Nm_per_s * (t - t_plan)))


def schedule_follower(s_nodes: np.ndarray, torque: np.ndarray, kind: np.ndarray, t_plan: np.ndarray,
                      torque_max: float, pace: PaceCorrector | None = None, brake_N: np.ndarray | None = None,
                      cue_lead_s: float = 0.0, release_lead_s: float = 0.0, v_nodes: np.ndarray | None = None,
                      m_brake_kg: float = 100.0) -> Controller:
    """Follow a DP plan. kind: 0 coast, 1 propel, 2 driver brake (dp.COAST/PROPEL/BRAKE).

    Controller part: the plan's torque (propel) or gate-off (coast, brake) for
    the current segment. Driver part: each contiguous braking block becomes a
    target-speed cue. It comes on when the look-ahead point s + v*cue_lead_s
    enters the block, and goes off once v <= v_exit + a_nom*release_lead_s
    (the speed still lost during the release reaction) or the vehicle leaves
    the block. The controller never brakes; the brake override zeroes torque
    once the driver actually brakes."""
    kind = np.asarray(kind)
    brake_N = np.zeros(len(kind)) if brake_N is None else np.asarray(brake_N)
    blocks = []
    k = 0
    while k < len(kind):
        if kind[k] == 2:
            j = k
            while j + 1 < len(kind) and kind[j + 1] == 2:
                j += 1
            v_exit = float(v_nodes[j + 1]) if v_nodes is not None else 0.0
            f = float(brake_N[k:j + 1].max())
            blocks.append((float(s_nodes[k]), float(s_nodes[j + 1]) if j + 1 < len(s_nodes) else math.inf, v_exit, f))
            k = j + 1
        else:
            k += 1
    st = {"cue": 0.0, "blk": -1}

    def seg(x):
        k = int(np.searchsorted(s_nodes, x, side="right") - 1)
        return min(max(k, 0), len(kind) - 1)

    def c(s, v, t):
        k = seg(s)
        if st["blk"] >= 0:
            s0, s1, v_exit, f = blocks[st["blk"]]
            if v <= v_exit + f / m_brake_kg * release_lead_s or s >= s1:
                st["cue"], st["blk"] = 0.0, -2 - st["blk"]   # released; remember which block is done
        if st["blk"] < 0:
            look = s + v * cue_lead_s
            for b, (s0, s1, v_exit, f) in enumerate(blocks):
                if s0 <= look < s1 and s < s1 and b != -2 - st["blk"] and v > v_exit:
                    st["cue"], st["blk"] = f, b
                    break
        if kind[k] == 2:
            return Command(0.0, True, st["cue"])
        T, cst = float(torque[k]), bool(kind[k] == 0)
        if pace is not None:
            tp = float(np.interp(s, s_nodes, t_plan))
            d = pace.delta(t, tp)
            if cst and d > 0:
                cst, T = False, 0.0
            T = min(max(T + d, 0.0), torque_max)
            if T == 0.0 and d <= 0:
                cst = True
        return Command(T, cst, st["cue"])
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
