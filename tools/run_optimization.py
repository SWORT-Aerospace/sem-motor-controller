#!/usr/bin/env python3
"""SYNTHETIC energy-strategy study: DP grid convergence, matched-time strategy
comparison, robustness to model error, and a bounded schedule export.

    python3 tools/run_optimization.py [--quick]

Writes docs/generated/optimization_synthetic.md, docs/figures/*.png and
build/schedules/dp_schedule_synthetic.csv. Every number is from synthetic
vehicle, motor, inverter and track models; none predicts real-vehicle energy.
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
from models.optimization.strategies import (PaceCorrector, SimConfig, bisect_param, constant_speed,  # noqa: E402
                                            pulse_and_coast, schedule_follower, simulate)
from models.optimization.track import synthetic_track  # noqa: E402
from models.vehicle.longitudinal import SYNTHETIC_VEHICLE  # noqa: E402
from models.vehicle.powertrain import SyntheticPhysicsMap  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
T_MAX = 1000.0
RESERVE = 30.0


def run_dp(track, veh, pmap, ds, dv, n_torque=10):
    t0 = time.time()
    cfg = dp.DPConfig(ds_m=ds, dv_mps=dv, n_torque=n_torque, t_max_s=T_MAX, reserve_s=RESERVE)
    r = dp.solve(track, veh, pmap, cfg)
    return r, time.time() - t0


def evaluate_dp(r, track, veh, pmap, sim, pace=None):
    ctrl = schedule_follower(r.s[:-1], r.u_torque, r.u_coast, r.t[:-1], sim.torque_max_Nm, pace)
    return simulate(track, veh, pmap, ctrl, sim)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="coarser grids (CI)")
    args = ap.parse_args()
    track, veh = synthetic_track(), SYNTHETIC_VEHICLE
    pmap = SyntheticPhysicsMap(veh)
    sim = SimConfig()
    t_target = T_MAX - RESERVE
    out = {"label": "SYNTHETIC", "t_max_s": T_MAX, "reserve_s": RESERVE, "track_m": track.length_m}

    # 1. grid convergence
    grids = [(20.0, 0.4), (10.0, 0.2)] if args.quick else [(20.0, 0.4), (10.0, 0.2), (5.0, 0.1)]
    conv = []
    best = None
    for ds, dv in grids:
        r, el = run_dp(track, veh, pmap, ds, dv)
        realized = evaluate_dp(r, track, veh, pmap, sim)
        conv.append({"ds_m": ds, "dv_mps": dv, "dp_energy_J": r.energy_J, "dp_time_s": r.time_s,
                     "feasible": r.feasible, "lambda": r.lam, "solve_s": el,
                     "realized_energy_J": realized.energy_J, "realized_time_s": realized.time_s})
        best = r
    out["grid_convergence"] = conv
    e = [c["dp_energy_J"] for c in conv]
    out["grid_rel_change_last"] = abs(e[-1] - e[-2]) / e[-1]

    # 2. matched-time comparison on the common forward simulator
    res = {}
    v_cs = bisect_param(lambda x: simulate(track, veh, pmap, constant_speed(x, veh), sim).time_s, 3.0, 12.0, t_target)
    res["constant_speed"] = (simulate(track, veh, pmap, constant_speed(v_cs, veh), sim), {"v_set_mps": v_cs})
    best_pc = None
    for width in (0.5, 1.0, 2.0):
        for frac in (0.5, 1.0):
            Tp = frac * sim.torque_max_Nm
            def tfun(c, width=width, Tp=Tp):
                return simulate(track, veh, pmap, pulse_and_coast(c - width / 2, c + width / 2, Tp), sim).time_s
            c = bisect_param(tfun, 3.0, 11.0, t_target, iters=22)
            rr = simulate(track, veh, pmap, pulse_and_coast(c - width / 2, c + width / 2, Tp), sim)
            if rr.finished and rr.time_s <= t_target + 0.5 and (best_pc is None or rr.energy_J < best_pc[0].energy_J):
                best_pc = (rr, {"band_center_mps": c, "band_width_mps": width, "pulse_torque_Nm": Tp})
    res["pulse_and_coast_best_of_6"] = best_pc
    pace = PaceCorrector()
    res["dp_schedule"] = (evaluate_dp(best, track, veh, pmap, sim), {"ds_m": best.cfg.ds_m, "dv_mps": best.cfg.dv_mps})
    res["dp_schedule_with_pace"] = (evaluate_dp(best, track, veh, pmap, sim, pace),
                                    {"pace_k": pace.k_Nm_per_s, "pace_bound_Nm": pace.bound_Nm})
    out["comparison"] = {k: {"energy_J": v[0].energy_J, "time_s": v[0].time_s, "finished": v[0].finished,
                             "accel_events": v[0].n_accel_events, "brake_energy_J": v[0].brake_energy_J,
                             "params": v[1]} for k, v in res.items()}

    # 3. robustness: the SAME plans/controllers on perturbed vehicles
    perturb = {"nominal": {}, "crr+20%": {"crr": veh.crr * 1.2}, "cda+20%": {"cda_m2": veh.cda_m2 * 1.2},
               "mass+5%": {"mass_kg": veh.mass_kg * 1.05}, "crr-20%": {"crr": veh.crr * 0.8}}
    rob = {}
    for name, kw in perturb.items():
        vp = dataclasses.replace(veh, **kw)
        pm = SyntheticPhysicsMap(vp)
        rob[name] = {
            "dp_no_pace": _summ(evaluate_dp(best, track, vp, pm, sim)),
            "dp_with_pace": _summ(evaluate_dp(best, track, vp, pm, sim, pace)),
            "constant_speed": _summ(simulate(track, vp, pm, constant_speed(v_cs, vp), sim)),
        }
    head = dataclasses.replace(sim, wind_mps=-2.0)
    rob["headwind 2 m/s"] = {
        "dp_no_pace": _summ(evaluate_dp(best, track, veh, pmap, head)),
        "dp_with_pace": _summ(evaluate_dp(best, track, veh, pmap, head, pace)),
        "constant_speed": _summ(simulate(track, veh, pmap, constant_speed(v_cs, veh), head)),
    }
    out["robustness"] = rob

    # 4. export bounded schedule
    sched = ROOT / "build" / "schedules" / "dp_schedule_synthetic.csv"
    dp.export_schedule(best, sched, sim.torque_max_Nm, pmap.label)
    out["schedule_csv"] = str(sched.relative_to(ROOT))

    (ROOT / "docs" / "generated").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "generated" / "optimization_synthetic.json").write_text(json.dumps(out, indent=1, default=float))
    _write_md(out)
    _plot(best, res, track)
    print(json.dumps({k: out[k] for k in ("grid_convergence", "grid_rel_change_last", "comparison")}, indent=1,
                     default=float))
    return 0


def _summ(r):
    return {"energy_J": round(r.energy_J, 1), "time_s": round(r.time_s, 1), "finished": r.finished}


def _write_md(out):
    L = ["# Optimisation study - SYNTHETIC", "",
         "> **SYNTHETIC.** Vehicle, motor, inverter, battery and track are invented placeholders "
         "(config/vehicle.synthetic.yaml, models/*). These numbers demonstrate the method; they say nothing "
         "about the real vehicle. Generated by `tools/run_optimization.py`.", "",
         f"Track {out['track_m']:.0f} m, finish-time limit {out['t_max_s']:.0f} s, planning reserve "
         f"{out['reserve_s']:.0f} s (target {out['t_max_s'] - out['reserve_s']:.0f} s).", "",
         "## DP grid convergence", "", "| ds m | dv m/s | DP energy J | DP time s | realized energy J | realized time s | solve s |",
         "|---|---|---|---|---|---|---|"]
    for c in out["grid_convergence"]:
        L.append(f"| {c['ds_m']:.0f} | {c['dv_mps']:.2f} | {c['dp_energy_J']:.0f} | {c['dp_time_s']:.1f} | "
                 f"{c['realized_energy_J']:.0f} | {c['realized_time_s']:.1f} | {c['solve_s']:.1f} |")
    L += ["", f"Relative change in DP energy between the two finest grids: {100*out['grid_rel_change_last']:.2f} %. "
          "Optimality is claimed only within the discretised model.", "",
          "## Matched-time comparison (common forward simulator with slew limits)", "",
          "| strategy | energy J | time s | finished | acceleration events | brake energy J | parameters |",
          "|---|---|---|---|---|---|---|"]
    for k, v in out["comparison"].items():
        L.append(f"| {k} | {v['energy_J']:.0f} | {v['time_s']:.1f} | {v['finished']} | {v['accel_events']} | "
                 f"{v['brake_energy_J']:.0f} | `{json.dumps(v['params'], default=float)}` |")
    L += ["", "## Robustness of fixed plans to model error", "",
          "| case | DP no pace E/T | DP + bounded pace E/T | constant speed E/T |", "|---|---|---|---|"]
    for k, v in out["robustness"].items():
        f = lambda d: f"{d['energy_J']:.0f} J / {d['time_s']:.1f} s{'' if d['finished'] else ' DNF'}"  # noqa: E731
        L.append(f"| {k} | {f(v['dp_no_pace'])} | {f(v['dp_with_pace'])} | {f(v['constant_speed'])} |")
    L += ["", "A time above the limit is a failed attempt regardless of energy. The reserve and the bounded pace "
          "correction exist for exactly these cases; their sizes must come from measured model uncertainty.", ""]
    (ROOT / "docs" / "generated" / "optimization_synthetic.md").write_text("\n".join(L))


def _plot(best, res, track):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figdir = ROOT / "docs" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    lap = track.lap_length_m
    sel = best.s <= lap
    ax[0].plot(best.s[sel], best.v[sel], lw=1.2, label="DP speed (plan)")
    ax[0].plot(best.s[sel], [track.v_limit(x) for x in best.s[sel]], "k--", lw=0.8, label="corner limit")
    ax[0].set_ylabel("speed [m/s]")
    ax[0].legend(loc="lower right")
    ax[1].step(best.s[:-1][sel[:-1]], best.u_torque[sel[:-1]], where="post", lw=1.0)
    ax[1].set_ylabel("motor torque [N*m]")
    ax[1].set_xlabel("position in lap 1 [m]")
    fig.suptitle("SYNTHETIC - DP plan, first lap (not a real vehicle or track)", color="#b00")
    fig.tight_layout()
    fig.savefig(figdir / "dp_plan_synthetic.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
