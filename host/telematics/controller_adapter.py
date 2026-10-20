"""Controller receive adapters: CAN frames from the external motor controller -> measurements.

The motor controller is built by another team. The telematics unit only listens: an adapter decodes frames
into measurements (measurement.py) and never produces a frame. Two adapters:

  SimFixtureAdapter  our own `semmc` protocol (protocol/protocol.yaml). It is a SIMULATION FIXTURE: the
                     controller team has not accepted it, so nothing on the vehicle sends it. It checks the
                     CRC-8 of every frame, takes `source_seq` from the protocol's per-message counter
                     (byte 1) and validity from `ctrl_validity`. The protocol gives no sample time for any
                     controller broadcast, so `t_sample_us` stays None and `t_unc_us` is one broadcast
                     period with basis "assumed": a stated assumption on sample-to-transmit latency, accepted
                     for simulated runs only, until the controller team states it.
  DbcAdapter         a DBC file (the usual CAN database format) plus a mapping file from DBC signals to
                     registry signals, units checked. This is the path for the controller team's real
                     message definitions. Without a counter or time signal named in the mapping it gives
                     no sequence and no sample time; a `latency_bound_ms` in the mapping gives the timestamp
                     bound with basis "documented" (the mapping is the controller team's statement); a DBC
                     carries no checksum algorithm, so frames are not checked beyond length.

Both report, per frame, one of: decoded, ignored (a known message we do not map), unknown_id, invalid.
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import pathlib
from typing import Optional

import yaml

from host.telematics import signals
from host.telematics.measurement import Measurement, checked
from protocol.generated import semmc_protocol as proto


@dataclasses.dataclass(frozen=True)
class Frame:
    can_id: int
    data: bytes
    extended: bool = False
    fd: bool = False


@dataclasses.dataclass
class AdapterResult:
    kind: str                            # decoded | ignored | unknown_id | invalid
    measurements: list[Measurement]
    message: Optional[str] = None
    detail: Optional[str] = None


class RecordIds:
    """Local record identifiers: increasing, assigned by the receiver, unrelated to any source counter."""

    def __init__(self, start: int = 0):
        self.n = start

    def __call__(self) -> int:
        self.n += 1
        return self.n


# ---------------------------------------------------------------- simulation fixture
# message -> [(field, registry signal, validity field in ctrl_validity or None, condition field or None)]
SIM_MAP = {
    "ctrl_motion": [("speed_mech_rad_s", "ctrl.motor_speed", "v_speed", None),
                    ("iq_A", "ctrl.phase_current_q", None, None),
                    ("vbus_V", "ctrl.dc_voltage", "v_vbus", None)],
    "ctrl_currents": [("id_A", "ctrl.phase_current_d", None, None),
                      ("ibatt_A", "ctrl.dc_current", "v_ibatt", None),
                      ("kcl_residual_A", "ctrl.kcl_residual", None, "kcl_available")],
    "ctrl_energy": [("energy_J", "ctrl.energy_counter", None, None), ("p_batt_W", "ctrl.dc_power", None, None)],
    "ctrl_energy_quality": [("integrated_s", "ctrl.energy_integrated_time", None, None),
                            ("gap_s", "ctrl.energy_gap_time", None, None)],
    "ctrl_thermal": [("t_fet_degC", "ctrl.fet_temp", "v_t_fet", None),
                     ("t_motor_degC", "ctrl.motor_temp", "v_t_motor", None)],
    "ctrl_status": [("state", "ctrl.state", None, None)],
    "ctrl_fault": [("first_fault", "ctrl.fault_code", None, None)],
    "ctrl_cmd_trace": [("accepted_Nm", "ctrl.torque_reference", None, None)],
}
VALIDITY_MSG = "ctrl_validity"
VALIDITY_FRESH_S = 0.3        # three ctrl_validity periods


class SimFixtureAdapter:
    id = "semmc-sim-fixture"
    status = "simulation fixture: our semmc protocol, not accepted by the controller team"

    def __init__(self, record_id: Optional[RecordIds] = None):
        self.rid = record_id or RecordIds()
        self.validity: Optional[tuple[int, dict]] = None      # (t_rx_us, flags) of the latest ctrl_validity
        self.companion_frames = 0                             # frames another node sent as a companion

    def describe(self) -> dict:
        return {"id": self.id, "status": self.status, "protocol": "semmc",
                "major": proto.PROTOCOL_MAJOR, "minor": proto.PROTOCOL_MINOR, "spec_hash": proto.SPEC_HASH,
                "sample_time": "none in the protocol: receive time only",
                "latency_bound": "one broadcast period, ASSUMED"}

    def _confirmed(self, t_rx_us: int, flag: Optional[str]) -> Optional[bool]:
        if flag is None:
            return True
        if self.validity is None or t_rx_us - self.validity[0] > VALIDITY_FRESH_S * 1e6:
            return None                                       # no fresh flag: unverified
        return bool(self.validity[1].get(flag))

    def decode(self, t_rx_us: int, f: Frame) -> AdapterResult:
        if f.extended or f.fd:
            return AdapterResult("unknown_id", [], detail="extended or FD frame: not semmc")
        m = proto.BY_ID.get(f.can_id)
        if m is None:
            return AdapterResult("unknown_id", [])
        name = m["name"]
        if len(f.data) != 8:
            return AdapterResult("invalid", [], name, f"length {len(f.data)}, semmc frames have 8 bytes")
        values, info = proto.decode(f.can_id, f.data)
        if info["status"] != "ok":
            return AdapterResult("invalid", [], name, info["status"])
        if m["sender"] != "controller":
            self.companion_frames += 1                       # a supervisor or monitor transmits on this bus
            return AdapterResult("ignored", [], name, "companion message")
        if name == VALIDITY_MSG:
            self.validity = (t_rx_us, values)
            return AdapterResult("decoded", [], name)
        if name not in SIM_MAP:
            return AdapterResult("ignored", [], name)
        seq = info.get("seq")
        unc = int(round(m["period_s"] * 1e6))
        out = []
        for fld, sig, flag, cond in SIM_MAP[name]:
            v = values[fld]
            unit = signals.lookup(sig).unit
            prov = f"{self.id}:{name}.{fld}"
            if cond is not None and not values.get(cond):
                out.append(checked(self.rid(), "controller", sig, None, unit, t_rx_us, t_unc_us=unc,
                                   t_unc_basis="assumed",
                                   source_seq=seq, provenance=prov + f" ({cond}=0)", invalid=True))
                continue
            sentinel = isinstance(v, float) and math.isnan(v)
            out.append(checked(self.rid(), "controller", sig, None if sentinel else v, unit, t_rx_us,
                               t_unc_us=unc, t_unc_basis="assumed", source_seq=seq, provenance=prov, invalid=sentinel,
                               confirmed=self._confirmed(t_rx_us, flag)))
        return AdapterResult("decoded", out, name)


# ---------------------------------------------------------------- DBC
class DbcAdapter:
    """A DBC file and a mapping file. Mapping (YAML):

        adapter_id: controller-dbc
        status: "draft: the controller team has not confirmed these definitions"
        dbc: path/to/file.dbc                    # relative to the mapping file
        signals:
          - {message: MotorStatus, signal: BusVoltage, dbc_unit: V, to: ctrl.dc_voltage,
             factor: 1.0, offset: 0.0, invalid_raw: [65535], latency_bound_ms: 20}
        sequence: {MotorStatus: RollingCounter}  # optional: a counter signal per message
        validity: {BusVoltage: BusVoltageValid}  # optional: a flag signal (1 = valid) in the same message

    `dbc_unit` must equal the unit text in the DBC, so a unit change in the DBC stops the adapter from
    loading instead of producing wrong values. `factor` and `offset` convert to the registry unit.
    """

    def __init__(self, mapping_path: pathlib.Path, record_id: Optional[RecordIds] = None):
        import cantools                                         # host dependency (requirements.txt)
        self.mapping_path = pathlib.Path(mapping_path)
        cfg = yaml.safe_load(self.mapping_path.read_text())
        self.id = cfg["adapter_id"]
        self.status = cfg["status"]
        dbc_path = (self.mapping_path.parent / cfg["dbc"]).resolve()
        self.dbc_sha256 = hashlib.sha256(dbc_path.read_bytes()).hexdigest()
        self.db = cantools.database.load_file(str(dbc_path), strict=False)
        self.rid = record_id or RecordIds()
        self.seq_sig = cfg.get("sequence") or {}
        self.valid_sig = cfg.get("validity") or {}
        self.map: dict[str, list[dict]] = {}
        for s in cfg["signals"]:
            msg = self.db.get_message_by_name(s["message"])
            dsig = msg.get_signal_by_name(s["signal"])
            reg = signals.lookup(s["to"])
            if reg is None:
                raise ValueError(f"{s['to']}: not a registry signal")
            if (dsig.unit or "") != s["dbc_unit"]:
                raise ValueError(f"{s['message']}.{s['signal']}: DBC unit {dsig.unit!r}, mapping says "
                                 f"{s['dbc_unit']!r}")
            self.map.setdefault(msg.name, []).append(s)
        self._names = {m.frame_id: m for m in self.db.messages}

    def describe(self) -> dict:
        return {"id": self.id, "status": self.status, "mapping": self.mapping_path.name,
                "dbc_sha256": self.dbc_sha256, "sample_time": "none unless the mapping names a time signal",
                "frame_check": "length only (a DBC defines no checksum)"}

    def decode(self, t_rx_us: int, f: Frame) -> AdapterResult:
        msg = self._names.get(f.can_id)
        if msg is None or bool(msg.is_extended_frame) != f.extended:
            return AdapterResult("unknown_id", [])
        if len(f.data) < msg.length:
            return AdapterResult("invalid", [], msg.name, f"length {len(f.data)} < {msg.length}")
        if msg.name not in self.map:
            return AdapterResult("ignored", [], msg.name)
        try:
            phys = msg.decode(f.data, decode_choices=False, scaling=True)
            raw = msg.decode(f.data, decode_choices=False, scaling=False)
        except Exception as e:                                  # cantools raises several types
            return AdapterResult("invalid", [], msg.name, f"{type(e).__name__}")
        seq_name = self.seq_sig.get(msg.name)
        seq = int(raw[seq_name]) if seq_name else None
        out = []
        for s in self.map[msg.name]:
            reg = signals.lookup(s["to"])
            sentinel = raw[s["signal"]] in (s.get("invalid_raw") or [])
            v = phys[s["signal"]] * s.get("factor", 1.0) + s.get("offset", 0.0)
            flag = self.valid_sig.get(s["signal"])
            confirmed = True if flag is None else bool(raw.get(flag))
            lat = s.get("latency_bound_ms")
            out.append(checked(self.rid(), "controller", s["to"], None if sentinel else v, reg.unit, t_rx_us,
                               t_unc_us=None if lat is None else int(lat * 1000), source_seq=seq,
                               t_unc_basis=None if lat is None else "documented",
                               provenance=f"{self.id}:{msg.name}.{s['signal']}", invalid=sentinel,
                               confirmed=confirmed))
        return AdapterResult("decoded", out, msg.name)


class NullAdapter:
    """No controller adapter: the log was recorded without CAN reception (every frame is unknown)."""
    id = "none"
    status = "no controller reception in this log"

    def __init__(self, record_id: Optional[RecordIds] = None):
        self.rid = record_id or RecordIds()

    def describe(self) -> dict:
        return {"id": self.id, "status": self.status}

    def decode(self, t_rx_us: int, f: Frame) -> AdapterResult:
        return AdapterResult("unknown_id", [], detail="no adapter")


def from_meta(desc: dict, mapping_dir: Optional[pathlib.Path] = None, record_id: Optional[RecordIds] = None):
    """Rebuild the adapter a log names in its metadata (`controller_adapter`), for the pit import."""
    if desc.get("id") == NullAdapter.id:
        return NullAdapter(record_id)
    if desc.get("id") == SimFixtureAdapter.id:
        return SimFixtureAdapter(record_id)
    if desc.get("mapping") and mapping_dir is not None:
        a = DbcAdapter(mapping_dir / desc["mapping"], record_id)
        if a.dbc_sha256 != desc.get("dbc_sha256"):
            raise ValueError("the DBC differs from the one the log was recorded with")
        return a
    raise ValueError(f"no adapter for {desc!r}")
