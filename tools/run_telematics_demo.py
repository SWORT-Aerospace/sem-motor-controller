#!/usr/bin/env python3
"""Telematics end-to-end demonstration: receive-only node, simulated external controller (HOST SIMULATION).

    python3 tools/run_telematics_demo.py --out build/telematics_demo            # real local Mosquitto broker
    python3 tools/run_telematics_demo.py --out build/telematics_demo --in-process   # simulated link, no broker

Chain, every link exercised in one run; no controller code of this project takes part and nothing has a
torque supervisor:

  simulated external controller (host/telematics/sim_vehicle.py, semmc fixture broadcast) + sensor fixtures
  (wheel Hall edges, GNSS + PPS, IMU, temperature probes, battery-side monitor)
  -> receive-only telematics node (host/telematics/node.py): timestamps, controller adapter -> measurements,
     bounded log queue -> STLG local log, 2 Hz sem.telemetry.v4 summary
  -> uplink: paho-mqtt client, QoS 1 -> Mosquitto (separate process, loopback)
  -> pit ingestion service (separate process): validate -> SQLite
  -> offline import of the local logs into the same database -> speed, distance, power, energy at two
     measurement boundaries and data quality.

Scenario (controller time, s; the drive profile is in sim_vehicle.default_profile):
  20.0-23.0   controller silent (no frames)               30.0-31.0   corrupted frames (bad CRC)
  40.0-50.0   ctrl_currents not sent (DC current missing)   55.0-58.0   bus-voltage validity flag cleared
  65.0-67.0   storage stalled (log queue fills)            80.0-97.0   broker down (killed and restarted)
  100.0-108.0 drive-wheel sensor disconnected             110.0-115.0 GNSS without fix (no PPS)
  120.0       telematics unit restarts without shutdown (power loss); back at 121.0 as boot 2
Prints one "TELEMATICS ..." line per check; exit code 1 if any fails.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.pit import energy, ingest  # noqa: E402
from host.telematics import stlg  # noqa: E402
from host.telematics.clocks import LocalClock, PpsModel  # noqa: E402
from host.telematics.controller_adapter import SimFixtureAdapter  # noqa: E402
from host.telematics.node import NodeConfig, SimLink, TelematicsNode, meta_fields  # noqa: E402
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig  # noqa: E402
from host.telematics.wheel import WheelConfig  # noqa: E402
from protocol.generated import semmc_protocol as proto  # noqa: E402

UNIT = "TLMSIM-0001"
DT = 0.01
SILENCE = (20.0, 23.0)
CORRUPT = (30.0, 31.0)
DROP_CURRENTS = ("ctrl_currents", 40.0, 50.0)
VBUS_INVALID = (55.0, 58.0)
STORAGE_STALL = (65.0, 67.0)
BROKER_DOWN = (80.0, 97.0)
WHEEL_DISCONNECT = (2, 100.0, 108.0)
GNSS_OUT = (110.0, 115.0)
RESTART = (120.0, 121.0)
DURATION = 165.0
CHANNELS = ("wheel_l", "wheel_r", "wheel_drive")
COMPANION_IDS = {m["id"] for m in proto.MESSAGES.values() if m["sender"] != "controller"}


def run_id(boot: int) -> str:
    return f"{UNIT}-B{boot:04d}"


class Bus:
    """The vehicle CAN bus of the simulation: the external controller writes, the node only reads. The node
    is never given a reference to this object, so it has no way to put a frame on the bus."""

    def __init__(self):
        self.frames: list[tuple[float, int, bytes, str]] = []

    def put(self, t: float, can_id: int, data: bytes, origin: str) -> None:
        self.frames.append((t, can_id, data, origin))


def _git():
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    return rev, dirty


def simulate(out: pathlib.Path, link_factory, duration: float = DURATION, actions=(), pace: float | None = None,
             ncfg: NodeConfig | None = None) -> dict:
    """Step vehicle, controller broadcast, sensors and the node; returns the run's evidence."""
    vcfg = VehicleSimConfig()
    sim = VehicleSim(vcfg, Faults(silence=(SILENCE,), corrupt=(CORRUPT,), drop_message=(DROP_CURRENTS,),
                                  vbus_invalid=(VBUS_INVALID,), wheel_disconnect=(WHEEL_DISCONNECT,),
                                  gnss_outage=(GNSS_OUT,)))
    clock = LocalClock()
    pps = PpsModel(outages=(GNSS_OUT,))
    pps_rng = np.random.default_rng(5)
    ncfg = ncfg or NodeConfig(wheel=WheelConfig(vcfg.wheel_circumference_m, vcfg.wheel_ppr), wheel_channels=CHANNELS,
                              battery_monitor=True)
    git, dirty = _git()
    bus = Bus()
    boots: dict[int, dict] = {}

    def start(boot: int, t: float, cause: str):
        rid = run_id(boot)
        adapter = SimFixtureAdapter()
        meta = meta_fields(ncfg, adapter, rid, UNIT, boot)
        meta.update(kind="HOST SIMULATION - not a vehicle run", session="TLMSIM-SESSION-1",
                    software={"repo_commit": git, "working_tree_dirty": dirty, "telematics_firmware": "host-sim"},
                    simulation={"controller": "host/telematics/sim_vehicle.py (stand-in for the external "
                                              "controller; semmc fixture protocol)",
                                "note": "SYNTHETIC vehicle and sensor numbers; no hardware"})
        w = stlg.Writer(out / f"{rid}.stlg", meta, ncfg.storage_bytes)
        link = link_factory(rid)
        node = TelematicsNode(ncfg, clock, w, link, adapter, rid, boot=boot,
                              flash_stalls=(STORAGE_STALL,), reset_cause=cause, t_start=t)
        boots[boot] = {"run_id": rid, "node": node, "writer": w, "link": link, "t_start": t}
        return node

    node = start(1, 0.0, "power-on (simulated)")
    truth = []
    acts = sorted(actions, key=lambda a: a[0])
    n = int(round(duration / DT))
    t_prev = 0.0
    wall0 = time.monotonic()
    for k in range(1, n + 1):
        t = round(k * DT, 6)
        while acts and acts[0][0] <= t:
            acts.pop(0)[1](t)
        if pace:
            delay = wall0 + t / pace - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        res = sim.step(t, DT)
        frames = sim.frames(t)
        for tx, cid, data in frames:
            bus.put(tx, cid, data, "external_controller")
        truth.append((t, sim.v, sim.dist, sim.v_bus * sim.i_ctrl, sim.v_batt * sim.i_batt))
        powered = node is not None
        if node is not None and t >= RESTART[0] and "t_end" not in boots[1]:
            boots[1]["lost_records_at_crash"] = node.crash()
            boots[1]["backlog_lost_at_crash"] = [m["seq"] for m in node.uq]
            boots[1]["t_end"] = t
            if hasattr(boots[1]["link"], "stop"):
                boots[1]["link"].stop()
            node = None
            powered = False
        if node is None and t >= RESTART[1]:
            node = start(2, t, "power loss (simulated: brown-out reset)")
            powered = True
            continue
        if not powered:
            t_prev = t
            continue
        for te, ch in res["edges"]:
            node.on_wheel_edge(te, ch)
        for ch in range(vcfg.wheel_channels):
            node.on_wheel_line(ch, sim.line_high(ch, t))
        for tx, cid, data in frames:
            node.on_can(tx, cid, data)
        for te, u in pps.edges(t_prev, t, pps_rng):
            node.on_pps(te, u)
        for kind, args in sim.sensors(t):
            node.on_sensor(t, kind, args)
        node.service(t, DT)
        t_prev = t
    node.close(duration)
    boots[2]["t_end"] = duration
    return {"sim": sim, "clock": clock, "pps": pps, "bus": bus, "boots": boots, "truth": truth, "ncfg": ncfg,
            "vcfg": vcfg, "git": git, "dirty": dirty, "wall_s": time.monotonic() - wall0}


