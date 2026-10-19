#!/usr/bin/env python3
"""Minimal reproducible case of the frozen CSIA adapter's disagreement on a clean simulated run (SIMULATED).

    python3 tools/csia_disagreement_case.py            # writes docs/generated/csia_clean_run_case.md
    python3 tools/csia_disagreement_case.py --check    # exit 1 if the page is stale

Verification record 11.3 reported that, on the simulated slowdown run of EXP-01 (every sensor correct), the frozen
CSIA vehicle adapter behind the shadow boundary reported an unattributed disagreement in 328 of 550 ticks. This tool
reproduces that number and takes it apart:

  A  the clean run, through the boundary as it was then (iq and p_dc passed, the adapter's default torque constant):
     ticks per explanation, the relationships failing, the operating condition (simulation truth) of failing ticks
  B  a minimal case on the frozen adapter itself: rotor speed, iq and p_dc held constant and simultaneous at two
     steady operating points of the same simulated vehicle; the E6 power balance and the torque constant that would
     balance each point
  C  the cause, classified
  D  the run again through the boundary as it is now (iq and p_dc withheld without a stated torque constant)

Nothing here changes the frozen adapter, its parameters or the frozen evaluation (docs/csia/); nothing here compares
it with the witness relations, which have no power-balance relation on these inputs. Simulated data only.
"""
from __future__ import annotations

import argparse
import collections
import math
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.assurance import csia_boundary as B  # noqa: E402
from host.pit import ingest  # noqa: E402
from host.telematics import sim_session  # noqa: E402
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig  # noqa: E402
from tools.run_vehicle_experiment import slowdown  # noqa: E402

DOC = ROOT / "docs" / "generated" / "csia_clean_run_case.md"
RADIUS = 1.5 / (2 * math.pi)
GEAR, FREEWHEEL = 10.0, False


def _adapter(kt=None):
    from host.csia_adapter.adapter import AdapterParams, VehicleCsiaAdapter
    kw = {} if kt is None else {"kt_Nm_per_A": kt}
    return VehicleCsiaAdapter(AdapterParams(wheel_radius_m=RADIUS, gear_ratio=GEAR, freewheel=FREEWHEEL, **kw))


def clean_run(workdir: pathlib.Path) -> dict:
    """A: the EXP-01 slowdown run (55 s, fixed seed) through the boundary of verification record 11."""
    from host.csia_adapter.adapter import Explain
    sim = sim_session.simulate(workdir, Faults(), 55.0, profile=slowdown, unit="TLMSIM-CSIA")
    db = ingest.connect(workdir / "pit.sqlite")
    rid, path = sim["runs"][0]
    ingest.import_log(db, path)
    data, _gate = B.qualified_samples(db, rid, accept_assumed_timing=True, power_inputs=True)
    ad = _adapter()
    lam_fail = ad.p.lam_fail
    truth = sim["truth"]                                   # (t, v, distance) in simulation time
    clock = sim["clock"]
    expl, fail, by_cond = collections.Counter(), collections.Counter(), collections.Counter()
    k, t, t1 = 0, data[0][0] + 0.1, data[-1][0]
    prev_v = None
    while t <= t1:
        while k < len(data) and data[k][0] <= t:
            ad.ingest(data[k][1], data[k][2])
            k += 1
        st = ad.tick(t)
        e = Explain(int(st.explanation)).name
        expl[e] += 1
        failing = sorted(r for r, lv in st.lambdas.items() if isinstance(lv, float) and math.isfinite(lv)
                         and lv > lam_fail)
        for r in failing:
            fail[r] += 1
        ts = clock.true(t)
        i = min(max(int(round(ts / 0.01)) - 1, 0), len(truth) - 1)
        v = truth[i][1]
        a = (v - truth[max(i - 50, 0)][1]) / 0.5 if i >= 50 else 0.0
        cond = ("stopped" if v < 0.5 else "accelerating" if a > 0.15 else "decelerating" if a < -0.15 else
                f"steady {v:.1f} m/s" if abs(v - 6.5) < 0.2 or abs(v - 4.0) < 0.2 else "transient")
        if failing:
            by_cond[cond] += 1
        prev_v = v
        t = round(t + 0.1, 6)
    db.close()
    return {"ticks": sum(expl.values()), "explanations": dict(expl), "failing": dict(fail),
            "failing_by_condition": dict(by_cond)}


