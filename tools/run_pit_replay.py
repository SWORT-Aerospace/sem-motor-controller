#!/usr/bin/env python3
"""Shadow replay of R3v and CSIA2 over one run in a pit database (advisory report only).

    python3 tools/run_pit_replay.py --db build/host_demo/pit.sqlite --run HOSTSIM-0001 --out build/pit_replay

The database is the pit's SQLite file with the run's local log imported
(`host/pit/ingest.py import_log`; the host and MQTT demonstrations do this).
Vehicle parameters come from the configuration the run's metadata names
(checked against its SHA-256), the freewheel state from the run's plant record
or the configuration. Writes OUT/report.md, OUT/report.json, OUT/timeline.csv,
and OUT/energy.json: controller-input energy, wheel distance and Wh/km over the
run (host/pit/energy.py), and the energy from valid, time-aligned V x I at the controller input and, when a
battery-side monitor is fitted, at the battery, with the missing intervals listed.
Exit code 0 when a report was written (whatever it found), 2 when the run is
not in the database.

This tool only reads the database and writes files: it has no CAN, MQTT or
controller interface and cannot command torque or change protection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.csia_adapter.adapter import AdapterParams  # noqa: E402
from host.pit import energy, shadow_replay  # noqa: E402
from tools import config_tool as ct  # noqa: E402


def params_for_run(meta: dict, config: pathlib.Path | None):
    cfg_rel = (meta.get("vehicle_config") or {}).get("path")
    path = config or (ROOT / cfg_rel if cfg_rel else None)
    if path is None or not path.exists():
        raise SystemExit(f"vehicle configuration not found ({path}); pass --config")
    notes = []
    want = (meta.get("vehicle_config") or {}).get("sha256")
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if want and want != got:
        notes.append(f"configuration {path.name} changed since the run (SHA-256 differs): parameters may not match")
    cfg = ct.load_yaml(path)
    C = cfg["vehicle"]["wheel_circumference_m"]
    gear = cfg["vehicle"]["gear_ratio"]
    kt = 1.5 * cfg["motor"]["pole_pairs"] * cfg["motor"]["flux_linkage_Wb"]
    # the simulated plant's freewheel flag only for a simulation; a vehicle run takes it from its configuration
    plant = (meta.get("plant") or {}) if shadow_replay.classify(meta)["synthetic"] else {}
    freewheel = plant.get("freewheel", cfg["vehicle"].get("freewheel_present", True))
    sens = meta.get("sensors") or {}
    ppr = sens.get("wheel_ppr")
    window = sens.get("wheel_window_s")
    if not C or not gear or not kt or not ppr:
        raise SystemExit("wheel circumference, gear ratio, torque constant or wheel pulses per revolution unknown")
    if window is None:
        notes.append("wheel counting window not in the run metadata: 0.1 s assumed for the speed quantisation")
    p = AdapterParams(wheel_radius_m=C / (2 * math.pi), gear_ratio=gear, freewheel=bool(freewheel), kt_Nm_per_A=kt)
    return p, kt, C / (ppr * (window or 0.1)), notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=pathlib.Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "pit_replay")
    ap.add_argument("--config", type=pathlib.Path, help="vehicle configuration (default: the one the run names)")
    a = ap.parse_args()
    db = sqlite3.connect(a.db)
    row = db.execute("SELECT meta_json FROM runs WHERE run_id=?", (a.run,)).fetchone()
    if row is None:
        print(f"REPLAY NOT AVAILABLE: run {a.run} is not in {a.db} (import its log first)")
        return 2
    meta = json.loads(row[0])
    params, kt, wheel_q, notes = params_for_run(meta, a.config)
    res = shadow_replay.run(db, a.run, params, kt, wheel_q, a.out, notes=tuple(notes))
    print(f"REPLAY {res['provenance']['data_class']}: {res.get('ticks', 0)} ticks; report in {a.out}/report.md")
    for mon, eps in (res.get("episodes") or {}).items():
        print(f"REPLAY {mon}: {len(eps)} attribution episode(s)")
    for x in res.get("insufficient", []):
        print(f"REPLAY INSUFFICIENT EVIDENCE: {x}")
    sens = meta.get("sensors") or {}
    chans = [v for _k, v in sorted((sens.get("wheel_channels") or {"0": "wheel_0"}).items())]
    per = [energy.run_summary(db, a.run, c, sens.get("wheel_window_s")) for c in chans]
    cross = energy.compare_channels(per)
    vi = {b: energy.vi_energy(db, a.run, b) for b in energy.BOUNDARIES}
    (a.out / "energy.json").write_text(json.dumps({"channels": per, "cross_check": cross, "vi_energy": vi}, indent=1,
                                                  sort_keys=True))
    for b, r in vi.items():
        if r["energy_J"] is None:
            print(f"REPLAY ENERGY {b}: not available ({'; '.join(r['notes'][1:]) or 'no aligned valid V and I'})")
        else:
            print(f"REPLAY ENERGY {b}: {r['energy_Wh']:.4f} Wh from valid aligned V x I over {r['covered_s']:.1f} s; "
                  f"{len(r['missing_intervals'])} missing interval(s), {r['missing_s']:.2f} s (bound "
                  f"{r['missing_energy_bound_J'] / 3600:.4f} Wh); {r['boundary_text']}")
    for en in per:
        if en["Wh_per_km"] is not None:
            print(f"REPLAY ENERGY: {en['energy_Wh']:.3f} Wh over {en['distance_m']:.1f} m ({en['channel']}) = "
                  f"{en['Wh_per_km']:.2f} Wh/km at the controller input")
    for x in sorted({n for en in per for n in en["notes"]}) + cross:
        print(f"REPLAY ENERGY NOTE: {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
