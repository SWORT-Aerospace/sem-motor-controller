#!/usr/bin/env python3
"""Firmware-in-the-loop vehicle simulation (SIMULATED): the simulated vehicle drives the telematics firmware's own C
code, and the log it writes goes through the pit: import, evidence review and the R3v and CSIA shadow replay.

    python3 tools/run_firmware_vehicle_sim.py --out build/firmware_vehicle_sim [--duration 140]
                                              [--gnss-outage 60:70] [--wheel-scale 0:90:110:1.05]

Inputs, generated per simulated millisecond by host/telematics/sim_vehicle.py: wheel edges and line levels, the
external controller's CAN frames (semmc simulation fixture), the IMU, three TMP117 channels, the battery-side
monitor, and the GNSS receiver as UBX-NAV-PVT bytes (host/telematics/ubx.py) at 10 Hz, 60 ms after each solution's
epoch, with a PPS edge at every whole UTC second while there is a fix. They go to the host simulator (tm_hostsim:
tm_app and tm_gnss, the code of the tm_u575_vehicle image without its register-level drivers), which writes the log
to a RAM flash; the log is then imported as a board's log would be.

What this shows: the firmware's logging and GNSS code, the import, the UTC mapping from the firmware's PPS records,
the evidence review and CSIA work together on one simulated drive. What it does not show: anything about the target
(interrupts, peripherals, timing) or about the vehicle. Every input is simulated.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.pit import ingest  # noqa: E402
from host.telematics import stlg, ubx  # noqa: E402
from host.telematics.clocks import PpsModel  # noqa: E402
from host.telematics.node import NodeConfig  # noqa: E402
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig, default_profile  # noqa: E402
from tools import telematics_import  # noqa: E402

GNSS_LATENCY_S = 0.06                  # NAV-PVT output after its epoch (assumed; the receiver's figure is a bench item)
UTC0 = PpsModel().utc_at_true_zero     # UTC at simulation time 0


def _us(t: float) -> int:
    return int(round(t * 1e6))


def script(duration: float, faults: Faults, img: pathlib.Path, slots: int) -> tuple[str, list, dict]:
    """The tm_hostsim script of one drive; also the simulated speed (t, v) and the input counts."""
    sim = VehicleSim(VehicleSimConfig(), faults, default_profile)
    cfg = sim.cfg
    pps = PpsModel(outages=tuple(faults.gnss_outage))
    ev, levels, truth, n = [], {}, [], collections.Counter()
    t_prev = 0.0
    for k in range(1, int(round(duration / 0.001)) + 1):
        t = round(k * 0.001, 6)
        res = sim.step(t, 0.001)
        truth.append((t, sim.v))
        for te, ch in res["edges"]:
            ev.append((_us(te), f"E {_us(te)} {ch}"))
            n["wheel_edges"] += 1
        for ch in range(cfg.wheel_channels):
            hi = sim.line_high(ch, t)
            if levels.get(ch) != hi:
                levels[ch] = hi
                ev.append((_us(t), f"L {_us(t)} {ch} {int(hi)}"))
        for tx, cid, data in sim.frames(t):
            ev.append((_us(tx), f"C {_us(tx)} {cid:x} {data.hex()}"))
            n["can_frames"] += 1
        for kind, args in sim.sensors(t):
            if kind == "gnss":
                speed, sacc, nsv, fix = args
                msg = ubx.from_sample(UTC0 + t, speed, sacc, nsv, fix)
                ev.append((_us(t + GNSS_LATENCY_S), f"G {_us(t + GNSS_LATENCY_S)} {msg.hex()}"))
                n["nav_pvt"] += 1
            elif kind == "imu":
                ev.append((_us(t), f"K {_us(t)} {stlg.IMU} {stlg.body_imu(*args).hex()}"))
                n["imu"] += 1
            elif kind == "temp":
                ev.append((_us(t), f"K {_us(t)} {stlg.TEMP} {stlg.body_temp(*args).hex()}"))
                n["temp"] += 1
            elif kind == "batt":
                ev.append((_us(t), f"K {_us(t)} {stlg.BATT} {stlg.body_batt(0, *args).hex()}"))
                n["batt"] += 1
        for te, _u in pps.edges(t_prev, t):
            ev.append((_us(te), f"U {_us(te)}"))
            n["pps_edges"] += 1
        t_prev = t
    ev.sort(key=lambda e: e[0])
    lines = [f"I {slots} {int(round(cfg.wheel_circumference_m * 1000))} {cfg.wheel_ppr} {img}"]
    lines += [x for _t, x in ev] + [f"P {_us(duration)}", "F", "W"]
    return "\n".join(lines) + "\n", truth, dict(n)


def _hostsim(build: pathlib.Path, text: str) -> None:
    if not (build / "CMakeCache.txt").exists():
        subprocess.run(["cmake", "-S", str(ROOT / "telematics" / "firmware"), "-B", str(build)], check=True)
    subprocess.run(["cmake", "--build", str(build)], check=True, capture_output=True)
    r = subprocess.run([str(build / "tm_hostsim")], input=text, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise SystemExit(f"tm_hostsim failed: {r.stderr}")


def run(out: pathlib.Path, duration: float, faults: Faults, build: pathlib.Path, slots: int = 1024) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    img, db_path = out / "flash.bin", out / "pit.sqlite"
    for p in (img, db_path):
        p.unlink(missing_ok=True)
    text, truth, n_in = script(duration, faults, img, slots)
    _hostsim(build, text)
    nc = NodeConfig()
    overrides = {"wheel_channels": {str(k): v for k, v in enumerate(nc.wheel_channels)},
                 "temp_channels": {str(k): v for k, v in enumerate(nc.temp_channels)}}
    res = telematics_import.run(img.read_bytes(), db_path, out / "import", overrides, plots=True)
    (sess,) = res["sessions"]
    rid, imp = sess["run_id"], sess["import"]
    db = ingest.connect(db_path)
    g = db.execute("SELECT t_rx_us, value, validity, utc, utc_q FROM measurements WHERE run_id=? AND "
                   "signal='gnss.speed' ORDER BY t_rx_us", (rid,)).fetchall()
    utc_err = [abs(u - (UTC0 + t / 1e6)) for t, _v, _val, u, q in g if q == "pps"]
    v_at = {round(t * 1000): v for t, v in truth}
    spd_err = [v - v_at.get(round(t / 1000 - GNSS_LATENCY_S * 1000), math.nan) for t, v, val, _u, _q in g
               if val == "valid"]
    spd_err = [e for e in spd_err if math.isfinite(e)]
    cnt = dict(db.execute("SELECT name, value FROM signals WHERE run_id=? AND name LIKE 'cnt_%' ORDER BY t_local_us",
                          (rid,)).fetchall())
    db.close()
    review = subprocess.run([sys.executable, str(ROOT / "tools" / "run_evidence_review.py"), "--db", str(db_path),
                             "--run", rid, "--out", str(out / "evidence_review"), "--pair", "wheel_l:wheel_r"],
                            capture_output=True, text=True)
    replay = subprocess.run([sys.executable, str(ROOT / "tools" / "run_pit_replay.py"), "--db", str(db_path),
                             "--run", rid, "--config", str(ROOT / "config" / "vehicle.synthetic.yaml"),
                             "--out", str(out / "replay")], capture_output=True, text=True)
    rep = json.loads((out / "replay" / "report.json").read_text()) if replay.returncode == 0 else {}
    summary = {
        "data_class": "SIMULATED", "run_id": rid, "duration_s": duration, "faults": repr(faults), "inputs": n_in,
        "import": {k: imp.get(k) for k in ("records", "blocks_corrupt", "block_seq_gaps", "utc_quality")},
        "accounting": imp.get("accounting"),
        "gnss": {"records": len(g), "valid": sum(r[2] == "valid" for r in g),
                 "speed_rms_error_mps": math.sqrt(sum(e * e for e in spd_err) / len(spd_err)) if spd_err else None,
                 "utc_max_error_s": max(utc_err) if utc_err else None, "utc_pps_share": len(utc_err) / max(len(g), 1)},
        "firmware_counters": {k[4:]: cnt.get(k) for k in ("cnt_gnss_frames", "cnt_gnss_checksum_errors",
                                                          "cnt_pps_edges", "cnt_pps_unlabelled", "cnt_log_records",
                                                          "cnt_log_dropped_queue", "cnt_log_dropped_storage")},
        "evidence_review": review.stdout.strip().splitlines()[-1] if review.stdout.strip() else review.stderr[-300:],
        "replay": {"returncode": replay.returncode, "relationships": rep.get("relationships"),
                   "episodes": rep.get("episodes"), "insufficient": rep.get("insufficient")},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def _faults(a) -> Faults:
    kw = {}
    if a.gnss_outage:
        t0, t1 = (float(x) for x in a.gnss_outage.split(":"))
        kw["gnss_outage"] = ((t0, t1),)
    if a.wheel_scale:
        ch, t0, t1, f = a.wheel_scale.split(":")
        kw["wheel_scale"] = ((int(ch), float(t0), float(t1), float(f)),)
    return Faults(**kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "firmware_vehicle_sim")
    ap.add_argument("--duration", type=float, default=140.0)
    ap.add_argument("--gnss-outage", default="", help="t0:t1 (s): no fix, no PPS")
    ap.add_argument("--wheel-scale", default="", help="channel:t0:t1:factor, e.g. 0:90:110:1.05")
    ap.add_argument("--build", type=pathlib.Path, default=ROOT / "build-telematics", help="host build with tm_hostsim")
    a = ap.parse_args()
    s = run(a.out, a.duration, _faults(a), a.build)
    print(json.dumps(s, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