def steady_point(v_target: float) -> dict:
    sim = VehicleSim(VehicleSimConfig(), Faults(), lambda t: v_target if t > 1.0 else 0.0)
    for k in range(1, 4001):
        sim.step(k * 0.01, 0.01)
    rotor = sim.v / sim.p.wheel_radius_m * sim.p.gear_ratio
    return {"v": sim.v, "rotor": rotor, "i_dc": sim.i_ctrl, "v_bus": sim.v_bus, "iq": sim.i_ctrl * 0.9,
            "p_dc": sim.v_bus * sim.i_ctrl}


def minimal(pt: dict, kt=None, secs: float = 3.0) -> tuple[str, float]:
    """B: the frozen adapter fed only rotor, iq and p_dc, constant and simultaneous (no timing effect possible)."""
    from host.csia_adapter.adapter import Explain, Sample
    ad = _adapter(kt)
    st, seq, t = None, 0, 0.0
    while t < secs:
        t = round(t + 0.01, 6)
        seq += 1
        for name, val, sg in (("rotor", pt["rotor"], 0.01 * pt["rotor"] + 2.0), ("iq", pt["iq"], 0.15),
                              ("p_dc", pt["p_dc"], 1.0)):
            ad.ingest(name, Sample(val, sg, t, "controller", t, seq, 1, {}))
        if abs(t * 10 - round(t * 10)) < 1e-9:
            st = ad.tick(t)
    return Explain(int(st.explanation)).name, st.lambdas["E6_power_balance"]


def balancing_kt(pt: dict) -> float:
    """The torque constant for which the adapter's E6 expectation (1 + 0.08) kt iq rotor + 3 W equals p_dc."""
    return (pt["p_dc"] - 3.0) / (1.08 * pt["iq"] * pt["rotor"])


def boundary_now(workdir: pathlib.Path) -> dict:
    db = ingest.connect(workdir / "pit.sqlite")
    rid = db.execute("SELECT run_id FROM runs").fetchone()[0]
    r = B.run(db, rid, RADIUS, GEAR, FREEWHEEL)
    db.close()
    return r


