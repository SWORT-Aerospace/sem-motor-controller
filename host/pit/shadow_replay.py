"""Pit-side shadow replay of the sensor-consistency monitors over one stored run.

Runs, side by side and in shadow mode, the monitors of the frozen v2
evaluation (docs/csia/EVALUATION_PROTOCOL_v2.md, results in
EVALUATION_RESULTS_v2.md):
  B1     range / NaN / freshness checks
  R3v    calibrated residuals + majority-vote attribution (the selected monitor)
  CSIA2  the v2 adapter with CSIA corroboration attribution (experimental)
each behind the evaluation's shared 3-tick persistence filter. The monitor
classes, the residual threshold and the E6 power-balance model are the frozen
ones (host/csia_adapter/evaluation_v2.py, docs/csia/V2_FREEZE.json); only the
vehicle parameters (wheel radius, gear ratio, torque constant, freewheel)
come from the run's own configuration. Nothing is re-tuned.

Shadow mode: this module reads the pit database and writes a report. It has
no CAN, MQTT or controller interface; it cannot command torque or change any
protection.

The report says what the evidence supports:
  * data class: synthetic (host simulation) or measured (vehicle), from the
    run metadata;
  * per input signal: samples and the share of 10 Hz ticks with a fresh sample;
  * per relationship: the ticks in which it was active (gated in, both ends fresh);
  * INSUFFICIENT EVIDENCE notes whenever parameters are synthetic for measured
    data, an input is assumed (road grade), a signal is missing, or no ground
    truth exists to score detections.
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import sqlite3

from host.csia_adapter import evaluation as EV
from host.csia_adapter import evaluation_v2 as EV2
from host.csia_adapter.adapter import AdapterParams
from host.csia_adapter.adapter_v2 import E6Model, VehicleCsiaAdapterV2
from host.pit import csia_replay

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
FREEZE = ROOT / "docs" / "csia" / "V2_FREEZE.json"

# signals each relationship needs (endpoints first, then auxiliary inputs); host/csia_adapter/adapter.py
RELATIONSHIPS = {
    "E1_rotor_wheeldrive": (["rotor", "wheel_drive"], []),
    "E2_wheel_lr_yaw": (["wheel_l", "wheel_r"], ["imu_gz"]),
    "E3a_gnss_wheel_l": (["gnss", "wheel_l"], ["imu_gz"]),
    "E3b_gnss_wheel_r": (["gnss", "wheel_r"], ["imu_gz"]),
    "E4_imu_wheel_l": (["imu_ax", "wheel_l"], ["grade"]),
    "E6_power_balance": (["p_dc", "iq"], ["rotor"]),
    "E7_gnss_wheeldrive": (["gnss", "wheel_drive"], []),
    "P_phase_current": (["iq", "iq_ref", "kcl"], []),
}
SIGNALS = ["rotor", "iq", "iq_ref", "kcl", "p_dc", "wheel_l", "wheel_r", "wheel_drive", "gnss", "imu_ax", "imu_gz",
           "grade"]
MIN_COVERAGE = 0.5


def frozen_settings() -> tuple[float, E6Model, dict]:
    f = json.loads(FREEZE.read_text())
    e6 = E6Model(**{k: f["e6_model"][k] for k in ("R_ohm", "c_sw_W_per_A", "p0_W", "s0_W", "u_R", "u_rel",
                                                     "align_max_gap_s")})
    return float(f["lam"]), e6, f


def make_monitors(params: AdapterParams, lam: float, e6: E6Model) -> list:
    """The frozen evaluation's B1, R3v and CSIA2, with this run's vehicle parameters."""
    b1 = EV.B1()
    b1.m = EV.SimpleChecks(params)
    r3v = EV2.ResidualV2("R3v", "vote", lam, e6)
    r3v.ad = VehicleCsiaAdapterV2(params, e6)
    csia2 = EV2.Csia2(e6)
    csia2.ad = VehicleCsiaAdapterV2(params, e6)
    return [EV2.Debounce(b1), EV2.Debounce(r3v), EV2.Debounce(csia2)]


def classify(meta: dict) -> dict:
    kind = str(meta.get("kind", ""))
    cal = (meta.get("calibration") or {}).get("provenance")
    cfg_path = (meta.get("vehicle_config") or {}).get("path", "")
    synthetic = "SIMULATION" in kind.upper() or "HOST" in kind.upper() or cal == "synthetic" or "synthetic" in cfg_path
    return {"data_class": "synthetic (host simulation)" if synthetic else "measured (vehicle)",
            "synthetic": synthetic, "kind": kind, "calibration_provenance": cal, "vehicle_config": cfg_path,
            "sensor_status": (meta.get("sensors") or {}).get("status")}


def run(db: sqlite3.Connection, run_id: str, params: AdapterParams, kt: float, wheel_q_mps: float,
        out: pathlib.Path | None = None, notes: tuple[str, ...] = ()) -> dict:
    """notes: caller's findings (for example a changed configuration) written into the report's evidence list."""
    row = db.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
    meta = json.loads(row[0]) if row else {}
    prov = classify(meta)
    lam, e6, freeze = frozen_settings()
    data = csia_replay.build_samples(db, run_id, kt, wheel_q_mps)
    res = {"run_id": run_id, "provenance": prov, "monitors": ["B1", "R3v", "CSIA2"],
           "frozen": {"lam": lam, "e6_model": freeze["e6_model"], "freeze_file": "docs/csia/V2_FREEZE.json"},
           "params": {k: getattr(params, k) for k in ("wheel_radius_m", "gear_ratio", "kt_Nm_per_A", "freewheel")},
           "shadow_mode": "advisory only: no CAN, MQTT or controller interface; no torque command; no protection change"}
    if not data:
        res.update(ticks=0, insufficient=[*notes, "no decoded signals for this run in the database"])
        return _write(res, [], out)

    mons = make_monitors(params, lam, e6)
    diag = VehicleCsiaAdapterV2(params, e6)                 # diagnostics only: which relationships were active
    t0, t1 = data[0][0], data[-1][0]
    k = 0
    timeline = []
    cover = {s: 0 for s in SIGNALS}
    n_samples = {s: 0 for s in SIGNALS}
    for _t, name, _s in data:
        if name in n_samples:
            n_samples[name] += 1
    last = {}
    active = {r: 0 for r in RELATIONSHIPS}
    t = t0 + 0.1
    while t <= t1:
        while k < len(data) and data[k][0] <= t:
            _ts, name, s = data[k]
            last[name] = data[k][0]
            for m in mons:
                m.ingest(name, s)
            diag.ingest(name, s)
            k += 1
        for sname in SIGNALS:
            if sname in last and t - last[sname] <= params.windows.get(sname, 0.25):
                cover[sname] += 1
        edges, _phys, fr = diag._rel(t)
        diag.last_tick = t
        for rname, (a, b, lv, g, _aux) in edges.items():
            if rname in active and g > 0 and math.isfinite(lv):
                active[rname] += 1
        outs = [m.tick(t) for m in mons]
        timeline.append({"t_local_s": round(t, 3),
                         **{f"{m.name}_suspects": sorted(o.suspects) for m, o in zip(mons, outs)},
                         **{f"{m.name}_implicated": sorted(o.implicated) for m, o in zip(mons, outs)}})
        t = round(t + 0.1, 6)
    ticks = len(timeline)
    res["ticks"] = ticks
    res["signals"] = {s: {"samples": n_samples[s], "fresh_tick_share": round(cover[s] / ticks, 3)} for s in SIGNALS}
    res["relationships"] = {r: {"needs": ins + aux, "active_ticks": active[r]} for r, (ins, aux) in RELATIONSHIPS.items()}

    insufficient = list(notes)
    if not prov["synthetic"]:
        insufficient.append("vehicle parameters and the E6 power-balance model are the frozen synthetic ones; "
                            "they must be identified on this vehicle's development data before any result is used")
    insufficient.append("road grade is assumed flat (no route map): relationships using grade (E4) rest on that "
                        "assumption")
    for s in SIGNALS:
        if s != "grade" and res["signals"][s]["fresh_tick_share"] < MIN_COVERAGE:
            users = [r for r, (ins, aux) in RELATIONSHIPS.items() if s in ins + aux]
            insufficient.append(f"signal {s} fresh in {res['signals'][s]['fresh_tick_share']:.0%} of ticks: "
                                f"{', '.join(users)} not reliably evaluable")
    for r, v in res["relationships"].items():
        if v["active_ticks"] == 0:
            insufficient.append(f"relationship {r} never active: no evidence about its endpoints from it")
    if prov["sensor_status"] and "PROVISIONAL" in prov["sensor_status"]:
        insufficient.append(f"sensor configuration provisional ({prov['sensor_status']})")

    faults = meta.get("injected_faults") or []
    if not faults:
        insufficient.append("no ground truth in the run metadata: detections are listed, not scored")
    res["scoring"] = _score(timeline, faults, [m.name for m in mons]) if faults else None
    res["episodes"] = {m.name: _episodes(timeline, m.name) for m in mons}
    res["insufficient"] = insufficient
    return _write(res, timeline, out)


def _episodes(timeline, mon):
    eps, cur = [], None
    for r in timeline:
        s = tuple(r[f"{mon}_suspects"])
        if s and (cur is None or cur["suspects"] != list(s)):
            if cur:
                eps.append(cur)
            cur = {"start_s": r["t_local_s"], "end_s": r["t_local_s"], "suspects": list(s)}
        elif s:
            cur["end_s"] = r["t_local_s"]
        elif cur:
            eps.append(cur)
            cur = None
    if cur:
        eps.append(cur)
    return eps


def _score(timeline, faults, names):
    """Synthetic runs only: first correct attribution and wrong-suspect ticks per injected fault."""
    out = {}
    for mon in names:
        per = []
        for f in faults:
            a, b = f["t_local_s"]
            first = next((r["t_local_s"] for r in timeline
                          if a <= r["t_local_s"] <= b + 2.0 and f["node"] in r[f"{mon}_suspects"]), None)
            per.append({"node": f["node"], "kind": f["kind"], "window_s": [round(a, 3), round(b, 3)],
                        "first_correct_s_after_onset": None if first is None else round(first - a, 2)})
        in_any = lambda t: any(f["t_local_s"][0] <= t <= f["t_local_s"][1] + 2.0 for f in faults)  # noqa: E731
        wrong = sum(1 for r in timeline if r[f"{mon}_suspects"] and
                    (not in_any(r["t_local_s"]) or
                     any(n not in {f["node"] for f in faults} for n in r[f"{mon}_suspects"])))
        out[mon] = {"faults": per, "ticks_with_a_wrong_or_unexplained_suspect": wrong}
    return out


def _write(res, timeline, out):
    if out is None:
        return res
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    with (out / "timeline.csv").open("w", newline="") as fh:
        if timeline:
            w = csv.DictWriter(fh, fieldnames=list(timeline[0]))
            w.writeheader()
            for r in timeline:
                w.writerow({k: "|".join(v) if isinstance(v, list) else v for k, v in r.items()})
    p = res["provenance"]
    L = [f"# Shadow replay report: run `{res['run_id']}`", "",
         f"Data class: **{p['data_class']}** (run kind: {p['kind'] or 'not recorded'}; calibration provenance: "
         f"{p['calibration_provenance']}; vehicle configuration: `{p['vehicle_config']}`). "
         "Monitors B1, R3v (selected) and CSIA2 (experimental), frozen v2 classes and thresholds "
         f"(`{res['frozen']['freeze_file']}`, residual threshold {res['frozen']['lam']:.3g}); vehicle parameters "
         f"from the run: {res['params']}. Shadow mode: {res['shadow_mode']}.", ""]
    if res.get("ticks"):
        L += ["## Input signals", "", "| Signal | Samples | Ticks with a fresh sample |", "|---|---|---|"]
        L += [f"| {s} | {v['samples']} | {v['fresh_tick_share']:.0%} |" for s, v in res["signals"].items()]
        L += ["", "## Relationships", "", "| Relationship | Needs | Active ticks (of %d) |" % res["ticks"], "|---|---|---|"]
        L += [f"| {r} | {', '.join(v['needs'])} | {v['active_ticks']} |" for r, v in res["relationships"].items()]
        L += ["", "## Attribution episodes (after the 3-tick persistence filter)", ""]
        for mon, eps in res["episodes"].items():
            L.append(f"* {mon}: " + ("; ".join(f"{e['start_s']}-{e['end_s']} s {e['suspects']}" for e in eps[:12])
                                     + (f"; and {len(eps) - 12} more" if len(eps) > 12 else "") if eps else "none"))
        if res.get("scoring"):
            L += ["", "## Against the injected faults (synthetic ground truth from the run metadata)", "",
                  "| Monitor | Fault | First correct attribution after onset | Ticks with a wrong or unexplained suspect |",
                  "|---|---|---|---|"]
            for mon, sc in res["scoring"].items():
                for f in sc["faults"]:
                    v = f["first_correct_s_after_onset"]
                    L.append(f"| {mon} | {f['kind']} {f['node']} {f['window_s'][0]}-{f['window_s'][1]} s | "
                             f"{'not attributed' if v is None else f'{v} s'} | "
                             f"{sc['ticks_with_a_wrong_or_unexplained_suspect']} |")
    L += ["", "## Insufficient evidence", ""] + [f"* {x}" for x in res.get("insufficient", [])] + [""]
    L += ["A synthetic run shows how the monitors behave on the host model; it is not evidence about real sensors. "
          "The frozen evaluation (`docs/csia/EVALUATION_RESULTS_v2.md`) found that CSIA2 did not meet its "
          "pre-registered criterion against R3v; this report does not change that.", ""]
    (out / "report.md").write_text("\n".join(L))
    return res
