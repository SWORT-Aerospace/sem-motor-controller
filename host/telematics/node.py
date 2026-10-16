"""Telematics node (HOST SIMULATION of the telematics unit's firmware structure).

Tasks, in priority order, as docs/ICD.md requires of the unit:
  1. CAN receive (interrupt): timestamp every frame in the telematics clock,
     hand it to the supervisor task directly, and enqueue a log record. The
     log queue is bounded; when it is full the record is dropped and counted.
     Receive never waits for the log writer.
  2. Supervisor task, 50 Hz: the existing Supervisor (host/telemetry_adapter/
     supervisor.py), run on the telematics clock. Its frames go to the bus
     first and are logged second.
  3. Log writer: moves queued records into STLG blocks at a bounded rate; a
     flash stall (injected) stops it, the queue fills, and drops are counted
     and reported, never hidden.
  4. Uplink, 2 Hz (the proposal says 1-5 Hz): a JSON summary to the MQTT topic
     over LTE. During an outage messages wait in a bounded queue; overflow
     drops the oldest and is counted. Replayed messages are flagged.

Nothing here runs on hardware. The rates and capacities are configuration,
chosen to exercise the behaviour, not measured.
"""
from __future__ import annotations

import collections
import dataclasses
import json
import math
from typing import Optional

from host.telematics import stlg
from host.telematics.clocks import LocalClock, UtcEstimator
from host.telemetry_adapter.supervisor import Supervisor
from protocol.generated import semmc_protocol as proto

STATES = ["BOOT", "SELF_TEST", "DISARMED", "READY", "MANUAL", "ECO_ASSIST", "DERATED", "FAULT_LATCHED"]
SCHEMA = "sem.telemetry.v1"


@dataclasses.dataclass
class NodeConfig:
    log_queue_capacity: int = 512        # records waiting for the log writer
    log_drain_per_s: float = 4000.0      # records per second the writer moves to flash
    storage_bytes: int = 8 * 1024 * 1024  # QSPI flash in the telematics proposal (8 MB)
    uplink_period_s: float = 0.5         # 2 Hz
    uplink_queue_capacity: int = 30      # messages held while LTE is down (15 s at 2 Hz)
    counters_period_s: float = 1.0
    topic: str = "sem/car/telemetry"


def _num(x) -> Optional[float]:
    """JSON has no NaN: an unknown value is null, never a number."""
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x


class SimLink:
    """LTE + MQTT as seen by the node: up/down schedule, latency, an in-process broker."""

    def __init__(self, outages=(), latency_s: float = 0.4, mangle: Optional[dict] = None):
        self.outages = tuple(outages)
        self.latency_s = latency_s
        self.mangle = mangle or {}       # uplink seq -> function(bytes) -> bytes (transport fault injection)
        self.broker: list[tuple[float, str, bytes]] = []

    def up(self, t_true: float) -> bool:
        return not any(a <= t_true < b for a, b in self.outages)

    def deliver(self, t_true: float, topic: str, seq: int, payload: bytes) -> None:
        if seq in self.mangle:
            payload = self.mangle[seq](payload)
        self.broker.append((t_true + self.latency_s, topic, payload))