def render(a: dict, pts: dict, mins: dict, kts: dict, cross: dict, now: dict) -> str:
    L = ["# CSIA clean-run disagreement: minimal reproducible case (SIMULATED)", "",
         "Generated by `python3 tools/csia_disagreement_case.py`; do not edit. Simulated data only. The frozen CSIA "
         "adapter, its parameters and the frozen evaluation (`docs/csia/`) are unchanged; nothing here compares the "
         "adapter with the witness relations, which have no power-balance relation on these inputs.", "",
         "## A. Reproduction", "",
         f"EXP-01 slowdown run (55 s, every sensor correct), through the shadow boundary as recorded in verification "
         f"record 11 (iq and p_dc passed; the adapter's default torque constant): {a['ticks']} ticks.", "",
         "| Explanation | Ticks |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(a["explanations"].items())]
    L += ["", "| Relationship above its failure threshold (lambda > 9) | Ticks |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(a["failing"].items())] or ["| none | 0 |"]
    L += ["", "| Operating condition of the failing ticks (simulation truth) | Ticks |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(a["failing_by_condition"].items())]
    L += ["", "## B. Minimal case", "",
          "The frozen adapter fed three inputs only (rotor speed, iq, p_dc), held constant and simultaneous for 3 s "
          "at two steady operating points of the same simulated vehicle. With constant simultaneous inputs no timing "
          "effect is possible.", "",
          "| Point | Rotor [rad/s] | DC current [A] | iq (fixture) [A] | p_dc [W] | E6 lambda, default kt 0.06 | "
          "Explanation | kt that balances E6 [N m/A] |", "|---|---|---|---|---|---|---|---|"]
    for name, pt in pts.items():
        e, lam = mins[name]
        L.append(f"| {name} | {pt['rotor']:.1f} | {pt['i_dc']:.3f} | {pt['iq']:.3f} | {pt['p_dc']:.2f} | {lam:.2f} | "
                 f"{e} | {kts[name]:.3f} |")
    L += ["", f"The torque constants that balance the two points exactly differ ({kts['cruise 6.5 m/s']:.3f} and "
          f"{kts['cruise 4.0 m/s']:.3f} N m/A): with the fixture's iq the balancing value goes as v_bus / (0.9 x rotor "
          "speed), so it changes with speed, which a motor's torque constant does not. Within E6's tolerance the "
          f"difference is hidden: with {kts['cruise 6.5 m/s']:.3f} the 4.0 m/s point gives lambda {cross['lam']:.2f} "
          f"({cross['expl']}). Fitting kt to this data would therefore mask the input mismatch, not resolve it, and it "
          "would be tuning; it is not done.", "",
          "## C. Cause", "",
          "* **Relationship:** E6 power balance only. E1, E2, E3a, E3b and E7 stay far below their threshold on the "
          "same run.",
          "* **Admissible inputs:** p_dc (ctrl.dc_voltage x ctrl.dc_current, aligned within 20 ms), iq "
          "(ctrl.phase_current_q), rotor (ctrl.motor_speed), all from the semmc fixture's 100 Hz frames.",
          "* **Timing:** not the cause: the minimal case uses constant, simultaneous inputs and fails the same way.",
          "* **Operating context:** the failures are at the higher steady speed and in transients with power; at "
          "4.0 m/s steady the residual stays under the threshold.",
          "* **Model assumptions:** E6 expects p_dc = (1 + 0.08) x kt x iq x rotor + 3 W, with iq the motor's q-axis "
          "current and kt the motor's torque constant. The boundary gave no kt (the motor data are open, B-MOTOR), so "
          "the adapter used its default 0.06 N m/A; and the simulation fixture's `ctrl_motion.iq_A` is 0.9 x the DC "
          "current, an illustrative field, not a current consistent with any torque.",
          "* **Classification:** an adapter input mismatch in an unsupported configuration: a required parameter "
          "defaulted and an input whose meaning differs from the relationship's model. Not a timing defect. Not shown "
          "to be a limitation of the CSIA algorithm: the case says nothing about E6 with a real motor's kt and a real "
          "q-axis current.", "",
          "## D. The boundary now", "",
          "The shadow boundary now withholds iq and p_dc unless the caller states the motor's torque constant, so E6 "
          "is gated instead of evaluated with a default, and it lists the adapter parameters left at their frozen "
          "defaults.", "", "| Verdict | Ticks |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in sorted(now["verdicts"].items())]
    L += ["", "Withheld for want of a torque constant: " + ", ".join(
        f"`{s}` {n['no torque constant']}" for s, n in sorted(now["gate"]["withheld"].items())
        if "no torque constant" in n) + ".", "",
          "Adapter parameters left at the frozen defaults: " + ", ".join(
              f"`{k}` = {v}" for k, v in sorted(now["adapter_defaults"].items())) + ".", ""]
    return "\n".join(L)


def build() -> str:
    work = pathlib.Path(tempfile.mkdtemp(prefix="csia_case_"))
    try:
        a = clean_run(work)
        pts = {"cruise 6.5 m/s": steady_point(6.5), "cruise 4.0 m/s": steady_point(4.0)}
        mins = {k: minimal(p) for k, p in pts.items()}
        kts = {k: balancing_kt(p) for k, p in pts.items()}
        e, lam = minimal(pts["cruise 4.0 m/s"], kts["cruise 6.5 m/s"])
        now = boundary_now(work)
        return render(a, pts, mins, kts, {"expl": e, "lam": lam}, now)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = build()
    if a.check:
        if not DOC.exists() or DOC.read_text() != text:
            print(f"stale: {DOC.relative_to(ROOT)} (run tools/csia_disagreement_case.py)")
            return 1
        print("csia clean-run case current")
        return 0
    DOC.write_text(text)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
