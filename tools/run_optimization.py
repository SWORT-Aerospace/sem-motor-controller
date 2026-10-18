#!/usr/bin/env python3
"""SYNTHETIC energy-strategy study, v0.2 actuator model.

    python3 tools/run_optimization.py [--quick] [--out DIR]

Coast, propulsion and DRIVER braking are separate actuators (models/optimization/dp.py).
Every strategy runs on one forward simulator with identical route, start, terminal
condition, finish-time target, actuator limits, driver model and auxiliary load
(models/optimization/strategies.py). Writes docs/generated/optimization_synthetic.{md,json},
docs/generated/dp_schedule_synthetic.csv, docs/generated/dp_driver_guidance_synthetic.csv
and docs/figures/dp_plan_synthetic.png. --quick (coarser grids, used by CI and
verify_all) writes the same files into build/optimization_quick/ instead, so the
committed full-resolution results are not overwritten. Every number comes from synthetic vehicle,
motor, inverter and track models; none of them predicts real-vehicle energy.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from models.optimization import dp  # noqa: E402
from models.optimization.strategies import (DriverModel, EnvelopeBrakeCue, PaceCorrector, SimConfig,  # noqa: E402
                                            bisect_param, constant_speed, pulse_and_coast, schedule_follower,
                                            simulate)
from models.optimization.track import synthetic_track, synthetic_track_flat  # noqa: E402
from models.vehicle.longitudinal import SYNTHETIC_VEHICLE, motor_torque_for_force, resistive_force, tractive_force  # noqa: E402
from models.vehicle.powertrain import SyntheticPhysicsMap  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "docs" / "generated"
FIGDIR = ROOT / "docs" / "figures"
T_MAX = 1000.0
RESERVE = 30.0
GUIDE = dp.GuidanceAssumptions(reaction_s=1.0, release_reaction_s=0.7, decel_tracking=0.20, speed_margin_mps=0.3)
SUPERSEDED = {"dp_schedule": 39715, "pulse_and_coast_best_of_6": 46229, "constant_speed": 55101,
              "dp_schedule_with_pace": 41673}


def summ(r):
    # A run is valid only if it finishes within the finish-time LIMIT (not just
    # the target), with no corner overspeed and no missed stop.
    return {"energy_J": round(r.energy_J, 1), "time_s": round(r.time_s, 1), "finished": r.finished,
            "valid": bool(r.valid and r.time_s <= T_MAX), "over_time_limit": bool(r.time_s > T_MAX), "brake_energy_J": round(r.brake_energy_J, 1), "aux_energy_J": round(r.aux_energy_J, 1),
            "final_speed_mps": round(r.final_speed_mps, 2), "overspeed_events": r.overspeed_events,
            "max_overspeed_mps": round(r.max_overspeed_mps, 3), "brake_applications": r.brake_applications,
            "accel_events": r.n_accel_events, "accel_limited_steps": r.accel_limited_steps,
            "reconciliation_residual_J": round(r.reconciliation["residual_J"], 3)}


def follower(r, sim, pace=None):
    return schedule_follower(r.s, r.u_torque, r.kind, r.t, sim.torque_max_Nm, pace, r.u_brake_N,
                             cue_lead_s=GUIDE.reaction_s, release_lead_s=GUIDE.release_reaction_s, v_nodes=r.v,
                             m_brake_kg=SYNTHETIC_VEHICLE.m_eff(coupled=not SYNTHETIC_VEHICLE.freewheel))


def solve_dp(track, veh, pmap, ds, dv, policy, margin=GUIDE.speed_margin_mps, extra_reserve=0.0):
    t0 = time.time()
    r = dp.solve(track, veh, pmap, dp.DPConfig(ds_m=ds, dv_mps=dv, t_max_s=T_MAX, reserve_s=RESERVE + extra_reserve,
                                               policy=policy, v_margin_mps=margin))
    return r, time.time() - t0


def solve_matched(track, veh, pmap, ds, dv, policy, sim, margin=GUIDE.speed_margin_mps):
    """Re-plan with a tighter internal target until the EXECUTED run (forward
    simulator, driver model) finishes within the matched target. Returns
    (plan, executed result, execution allowance [s], solve seconds)."""
    t_target = T_MAX - RESERVE
    extra, el_tot = 0.0, 0.0
    for _ in range(5):
        r, el = solve_dp(track, veh, pmap, ds, dv, policy, margin, extra)
        el_tot += el
        if not r.feasible:
            return r, None, extra, el_tot
        x = simulate(track, veh, pmap, follower(r, sim), sim)
        if x.time_s <= t_target + 0.5:
            return r, x, extra, el_tot
        extra += x.time_s - t_target + 0.2
    return r, x, extra, el_tot


# --------------------------------------------------------------------------- audits
def accounting_audit(veh, pmap):
    pts = []
    for v, T in ((4.0, 0.5), (6.0, 1.0), (8.0, 2.0)):
        b = pmap.breakdown(v, T, 46.0)
        w = v * veh.gear_ratio / veh.wheel_radius_m
        b.update({"v_mps": v, "torque_Nm": T, "wheel_W": tractive_force(veh, T) * v,
                  "drivetrain_loss_W": T * w - tractive_force(veh, T) * v,
                  "v01_omitted_friction_W": veh and pmap.motor.friction_Nm * w})
        pts.append({k: round(x, 3) if isinstance(x, float) else x for k, x in b.items()})
    return pts


def legacy_clip_residual(track, veh, pmap, a_max):
    """Re-run the v0.1 clip `a = min(a, a_max)` (energy charged for the FULL
    torque) against the v0.2 torque limit, on a constant full-torque launch."""
    out = {}
    for name in ("v0.1_clip", "v0.2_torque_limit"):
        v = t = E = W_trac = W_res = dKE = 0.0
        m = veh.m_eff(coupled=True)
        n_act = 0
        while t < 20.0:
            T = 2.0
            f_res = resistive_force(veh, v)
            if name == "v0.2_torque_limit":
                T = min(T, motor_torque_for_force(veh, f_res + m * a_max))
            a = (tractive_force(veh, T) - f_res) / m
            if name == "v0.1_clip" and a > a_max:
                a, n_act = a_max, n_act + 1
            elif name == "v0.2_torque_limit" and T < 2.0:
                n_act += 1
            v_new = v + a * 0.05
            ds = 0.5 * (v + v_new) * 0.05
            W_trac += tractive_force(veh, T) * ds
            W_res += f_res * ds
            dKE += 0.5 * m * (v_new ** 2 - v ** 2)
            E += pmap.p_batt(0.5 * (v + v_new), T, 46.0) * 0.05
            v, t = v_new, t + 0.05
        out[name] = {"battery_J": round(E, 1), "tractive_work_J": round(W_trac, 1), "delta_ke_J": round(dKE, 1),
                     "resistive_work_J": round(W_res, 1), "residual_J": round(W_trac - dKE - W_res, 1),
                     "steps_limited": n_act, "final_speed_mps": round(v, 3)}
    return out


def coast_from_rest(track, veh, s0, s_check):
    """Speed reached at s_check when coasting from rest at s0 (no brake)."""
    s = v = 0.0
    s = s0
    m = veh.m_eff(coupled=not veh.freewheel)
    while s < s_check:
        f = resistive_force(veh, v, track.grade(s), 0.0, track.curvature(s), not veh.freewheel)
        v = max(v - f / m * 0.05, 0.0)
        s += v * 0.05
        if v == 0.0 and f >= 0.0:
            return 0.0
    return v


# --------------------------------------------------------------------------- comparisons
def matched_comparison(track, veh, pmap, sim, ds, dv, quick):
    t_target = T_MAX - RESERVE
    res, notes = {}, {}
    brake = EnvelopeBrakeCue(track, veh, a_nominal=1.0, reaction_assumed_s=GUIDE.reaction_s, margin_mps=0.3)
    bcap = lambda s: float(np.interp(s, brake.s_env, brake.v_env))  # noqa: E731  cruise never targets above the envelope
    _, cenv, bad = dp.coast_envelope(track, veh)
    s_env = np.arange(0.0, track.length_m + 1.0, 1.0)
    vcap = (lambda s: float(np.interp(s, s_env, np.maximum(cenv - 0.2, 0.0)))) if bad is None else None

    for pol, key in (("propulsion_coast_brake", "dp_propulsion_coast_brake"), ("propulsion_coast", "dp_torque_only")):
        r, x, extra, el = solve_matched(track, veh, pmap, ds, dv, pol, sim)
        notes[key] = {"dp_feasible": r.feasible, "dp_reason": r.infeasible_reason, "dp_energy_J": round(r.energy_J, 1),
                      "dp_brake_energy_J": round(r.brake_energy_J, 1), "dp_time_s": round(r.time_s, 1),
                      "execution_allowance_s": round(extra, 2), "solve_s": round(el, 1)}
        if r.feasible and x is not None:
            res[key] = (x, {"ds_m": ds, "dv_mps": dv, "policy": pol, "plan_margin_mps": GUIDE.speed_margin_mps,
                            "plan_internal_target_s": round(T_MAX - RESERVE - extra, 1)})
            notes[key]["plan"] = r

    for key, mk in (("constant_speed_driver_brake", lambda x: constant_speed(x, veh, brake=brake, v_cap=bcap)),
                    ("constant_speed_torque_only", (lambda x: constant_speed(x, veh, v_cap=vcap)) if vcap else None)):
        if mk is None:
            notes[key] = {"reason": "no coast envelope exists (see DP torque-only)"}
            continue
        x = bisect_param(lambda q: simulate(track, veh, pmap, mk(q), sim).time_s, 3.0, 12.0, t_target)
        res[key] = (simulate(track, veh, pmap, mk(x), sim), {"v_set_mps": round(x, 3)})

    for key, cue, cap in (("pulse_and_coast_driver_brake", brake, bcap), ("pulse_and_coast_torque_only", None, vcap)):
        if key.endswith("torque_only") and vcap is None:
            notes[key] = {"reason": "no coast envelope exists (see DP torque-only)"}
            continue
        best = None
        widths = (1.0,) if quick else (0.5, 1.0, 2.0)
        for width in widths:
            for frac in (0.5, 1.0):
                Tp = frac * sim.torque_max_Nm

                def mk(c, width=width, Tp=Tp):
                    return pulse_and_coast(c - width / 2, c + width / 2, Tp, brake=cue, v_cap=cap)
                c = bisect_param(lambda q: simulate(track, veh, pmap, mk(q), sim).time_s, 3.0, 11.0, t_target, iters=22)
                rr = simulate(track, veh, pmap, mk(c), sim)
                if rr.valid and rr.time_s <= t_target + 0.5 and (best is None or rr.energy_J < best[0].energy_J):
                    best = (rr, {"band_center_mps": round(c, 3), "band_width_mps": width, "pulse_torque_Nm": Tp})
        if best:
            res[key] = best
        else:
            notes[key] = {"reason": "no valid setting met the finish target"}
    return res, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="coarser grids (CI); writes to build/optimization_quick")
    ap.add_argument("--out", type=pathlib.Path, help="output directory for every file (default: docs/generated and "
                    "docs/figures; build/optimization_quick with --quick)")
    args = ap.parse_args()
    global GEN, FIGDIR
    if args.out or args.quick:
        GEN = FIGDIR = args.out or ROOT / "build" / "optimization_quick"
        GEN.mkdir(parents=True, exist_ok=True)
    veh = SYNTHETIC_VEHICLE
    pmap = SyntheticPhysicsMap(veh)
    sim = SimConfig(driver=DriverModel(GUIDE.reaction_s, GUIDE.release_reaction_s, 1.0))
    trackA, trackB = synthetic_track(), synthetic_track_flat()
    out = {"label": "SYNTHETIC", "t_max_s": T_MAX, "reserve_s": RESERVE, "track_m": trackA.length_m,
           "guidance_assumptions": dataclasses.asdict(GUIDE), "superseded_v01_J": SUPERSEDED}

    out["accounting"] = accounting_audit(veh, pmap)
    out["accel_clip_audit"] = {"synthetic_a_max_1.5": legacy_clip_residual(trackA, veh, pmap, 1.5),
                               "tight_a_max_0.3": legacy_clip_residual(trackA, veh, pmap, 0.3)}
    out["torque_only_physics"] = {"coast_from_rest_700m_speed_at_1050m_mps":
                                  round(coast_from_rest(trackA, veh, 700.0, 1050.0), 3),
                                  "corner_limit_at_1050m_mps": round(trackA.v_limit(1060.0), 3)}

    # grid convergence (propulsion + coast + driver brake, track A)
    grids = [(20.0, 0.4), (10.0, 0.2)] if args.quick else [(20.0, 0.4), (10.0, 0.2), (5.0, 0.1), (2.5, 0.05)]
    conv, best = [], None
    for ds, dv in grids:
        r, el = solve_dp(trackA, veh, pmap, ds, dv, "propulsion_coast_brake")
        realized = simulate(trackA, veh, pmap, follower(r, sim), sim)
        conv.append({"ds_m": ds, "dv_mps": dv, "dp_energy_J": r.energy_J, "dp_brake_J": r.brake_energy_J,
                     "dp_time_s": r.time_s, "feasible": r.feasible, "solve_s": el,
                     "realized": summ(realized)})
        best = r
    out["grid_convergence"] = conv
    e = [c["dp_energy_J"] for c in conv]
    out["grid_rel_change_last"] = abs(e[-1] - e[-2]) / e[-1]
    ds, dv = grids[-2]   # comparisons on the second-finest grid (the finest is the convergence check)

    comps = {}
    for tname, trk in (("A_synthetic", trackA), ("B_synthetic_flat", trackB)):
        res, notes = matched_comparison(trk, veh, pmap, sim, ds, dv, args.quick)
        comps[tname] = {"results": {k: dict(summ(v[0]), params=v[1]) for k, v in res.items()},
                        "notes": {k: {kk: vv for kk, vv in n.items() if kk != "plan"} for k, n in notes.items()},
                        "grid": {"ds_m": ds, "dv_mps": dv}}
        if tname == "A_synthetic":
            planA = notes["dp_propulsion_coast_brake"].get("plan")
        else:
            planB_to = notes["dp_torque_only"].get("plan")
            planB_pb = notes["dp_propulsion_coast_brake"].get("plan")
    out["comparison"] = comps

    # driver-guidance robustness of the braking plan (track A)
    rob_g = {}
    for margin in (0.0, GUIDE.speed_margin_mps):
        r, _ = solve_dp(trackA, veh, pmap, ds, dv, "propulsion_coast_brake", margin=margin)
        for tau in (0.5, 1.0, 1.5):
            for gain in (1.0 - GUIDE.decel_tracking, 1.0, 1.0 + GUIDE.decel_tracking):
                sm = dataclasses.replace(sim, driver=DriverModel(tau, GUIDE.release_reaction_s * tau / GUIDE.reaction_s,
                                                                 gain))
                rob_g[f"margin {margin} m/s, reaction {tau} s, decel x{gain:.1f}"] = summ(
                    simulate(trackA, veh, pmap, follower(r, sim), sm))
    out["guidance_robustness"] = rob_g

    # model-error robustness of the braking plan (+ bounded pace correction)
    pace = PaceCorrector()
    perturb = {"nominal": {}, "crr+20%": {"crr": veh.crr * 1.2}, "cda+20%": {"cda_m2": veh.cda_m2 * 1.2},
               "mass+5%": {"mass_kg": veh.mass_kg * 1.05}, "crr-20%": {"crr": veh.crr * 0.8}}
    rob = {}
    for name, kw in perturb.items():
        vp = dataclasses.replace(veh, **kw)
        pm = SyntheticPhysicsMap(vp)
        rob[name] = {"dp_no_pace": summ(simulate(trackA, vp, pm, follower(planA, sim), sim)),
                     "dp_with_pace": summ(simulate(trackA, vp, pm, follower(planA, sim, pace), sim))}
    head = dataclasses.replace(sim, wind_mps=-2.0)
    rob["headwind 2 m/s"] = {"dp_no_pace": summ(simulate(trackA, veh, pmap, follower(planA, sim), head)),
                             "dp_with_pace": summ(simulate(trackA, veh, pmap, follower(planA, sim, pace), head))}
    out["model_robustness"] = rob

    # exports
    dp.export_schedule(planA, GEN / "dp_schedule_synthetic.csv", sim.torque_max_Nm, pmap.label)
    blocks = dp.export_guidance(planA, GEN / "dp_driver_guidance_synthetic.csv", GUIDE)
    out["guidance_blocks"] = len(blocks)
    if planB_to is not None:
        dp.export_schedule(planB_to, GEN / "dp_schedule_torque_only_flat_synthetic.csv", sim.torque_max_Nm,
                           pmap.label)
    GEN.mkdir(parents=True, exist_ok=True)
    (GEN / "optimization_synthetic.json").write_text(json.dumps(out, indent=1, default=float))
    _write_md(out)
    _plot(planA, planB_to, trackA, trackB)
    print(json.dumps({"grid": [(c["ds_m"], round(c["dp_energy_J"]), round(c["dp_brake_J"])) for c in conv],
                      "A": {k: (v["energy_J"], v["time_s"], v["valid"]) for k, v in comps["A_synthetic"]["results"].items()},
                      "B": {k: (v["energy_J"], v["time_s"], v["valid"]) for k, v in comps["B_synthetic_flat"]["results"].items()}},
                     indent=1))
    return 0


def _fmt(v):
    ok = "" if v["valid"] else (" **DNF**" if not v["finished"] else
                                (" **OVER LIMIT**" if v.get("over_time_limit") else " **INVALID**"))
    return (f"{v['energy_J']:.0f} | {v['time_s']:.1f}{ok} | {v['brake_energy_J']:.0f} | {v['aux_energy_J']:.0f} | "
            f"{v['final_speed_mps']:.2f} | {v['overspeed_events']} ({v['max_overspeed_mps']:.2f}) | "
            f"{v['brake_applications']} | {v['accel_events']} | {v['reconciliation_residual_J']:.2f}")


def _write_md(out):
    L = ["# Optimisation study v0.2 - SYNTHETIC", "",
         "> **SYNTHETIC.** Vehicle, motor, inverter, battery and track are invented placeholders. These numbers "
         "demonstrate the method; they say nothing about the real vehicle. Generated by `tools/run_optimization.py`. "
         "**All v0.1 savings figures are superseded** (section 7).", "",
         "Actuators are separate: **coast** (gates off), **propulsion** (controller torque) and **driver braking** "
         "(friction brake; issued as guidance, never a controller command). Every strategy below runs on one "
         "forward simulator. The route, start (rest at 0 m) and terminal condition (finish line; final speed free, "
         "no credit for remaining kinetic energy) are identical for all of them, and so are the finish target "
         f"({out['t_max_s']:.0f} s limit − {out['reserve_s']:.0f} s reserve), the torque limit, slews, the "
         "acceleration bound, the auxiliary load and the driver model (reaction "
         f"{out['guidance_assumptions']['reaction_s']} s, release {out['guidance_assumptions']['release_reaction_s']} s). "
         "Nothing brakes automatically. Overspeed above a corner limit, or a missed stop, makes a run INVALID.", "",
         "## 1. Battery-terminal energy accounting (see `docs/ENERGY_ACCOUNTING.md`)", "",
         "| v m/s | T N*m | shaft W | motor friction W | Cu+Fe W | inverter W | aux W | battery W | wheel W | drivetrain loss W |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for p in out["accounting"]:
        L.append(f"| {p['v_mps']} | {p['torque_Nm']} | {p['shaft_W']:.2f} | {p['motor_friction_W']:.2f} | "
                 f"{p['motor_cu_fe_W']:.2f} | {p['inverter_W']:.2f} | {p['aux_W']:.2f} | {p['total_W']:.2f} | "
                 f"{p['wheel_W']:.2f} | {p['drivetrain_loss_W']:.2f} |")
    L += ["", "v0.1 charged `T·ω` and omitted the motor's own friction power `T_f·ω` (the 'motor friction' column) "
          "while driving. v0.2 charges the electromagnetic power `(T+T_f)·ω`.", "",
          "## 2. Acceleration-clipping audit", "",
          "v0.1 clipped the *acceleration* (`a = min(a, a_max)`) but charged the energy of the *full* torque. The "
          "fix limits the torque itself, so the force, torque, power and energy belong to the same operating point. "
          "Test: constant 2 N·m launch, 20 s.", "",
          "| a_max | method | steps limited | battery J | tractive work J | ΔKE J | resistive J | residual J |",
          "|---|---|---|---|---|---|---|---|"]
    for amax, d in out["accel_clip_audit"].items():
        for meth, x in d.items():
            L.append(f"| {amax} | {meth} | {x['steps_limited']} | {x['battery_J']} | {x['tractive_work_J']} | "
                     f"{x['delta_ke_J']} | {x['resistive_work_J']} | **{x['residual_J']}** |")
    L += ["", "With the synthetic `a_max` = 1.5 m/s² the limit never binds (2 N·m produces < 0.8 m/s²), so the v0.1 "
          "numbers were **not** distorted by clipping. With a binding limit, the v0.1 clip creates work that "
          "appears in neither kinetic energy nor losses (non-zero residual). The v0.2 limit has none.", "",
          "## 3. DP grid convergence (track A, propulsion + coast + driver braking)", "",
          "| ds m | dv m/s | DP battery J | DP brake J | DP time s | executed battery J | executed time s | valid | solve s |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in out["grid_convergence"]:
        r = c["realized"]
        L.append(f"| {c['ds_m']:g} | {c['dv_mps']:.2f} | {c['dp_energy_J']:.0f} | {c['dp_brake_J']:.0f} | "
                 f"{c['dp_time_s']:.1f} | {r['energy_J']:.0f} | {r['time_s']:.1f} | {r['valid']} | {c['solve_s']:.1f} |")
    L += ["", f"Relative change in DP energy between the two finest grids: {100*out['grid_rel_change_last']:.2f} %. "
          "Comparisons below use the second-finest grid; read their differences against this discretisation "
          "error, and treat optimality as holding only within the discretised model.", ""]
    phys = out["torque_only_physics"]
    for tname, c in out["comparison"].items():
        L += [f"## 4{'a' if tname.startswith('A') else 'b'}. Matched-time comparison, track {tname} "
              f"(grid {c['grid']['ds_m']} m / {c['grid']['dv_mps']} m/s)", "",
              "| strategy | battery J | time s | friction-brake J | aux J | final v m/s | overspeed events (max m/s) | "
              "brake applications | accel events | energy residual J | parameters |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in c["results"].items():
            L.append(f"| {k} | {_fmt(v)} | `{json.dumps(v['params'], default=float)}` |")
        for k, n in c["notes"].items():
            if "reason" in n or not n.get("dp_feasible", True):
                L.append(f"| {k} | n/a | **infeasible** | | | | | | | | {n.get('dp_reason') or n.get('reason')} |")
        L.append("")
        if tname.startswith("A"):
            L += [f"**Torque-only on track A is physically infeasible.** Coasting from rest at 700 m (top of the 1 % "
                  f"descent) reaches {phys['coast_from_rest_700m_speed_at_1050m_mps']:.2f} m/s at the R = 20 m corner, "
                  f"where the limit is {phys['corner_limit_at_1050m_mps']:.2f} m/s. No torque schedule can fix that. "
                  "Meeting that corner needs braking: the driver's friction brake in the first vehicle version, or "
                  "regeneration later (deferred, ADR-0007). The DP reports this; it does not brake silently.", ""]
    L += ["## 5. Driver-guidance robustness (track A braking plan)", "",
          "The plan is issued with an assumed 1.0 s reaction. The rows vary the driver's actual reaction and "
          "achieved deceleration, with and without a planning margin below the corner limits.", "",
          "| case | battery J | time s | friction-brake J | aux J | final v | overspeed events (max m/s) | brake applications | accel events | residual J |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in out["guidance_robustness"].items():
        L.append(f"| {k} | {_fmt(v)} |")
    L += ["", "## 6. Robustness of the fixed braking plan to model error", "",
          "| case | DP no pace E / T / valid | DP + bounded pace E / T / valid |", "|---|---|---|"]
    for k, v in out["model_robustness"].items():
        f = lambda d: (f"{d['energy_J']:.0f} J / {d['time_s']:.1f} s / "  # noqa: E731
                       f"{'valid' if d['valid'] else ('**OVER LIMIT**' if d['over_time_limit'] else '**INVALID**')}")
        L.append(f"| {k} | {f(v['dp_no_pace'])} | {f(v['dp_with_pace'])} |")
    L += ["", "## 7. Superseded v0.1 figures", "",
          "The v0.1 study (39.7 kJ DP, 46.2 kJ pulse-and-coast, 55.1 kJ constant speed, i.e. 28 % and 14 % "
          "'savings') is **withdrawn**. Its DP exported braking segments as coast. Its simulator braked every "
          "strategy automatically to an envelope. Its power map omitted the motor friction power. Use only the "
          "v0.2 tables above, and only as a demonstration of method on synthetic models.", ""]
    (GEN / "optimization_synthetic.md").write_text("\n".join(L))


def _plot(planA, planB, trackA, trackB):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figdir = FIGDIR
    figdir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    lap = trackA.lap_length_m
    sel = planA.s <= lap
    ax[0].plot(planA.s[sel], planA.v[sel], lw=1.2, label="plan: propulsion+coast+driver brake (track A)")
    if planB is not None:
        ax[0].plot(planB.s[planB.s <= lap], planB.v[planB.s <= lap], lw=1.0, label="plan: torque only (flat track B)")
    ax[0].plot(planA.s[sel], [trackA.v_limit(x) for x in planA.s[sel]], "k--", lw=0.8, label="corner limit")
    ax[0].set_ylabel("speed [m/s]")
    ax[0].legend(loc="lower right", fontsize=8)
    seg = planA.s[:-1][sel[:-1]]
    ax[1].step(seg, planA.u_torque[sel[:-1]], where="post", lw=1.0)
    ax[1].set_ylabel("controller torque [N*m]")
    ax[2].step(seg, planA.u_brake_N[sel[:-1]], where="post", lw=1.0, color="#b00")
    ax[2].set_ylabel("DRIVER brake force [N]")
    ax[2].set_xlabel("position in lap 1 [m]")
    fig.suptitle("SYNTHETIC - DP plan, first lap (not a real vehicle or track)", color="#b00")
    fig.tight_layout()
    fig.savefig(figdir / "dp_plan_synthetic.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
