#!/usr/bin/env python3
"""Simulated pre-checks of the vehicle-validation protocols (research/vehicle_validation/). SIMULATED only.

    python3 tools/run_vehicle_experiment.py --out build/vehicle_experiments [--only EXP-01]

Each protocol (EXP-01 to EXP-04) states what a disturbance should look like in the evidence (its signature) and what
would show the analysis wrong (its falsifier). Before anyone drives, this runs the whole analysis chain on simulated
drives in which the disturbance is known exactly:

    sim_session (vehicle model, external-controller stand-in, receive-only node, STLG log)
      -> host/pit/ingest.py (records, measurements, evidence, stream timing)
      -> host/assurance/review.py (context, witnesses, conclusions, receipts)
      -> this file: the protocol's signature and falsifier checked against the result

What a PASS here means: the host analysis, on synthetic data, separates the cases the protocol needs it to separate.
What it does not mean: anything about the vehicle, its sensors or the firmware. The vehicle result of a protocol
exists only once its run sheet is filled in from a physical test with the independent ground truth the protocol
names. A FAIL is kept and reported, not tuned away: change the protocol or the analysis on purpose, with a reason.

Parameters the simulation knows exactly (gear ratio, freewheel, coast-down deceleration) are passed to the review as
SIMULATION values; on the vehicle they are UNSUPPORTED until the vehicle team states them with a source.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import shutil
import sys
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.assurance import review, verdicts  # noqa: E402
from host.pit import ingest  # noqa: E402
from host.telematics import sim_session  # noqa: E402
from host.telematics.node import NodeConfig  # noqa: E402
from host.telematics.sim_vehicle import Faults, VehicleSimConfig, default_profile  # noqa: E402
from host.telematics.wheel import WheelConfig  # noqa: E402
from models.vehicle.longitudinal import SYNTHETIC_VEHICLE, resistive_force  # noqa: E402

DATA_CLASS = "SIMULATED"
SIM_PARAMS = {"drivetrain.gear_ratio": SYNTHETIC_VEHICLE.gear_ratio, "drivetrain.freewheel": False,
              "vehicle.coast_decel_mps2": round(resistive_force(SYNTHETIC_VEHICLE, 6.5) / SYNTHETIC_VEHICLE.mass_kg, 4)}
PAIRS = (("wheel_l", "wheel_r"),)


def slowdown(t: float) -> float:
    """A real slowdown: 6.5 m/s; the driver brakes from 25 s to 29 s (the model brakes at 0.6 m/s^2 while the target
    is 0, so to about 4 m/s); 4.0 m/s to 45 s; then 6.5 m/s again."""
    if 25.0 <= t < 29.0:
        return 0.0
    if 29.0 <= t < 45.0:
        return 4.0
    return default_profile(t)


@dataclasses.dataclass(frozen=True)
class Variant:
    exp: str
    name: str
    what: str
    duration: float = 55.0
    faults: Faults = dataclasses.field(default_factory=Faults)
    profile: Callable[[float], float] = default_profile
    power_cuts: tuple = ()
    can_delay: tuple = ()
    can_stall: tuple = ()
    configured_circumference_m: Optional[float] = None   # the unit's setting when it differs from the true 1.50 m


VARIANTS = (
    Variant("EXP-01", "wheel_corruption", "wheel_l edges at 0.85 x the true rate from 25 s to 45 s (a wrong "
            "circumference or lost edges): plausible but wrong speed on one path",
            faults=Faults(wheel_scale=((0, 25.0, 45.0, 0.85),))),
    Variant("EXP-01", "shared_scaling_error", "the unit is configured with a circumference 15 % short (1.275 m for "
            "1.50 m): every wheel speed and the motor speed through the drivetrain read 15 % low together; GNSS is "
            "right", configured_circumference_m=1.275),
    Variant("EXP-01", "real_slowdown", "the driver brakes from 6.5 to about 4 m/s from 25 s to 29 s and holds 4.0 m/s "
            "to 45 s; every sensor is correct", profile=slowdown),
    Variant("EXP-02", "real_drag", "a 150 N drag the driver model does not know of (a dragging brake) from 25 s to "
            "30 s: the vehicle slows while propulsion power is applied", faults=Faults(extra_drag=((25.0, 30.0, 150.0),))),
    Variant("EXP-02", "imu_offset", "the IMU's longitudinal axis reads 1.2 m/s^2 low from 25 s to 35 s; the vehicle "
            "cruises normally", faults=Faults(imu_offset=((25.0, 35.0, -1.2),))),
    Variant("EXP-03", "unit_power_cut", "the telematics unit loses power at 30.0 s and boots again at 30.5 s "
            "(brown-out); every source stops at once", power_cuts=((30.0, 30.5),)),
    Variant("EXP-03", "independent_losses", "GNSS outage and wheel_l sensor disconnected, both from 30 s to 34 s: two "
            "independent causes at the same time", faults=Faults(gnss_outage=((30.0, 34.0),),
                                                               wheel_disconnect=((0, 30.0, 34.0),))),
    Variant("EXP-04", "can_stall", "controller frames sent from 30.0 s to 30.6 s are held and released together at "
            "30.6 s", can_stall=((30.0, 30.6),)),
    Variant("EXP-04", "can_constant_delay", "controller frames sent from 30 s to 40 s arrive 0.3 s late, in order "
            "(a constant added latency)", can_delay=((30.0, 40.0, 0.3),)),
)


# ---------------------------------------------------------------- timeline helpers
def share(tl: list, a: float, b: float, result: str) -> float:
    """Fraction of [a, b] during which a timeline ([[t_s, value], ...] at changes) shows `result`."""
    if not tl or b <= a:
        return 0.0
    tot = 0.0
    for i, (t0, r) in enumerate(tl):
        t1 = tl[i + 1][0] if i + 1 < len(tl) else float("inf")
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo and r == result:
            tot += hi - lo
    return tot / (b - a)


def ever(tl: list, a: float, b: float, result: str) -> bool:
    return share(tl, a, b, result) > 0.0 or any(a <= t <= b and r == result for t, r in (tl or []))


def inconsistent_outside(res: dict, a: float, b: float) -> list[str]:
    """Relations that were INCONSISTENT outside [a, b] (after the start-up)."""
    t_end = res["t_last_s"]
    return sorted(k for k, tl in res["timeline"].items() if not k.startswith("localization:") and
                  (ever(tl, 6.0, a, "INCONSISTENT") or ever(tl, b, t_end, "INCONSISTENT")))


def statements(res: dict) -> list[str]:
    return [a["statement"] for a in res["ambiguous"].values()] + [c["statement"] for c in res["common_cause"]]


# ---------------------------------------------------------------- signatures and falsifiers per variant
def _c(cid: str, ok: bool, detail: str, role: str = "signature") -> dict:
    return {"id": cid, "role": role, "pass": bool(ok), "detail": detail}


def check(v: Variant, res: list[dict], reps: list[dict], local: Callable[[float], float] = lambda t: t) \
        -> list[dict]:
    """The variant's checks. The analysis only knows the unit's clock; its times are moved back to simulation time
    with `local` (the simulated clock: offset and drift), in which the windows below are written."""
    r = {**res[0], "timeline": {k: [[x[0] - (local(x[0]) - x[0]), x[1]] for x in tl]
                                for k, tl in res[0]["timeline"].items()}}
    r["t_last_s"] = res[0]["t_last_s"] - (local(res[0]["t_last_s"]) - res[0]["t_last_s"])
    r["common_cause"] = [{**c, "t_us": None if c["t_us"] is None else c["t_us"] - (local(c["t_us"] / 1e6) -
                                                                                    c["t_us"] / 1e6) * 1e6}
                         for c in res[0]["common_cause"]]
    tl = r["timeline"]
    out = []
    if v.name == "wheel_corruption":
        a, b = 27.0, 44.0
        for rel in ("B1:wheel_l", "B3:wheel_l-wheel_r", "B2:wheel_l"):
            s = share(tl.get(rel), a, b, "INCONSISTENT")
            out.append(_c(f"{rel} inconsistent", s >= 0.5, f"INCONSISTENT for {s:.0%} of {a:.0f}-{b:.0f} s"))
        s = share(tl.get("B1:wheel_r"), a, b, "CONSISTENT")
        out.append(_c("B1:wheel_r consistent (witness path clean)", s >= 0.5, f"CONSISTENT for {s:.0%}"))
        loc = sorted(k.split(":", 1)[1] for k in r["ambiguous"] if k.startswith("localization:"))
        st = r["ambiguous"].get("localization:wheel.wheel_l.speed", {}).get("statement", "")
        out.append(_c("conditional localization to the wheel_l evidence path only", loc == ["wheel.wheel_l.speed"]
                      and st.startswith("conditional localization"), f"localizations: {loc or 'none'}"))
        out.append(_c("no localization to a correct path", not set(loc) - {"wheel.wheel_l.speed"},
                      f"localizations: {loc or 'none'}", "falsifier"))
        bad = inconsistent_outside(r, 24.0, 47.0)
        out.append(_c("no inconsistency outside the disturbance", not bad, f"outside 24-47 s: {bad or 'none'}"))
    elif v.name == "shared_scaling_error":
        a, b = 20.0, 50.0
        for rel in ("B1:wheel_l", "B1:wheel_r"):
            s_ = share(tl.get(rel), a, b, "INCONSISTENT")
            out.append(_c(f"{rel} inconsistent", s_ >= 0.5, f"INCONSISTENT for {s_:.0%} of {a:.0f}-{b:.0f} s"))
        s_ = share(tl.get("B3:wheel_l-wheel_r"), a, b, "CONSISTENT")
        out.append(_c("the wheels agree with each other", s_ >= 0.5, f"B3 CONSISTENT for {s_:.0%}"))
        amb = {k.split(":", 1)[1]: x for k, x in r["ambiguous"].items() if k.startswith("localization:")}
        g = amb.get("gnss.speed")
        out.append(_c("no confident localization to the correct GNSS path", g is not None and "does not separate" in
                      g["statement"] and g["candidates"][0].startswith("a common value error") and
                      "wheel.circumference_m" in g["candidates"][0],
                      (g["statement"][:160] + " / first candidate: " + g["candidates"][0][:110]) if g else
                      "no conclusion on gnss.speed", "falsifier"))
        out.append(_c("no localization to a wheel path", not [k for k in amb if k.startswith("wheel.")],
                      f"localizations: {sorted(amb) or 'none'}", "falsifier"))
    elif v.name == "real_slowdown":
        bad = sorted(k for k, t in tl.items() if not k.startswith("localization:") and
                     ever(t, 6.0, r["t_last_s"], "INCONSISTENT"))
        out.append(_c("a real slowdown is not an inconsistency", not bad, f"INCONSISTENT relations: {bad or 'none'}",
                      "falsifier"))
        loc = [k for k in r["ambiguous"] if k.startswith("localization:")]
        out.append(_c("no localization", not loc, f"{loc or 'none'}", "falsifier"))
        out.append(_c("the slowdown was evaluated (not hidden as inapplicable throughout)",
                      share(tl.get("B1:wheel_l"), 32.0, 44.0, "CONSISTENT") >= 0.5,
                      f"B1:wheel_l CONSISTENT for {share(tl.get('B1:wheel_l'), 32.0, 44.0, 'CONSISTENT'):.0%} of "
                      "32-44 s at 4.0 m/s"))
    elif v.name == "real_drag":
        a1 = share(tl.get("A1"), 25.5, 30.0, "INCONSISTENT")
        b4 = share(tl.get("B4"), 25.0, 31.0, "INCONSISTENT")
        b4c = share(tl.get("B4"), 25.5, 30.0, "CONSISTENT")
        out.append(_c("A1 effort without the expected response", a1 >= 0.3, f"A1 INCONSISTENT for {a1:.0%} of 25.5-30 s"))
        out.append(_c("B4 IMU agrees with the wheels (the response is real)", b4 <= 0.1 and b4c >= 0.5,
                      f"B4 INCONSISTENT {b4:.0%}, CONSISTENT {b4c:.0%}"))
        amb = r["ambiguous"].get("relation:A1")
        out.append(_c("A1 stays ambiguous between load and measurement", bool(amb) and any(
            "load" in c for c in amb["candidates"]) and any("IMU" in c for c in amb["candidates"]),
            f"candidates: {amb['candidates'] if amb else 'none'}"))
    elif v.name == "imu_offset":
        b4 = share(tl.get("B4"), 26.5, 35.0, "INCONSISTENT")
        out.append(_c("B4 IMU disagrees with the wheels (separates it from a real drag)", b4 >= 0.5,
                      f"B4 INCONSISTENT for {b4:.0%} of 26.5-35 s"))
        a1i = share(tl.get("A1"), 26.0, 35.0, "INAPPLICABLE")
        out.append(_c("LIMITATION: A1 cannot see an IMU offset at cruise power", a1i >= 0.5,
                      f"A1 INAPPLICABLE for {a1i:.0%} of 26-35 s: the simulated cruise needs about 33 W, below the "
                      "50 W effort floor; only B4 separates an IMU offset from a real load here", "limitation"))
        bad = [k for k in inconsistent_outside(r, 25.0, 38.0)]
        out.append(_c("no inconsistency outside the disturbance (2 s to settle: 1 s windows)", not bad,
                      f"outside 25-38 s: {bad or 'none'}"))
    elif v.name == "unit_power_cut":
        cc = [c for c in r["common_cause"] if c["verdict"] == "SUPPORTED" and 29.0e6 <= (c["t_us"] or 0) <= 30.7e6]
        out.append(_c("a supported shared-path event at the cut", bool(cc),
                      "; ".join(c["statement"] for c in cc) or "none"))
        nxt = reps[1].get("boot") if len(reps) > 1 else None
        out.append(_c("the next session records a power reset", bool(nxt) and "brown-out" in str(nxt.get("cause")),
                      f"next session boot record: {nxt}"))
    elif v.name == "independent_losses":
        ev = [c for c in r["common_cause"] if 29.0e6 <= (c["t_us"] or 0) <= 31.0e6]
        out.append(_c("the simultaneous loss is reported", bool(ev), "; ".join(c["statement"] for c in ev) or "none"))
        out.append(_c("simultaneity alone is never a supported common cause",
                      all(c["verdict"] != "SUPPORTED" for c in ev), "; ".join(c["verdict"] for c in ev) or "none",
                      "falsifier"))
    elif v.name == "can_stall":
        t = reps[0]["timing"].get("can:ctrl_motion", {})
        out.append(_c("the stall is visible in the stream timing", t.get("late", 0) >= 1 and t.get("bursts", 0) >= 1
                      and t.get("wait_bounded", 0) >= 1, f"late {t.get('late')}, bursts {t.get('bursts')}, "
                                                         f"wait-bounded frames {t.get('wait_bounded')}"))
        held = [k for k in ("A1", "B2:wheel_l") if ever(tl.get(k), 30.5, 31.2, "INSUFFICIENT_EVIDENCE")]
        out.append(_c("released frames are not compared as fresh", bool(held),
                      f"INSUFFICIENT_EVIDENCE around the release: {held or 'none'}"))
        bad = [k for k, x in tl.items() if not k.startswith("localization:") and ever(x, 29.0, 33.0, "INCONSISTENT")]
        out.append(_c("a stall alone produces no inconsistency", not bad, f"{bad or 'none'}", "falsifier"))
    elif v.name == "can_constant_delay":
        t = reps[0]["timing"].get("can:ctrl_motion", {})
        out.append(_c("onset and end of the delay are visible", t.get("late", 0) >= 1 and t.get("bursts", 0) >= 1,
                      f"late {t.get('late')}, bursts {t.get('bursts')}"))
        s = share(tl.get("B2:wheel_l"), 31.0, 39.0, "CONSISTENT")
        out.append(_c("LIMITATION: a constant latency is not observable from the receive side", s >= 0.5,
                      f"B2:wheel_l evaluated as CONSISTENT for {s:.0%} of 31-39 s with values 0.3 s old (simulated "
                      "data, assumed bounds accepted). A producer timestamp alone would not settle it: it also needs a "
                      "known relation between the controller's clock and the unit's, with an uncertainty bound; "
                      "without that the sample age is unknown", "limitation"))
        bad = [k for k, x in tl.items() if not k.startswith("localization:") and ever(x, 29.0, 41.0, "INCONSISTENT")]
        out.append(_c("a delay at steady speed produces no inconsistency", not bad, f"{bad or 'none'}", "falsifier"))
    words = [w for s in statements(r) for w in verdicts.FORBIDDEN_LABELS if w in s.lower()]
    out.append(_c("no fault is named", not words, f"{words or 'none'}", "falsifier"))
    return out


def run_variant(v: Variant, out: pathlib.Path) -> dict:
    d = out / f"{v.exp}_{v.name}"
    if d.exists():
        shutil.rmtree(d)
    ncfg = None
    if v.configured_circumference_m is not None:
        vc = VehicleSimConfig()
        ncfg = NodeConfig(wheel=WheelConfig(v.configured_circumference_m, vc.wheel_ppr),
                          wheel_channels=sim_session.CHANNELS, battery_monitor=True)
    sim = sim_session.simulate(d, v.faults, v.duration, profile=v.profile, power_cuts=v.power_cuts,
                               can_delay=v.can_delay, can_stall=v.can_stall, unit=f"TLMSIM-{v.exp}",
                               ncfg=ncfg, note=f"{v.exp} {v.name}: {v.what}")
    db = ingest.connect(d / "pit.sqlite")
    reps = [ingest.import_log(db, p) for _rid, p in sim["runs"]]
    res = [review.run(db, rid, dict(SIM_PARAMS), wheel_pairs=PAIRS) for rid, _p in sim["runs"]]
    db.close()
    checks = check(v, res, reps, sim["clock"].local)
    return {"experiment": v.exp, "variant": v.name, "what": v.what, "data_class": DATA_CLASS,
            "runs": [x["run_id"] for x in res], "parameters": {k: f"{val} (SIMULATION value)" for k, val in
                                                               SIM_PARAMS.items()},
            "checks": checks, "pass": all(c["pass"] for c in checks),
            "counts": res[0]["counts"], "ambiguous": res[0]["ambiguous"], "common_cause": res[0]["common_cause"],
            "relation_set": res[0]["relation_set"]}


def render(results: list[dict]) -> str:
    L = ["# Vehicle-validation protocols: simulated pre-check (SIMULATED)", "",
         "Generated by `python3 tools/run_vehicle_experiment.py`. Every row is the host analysis on SYNTHETIC drives "
         "in which the disturbance is known; it tests the analysis, not the vehicle. No vehicle result exists until a "
         "protocol's run sheet is filled in from a physical test (research/vehicle_validation/).", "",
         "| Experiment | Variant | Check | Role | Result | Detail |", "|---|---|---|---|---|---|"]
    for r in results:
        for c in r["checks"]:
            L.append(f"| {r['experiment']} | {r['variant']} | {c['id']} | {c['role']} | "
                     f"{'PASS' if c['pass'] else 'FAIL'} | {c['detail'].replace('|', '/')} |")
    L += ["", "A `limitation` row passes when the known limitation is reproduced: it is a property of the receive "
          "side to be fixed by the interface (a producer timestamp with a stated clock relation and uncertainty "
          "bound, or a documented delay bound), not a success.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "vehicle_experiments")
    ap.add_argument("--only", action="append", default=[], help="EXP-01 ... EXP-04 (repeatable)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    results = [run_variant(v, a.out) for v in VARIANTS if not a.only or v.exp in a.only]
    (a.out / "results.json").write_text(json.dumps(results, indent=1, sort_keys=True, default=str) + "\n")
    (a.out / "results.md").write_text(render(results))
    for r in results:
        print(f"{r['experiment']} {r['variant']}: {'PASS' if r['pass'] else 'FAIL'} "
              f"({sum(c['pass'] for c in r['checks'])}/{len(r['checks'])} checks, {DATA_CLASS})")
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
