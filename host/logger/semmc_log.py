"""semmc-log v1: timestamped event logs (scenarios, controller TX, replays).

One event per line: ``<t_us> <KIND> <payload>``. Times are the LOCAL monotonic
receive/apply time of the controller (microseconds). Source timestamps and
clock domains travel inside the CAN payloads (see protocol/protocol.yaml).

This module is used for both directions:
  * building scenario logs that the host executable replays, and
  * decoding the controller's transmitted frames with the Python codec.
"""
from __future__ import annotations

import dataclasses
import math
import pathlib
from typing import Iterable, Iterator

from protocol.generated import semmc_protocol as proto

HEADER = "# semmc-log v1"


@dataclasses.dataclass(frozen=True, order=True)
class Event:
    t_us: int
    kind: str
    payload: str = ""

    def line(self) -> str:
        return f"{self.t_us} {self.kind} {self.payload}".rstrip()


def can_event(t_us: int, can_id: int, data: bytes) -> Event:
    if len(data) != 8:
        raise ValueError("semmc frames are 8 bytes")
    return Event(t_us, "CAN", f"{can_id:03X} {data.hex().upper()}")


def io_event(t_us: int, **kv) -> Event:
    keymap = {"mode_eco": "eco", "arm_switch": "arm", "fault_reset": "reset", "estop_chain_ok": "estop_ok",
              "driver_present": "present"}
    parts = []
    for k, v in kv.items():
        k = keymap.get(k, k)
        parts.append(f"{k}={int(v) if isinstance(v, bool) else v}")
    return Event(t_us, "IO", " ".join(parts))


def kv_event(t_us: int, kind: str, **kv) -> Event:
    def fmt(v):
        if isinstance(v, bool):
            return str(int(v))
        if isinstance(v, float) and math.isnan(v):
            return "nan"
        return str(v)
    return Event(t_us, kind, " ".join(f"{k}={fmt(v)}" for k, v in kv.items()))


def write_log(path: str | pathlib.Path, events: Iterable[Event]) -> pathlib.Path:
    evs = sorted(events, key=lambda e: e.t_us)  # stable: equal times keep insertion order
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(HEADER + "\n")
        for e in evs:
            f.write(e.line() + "\n")
    return path


def read_events(path: str | pathlib.Path) -> Iterator[Event]:
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        t, kind, *rest = line.split(" ", 2)
        yield Event(int(t), kind, rest[0] if rest else "")


def decode_can_line(e: Event):
    """Return (t_us, message_name, values, info) for a CAN event."""
    cid_s, hex_s = e.payload.split()
    cid = int(cid_s, 16)
    data = bytes.fromhex(hex_s)
    values, info = proto.decode(cid, data)
    name = proto.BY_ID[cid]["name"] if cid in proto.BY_ID else f"0x{cid:03X}"
    return e.t_us, name, values, info


def decode_tx_log(path) -> list[tuple[int, str, dict, dict]]:
    return [decode_can_line(e) for e in read_events(path) if e.kind == "CAN"]