class TelematicsNode:
    def __init__(self, cfg: NodeConfig, clock: LocalClock, writer: stlg.Writer, link: SimLink,
                 supervisor: Supervisor, run_id: str, flash_stalls=(), supervisor_stalls=()):
        self.cfg = cfg
        self.clock = clock
        self.utc = UtcEstimator()
        self.w = writer
        self.link = link
        self.sup = supervisor
        self.run_id = run_id
        self.flash_stalls = tuple(flash_stalls)
        self.supervisor_stalls = tuple(supervisor_stalls)
        self.q: collections.deque = collections.deque()
        self.uq: collections.deque = collections.deque()
        self.c = {k: 0 for k in stlg.COUNTER_NAMES}
        self.drain_credit = 0.0
        self.next_uplink = cfg.uplink_period_s
        self.next_counters = cfg.counters_period_s
        self.up_seq = 0
        self.latest: dict = {}
        self.p_acc = [0.0, 0]                 # p_batt samples since the last uplink (mean)
        self.gnss_latest = (math.nan, math.nan, 0, False)
        self.sup_rate: collections.Counter = collections.Counter()  # requests per whole second (control health)
        self.drop_log: list[tuple[float, str, int]] = []

    # ---- time helpers ------------------------------------------------------------------
    def t_us(self, t_true: float) -> int:
        return int(round(self.clock.local(t_true) * 1e6))

    @staticmethod
    def _in(t, windows):
        return any(a <= t < b for a, b in windows)

    # ---- 1. receive (ISR) ---------------------------------------------------------------
    def _enqueue(self, t_true: float, rtype: int, body: bytes) -> None:
        if len(self.q) >= self.cfg.log_queue_capacity:
            self.c["log_dropped_queue"] += 1
            return
        self.q.append((self.t_us(t_true), rtype, body))
        self.c["queue_high_water"] = max(self.c["queue_high_water"], len(self.q))

    def on_can(self, t_true: float, can_id: int, data: bytes) -> None:
        t_local = self.clock.local(t_true)
        self.c["rx_frames"] += 1
        self.sup.on_frame(t_local, can_id, data)          # control path first, no queue in between
        self._enqueue(t_true, stlg.CAN, stlg.body_can(can_id, data))
        m = proto.BY_ID.get(can_id)
        if m is None:
            return
        values, info = proto.decode(can_id, data)
        if info["status"] != "ok":
            return
        self.latest[m["name"]] = values
        if m["name"] == "ctrl_energy" and math.isfinite(values["p_batt_W"]):
            self.p_acc[0] += values["p_batt_W"]
            self.p_acc[1] += 1

    def on_sensor(self, t_true: float, kind: str, args: tuple) -> None:
        if kind == "wheel":
            self._enqueue(t_true, stlg.WHEEL, stlg.body_wheel(*args))
        elif kind == "gnss":
            self.gnss_latest = args
            self._enqueue(t_true, stlg.GNSS, stlg.body_gnss(*args))
        elif kind == "imu":
            self._enqueue(t_true, stlg.IMU, stlg.body_imu(*args))

    def on_pps(self, t_true: float, utc_s: int) -> None:
        self.utc.add_edge(self.t_us(t_true) / 1e6, utc_s)   # timer capture: 1 us resolution
        self._enqueue(t_true, stlg.PPS, stlg.body_pps(utc_s))

    # ---- 2. supervisor task ---------------------------------------------------------------
    def supervisor_tick(self, t_true: float) -> list[tuple[int, bytes]]:
        if self._in(t_true, self.supervisor_stalls):
            self.c["supervisor_overruns"] += 1
            return []
        out = self.sup.tick(self.clock.local(t_true))
        for cid, data in out:
            if cid == proto.MESSAGES["sup_torque_req"]["id"]:
                self.sup_rate[int(t_true)] += 1
            self._enqueue(t_true, stlg.CAN, stlg.body_can(cid, data))
        return out

    # ---- 3 + 4. writer and uplink -------------------------------------------------------
    def service(self, t_true: float, dt: float) -> None:
        if not self._in(t_true, self.flash_stalls):
            self.drain_credit = min(self.drain_credit + self.cfg.log_drain_per_s * dt, self.cfg.log_queue_capacity)
            while self.q and self.drain_credit >= 1.0:
                t_us, rtype, body = self.q.popleft()
                self.w.add(t_us, rtype, body)
                self.drain_credit -= 1.0
                self.c["log_records"] += 1
        self.c["log_dropped_storage"] = self.w.dropped_storage
        if t_true + 1e-9 >= self.next_counters:
            self._enqueue(t_true, stlg.COUNTERS, stlg.body_counters(self.c))
            self.next_counters += self.cfg.counters_period_s
        if t_true + 1e-9 >= self.next_uplink:
            self._uplink(t_true)
            self.next_uplink += self.cfg.uplink_period_s

    def _message(self, t_true: float) -> dict:
        t_local = self.clock.local(t_true)
        u, q, err = self.utc.utc(t_local)
        st = self.latest.get("ctrl_status", {})
        mo = self.latest.get("ctrl_motion", {})
        en = self.latest.get("ctrl_energy", {})
        eq = self.latest.get("ctrl_energy_quality", {})
        tr = self.latest.get("ctrl_cmd_trace", {})
        last_req = self.sup.log[-1] if self.sup.log else {}
        p_mean = self.p_acc[0] / self.p_acc[1] if self.p_acc[1] else None
        self.p_acc = [0.0, 0]
        g = self.gnss_latest
        return {
            "schema": SCHEMA, "run_id": self.run_id, "seq": self.up_seq, "t_local_ms": int(round(t_local * 1000)),
            "utc": _num(u), "utc_q": q, "utc_err_s": _num(err),
            "ctrl": {"state": STATES[st["state"]] if "state" in st and st["state"] < len(STATES) else None,
                     "speed_mech_rad_s": _num(mo.get("speed_mech_rad_s")), "iq_A": _num(mo.get("iq_A")),
                     "vbus_V": _num(mo.get("vbus_V")), "p_batt_W_mean": _num(p_mean),
                     "energy_J": _num(en.get("energy_J")), "energy_integrated_s": _num(eq.get("integrated_s")),
                     "energy_gap_s": _num(eq.get("gap_s")), "accepted_Nm": _num(tr.get("accepted_Nm")),
                     "reason": tr.get("reason")},
            "sup": {"torque_Nm": _num(last_req.get("torque_Nm")), "reason": last_req.get("reason")},
            "gnss": {"speed_mps": _num(g[0]), "sacc_mps": _num(g[1]), "num_sv": g[2], "fix": bool(g[3])},
            "counters": dict(self.c),
            "replayed": False,
        }

    def _uplink(self, t_true: float) -> None:
        msg = self._message(t_true)
        self.up_seq += 1
        if not self.link.up(t_true):
            if len(self.uq) >= self.cfg.uplink_queue_capacity:
                self.uq.popleft()
                self.c["uplink_dropped"] += 1
                self.drop_log.append((t_true, "uplink_queue_full", 1))
            self.uq.append(msg)
            return
        while self.uq:                                  # backlog first, oldest first, flagged
            old = self.uq.popleft()
            old["replayed"] = True
            self._send(t_true, old)
        self._send(t_true, msg)

    def _send(self, t_true: float, msg: dict) -> None:
        self.link.deliver(t_true, self.cfg.topic, msg["seq"], json.dumps(msg, sort_keys=True).encode())
        self.c["uplink_sent"] += 1

    def close(self, t_true: float) -> None:
        while self.q:                                   # orderly shutdown: drain everything
            t_us, rtype, body = self.q.popleft()
            self.w.add(t_us, rtype, body)
            self.c["log_records"] += 1
        self.c["log_records"] += 1                      # the final counters record, written last and directly
        self.w.add(self.t_us(t_true), stlg.COUNTERS, stlg.body_counters(self.c))
        self.w.close()