# ---------------------------------------------------------------- analysis and checks
_TS: dict = {}


def _true_at(truth, clock, t_local_us: int, col: int) -> float:
    t = clock.true(t_local_us / 1e6)
    ts = _TS.get(id(truth))
    if ts is None:
        ts = _TS[id(truth)] = [r[0] for r in truth]
    k = min(max(bisect.bisect_left(ts, t), 1), len(ts) - 1)
    (t0, *a), (t1, *b) = truth[k - 1], truth[k]
    f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
    return a[col - 1] + f * (b[col - 1] - a[col - 1])


def _true_energy(truth, clock, intervals_local_s, col: int) -> float:
    """True energy (column col: 3 controller input power, 4 battery power) inside the given local intervals."""
    e = 0.0
    loc = [(a, b) for a, b, *_r in intervals_local_s]
    for (t, *_v), nxt in zip(truth, truth[1:]):
        tl = clock.local(t)
        if any(a <= tl < b for a, b in loc):
            e += nxt[col] * (nxt[0] - t)
    return e


def analyse(ev: dict, db: sqlite3.Connection, live_rep: dict) -> tuple[list[dict], dict]:
    checks = []

    def check(cid, ok, detail):
        checks.append({"id": cid, "pass": bool(ok), "detail": detail})

    clock, truth, boots, bus, ncfg, vcfg = ev["clock"], ev["truth"], ev["boots"], ev["bus"], ev["ncfg"], ev["vcfg"]
    imps = {b: ingest.import_log(db, pathlib.Path(boots[b]["writer"].path)) for b in boots}
    reimps = {b: ingest.import_log(db, pathlib.Path(boots[b]["writer"].path)) for b in boots}

    # 1. receive only
    origins = collections.Counter(o for *_r, o in bus.frames)
    api = [n for n in ("supervisor_tick", "tick", "transmit", "send_frame", "tx") if hasattr(TelematicsNode, n)]
    comp_logged = sum(1 for b in boots for (cid,) in db.execute(
        "SELECT can_id FROM records WHERE run_id=? AND rtype=?", (boots[b]["run_id"], stlg.CAN2)) if cid in COMPANION_IDS)
    check("receive_only_no_command_frames",
          set(origins) == {"external_controller"} and not api and comp_logged == 0 and
          all(boots[b]["node"].c["companion_frames_seen"] == 0 for b in boots),
          f"{sum(origins.values())} frames on the bus, all from the external controller ({dict(origins)}); the node "
          f"class has no transmit or supervisor method ({api or 'none found'}); frames with a supervisor or monitor "
          f"identifier in the logs: {comp_logged}")

    # 2. missing or invalid data is never zero or healthy
    lm = [(clock.true(r[0] / 1000.0), json.loads(r[1])) for r in db.execute(
        "SELECT t_local_ms, payload FROM live WHERE schema='sem.telemetry.v4' ORDER BY run_id, seq")]

    def qs(sig, a, b):
        return collections.Counter((m["m"][sig]["q"], m["m"][sig]["v"] is None) for t, m in lm if a <= t < b)
    sil = qs("ctrl.dc_voltage", SILENCE[0] + 0.5, SILENCE[1])
    cur = qs("ctrl.dc_current", DROP_CURRENTS[1] + 0.5, DROP_CURRENTS[2])
    vin = qs("ctrl.dc_voltage", VBUS_INVALID[0] + 0.2, VBUS_INVALID[1])
    whl = qs("wheel.wheel_drive.speed", WHEEL_DISCONNECT[1] + 1.0, WHEEL_DISCONNECT[2])
    gns = qs("gnss.speed", GNSS_OUT[0] + 0.5, GNSS_OUT[1])
    bad_value = sum(1 for _t, m in lm for e in m["m"].values() if e["q"] not in ("valid", "unverified") and e["v"] is not None)
    bad_db = db.execute("SELECT COUNT(*) FROM measurements WHERE validity NOT IN ('valid','unverified') AND value IS "
                        "NOT NULL").fetchone()[0]
    silent = [m["adapter"]["silent_ms"] for t, m in lm if SILENCE[0] + 0.5 <= t < SILENCE[1]]
    ok2 = (sil and set(sil) == {("stale", True)} and cur and set(cur) == {("stale", True)} and vin and
           set(vin) == {("invalid", True)} and whl and all(v for (_q, v) in whl) and gns and set(gns) == {("invalid", True)}
           and bad_value == 0 and bad_db == 0 and silent and min(silent) >= 500)
    check("missing_or_invalid_data_is_null_never_zero",
          ok2,
          f"live messages: DC voltage during controller silence {dict(sil)} with adapter silent "
          f"{min(silent) if silent else '?'}-{max(silent) if silent else '?'} ms; DC current while ctrl_currents was "
          f"not sent {dict(cur)}; DC voltage with its validity flag cleared {dict(vin)}; drive-wheel speed with the "
          f"sensor disconnected {dict(whl)}; GNSS speed without fix {dict(gns)} (q, value null); entries with a "
          f"value but not valid: {bad_value} live, {bad_db} in the pit's measurements table")

    # 3. every dropped record accounted for
    acc = []
    ok3 = True
    for b in sorted(boots):
        nd, w, imp = boots[b]["node"], boots[b]["writer"], imps[b]
        lost = boots[b].get("lost_records_at_crash", 0)
        a = imp.get("accounting") or {}
        ok3 &= imp["records"] == w.records and a.get("missing_from_file", 1) == 0 and imp["blocks_corrupt"] == 0
        if b == 2:
            ok3 &= imp["final_counters"] and a["unit_log_records"] == imp["records"]
        acc.append(f"boot {b}: {imp['records']} records in the log = written {w.records}; queue drops "
                   f"{nd.c['log_dropped_queue']}, storage drops {w.dropped_storage}"
                   + (f"; {lost} records lost in the restart (queue and open block), after the last counters "
                      f"record, as the import reports ('{a.get('after_last_counters')}')" if b == 1 else
                      "; orderly close, final counters record matches the file"))
    stall = boots[1]["node"].c["log_dropped_queue"]
    ok3 &= stall > 0
    up = []
    for b in sorted(boots):
        nd = boots[b]["node"]
        rid = boots[b]["run_id"]
        stored = {r[0] for r in db.execute("SELECT seq FROM live WHERE run_id=?", (rid,))}
        rejected = live_rep.get("rejected_seqs", {}).get(rid, set())
        dropped = {s for _t, _w, s in nd.drop_log}
        crash = set(boots[b].get("backlog_lost_at_crash", []))
        unacked = set(live_rep.get("unacked", {}).get(rid, []))
        cls = {s: ("stored" if s in stored else "rejected" if s in rejected else "dropped on the car" if s in dropped
                   else "lost in the restart" if s in crash else "unacknowledged" if s in unacked else "UNACCOUNTED")
               for s in range(nd.up_seq)}
        cnt = collections.Counter(cls.values())
        ok3 &= cnt.get("UNACCOUNTED", 0) == 0
        up.append(f"boot {b}: published {nd.up_seq} = " + ", ".join(f"{v} {k}" for k, v in sorted(cnt.items())))
    check("every_dropped_record_accounted_for", ok3,
          "; ".join(acc) + f". Uplink: " + "; ".join(up))

    # 4. acquisition continues through the uplink outage
    rid1 = boots[1]["run_id"]
    per_s = collections.Counter()
    for (t_us,) in db.execute("SELECT t_local_us FROM records WHERE run_id=? AND rtype IN (?,?)",
                              (rid1, stlg.WHEEL_EDGES, stlg.CAN2)):
        per_s[int(clock.true(t_us / 1e6))] += 1
    a, b = int(BROKER_DOWN[0]), int(BROKER_DOWN[1])
    before = [per_s[s] for s in range(70, 80)]
    during = [per_s[s] for s in range(a, b)]
    nd1 = boots[1]["node"]
    ok4 = min(during) >= 0.97 * min(before) and nd1.c["uplink_dropped"] > 0
    check("acquisition_continues_through_uplink_outage", ok4,
          f"CAN and wheel records logged per second while the uplink was down {min(during)}-{max(during)}, in the "
          f"10 s before {min(before)}-{max(before)}; uplink backlog high water {nd1.c['uplink_queue_high_water']}/"
          f"{ncfg.uplink_queue_capacity}, {nd1.c['uplink_dropped']} oldest messages dropped on the car and counted")

    # 5. re-ingestion adds nothing
    ok5 = all(reimps[b]["new_records"] == 0 and reimps[b]["new_measurements"] == 0 for b in boots) and \
        live_rep.get("duplicate_outcome") in ("duplicate", None)
    check("reingestion_creates_no_duplicates", ok5,
          "second import of each log: " + ", ".join(f"boot {b} {reimps[b]['new_records']} records / "
                                                    f"{reimps[b]['new_measurements']} measurements added" for b in boots)
          + (f"; an exact copy of live message seq {live_rep['duplicate_seq']} re-published: "
             f"{live_rep['duplicate_outcome']}" if live_rep.get("duplicate_outcome") else ""))

    # 6. speed and distance from edges
    err, n_ok = [], 0
    for b in boots:
        for t_s, v in db.execute("SELECT t_sample_us, value FROM measurements WHERE run_id=? AND signal="
                                 "'wheel.wheel_l.speed' AND validity='valid' AND t_sample_us IS NOT NULL",
                                 (boots[b]["run_id"],)):
            vt = _true_at(truth, clock, t_s, 1)
            if vt > 0.5:
                err.append(v - vt)
            n_ok += 1
    rms = math.sqrt(sum(e * e for e in err) / len(err)) if err else math.nan
    d = {b: energy.wheel_distance(db, boots[b]["run_id"], "wheel_l") for b in boots}
    pitch = vcfg.wheel_circumference_m / vcfg.wheel_ppr
    # true distance from the session's start to its last distance record in the log (the records still in the
    # queue when boot 1 lost power never reached the log)
    d_true = {b: _true_at(truth, clock, d[b]["t_us"], 2) - _true_at(truth, clock, clock.local(boots[b]["t_start"]) * 1e6, 2)
              for b in boots}
    derr = {b: d[b]["distance_m"] - d_true[b] for b in boots}
    dd = energy.wheel_distance(db, boots[1]["run_id"], "wheel_drive")
    stand = collections.Counter(r[0] for r in db.execute(
        "SELECT validity FROM measurements WHERE run_id=? AND signal='wheel.wheel_l.speed' AND t_rx_us>?",
        (boots[2]["run_id"], int(clock.local(150.0) * 1e6))))
    ok6 = (rms < 0.05 and all(abs(e) <= 2 * pitch for e in derr.values()) and dd["no_evidence_records"] > 0
           and stand.get("valid", 0) + stand.get("no_evidence", 0) > 0)
    check("speed_and_distance_from_edge_timing", ok6,
          f"wheel_l speed: {len(err)} edge-period samples above 0.5 m/s, RMS error {rms:.4f} m/s against the "
          f"simulated speed; distance boot 1 {d[1]['distance_m']:.2f} m ({derr[1]:+.3f} m), boot 2 "
          f"{d[2]['distance_m']:.2f} m ({derr[2]:+.3f} m), pitch {pitch:.4f} m; drive wheel: "
          f"{dd['no_evidence_records']} no-evidence records while disconnected; parked at the end: {dict(stand)} "
          "(0 m/s only with the line held active, otherwise no evidence)")

    # 7. energy at two boundaries
    en = {}
    ok7 = True
    for b in boots:
        rid = boots[b]["run_id"]
        for bound, col in (("controller_input", 3), ("battery", 4)):
            r = energy.vi_energy(db, rid, bound)
            span = db.execute("SELECT MIN(t_local_us), MAX(t_local_us) FROM records WHERE run_id=?", (rid,)).fetchone()
            covered_true = _true_energy(truth, clock, [(span[0] / 1e6, span[1] / 1e6)], col) - \
                _true_energy(truth, clock, r["missing_intervals"], col)
            rel = abs(r["energy_J"] - covered_true) / covered_true if covered_true else math.nan
            r["true_over_covered_J"] = covered_true
            r["true_total_J"] = _true_energy(truth, clock, [(span[0] / 1e6, span[1] / 1e6)], col)
            r["relative_error"] = rel
            en[(b, bound)] = r
            ok7 &= rel < 0.01
    miss = en[(1, "controller_input")]["missing_intervals"]
    causes = [m[2] for m in miss]
    ok7 &= len(miss) >= 3
    e_c = sum(en[(b, "controller_input")]["energy_J"] for b in boots)
    e_b = sum(en[(b, "battery")]["energy_J"] for b in boots)
    check("energy_from_valid_aligned_v_and_i_at_two_boundaries", ok7,
          f"controller input {e_c / 3600:.3f} Wh, battery {e_b / 3600:.3f} Wh (difference {(e_b - e_c) / 3600:.3f} Wh: "
          f"telematics, auxiliaries and harness); each within "
          f"{max(en[k]['relative_error'] for k in en) * 100:.3f} % of the simulated energy over the same covered "
          f"intervals; boot 1 controller-input missing intervals {len(miss)} "
          f"({en[(1, 'controller_input')]['missing_s']:.2f} s): " + " | ".join(causes))

    # 8. restart recorded as a gap
    b2 = imps[2]["boot"] or {}
    gap = (db.execute("SELECT MIN(t_local_us) FROM records WHERE run_id=?", (boots[2]["run_id"],)).fetchone()[0] -
           db.execute("SELECT MAX(t_local_us) FROM records WHERE run_id=?", (boots[1]["run_id"],)).fetchone()[0]) / 1e6
    check("telemetry_restart_is_a_new_session_and_a_reported_gap",
          b2.get("boot_count") == 2 and "power loss" in b2.get("cause", "") and gap >= RESTART[1] - RESTART[0] - 0.1,
          f"boot 2 log starts with BOOT (count {b2.get('boot_count')}, cause '{b2.get('cause')}'); {gap:.2f} s "
          f"without any record between the sessions; boot 1 ends without a final counters record "
          f"({imps[1]['accounting']['after_last_counters']})")
    # 9. live path: what another client publishes is validated, a v4 message with a supervisor block refused
    if live_rep.get("injected_invalid"):
        rej = db.execute("SELECT reason FROM rejected WHERE source='live'").fetchall()
        reasons = sorted({r[0] for r in rej})
        check("live_messages_validated_before_storage",
              len(rej) == live_rep["injected_invalid"] and any("'sup' block" in r for r in reasons),
              f"{live_rep['injected_invalid']} malformed messages published by another client, {len(rej)} rejected "
              f"with reasons {reasons}; receipts by outcome {live_rep.get('rx')}")
    summary = {"import": {b: imps[b] for b in boots}, "energy": {f"boot{b}_{k}": v for (b, k), v in en.items()},
               "distance": d, "speed_rms_mps": rms}
    return checks, summary


