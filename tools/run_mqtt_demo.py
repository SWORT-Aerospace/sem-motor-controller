#!/usr/bin/env python3
"""LEGACY supervised telemetry pipeline through a real local MQTT broker (host software; research only).

    python3 tools/run_mqtt_demo.py --legacy-supervised --out build/mqtt_demo [--duration 120] [--pace 2]

Superseded for the telematics delivery by tools/run_telematics_demo.py, which runs the receive-only node
against a simulated external controller. This one keeps the v0.5 chain with the ECO supervisor and the
project's own controller core, and runs only when `--legacy-supervised` is given.

Needs the C host build (`cmake -S firmware -B build && cmake --build build`)
and a Mosquitto binary (docs/MQTT_SETUP.md). Chain:

  synthetic driver + plant -> controller core (C) -> CAN -> telematics node model
  (receive timestamps, supervisor task, bounded log queue -> STLG local log)
  -> uplink: paho-mqtt client, QoS 1 -> Mosquitto (separate process, loopback)
  -> pit ingestion service (separate process): validate -> SQLite
  -> offline import of the STLG log into the same database.

The simulation runs `pace` times faster than the wall clock so that the broker,
the pit service and the network threads run in real time against it.

Scenario (controller time for the default 120 s; scaled for other durations):
  0.1 arm, 0.3 ECO; speed hold at 6 m/s by the supervisor (whole run)
  15    four malformed messages and one valid sem.telemetry.v1 message published by another client
  20    an exact copy of an earlier car message published again (duplicate)
  40-60 broker killed (SIGKILL) and restarted with its persistence files
  75-85 pit service killed (SIGKILL) and restarted (same client id, persistent session)
  90-100 GNSS without fix: UTC in holdover
Prints one "MQTT ..." line per check; exit code 1 if any fails.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paho.mqtt.client as mqtt  # noqa: E402

from host.logger.semmc_log import io_event  # noqa: E402
from host.csia_adapter.adapter import AdapterParams  # noqa: E402
from host.pit import ingest, shadow_replay  # noqa: E402
from host.telematics.mqtt_link import MqttLink  # noqa: E402
from host.telemetry_adapter.legacy_node import SCHEMA, NodeConfig  # noqa: E402
from tools import mqtt_broker  # noqa: E402
from tools.run_host_demo import build_chain, simulate  # noqa: E402

RUN_ID = "HOSTMQTT-0001"
BASE = {"inject_invalid": 15.0, "inject_duplicate": 20.0, "broker_down": (40.0, 60.0), "pit_down": (75.0, 85.0),
        "gnss_out": (90.0, 100.0)}


SUPERVISOR_PERIOD_MS = 20.0


def step_timing(svc_ms: dict, period_ms: float = SUPERVISOR_PERIOD_MS) -> tuple[bool, str]:
    """Whether the telematics service step ever waits on the network, judged from its wall times per phase.

    A step that blocks on the broker or the pit (a synchronous publish, connect or acknowledgement wait)
    is slow on every attempt while the far end is down, so it shows as a high 99th percentile or as many
    steps over the supervisor period in the outage phases. A single slow step is what a shared host
    produces when another process (here, the restarted pit service) takes the CPU; it is reported but
    does not fail the check. Criterion, per phase: 99th percentile below a quarter of the period, and at
    most one step in 200 (at least one) at or above the period."""
    p99 = {k: sorted(v)[int(0.99 * (len(v) - 1))] for k, v in svc_ms.items() if v}
    mx = {k: max(v) for k, v in svc_ms.items() if v}
    over = {k: sum(x >= period_ms for x in v) for k, v in svc_ms.items() if v}
    allowed = {k: max(1, len(v) // 200) for k, v in svc_ms.items() if v}
    ok = bool(p99) and all(p99[k] < period_ms / 4 for k in p99) and all(over[k] <= allowed[k] for k in over)
    detail = ", ".join(f"{k} {p99[k]:.2f}/{mx[k]:.2f} ms, {over[k]} of {len(svc_ms[k])} steps over the period"
                       for k in p99)
    return ok, detail


def scenario(duration: float) -> dict:
    k = duration / 120.0
    return {key: tuple(round(x * k, 2) for x in v) if isinstance(v, tuple) else round(v * k, 2)
            for key, v in BASE.items()}


INVALID = [
    ("truncated JSON", lambda good: good[: len(good) // 2]),
    ("wrong schema", lambda good: json.dumps(dict(json.loads(good), schema="sem.telemetry.v0")).encode()),
    ("seq as boolean", lambda good: json.dumps(dict(json.loads(good), seq=True)).encode()),
    ("vbus out of range", lambda good: json.dumps(dict(json.loads(good), seq=10**6,
                                                       ctrl=dict(json.loads(good)["ctrl"], vbus_V=9999.0))).encode()),
]


# a valid message in the previous schema version from another producer: the pit must still accept it
LEGACY_V1 = json.dumps({"schema": "sem.telemetry.v1", "run_id": "LEGACY-V1", "seq": 0, "t_local_ms": 0, "utc": None,
                        "utc_q": "none", "ctrl": {"state": "READY"}, "replayed": False}, sort_keys=True).encode()


class RecordingLink(MqttLink):
    """MqttLink that keeps what the car handed over (for the demonstration's accounting)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.payloads: dict[int, bytes] = {}
        self.replayed_handed: set[int] = set()

    def deliver(self, t_true, topic, seq, payload):
        ok = super().deliver(t_true, topic, seq, payload)
        if ok:
            self.payloads[seq] = payload
            if json.loads(payload)["replayed"]:
                self.replayed_handed.add(seq)
        return ok


def publish_raw(port: int, topic: str, payloads: list[bytes]) -> None:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sem-demo-injector", protocol=mqtt.MQTTv311)
    c.connect("127.0.0.1", port, keepalive=5)
    c.loop_start()
    for p in payloads:
        c.publish(topic, p, qos=1).wait_for_publish(timeout=5)
    c.disconnect()
    c.loop_stop()


def run(out: pathlib.Path, build: pathlib.Path, duration: float = 120.0, pace: float = 2.0) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sc = scenario(duration)
    broker = mqtt_broker.Mosquitto(out / "broker")
    broker.start()
    dbp = out / "pit.sqlite"
    pit_cmd = [sys.executable, "-m", "host.pit.mqtt_ingest", "--port", str(broker.port), "--db", str(dbp)]
    pit = {"proc": subprocess.Popen(pit_cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True)}
    ncfg = NodeConfig()
    link = RecordingLink("127.0.0.1", broker.port, client_id=f"car-{RUN_ID}")
    link.start()
    if not link.wait_connected(10):
        raise RuntimeError("car-side MQTT client could not connect to the local broker")
    time.sleep(0.5)                                         # let the pit service subscribe

    def io_schedule(us):
        return [io_event(0, arm=False, throttle=0.0, eco=False), io_event(us(0.1), arm=True), io_event(us(0.3), eco=True)]

    ch = build_chain(out, build, link, run_id=RUN_ID, flash_stalls=(), supervisor_stalls=(),
                     gnss_outages=(sc["gnss_out"],), wheel_faults=(), temp_faults=(), io_schedule=io_schedule, sup_off=None,
                     ncfg=ncfg, kind="HOST SOFTWARE with a real local MQTT broker - not a vehicle run")
    node = ch.node
    wall = {}                                               # event -> monotonic seconds
    svc_ms = collections.defaultdict(list)                  # phase -> node.service wall times (ms)
    backlog_max = [0]
    phase = ["normal"]
    orig_service = node.service

    def timed_service(t, dt):
        t0 = time.perf_counter()
        orig_service(t, dt)
        svc_ms[phase[0]].append((time.perf_counter() - t0) * 1000.0)
        backlog_max[0] = max(backlog_max[0], len(node.uq))

    node.service = timed_service
    seq_at = {}

    def mark(name):
        def f(t):
            wall[name] = time.monotonic()
            seq_at[name] = node.up_seq
        return f

    def kill_broker(t):
        mark("broker_kill")(t)
        broker.kill()
        phase[0] = "broker_down"

    def start_broker(t):
        broker.start()
        mark("broker_start")(t)
        phase[0] = "after_broker"

    def kill_pit(t):
        mark("pit_kill")(t)
        pit["proc"].kill()
        pit["proc"].wait(10)
        phase[0] = "pit_down"

    def start_pit(t):
        pit["proc"] = subprocess.Popen(pit_cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True)
        mark("pit_start")(t)
        phase[0] = "after_pit"

    good_example = {}

    def inject_invalid(t):
        good = next(iter(link.payloads.values()))
        good_example["payload"] = good
        publish_raw(broker.port, ncfg.topic, [f(good) for _n, f in INVALID] + [LEGACY_V1])

    dup = {}

    def inject_duplicate(t):
        seq = min(link.payloads)
        dup["seq"] = seq
        publish_raw(broker.port, ncfg.topic, [link.payloads[seq]])

    actions = [(sc["inject_invalid"], inject_invalid), (sc["inject_duplicate"], inject_duplicate),
               (sc["broker_down"][0], kill_broker), (sc["broker_down"][1], start_broker),
               (sc["pit_down"][0], kill_pit), (sc["pit_down"][1], start_pit)]
    wall["sim_start"] = time.monotonic()
    unix0 = time.time()
    truth, _summary_c = simulate(ch, duration, actions=actions, pace=pace)
    wall["sim_end"] = time.monotonic()
    late_s = wall["sim_end"] - wall["sim_start"] - duration / pace

    unacked = link.flush(15.0)
    # wait until the pit has stored everything acknowledged (or 15 s pass)
    db = sqlite3.connect(dbp, timeout=10)
    end = time.monotonic() + 15.0
    acked = link.acked_seqs()
    while time.monotonic() < end:
        have = {r[0] for r in db.execute("SELECT seq FROM live WHERE run_id=?", (RUN_ID,))}
        if set(acked) <= have:
            break
        time.sleep(0.2)
    db.close()
    pit["proc"].terminate()
    pit_rc = pit["proc"].wait(15)
    link.stop()
    broker.stop()

    # ---------------------------------------------------------------- offline import + evidence
    db = ingest.connect(dbp)
    imp = ingest.import_log(db, out / "run.stlg")
    # shadow replay of R3v and CSIA2 on the imported log (no injected faults here: nothing to score against)
    kt = 1.5 * ch.cfg["motor"]["pole_pairs"] * ch.cfg["motor"]["flux_linkage_Wb"]
    shadow = shadow_replay.run(db, RUN_ID, AdapterParams(wheel_radius_m=ch.C / (2 * math.pi), gear_ratio=ch.gear,
                                                         freewheel=False, kt_Nm_per_A=kt),
                               kt, ch.C / (ch.scfg.wheel_ppr * ch.scfg.wheel_window_s), out / "pit_replay")
    checks = []

    def check(cid, ok, detail):
        checks.append({"id": cid, "pass": bool(ok), "detail": detail})

    # 1. broker outage seen and recovered by the car-side client
    ev = link.events
    t_k, t_s = wall["broker_kill"], wall["broker_start"]
    disc = next((t for t, kind, _d in ev if kind == "disconnect" and t >= t_k), None)
    reconn = next((t for t, kind, _d in ev if kind == "connect" and t >= t_s), None)
    check("broker_outage_detected_and_recovered",
          disc is not None and disc - t_k < 2.0 and reconn is not None and reconn - t_s < 10.0,
          f"broker killed at {sc['broker_down'][0]:.1f} s, client saw the disconnect "
          f"{(disc - t_k) * 1000:.0f} ms later (wall); broker restarted at {sc['broker_down'][1]:.1f} s, client "
          f"reconnected {(reconn - t_s):.2f} s later (wall), i.e. {(reconn - t_s) * pace:.1f} s of controller time")

    # 2. control and the uplink path never wait on the network
    def rate(a, b):
        return [node.sup_rate[s] for s in range(int(math.ceil(a)), int(b))]
    t_reconn_sim = sc["broker_down"][1] + (reconn - t_s) * pace
    r_out = rate(sc["broker_down"][0], t_reconn_sim)
    eco = [s for (t, s, *_r) in truth if sc["broker_down"][0] <= t < t_reconn_sim]
    p99 = {k: sorted(v)[int(0.99 * (len(v) - 1))] for k, v in svc_ms.items() if v}
    mx = {k: max(v) for k, v in svc_ms.items() if v}
    timing_ok, timing = step_timing(svc_ms)
    check("control_and_uplink_unaffected_by_broker_outage",
          all(49 <= r <= 51 for r in r_out) and all(s == "ECO_ASSIST" for s in eco) and timing_ok,
          f"supervisor requests/s while the broker was unreachable {sorted(set(r_out))}; ECO_ASSIST in "
          f"{sum(s == 'ECO_ASSIST' for s in eco)}/{len(eco)} steps; telematics service step (log writer + uplink) "
          f"wall time p99/max: {timing} (supervisor period {SUPERVISOR_PERIOD_MS:g} ms; pass: p99 below a quarter "
          f"of the period and at most one step in 200 over it, per phase)")

    # 3. the local log keeps everything during the outage
    db.row_factory = None
    per_s = collections.Counter()
    for (t_us,) in db.execute("SELECT t_local_us FROM records WHERE run_id=? AND rtype=1", (RUN_ID,)):
        per_s[int(ch.clock.true(t_us / 1e6))] += 1
    a, b = int(sc["broker_down"][0]), int(sc["broker_down"][1])
    before = [per_s[s] for s in range(2, a)]
    during = [per_s[s] for s in range(a, b)]
    check("local_log_complete_during_broker_outage",
          imp["blocks_corrupt"] == 0 and imp["block_seq_gaps"] == 0 and node.c["log_dropped_queue"] == 0 and
          node.c["log_dropped_storage"] == 0 and imp["records"] == ch.writer.records and min(during) >= min(before),
          f"records written {ch.writer.records} = imported {imp['records']} ({imp['blocks_ok']} blocks ok, "
          f"{imp['blocks_corrupt']} corrupt, {imp['block_seq_gaps']} sequence gaps); log queue and storage drops "
          f"{node.c['log_dropped_queue']}/{node.c['log_dropped_storage']}; CAN records per second while the broker "
          f"was down {min(during)}-{max(during)}, before it {min(before)}-{max(before)}")

    # 4-6. sequence accounting
    db.row_factory = sqlite3.Row
    live = {r["seq"]: r for r in db.execute("SELECT * FROM live WHERE run_id=?", (RUN_ID,))}
    dropped = {seq for _t, _why, seq in node.drop_log}
    acked = link.acked_seqs()
    classes = {"stored at pit": set(), "dropped on car (queue full)": set(), "never acknowledged by broker": set(),
               "acknowledged by broker, not at pit": set(), "never handed to the link": set()}
    for s in range(node.up_seq):
        if s in live:
            classes["stored at pit"].add(s)
        elif s in dropped:
            classes["dropped on car (queue full)"].add(s)
        elif s in link.handed and s not in acked:
            classes["never acknowledged by broker"].add(s)
        elif s in acked:
            classes["acknowledged by broker, not at pit"].add(s)
        else:
            classes["never handed to the link"].add(s)
    n_cls = {k: len(v) for k, v in classes.items()}
    check("uplink_backlog_bounded_and_drops_counted",
          backlog_max[0] <= ncfg.uplink_queue_capacity and node.c["uplink_dropped"] == len(dropped) and
          not (dropped & set(live)),
          f"backlog high water {backlog_max[0]}/{ncfg.uplink_queue_capacity}; dropped on the car "
          f"{node.c['uplink_dropped']} (counter) = {len(dropped)} (sequence numbers "
          f"{min(dropped) if dropped else '-'}..{max(dropped) if dropped else '-'}); none of them reached the pit")
    check("every_sequence_number_accounted",
          sum(n_cls.values()) == node.up_seq and n_cls["acknowledged by broker, not at pit"] == 0 and
          n_cls["never acknowledged by broker"] == 0 and n_cls["never handed to the link"] == 0 and not unacked,
          f"published {node.up_seq}: " + ", ".join(f"{k} {v}" for k, v in n_cls.items()))
    rep_rows = sum(1 for r in live.values() if r["replayed"])
    check("replayed_messages_flagged",
          rep_rows == len(link.replayed_handed & set(live)) and rep_rows > 0,
          f"{rep_rows} messages stored with replayed=true, equal to the backlog messages sent after reconnection")

    # 7-8. validation and idempotence
    rx = db.execute("SELECT outcome, reason, seq, dup_flag FROM rx").fetchall()
    rej = [r["reason"] for r in rx if r["outcome"] == "rejected"]
    check("invalid_messages_rejected_before_storage",
          len(rej) == len(INVALID) and 10**6 not in live and
          db.execute("SELECT COUNT(*) FROM rejected").fetchone()[0] == len(INVALID),
          f"{len(INVALID)} malformed messages published, {len(rej)} rejected with reasons {sorted(rej)}; "
          "none stored")
    dups = [r for r in rx if r["outcome"] == "duplicate"]
    before_rows = db.execute("SELECT COUNT(*) FROM live").fetchone()[0]
    again = [ingest.ingest_payload(db, time.time(), ncfg.topic, link.payloads[s])[0] for s in sorted(live)
             if s in link.payloads]
    after_rows = db.execute("SELECT COUNT(*) FROM live").fetchone()[0]
    check("duplicates_ignored_and_ingest_idempotent",
          any(r["seq"] == dup["seq"] for r in dups) and after_rows == before_rows and set(again) == {"duplicate"},
          f"{len(dups)} duplicate receipts (the injected copy of seq {dup['seq']}"
          f"{' plus redeliveries' if len(dups) > 1 else ''}; MQTT DUP flag set on "
          f"{sum(1 for r in dups if r['dup_flag'])}); re-ingesting all {len(again)} stored payloads added "
          f"{after_rows - before_rows} rows")

    # 9. pit restart: the broker queued for the persistent session
    in_window = set(range(seq_at["pit_kill"], seq_at["pit_start"]))
    pev = db.execute("SELECT kind, detail FROM pit_events").fetchall()
    resumed = [d for k, d in pev if k == "connect" and "session_present=True" in d]
    check("pit_restart_without_loss",
          in_window and in_window <= set(live) and len(resumed) >= 1,
          f"{len(in_window)} car messages published while the pit service was down "
          f"({sc['pit_down'][0]:.0f}-{sc['pit_down'][1]:.0f} s): all stored after it reconnected "
          f"(session resumed {len(resumed)} time(s))")

    # 9b. live wheel speed (v2) and probe temperatures (v3) equal the values the offline import derives from the
    # logged records: the latest logged wheel window or probe sample at the message time
    import bisect
    log_sig = {}
    for kind, names, prefix in (("wheel", ncfg.wheel_channels, ""), ("temp", ncfg.temp_channels, "temp_")):
        for name in names:
            log_sig[kind, name] = db.execute("SELECT t_local_us, value FROM signals WHERE run_id=? AND name=? "
                                             "ORDER BY t_local_us", (RUN_ID, prefix + name)).fetchall()
    cmp = {k: collections.Counter() for k in ("wheel", "temp")}
    for r in live.values():
        m = json.loads(r["payload"])
        for kind, block in (("wheel", m["wheel"]["speed_mps"]), ("temp", m["temp"]["probe_degC"])):
            for name, v_live in block.items():
                sig = log_sig.get((kind, name), [])
                k = bisect.bisect_right([x[0] for x in sig], r["t_local_ms"] * 1000 + 1000) - 1
                if v_live is None:
                    cmp[kind]["null"] += 1
                    continue
                cmp[kind]["compared"] += 1
                if k < 0 or sig[k][1] is None or abs(sig[k][1] - v_live) > 1e-9:
                    cmp[kind]["mismatched"] += 1
    legacy = db.execute("SELECT schema, payload FROM live WHERE run_id='LEGACY-V1'").fetchall()
    w, tp = cmp["wheel"], cmp["temp"]
    check("live_wheel_and_temperature_match_log_and_v1_still_accepted",
          w["compared"] > 0 and tp["compared"] > 0 and w["mismatched"] == 0 and tp["mismatched"] == 0
          and len(legacy) == 1 and legacy[0][0] == "sem.telemetry.v1",
          f"live values (schema {SCHEMA}) compared with the latest logged record: {w['compared']} wheel speeds, "
          f"{w['mismatched']} differ, {w['null']} null (no fresh window); {tp['compared']} probe temperatures, "
          f"{tp['mismatched']} differ, {tp['null']} null (no fresh valid sample); a valid sem.telemetry.v1 message "
          f"from another producer was stored as v1: {len(legacy) == 1}")

    # 10. timestamps and missing data
    rows = [live[s] for s in sorted(live)]
    mono = all(b["t_local_ms"] > a["t_local_ms"] for a, b in zip(rows, rows[1:]))
    q = collections.Counter(r["utc_q"] for r in rows)
    g0, g1 = sc["gnss_out"]
    true_s = {r["seq"]: ch.clock.true(r["t_local_ms"] / 1000.0) for r in rows}     # car clock -> simulation time
    hold = [json.loads(r["payload"]) for r in rows if g0 + 3.0 <= true_s[r["seq"]] <= g1]   # 2.5 s PPS holdover
    hold_ok = bool(hold) and all(m["utc_q"] == "holdover" and m["gnss"]["speed_mps"] is None and not m["gnss"]["fix"]
                                 for m in hold)
    lat = {"live": [], "replayed": []}
    for r in rows:
        gen_unix = unix0 + true_s[r["seq"]] / pace
        lat["replayed" if r["replayed"] else "live"].append(r["received_s"] - gen_unix)
    check("timestamps_and_missing_data_explicit",
          mono and hold_ok and all(r["received_s"] for r in rows) and min(lat["live"]) > -0.05,
          f"car time t_local_ms increases with seq: {mono}; UTC quality {dict(q)}; {len(hold)} messages in the "
          f"GNSS outage carry utc_q=holdover, gnss speed null, fix false; pit receive time recorded for all; "
          f"generation-to-storage delay (wall clock) live median {sorted(lat['live'])[len(lat['live']) // 2] * 1000:.0f} ms, "
          f"max {max(lat['live']):.2f} s; replayed max {max(lat['replayed']) if lat['replayed'] else float('nan'):.1f} s")

    check("pit_shadow_replay_reports_missing_ground_truth",
          shadow.get("ticks", 0) > 0 and shadow.get("scoring") is None and
          any("no ground truth" in x for x in shadow.get("insufficient", [])),
          f"R3v and CSIA2 replayed in shadow mode over {shadow.get('ticks', 0)} ticks of the imported log; no faults "
          f"were injected, so the report lists attributions without scoring them (R3v "
          f"{len(shadow['episodes'].get('R3v', []))}, CSIA2 {len(shadow['episodes'].get('CSIA2', []))} episodes); "
          "report pit_replay/report.md")
    res = {"kind": "HOST SOFTWARE with a real local MQTT broker (not vehicle firmware)", "run_id": RUN_ID,
           "duration_s": duration, "pace": pace, "loop_late_s": late_s, "scenario": sc,
           "broker": mqtt_broker.version(broker.binary), "paho_mqtt": mqtt.__version__ if hasattr(mqtt, "__version__")
           else __import__("paho.mqtt").mqtt.__version__, "repo_commit": ch.git, "working_tree_dirty": ch.dirty,
           "checks": checks, "counters": node.c, "published": node.up_seq, "classes": n_cls, "import": imp, "pit_exit_code": pit_rc,
           "link_events": [(round(t - wall["sim_start"], 3), k, d) for t, k, d in link.events],
           "pit_events": [tuple(r) for r in pev], "service_ms_p99": p99, "service_ms_max": mx}
    (out / "summary.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    L = ["# Telemetry pipeline through a real MQTT broker (HOST SOFTWARE)", "",
         f"Run `{RUN_ID}`, {duration:.0f} s of controller time at {pace:g}x wall-clock speed, commit "
         f"`{ch.git[:12]}`{' plus uncommitted changes' if ch.dirty else ''}. Broker: {res['broker']} on loopback; "
         f"client: paho-mqtt {res['paho_mqtt']}. Command: `python3 tools/run_mqtt_demo.py --legacy-supervised --out build/mqtt_demo`. "
         "Synthetic plant and sensors; the car side is the host model of the telematics unit, not its firmware, and "
         "no LTE modem is involved. Nothing here was measured on hardware.", "",
         "| Check | Result | Evidence |", "|---|---|---|"]
    L += [f"| `{c['id']}` | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |" for c in checks]
    L += ["", "Wall-clock figures (delays, service times) vary from run to run; the checks test invariants, not "
          "those numbers.", ""]
    (out / "summary.md").write_text("\n".join(L))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "mqtt_demo")
    ap.add_argument("--build", type=pathlib.Path, default=ROOT / "build")
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--pace", type=float, default=2.0, help="simulated seconds per wall-clock second")
    ap.add_argument("--samples", type=pathlib.Path, help="copy summary.md and summary.json here")
    ap.add_argument("--legacy-supervised", action="store_true",
                    help="confirm this LEGACY research simulation: the telematics model runs the ECO supervisor and "
                         "sends torque requests to the simulated controller (never the deployed telematics path)")
    a = ap.parse_args()
    if not a.legacy_supervised:
        print("LEGACY research simulation with the ECO supervisor and the project's own controller core. The "
              "deployed telematics unit is receive-only: run tools/run_telematics_demo.py. To run this one anyway, "
              "add --legacy-supervised.")
        return 2
    if mqtt_broker.find_mosquitto() is None:
        print("MQTT NOT AVAILABLE: no mosquitto binary (set SEMMC_MOSQUITTO or see docs/MQTT_SETUP.md)")
        return 2
    out = a.out if a.out.is_absolute() else ROOT / a.out
    build = a.build if a.build.is_absolute() else ROOT / a.build
    res = run(out, build, a.duration, a.pace)
    for c in res["checks"]:
        print(f"MQTT {'PASS' if c['pass'] else 'FAIL'} {c['id']}: {c['detail']}")
    if a.samples:
        s = a.samples if a.samples.is_absolute() else ROOT / a.samples
        s.mkdir(parents=True, exist_ok=True)
        for f in ("summary.md", "summary.json"):
            shutil.copy(out / f, s / f)
        shutil.copy(out / "pit_replay" / "report.md", s / "pit_replay_report.md")
    ok = all(c["pass"] for c in res["checks"])
    print(f"MQTT {'ALL PASS' if ok else 'FAILURES'}: {sum(c['pass'] for c in res['checks'])}/{len(res['checks'])} "
          f"checks; outputs in {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
