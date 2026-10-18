#!/usr/bin/env python3
"""Speed hold vs pulse-and-coast through the controller core and the host plant (HOST SIMULATION).

    python3 tools/run_policy_comparison.py [--build build] [--duration 200]

Each policy runs as the supervisor of the lockstep co-simulation
(host/telemetry_adapter/e2e.py): its requests pass the controller's freshness
checks, state machine, ceilings and slew, and the host plant integrates the
motor and vehicle. Energy is the plant's battery-terminal energy; the measure
is energy per metre over the steady part of the run (after 40 s), so a small
difference in average speed does not decide the comparison.

The host plant's losses are copper and current-proportional inverter terms
only (firmware/platform/host/sim_plant.c): it has no loss that is independent
of torque while driving. This is the case in which pulse-and-glide is not
expected to help (docs/MATH_SPEC.md 4.5). The synthetic physics map of the
optimisation study (models/vehicle/powertrain.py) has such a loss (iron loss
~ w^1.5) and reaches the opposite result. Which case the vehicle is in has to
be measured (input sheet: loss map / coast-down).
Writes docs/generated/policy_comparison_host.md.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from host.telemetry_adapter.e2e import Scenario, run  # noqa: E402
from host.telemetry_adapter.supervisor import pulse_and_coast_policy, speed_hold_policy  # noqa: E402
from tools import config_tool as ct  # noqa: E402

T0 = 40.0


def measure(rows, t0: float, m_eff: float, kt: float, r_s: float):
    """Energy per metre over whole cycles: for pulse-and-coast the window runs from
    the first to the last gate-on instant after t0 (the same point of the cycle,
    so the same speed); for steady policies from t0 to the end. Reports the
    kinetic-energy change that remains in the window and a loss decomposition."""
    r = [x for x in rows if float(x["t_s"]) >= t0]
    on = [i for i in range(1, len(r)) if r[i]["pwm_enable"] == "1" and r[i - 1]["pwm_enable"] == "0"]
    gate_on_events = len(on)
    if 2 <= gate_on_events <= len(r) // 20:          # cycling, not chattering every step
        r = r[on[0]:on[-1] + 1]
    a, b = r[0], r[-1]
    ds = float(b["s_m"]) - float(a["s_m"])
    de = float(b["energy_plant_J"]) - float(a["energy_plant_J"])
    dt = float(b["t_s"]) - float(a["t_s"])
    dke = 0.5 * m_eff * (float(b["v_mps"]) ** 2 - float(a["v_mps"]) ** 2)
    cu = mech = 0.0
    for x, y in zip(r, r[1:]):
        h = float(y["t_s"]) - float(x["t_s"])
        iq, idd, w = float(x["iq_meas_A"]), float(x["id_meas_A"]), float(x["speed_mech_rad_s"])
        cu += 1.5 * r_s * (iq * iq + idd * idd) * h
        mech += kt * iq * w * h
    coast = sum(1 for x in r if x["pwm_enable"] == "0") / len(r)
    return {"J_per_m": de / ds, "v_mean": ds / dt, "energy_J": de, "distance_m": ds, "coast_fraction": coast,
            "dKE_J_per_m": dke / ds, "cu_J_per_m": cu / ds, "mech_J_per_m": mech / ds,
            "other_J_per_m": (de - cu - mech) / ds, "gate_on_events": gate_on_events, "window_s": dt}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=pathlib.Path, default=ROOT / "build")
    ap.add_argument("--duration", type=float, default=200.0)
    a = ap.parse_args()
    cfg = ct.load_yaml(ROOT / "config" / "vehicle.synthetic.yaml")
    C, G, tmax = cfg["vehicle"]["wheel_circumference_m"], cfg["vehicle"]["gear_ratio"], cfg["limits"]["max_motor_torque_Nm"]
    kt = 1.5 * cfg["motor"]["pole_pairs"] * cfg["motor"]["flux_linkage_Wb"]
    r_w = C / (2 * 3.141592653589793)
    m_eff = cfg["vehicle"]["mass_with_driver_kg"] + cfg["motor"]["inertia_kg_m2"] * G * G / (r_w * r_w)
    cases = [("speed hold 6.0 m/s", speed_hold_policy(6.0, 1.5, C, G, tmax))]
    for lo, hi, tq in ((5.5, 6.5, 1.0), (5.5, 6.5, 2.0), (5.0, 7.0, 1.0)):
        cases.append((f"pulse {tq:.1f} N*m, coast {lo:.1f}-{hi:.1f} m/s", pulse_and_coast_policy(lo, hi, tq, C, G)))
    res = []
    for name, pol in cases:
        out = ROOT / "build" / "policy_cmp" / name.replace(" ", "_").replace("*", "").replace("/", "")
        rr = run(Scenario(duration_s=a.duration, supervisor_off_at_s=None, policy=pol), a.build, out)
        res.append((name, measure(rr.csv_rows, T0, m_eff, kt, cfg["motor"]["phase_resistance_ohm"])))
        m = res[-1][1]
        print(f"{name:42s} {m['J_per_m']:.3f} J/m at {m['v_mean']:.2f} m/s, gates off {m['coast_fraction'] * 100:.0f} %, "
              f"dKE {m['dKE_J_per_m']:+.3f} J/m, cu {m['cu_J_per_m']:.3f}, mech {m['mech_J_per_m']:.3f}, "
              f"other {m['other_J_per_m']:.3f}, window {m['window_s']:.0f} s")
    base = res[0][1]["J_per_m"]
    L = ["# Speed hold vs pulse-and-coast on the host plant (HOST SIMULATION)", "",
         f"Command: `python3 tools/run_policy_comparison.py --duration {a.duration:.0f}`. Each policy is the supervisor "
         "of the co-simulation; its requests pass the controller core; energy is the host plant's battery-terminal "
         f"energy. Window: whole pulse-and-coast cycles after {T0:.0f} s (gate-on to gate-on), or {T0:.0f} s to the "
         "end for steady policies. Synthetic configuration and plant.", "",
         "| policy | J/m | vs speed hold | mean speed m/s | gates off | window s | remaining dKE J/m | "
         "copper J/m | kt iq w J/m | other J/m | gate-on events |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in res:
        L.append(f"| {name} | {m['J_per_m']:.3f} | {100 * (m['J_per_m'] / base - 1):+.1f} % | {m['v_mean']:.2f} | "
                 f"{m['coast_fraction'] * 100:.0f} % | {m['window_s']:.0f} | {m['dKE_J_per_m']:+.3f} | "
                 f"{m['cu_J_per_m']:.3f} | {m['mech_J_per_m']:.3f} | {m['other_J_per_m']:.3f} | "
                 f"{m['gate_on_events']} |")
    L += ["", "Reading the table: 'kt iq w' is the electromagnetic work, 'copper' the I^2R loss computed from the "
          "measured currents (1.5 R (id^2 + iq^2)), 'other' the remainder (inverter and plant terms). The "
          "electromagnetic work per metre is set by the road load and is nearly the same for every policy at the "
          "same mean speed, so the policies differ through the copper loss (higher pulses: more I^2R) and through "
          "the 'other' term. This host plant has no loss that is independent of torque while driving; the "
          "optimisation study's synthetic physics map has one (iron loss ~ w^1.5), and there pulse-and-coast "
          "saves energy (`optimization_synthetic.md` 4b). Which case the vehicle is in has to be measured.", ""]
    (ROOT / "docs" / "generated" / "policy_comparison_host.md").write_text("\n".join(L))
    print("wrote docs/generated/policy_comparison_host.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