def plots(ev: dict, db: sqlite3.Connection, out: pathlib.Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    clock, boots = ev["clock"], ev["boots"]

    def s(sig, valid_only=True):
        xs, ys = [], []
        for b in sorted(boots):
            for t, v, _u, _q in energy.series(db, boots[b]["run_id"], sig, usable_only=valid_only):
                xs.append(clock.true(t / 1e6))
                ys.append(v)
        return xs, ys
    files = []
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    tt = [r[0] for r in ev["truth"]]
    ax[0].plot(tt, [r[1] for r in ev["truth"]], color="0.7", lw=3, label="simulated speed")
    for ch in CHANNELS:
        ax[0].plot(*s(f"wheel.{ch}.speed"), ".", ms=2, label=f"{ch} (edge periods)")
    ax[0].plot(*s("gnss.speed"), ".", ms=1, label="GNSS")
    ax[0].set_ylabel("speed [m/s]")
    ax[0].legend(fontsize=7, loc="upper right")
    for k, ch in enumerate(CHANNELS):
        for b in sorted(boots):
            rows = energy.series(db, boots[b]["run_id"], f"wheel.{ch}.distance", usable_only=False)
            ax[1].plot([clock.true(t / 1e6) for t, *_r in rows], [v for _t, v, *_r in rows], lw=1, color=f"C{k}",
                       label=ch if b == 1 else None)
    ax[1].set_ylabel("distance [m] (per session)")
    ax[1].set_xlabel("time [s]")
    ax[1].legend(fontsize=7)
    fig.suptitle("Wheel speed and distance from edge timing (HOST SIMULATION)")
    fig.savefig(out / "speed_distance.png", dpi=110)
    files.append("speed_distance.png")
    fig, ax = plt.subplots(figsize=(10, 4))
    for b in sorted(boots):
        for bound, v_sig, i_sig, c in (("controller input", "ctrl.dc_voltage", "ctrl.dc_current", "C0"),
                                       ("battery", "batt.voltage", "batt.current", "C1")):
            V = energy.series(db, boots[b]["run_id"], v_sig)
            I = energy.series(db, boots[b]["run_id"], i_sig)
            vt = [r[0] for r in V]
            xs, ys = [], []
            for t, i, *_r in I:
                k = bisect.bisect_left(vt, t)
                if 0 < k < len(V) and abs(vt[k] - t) < 20000:
                    xs.append(clock.true(t / 1e6))
                    ys.append(V[k][1] * i)
            ax.plot(xs, ys, ".", ms=1, color=c, label=bound if b == 1 else None)
    ax.set_ylabel("power [W] (valid, aligned V x I)")
    ax.set_xlabel("time [s]")
    ax.legend()
    fig.savefig(out / "power.png", dpi=110)
    files.append("power.png")
    fig, ax = plt.subplots(figsize=(10, 3.5))
    sigs = ["ctrl.dc_voltage", "ctrl.dc_current", "wheel.wheel_drive.speed", "gnss.speed"]
    colors = {"valid": "tab:green", "unverified": "tab:olive", "invalid": "tab:red", "out_of_range": "tab:purple",
              "decode_error": "black", "no_evidence": "tab:orange"}
    pts = collections.defaultdict(lambda: ([], []))
    for y, sig in enumerate(sigs):
        for b in sorted(boots):
            for t, _v, _u, q in energy.series(db, boots[b]["run_id"], sig, usable_only=False):
                pts[q][0].append(clock.true(t / 1e6))
                pts[q][1].append(y)
    for q, (xs, ys) in pts.items():
        ax.plot(xs, ys, "|", color=colors[q], ms=6, ls="none", label=q)
    ax.legend(fontsize=7, loc="upper left", ncol=len(pts))
    ax.set_yticks(range(len(sigs)), sigs)
    ax.set_xlabel("time [s] (no mark: nothing received)")
    fig.tight_layout()
    fig.savefig(out / "data_quality.png", dpi=110)
    files.append("data_quality.png")
    plt.close("all")
    return files


def run(out: pathlib.Path, in_process: bool = False, pace: float = 4.0, duration: float = DURATION) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    live_rep: dict = {"rejected_seqs": {}, "unacked": {}}
    dbp = out / "pit.sqlite"
    if in_process:
        links = {}

        def factory(rid):
            links[rid] = SimLink(outages=(BROKER_DOWN,))
            return links[rid]
        ev = simulate(out, factory, duration)
        db = ingest.connect(dbp)
        for rid, link in links.items():
            r = ingest.ingest_live(db, link.broker, "sem/car/telemetry")
            live_rep[rid] = r
        mode = "in-process simulated link"
    else:
        ev, db, mode = _run_broker(out, dbp, live_rep, pace, duration)
    checks, summ = analyse(ev, db, live_rep)
    files = plots(ev, db, out)
    with (out / "measurements.csv").open("w") as f:
        f.write("run_id,record_id,source,signal,value,unit,t_rx_us,t_sample_us,t_unc_us,source_seq,validity,provenance\n")
        for r in db.execute("SELECT run_id, record_id, source, signal, value, unit, t_rx_us, t_sample_us, t_unc_us, "
                            "source_seq, validity, provenance FROM measurements ORDER BY run_id, t_rx_us, record_id"):
            f.write(",".join("" if x is None else str(x) for x in r) + "\n")
    res = {"kind": "HOST SIMULATION (receive-only telematics node; simulated external controller)", "mode": mode,
           "unit": UNIT, "duration_s": duration, "repo_commit": ev["git"], "working_tree_dirty": ev["dirty"],
           "checks": checks, "counters": {b: ev["boots"][b]["node"].c for b in ev["boots"]},
           "energy": {k: {kk: vv for kk, vv in v.items() if kk != "notes"} for k, v in summ["energy"].items()},
           "distance": summ["distance"], "speed_rms_mps": summ["speed_rms_mps"], "plots": files,
           "wall_s": ev["wall_s"]}
    (out / "summary.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    L = ["# Telematics end-to-end demonstration (HOST SIMULATION)", "",
         f"Unit `{UNIT}`, {duration:.0f} s of simulated driving, {mode}, commit `{ev['git'][:12]}`"
         f"{' plus uncommitted changes' if ev['dirty'] else ''}. Command: `python3 tools/run_telematics_demo.py "
         f"--out build/telematics_demo{' --in-process' if in_process else ''}`. The external controller is a Python "
         "stand-in broadcasting the semmc simulation fixture; the node is the host model of the receive-only "
         "telematics unit, not its firmware; no supervisor takes part. Nothing here was measured on hardware.", "",
         "| Check | Result | Evidence |", "|---|---|---|"]
    L += [f"| `{c['id']}` | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |" for c in checks]
    L += ["", "## Energy", "", "| Session | Boundary | Energy [Wh] | Covered [s] | Missing [s] | Missing-energy bound [Wh] "
          "| Error vs simulation |", "|---|---|---|---|---|---|---|"]
    for k, v in summ["energy"].items():
        L.append(f"| {k.split('_')[0]} | {v['boundary']} | {v['energy_Wh']:.4f} | {v['covered_s']:.1f} | "
                 f"{v['missing_s']:.2f} | {v['missing_energy_bound_J'] / 3600:.4f} | {v['relative_error'] * 100:.3f} % |")
    L += ["", "Controller input energy is measured by the controller's own sensors at its DC terminals; battery "
          "energy by the battery-side monitor, which also sees the telematics unit and the other auxiliary loads. "
          "Missing intervals are not filled in; their bound is the largest observed power times their length.", "",
          "Plots: " + ", ".join(f"`{f}`" for f in files) + ".", ""]
    (out / "summary.md").write_text("\n".join(L))
    db.close()
    return res


def _run_broker(out, dbp, live_rep, pace, duration):
    import paho.mqtt.client as mqtt
    from host.telematics.mqtt_link import MqttLink
    from tools import mqtt_broker
    broker = mqtt_broker.Mosquitto(out / "broker")
    broker.start()
    pit_cmd = [sys.executable, "-m", "host.pit.mqtt_ingest", "--port", str(broker.port), "--db", str(dbp)]
    pit = subprocess.Popen(pit_cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True)
    links = {}

    class Recording(MqttLink):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.payloads = {}

        def deliver(self, t_true, topic, seq, payload):
            ok = super().deliver(t_true, topic, seq, payload)
            if ok:
                self.payloads[seq] = payload
            return ok

    def factory(rid):
        link = Recording("127.0.0.1", broker.port, client_id=f"car-{rid}")
        link.start()
        link.wait_connected(10)
        links[rid] = link
        return link
    time.sleep(0.5)
    invalid = {}

    def inject(t):
        rid = run_id(1)
        good = json.loads(next(iter(links[rid].payloads.values())))
        bad = [json.dumps(dict(good, seq=10**6, m=dict(good["m"], **{"ctrl.dc_voltage": {"v": 0.0, "u": "V",
                                                                     "q": "stale", "age_ms": 900, "seq": None,
                                                                     "ts": "rx"}}))).encode(),
               json.dumps(dict(good, seq=10**6 + 1, sup={"torque_Nm": 2.0})).encode(),
               b"{not json"]
        invalid["n"] = len(bad)
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sem-demo-injector", protocol=mqtt.MQTTv311)
        c.connect("127.0.0.1", broker.port, keepalive=5)
        c.loop_start()
        for p in bad + [links[rid].payloads[min(links[rid].payloads)]]:
            c.publish("sem/car/telemetry", p, qos=1).wait_for_publish(timeout=5)
        live_rep["duplicate_seq"] = min(links[rid].payloads)
        c.disconnect()
        c.loop_stop()
    actions = [(10.0, inject), (BROKER_DOWN[0], lambda t: broker.kill()), (BROKER_DOWN[1], lambda t: broker.start())]
    ev = simulate(out, factory, duration, actions=actions, pace=pace)
    for rid, link in links.items():
        if link.client.is_connected():
            live_rep["unacked"][rid] = link.flush(15.0)
    db = sqlite3.connect(dbp, timeout=10)
    end = time.monotonic() + 15.0
    while time.monotonic() < end:
        have = {(r[0], r[1]) for r in db.execute("SELECT run_id, seq FROM live")}
        if all((rid, s) in have for rid, link in links.items() for s in link.acked_seqs()):
            break
        time.sleep(0.2)
    db.close()
    pit.terminate()
    pit.wait(15)
    for link in links.values():
        try:
            link.stop()
        except Exception:
            pass
    broker.stop()
    db = ingest.connect(dbp)
    rx = collections.Counter(r[0] for r in db.execute("SELECT outcome FROM rx"))
    dup = db.execute("SELECT outcome FROM rx WHERE run_id=? AND seq=? ORDER BY rx", (run_id(1), live_rep["duplicate_seq"])
                     ).fetchall()
    live_rep["duplicate_outcome"] = dup[-1][0] if len(dup) >= 2 else "not received twice"
    live_rep["rx"] = dict(rx)
    live_rep["injected_invalid"] = invalid.get("n")
    return ev, db, f"real Mosquitto broker on loopback, pit ingestion service as its own process, pace {pace:g}x"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "telematics_demo")
    ap.add_argument("--in-process", action="store_true", help="simulated link and broker (no Mosquitto needed)")
    ap.add_argument("--pace", type=float, default=4.0, help="simulated seconds per wall-clock second (broker mode)")
    ap.add_argument("--samples", type=pathlib.Path, help="copy summary.md, summary.json and the plots here")
    a = ap.parse_args()
    if not a.in_process:
        from tools import mqtt_broker
        if mqtt_broker.find_mosquitto() is None:
            print("TELEMATICS NOT AVAILABLE: no mosquitto binary (docs/MQTT_SETUP.md), or use --in-process")
            return 2
    out = a.out if a.out.is_absolute() else ROOT / a.out
    res = run(out, a.in_process, a.pace)
    for c in res["checks"]:
        print(f"TELEMATICS {'PASS' if c['pass'] else 'FAIL'} {c['id']}: {c['detail']}")
    if a.samples:
        s = a.samples if a.samples.is_absolute() else ROOT / a.samples
        s.mkdir(parents=True, exist_ok=True)
        for f in ["summary.md", "summary.json"] + res["plots"]:
            shutil.copy(out / f, s / f)
    ok = all(c["pass"] for c in res["checks"])
    print(f"TELEMATICS {'ALL PASS' if ok else 'FAILURES'}: {sum(c['pass'] for c in res['checks'])}/"
          f"{len(res['checks'])} checks; outputs in {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
