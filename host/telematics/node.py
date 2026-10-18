"""Telematics node: the receive-only telematics unit (HOST SIMULATION of the firmware structure).

The motor controller belongs to another team. This node listens to its CAN broadcast and to the unit's own
sensors, logs everything locally and sends a summary to the pit. It has no supervisor and no transmit
path: there is no method that returns or sends a CAN frame, so it cannot request torque, arm, reset a
fault, change a controller setting or take part in protection or precharge. (The earlier supervised model
is kept for research simulations only, in host/telemetry_adapter/legacy_node.py.)

Tasks, in priority order, as the firmware (telematics/firmware) has them:
  1. Receive (interrupt): every CAN frame is timestamped in the telematics clock and queued for the log
     as raw bytes (STLG CAN2), then decoded by the controller adapter into measurements for the live
     summary; every wheel edge is timestamped by the capture timer. The log queue is bounded: when it is
     full the record is dropped and counted. Receive never waits.
  2. Record task, every `wheel_record_period_s`: one WHEEL_EDGES record per channel (a heartbeat when the
     channel had no edge), so silence is logged.
  3. Log writer: moves queued records into STLG blocks at a bounded rate; a storage stall (injected)
     stops it, the queue fills, drops are counted.
  4. Uplink, 2 Hz: a `sem.telemetry.v4` summary of the latest measurement per signal, each with its
     validity and age (compact entries, units from the named signal registry); a missing or stale value is
     null with q "missing" or "stale", never 0. While the
     link is down messages wait in a bounded queue (the oldest is dropped and counted); later they are sent
     oldest first with replayed = true. The log does not depend on the uplink.

Nothing here runs on hardware. Rates and capacities are configuration chosen to exercise the behaviour.
"""
from __future__ import annotations

import collections
import dataclasses
import json
import math
from typing import Optional

from host.telematics import signals, stlg
from host.telematics.clocks import LocalClock, UtcEstimator
from host.telematics.controller_adapter import Frame, RecordIds
from host.telematics.measurement import LatestTable, checked
from host.telematics.wheel import EdgeAccumulator, WheelConfig, WheelEstimator

SCHEMA = "sem.telemetry.v4"           # live message produced by this node
# what the pit accepts: v4 from this node; v1 to v3 from the legacy supervised simulation and older runs
SCHEMAS_ACCEPTED = ("sem.telemetry.v1", "sem.telemetry.v2", "sem.telemetry.v3", "sem.telemetry.v4")
CONTROLLER_LIVE = ("ctrl.dc_voltage", "ctrl.dc_current", "ctrl.dc_power", "ctrl.energy_counter", "ctrl.motor_speed",
                   "ctrl.fet_temp", "ctrl.motor_temp", "ctrl.state", "ctrl.fault_code")


@dataclasses.dataclass
class NodeConfig:
    log_queue_capacity: int = 512        # records waiting for the log writer
    log_drain_per_s: float = 4000.0      # records per second the writer moves to storage
    storage_bytes: int = 16 * 1024 * 1024  # SPI NOR flash of the telematics bill of materials (16 MB)
    uplink_period_s: float = 0.5         # 2 Hz
    uplink_queue_capacity: int = 30      # messages held while the link is down (15 s at 2 Hz)
    counters_period_s: float = 1.0
    topic: str = "sem/car/telemetry"
    wheel: Optional[WheelConfig] = None  # None: circumference or pulses per revolution unknown -> no speed
    wheel_channels: tuple = ("wheel_l", "wheel_r", "wheel_drive")
    wheel_record_period_s: float = 0.05
    temp_channels: tuple = ("battery_surface", "motor_case", "ambient")
    controller_live: tuple = CONTROLLER_LIVE
    battery_monitor: bool = False        # a battery-side V/I monitor is fitted (total battery energy)


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


def _num(x) -> Optional[float]:
    """JSON has no NaN: an unknown value is null, never a number."""
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x


