"""Companion-computer supervisor (energy strategy side of the CAN contract).

The supervisor:
  * announces a session (sup_hello) and waits for the controller's ctrl_session
    echo before sending anything with authority;
  * sends supervisor-declared bounds (sup_limits) and a torque request
    (sup_torque_req) every period, stamped with its OWN monotonic clock;
  * detects controller reboots (ctrl_status.boot_id change) and re-handshakes;
  * never sends arming, mode selection, fault reset or PWM commands - the
    protocol has no such messages.

Timing (50 Hz, 100 ms timeout) is PROVISIONAL and simulation-only.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable, Optional

from protocol.generated import semmc_protocol as proto

Policy = Callable[[float, "Telemetry"], tuple[float, bool]]


@dataclasses.dataclass
class Telemetry:
    """Latest decoded controller telemetry, with LOCAL receive times."""
    speed_mech_rad_s: float = math.nan
    speed_rx_s: float = -math.inf
    state: Optional[int] = None
    boot_id: Optional[int] = None
    accepted_Nm: float = math.nan
    reason: int = 0
    energy_J: float = math.nan
    vbus_V: float = math.nan


@dataclasses.dataclass
class SupervisorConfig:
    session_id: int = 0xC0FFEE01
    period_s: float = 0.02            # PROVISIONAL
    hello_period_s: float = 0.5
    limits_period_s: float = 0.1
    max_torque_Nm: float = 2.0
    max_batt_power_W: float = 1500.0


class Supervisor:
    def __init__(self, cfg: SupervisorConfig, policy: Policy):
        self.cfg = cfg
        self.policy = policy
        self.tel = Telemetry()
        self.tag = 0
        self.seq = {n: 0 for n in ("sup_hello", "sup_limits", "sup_torque_req")}
        self.limits_seq = 0
        self.next_hello = 0.0
        self.next_limits = 0.0
        self.next_req = 0.0
        self.frozen: Optional[tuple[float, bool, int]] = None  # (torque, coast, src_ms) for fault injection
        self.enabled = True
        self.log: list[dict] = []

    # ---- receive -------------------------------------------------------------
    def on_frame(self, t_s: float, can_id: int, data: bytes) -> None:
        if can_id not in proto.BY_ID:
            return
        name = proto.BY_ID[can_id]["name"]
        values, info = proto.decode(can_id, data)
        if info["status"] != "ok":
            return
        if name == "ctrl_session":
            if values["companion_session_echo"] == self.cfg.session_id and values["session_tag"] != 0:
                if values["session_tag"] != self.tag:
                    self.tag = values["session_tag"]
                    self.next_limits = t_s  # send bounds immediately
        elif name == "ctrl_status":
            if self.tel.boot_id is not None and values["boot_id"] != self.tel.boot_id:
                self.tag = 0  # controller rebooted: handshake again
                self.next_hello = t_s
            self.tel.boot_id = values["boot_id"]
            self.tel.state = values["state"]
        elif name == "ctrl_motion":
            if not math.isnan(values["speed_mech_rad_s"]):
                self.tel.speed_mech_rad_s = values["speed_mech_rad_s"]
                self.tel.speed_rx_s = t_s
            self.tel.vbus_V = values["vbus_V"]
        elif name == "ctrl_cmd_trace":
            self.tel.accepted_Nm = values["accepted_Nm"]
            self.tel.reason = values["reason"]
        elif name == "ctrl_energy":
            self.tel.energy_J = values["energy_J"]

    # ---- transmit --------------------------------------------------------------
    def _enc(self, name: str, values: dict) -> bytes:
        data, _sat, _inv = proto.encode(name, values, self.seq[name])
        self.seq[name] = (self.seq[name] + 1) & 0xFF
        return data

    def tick(self, t_s: float) -> list[tuple[int, bytes]]:
        out: list[tuple[int, bytes]] = []
        t_s = round(t_s, 6)  # schedule on microsecond ticks: no float-accumulation skips
        if not self.enabled:
            return out
        if self.tag == 0 and t_s >= self.next_hello:
            out.append((proto.MESSAGES["sup_hello"]["id"], self._enc("sup_hello", {
                "proto_major": proto.PROTOCOL_MAJOR, "proto_minor": proto.PROTOCOL_MINOR, "role": 1,
                "companion_session": self.cfg.session_id})))
            self.next_hello = round(t_s + self.cfg.hello_period_s, 6)
        if self.tag == 0:
            return out
        if t_s >= self.next_limits:
            # ICD 1.2: a new limits_seq only when the content changes; a
            # periodic re-send of the same set is a refresh (same seq).
            content = (self.cfg.max_torque_Nm, self.cfg.max_batt_power_W)
            if content != getattr(self, "_limits_content", None):
                self.limits_seq = (self.limits_seq + 1) & 0xFF
                self._limits_content = content
            out.append((proto.MESSAGES["sup_limits"]["id"], self._enc("sup_limits", {
                "session_tag": self.tag, "limits_seq": self.limits_seq,
                "max_torque_Nm": self.cfg.max_torque_Nm, "max_batt_power_W": self.cfg.max_batt_power_W})))
            self.next_limits = round(t_s + self.cfg.limits_period_s, 6)
        if t_s >= self.next_req:
            if self.frozen is not None:
                torque, coast, src_ms = self.frozen
            else:
                torque, coast = self.policy(t_s, self.tel)
                src_ms = int(round(t_s * 1000.0)) & 0xFFFF
            out.append((proto.MESSAGES["sup_torque_req"]["id"], self._enc("sup_torque_req", {
                "session_tag": self.tag, "limits_ref": self.limits_seq & 0xF, "coast_request": coast,
                "reserved": 0, "torque_Nm": torque, "src_time_ms": src_ms})))
            self.log.append({"t_s": t_s, "torque_Nm": torque, "coast": coast})
            self.next_req = round(t_s + self.cfg.period_s, 6)
        return out


def speed_hold_policy(target_mps: float, kp_Nm_per_mps: float, wheel_circumference_m: float,
                      gear_ratio: float, max_torque: float) -> Policy:
    """Simple bounded proportional speed hold (a test policy, not a strategy)."""
    k = wheel_circumference_m / (2.0 * math.pi) / gear_ratio

    def policy(t_s: float, tel: Telemetry):
        if math.isnan(tel.speed_mech_rad_s):
            return 0.0, False
        v = tel.speed_mech_rad_s * k
        torque = max(0.0, min(max_torque, kp_Nm_per_mps * (target_mps - v) + 0.15))
        return torque, False
    return policy