class TelematicsNode:
    def __init__(self, cfg: NodeConfig, clock: LocalClock, writer: stlg.Writer, link, adapter, run_id: str,
                 boot: int = 0, flash_stalls=(), reset_cause: str = "power-on (simulated)", t_start: float = 0.0):
        self.cfg = cfg
        self.clock = clock
        self.utc = UtcEstimator()
        self.w = writer
        self.link = link
        self.adapter = adapter
        self.run_id = run_id
        self.boot = boot
        self.flash_stalls = tuple(flash_stalls)
        self.q: collections.deque = collections.deque()
        self.uq: collections.deque = collections.deque()
        self.c = {k: 0 for k in ("rx_frames", "frames_decoded", "frames_ignored", "frames_unknown", "frames_invalid",
                                 "companion_frames_seen", "log_records", "log_dropped_queue", "log_dropped_storage",
                                 "queue_high_water", "uplink_sent", "uplink_dropped", "uplink_queue_high_water",
                                 "wheel_records", "wheel_edges_lost", "storage_stall_events")}
        self.c["log_queue_capacity"] = cfg.log_queue_capacity
        self.c["uplink_queue_capacity"] = cfg.uplink_queue_capacity
        self.drain_credit = 0.0
        self.next_uplink = t_start + cfg.uplink_period_s
        self.next_counters = t_start + cfg.counters_period_s
        self.next_wheel = t_start + cfg.wheel_record_period_s
        self.up_seq = 0
        self.rid = RecordIds()
        if getattr(adapter, "rid", None) is not None:
            adapter.rid = self.rid                  # one local record-id sequence for the whole node
        self.latest = LatestTable()
        self.last_decoded_us: Optional[int] = None
        self.acc = {ch: EdgeAccumulator(ch) for ch in range(len(cfg.wheel_channels))}
        self.line_high = {ch: True for ch in self.acc}
        self.est = ({ch: WheelEstimator(cfg.wheel, name, self.rid) for ch, name in enumerate(cfg.wheel_channels)}
                    if cfg.wheel else {})
        self.drop_log: list[tuple[float, str, int]] = []    # (time, reason, uplink seq dropped)
        self._stalled = False
        self._enqueue_direct(t_start, stlg.BOOT, stlg.body_boot(boot, 0, reset_cause))

    # ---- time helpers ------------------------------------------------------------------
    def t_us(self, t_true: float) -> int:
        return int(round(self.clock.local(t_true) * 1e6))

    @staticmethod
    def _in(t, windows):
        return any(a <= t < b for a, b in windows)

    # ---- 1. receive (interrupts) -------------------------------------------------------
    def _enqueue_us(self, t_us: int, rtype: int, body: bytes) -> None:
        if len(self.q) >= self.cfg.log_queue_capacity:
            self.c["log_dropped_queue"] += 1
            return
        self.q.append((t_us, rtype, body))
        self.c["queue_high_water"] = max(self.c["queue_high_water"], len(self.q))

    def _enqueue(self, t_true: float, rtype: int, body: bytes) -> None:
        self._enqueue_us(self.t_us(t_true), rtype, body)

    def _enqueue_direct(self, t_true: float, rtype: int, body: bytes) -> None:
        self.q.appendleft((self.t_us(t_true), rtype, body))

    def on_can(self, t_true: float, can_id: int, data: bytes, extended: bool = False, fd: bool = False) -> None:
        t = self.t_us(t_true)
        self.c["rx_frames"] += 1
        self._enqueue_us(t, stlg.CAN2, stlg.body_can2(can_id, data, extended, fd))   # raw evidence first
        res = self.adapter.decode(t, Frame(can_id, bytes(data), extended, fd))
        self.c["frames_unknown" if res.kind == "unknown_id" else "frames_" + res.kind] += 1
        self.c["companion_frames_seen"] = getattr(self.adapter, "companion_frames", 0)
        if res.kind == "decoded":
            self.last_decoded_us = t
        for m in res.measurements:
            self.latest.put(m)

    def on_wheel_edge(self, t_true: float, channel: int) -> None:
        self.acc[channel].edge(self.t_us(t_true))

    def on_wheel_line(self, channel: int, high: bool) -> None:
        self.line_high[channel] = high

    def on_sensor(self, t_true: float, kind: str, args: tuple) -> None:
        t = self.t_us(t_true)
        if kind == "gnss":
            speed, sacc, num_sv, fix = args
            self._enqueue_us(t, stlg.GNSS, stlg.body_gnss(*args))
            prov = "gnss-ubx (simulated)"
            self.latest.put(checked(self.rid(), "gnss", "gnss.speed", speed if fix else None, "m/s", t,
                                    provenance=prov, invalid=not fix))
            self.latest.put(checked(self.rid(), "gnss", "gnss.speed_acc", sacc if fix else None, "m/s", t,
                                    provenance=prov, invalid=not fix))
            self.latest.put(checked(self.rid(), "gnss", "gnss.num_sv", num_sv, "1", t, provenance=prov))
        elif kind == "imu":
            ax, gz = args
            self._enqueue_us(t, stlg.IMU, stlg.body_imu(ax, gz))
            self.latest.put(checked(self.rid(), "imu", "imu.ax", ax, "m/s^2", t, provenance="imu (simulated)"))
            self.latest.put(checked(self.rid(), "imu", "imu.gz", gz, "rad/s", t, provenance="imu (simulated)"))
        elif kind == "temp":
            ch, status, deg = args
            body = stlg.body_temp(ch, status, deg)
            self._enqueue_us(t, stlg.TEMP, body)
            v = stlg.parse_body(stlg.TEMP, body)["deg_c"]      # the live value is the logged value
            self.latest.put(checked(self.rid(), "temp", f"temp.{self.cfg.temp_channels[ch]}", v, "degC", t,
                                    provenance=f"temp-probe:ch{ch}", invalid=v is None))
        elif kind == "batt":
            volts, amps = args
            self._enqueue_us(t, stlg.BATT, stlg.body_batt(0, volts, amps))
            for sig, v in (("batt.voltage", volts), ("batt.current", amps)):
                self.latest.put(checked(self.rid(), "batt", sig, v, signals.lookup(sig).unit, t,
                                        provenance="battery-monitor (simulated)", invalid=v is None))

    def on_pps(self, t_true: float, utc_s: int) -> None:
        self.utc.add_edge(self.t_us(t_true) / 1e6, utc_s)   # timer capture: 1 us resolution
        self._enqueue(t_true, stlg.PPS, stlg.body_pps(utc_s))

    # ---- 2. record task ------------------------------------------------------------------
    def _wheel_records(self, t_true: float) -> None:
        t = self.t_us(t_true)
        for ch, acc in self.acc.items():
            r = acc.take(t, self.line_high[ch])
            self.c["wheel_records"] += 1
            self.c["wheel_edges_lost"] += r.lost
            self._enqueue_us(r.t_us, stlg.WHEEL_EDGES,
                             stlg.body_wheel_edges(ch, r.flags, r.n, r.span_us, r.total, r.rec_seq, r.lost))
            if ch in self.est:
                for m in self.est[ch].feed(r):
                    self.latest.put(m)

    # ---- 3 + 4. writer and uplink -------------------------------------------------------
    def service(self, t_true: float, dt: float) -> None:
        if t_true + 1e-9 >= self.next_wheel:
            self._wheel_records(t_true)
            self.next_wheel += self.cfg.wheel_record_period_s
        stalled = self._in(t_true, self.flash_stalls)
        if stalled and not self._stalled:
            self.c["storage_stall_events"] += 1
        self._stalled = stalled
        if not stalled:
            self.drain_credit = min(self.drain_credit + self.cfg.log_drain_per_s * dt, self.cfg.log_queue_capacity)
            while self.q and self.drain_credit >= 1.0:
                t_us, rtype, body = self.q.popleft()
                self.w.add(t_us, rtype, body)
                self.drain_credit -= 1.0
                self.c["log_records"] += 1
        self.c["log_dropped_storage"] = self.w.dropped_storage
        if t_true + 1e-9 >= self.next_counters:
            self._enqueue(t_true, stlg.COUNTERS2, stlg.body_counters2(self.c))
            self.next_counters += self.cfg.counters_period_s
        if t_true + 1e-9 >= self.next_uplink:
            self._uplink(t_true)
            self.next_uplink += self.cfg.uplink_period_s

    def live_signals(self) -> list[str]:
        out = list(self.cfg.controller_live)
        if self.cfg.wheel:
            out += [f"wheel.{n}.{q}" for n in self.cfg.wheel_channels for q in ("speed", "distance")]
        out += ["gnss.speed", "gnss.speed_acc", "gnss.num_sv", "imu.ax", "imu.gz"]
        out += [f"temp.{n}" for n in self.cfg.temp_channels]
        if self.cfg.battery_monitor:
            out += ["batt.voltage", "batt.current"]
        return out

    def message(self, t_true: float) -> dict:
        t_local = self.clock.local(t_true)
        now = self.t_us(t_true)
        u, q, err = self.utc.utc(t_local)
        a = self.adapter
        return {
            "schema": SCHEMA, "run_id": self.run_id, "boot": self.boot, "seq": self.up_seq,
            "t_local_ms": int(round(t_local * 1000)), "utc": _num(u), "utc_q": q, "utc_err_s": _num(err),
            "adapter": {"id": a.id, "fixture": a.id.endswith("fixture"),
                        "silent_ms": None if self.last_decoded_us is None else (now - self.last_decoded_us) // 1000},
            "registry": signals.REGISTRY_ID,
            "m": {k: compact(e) for k, e in self.latest.summary(now, self.live_signals()).items()},
            "counters": dict(self.c),
            "replayed": False,
        }

    def _uplink(self, t_true: float) -> None:
        msg = self.message(t_true)
        self.up_seq += 1
        if not self.link.up(t_true):
            self._backlog(t_true, msg)
            return
        while self.uq:                                  # backlog first, oldest first, flagged
            old = self.uq.popleft()
            old["replayed"] = True
            if not self._send(t_true, old):
                self.uq.appendleft(old)                 # the link refused it: keep it, try again next period
                self._backlog(t_true, msg)
                return
        if not self._send(t_true, msg):
            self._backlog(t_true, msg)

    def _backlog(self, t_true: float, msg: dict) -> None:
        if len(self.uq) >= self.cfg.uplink_queue_capacity:
            dropped = self.uq.popleft()
            self.c["uplink_dropped"] += 1
            self.drop_log.append((t_true, "uplink_queue_full", dropped["seq"]))
        self.uq.append(msg)
        self.c["uplink_queue_high_water"] = max(self.c["uplink_queue_high_water"], len(self.uq))

    def _send(self, t_true: float, msg: dict) -> bool:
        """Hand one message to the link. A link may refuse (returns False), e.g. a real MQTT client whose
        connection dropped between the up() check and the publish; SimLink never refuses (returns None)."""
        ok = self.link.deliver(t_true, self.cfg.topic, msg["seq"], json.dumps(msg, sort_keys=True).encode())
        if ok is False:
            return False
        self.c["uplink_sent"] += 1
        return True

    def close(self, t_true: float) -> None:
        """Orderly shutdown: drain the queue, write the final counters record directly, close the log."""
        while self.q:
            t_us, rtype, body = self.q.popleft()
            self.w.add(t_us, rtype, body)
            self.c["log_records"] += 1
        self.c["log_records"] += 1
        self.c["log_dropped_storage"] = self.w.dropped_storage
        self.w.add(self.t_us(t_true), stlg.COUNTERS2, stlg.body_counters2(self.c))
        self.w.close()

    def crash(self) -> int:
        """Telemetry restart without shutdown (power loss, watchdog): queued records and the block being
        filled are lost. Returns the number of records lost, which the restarted unit cannot know; the pit
        sees them as the difference between the last counters record and the records it holds."""
        lost = len(self.q) + self.w.n_in_buf
        self.q.clear()
        self.w.buf = bytearray()
        self.w.n_in_buf = 0
        self.w.f.close()
        return lost


TS_CODE = {"sample": "s", "rx": "r", None: None}


def compact(e: dict) -> list:
    """A live entry as [value, q, age_ms, source seq, time reference ("s" sample, "r" receive)] plus the upper
    bound when there is one. The unit is the registry's (the message names the registry). Values are rounded
    to 6 significant digits on the uplink only (the log keeps every received byte); the compact form roughly
    halves the message (3.3 KB with named fields and full floats in the demonstration)."""
    v = e["v"] if e["v"] is None else float(f"{e['v']:.6g}")       # 6 significant digits on the uplink
    out = [v, e["q"], e["age_ms"], e["seq"], TS_CODE[e["ts"]]]
    if "upper" in e:
        out.append(float(f"{e['upper']:.4g}"))
    return out


def meta_fields(cfg: NodeConfig, adapter, run_id: str, unit_id: str, boot: int) -> dict:
    """Run metadata the node's log carries (the caller adds provenance and the run kind)."""
    w = cfg.wheel
    return {"run_id": run_id, "unit_id": unit_id, "boot": boot,
            "format": {"name": "STLG", "version": stlg.VERSION, "block_payload_bytes": stlg.BLOCK_BYTES},
            "clock": {"domain": "telematics", "unit": "us", "utc_from": "logged PPS edges"},
            "storage_bytes": cfg.storage_bytes, "controller_adapter": adapter.describe(),
            "transmits": "nothing: receive-only node",
            "sensors": {"wheel_circumference_m": w.circumference_m if w else None, "wheel_ppr": w.ppr if w else None,
                        "wheel_active_high": w.active_high if w else None,
                        "wheel_record_period_s": cfg.wheel_record_period_s,
                        "wheel_channels": {str(k): v for k, v in enumerate(cfg.wheel_channels)},
                        "temp_channels": {str(k): v for k, v in enumerate(cfg.temp_channels)},
                        "battery_monitor": cfg.battery_monitor}}
