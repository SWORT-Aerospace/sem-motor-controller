"""Linux SocketCAN bridge for the semmc controller (raw socket, any Linux computer).

STATUS: optional adapter, PROPOSAL. It was written against a REFERENCE project
(Cornell's CHUDS CAN-FD bus, urban-concept@c422c0f), which is NOT confirmed to
be our vehicle's bus. Our vehicle's telematics proposal (telematics_overview /
telematics_data_flow v0.1, 14/10/2026) uses a CAN 2.0B bus and an STM32U575
unit, not a Linux VCU; this module is then only useful on a pit or bench
computer with a USB-CAN adapter. Not run on any vehicle.

What it does:
* The controller's protocol messages occupy one 64-identifier block whose base
  is the calibration parameter supervision.can_id_base (default here: the
  protocol's own numbering, 0x300). The base passed to these functions MUST
  equal the controller's calibration.
* CAN_RAW_FILTER passes only that block (id = base, mask 0x7C0).
* Frames are translated to the protocol's canonical numbers and decoded with
  the generated, golden-vector-tested codec (protocol/generated/semmc_protocol.py).
* CAN_RAW_FD_FRAMES is enabled so the socket also works on an FD bus (reference
  project case); FD frames are ignored.
* RECEIVE ONLY. The earlier `send()` (supervisor frames onto the bus) was removed
  in v0.7: the telematics scope has no propulsion authority. `open_socket` hands
  out a wrapper with `recv` and `close` only, so code holding it cannot transmit
  (tests/telematics/test_receive_only_boundary.py). The kernel socket itself could
  transmit; nothing here exposes that.

Linux only (AF_CAN). The pure functions (pack/unpack, filter, translation) are
unit-tested without a CAN interface.
"""
from __future__ import annotations

import socket
import struct
from typing import Iterator, Optional

from protocol.generated import semmc_protocol as proto

SEMMC_ID_BASE = 0x300           # protocol numbering; the bus block base is a calibration value
SEMMC_ID_MASK = 0x7C0           # one 64-identifier block
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_SFF_MASK = 0x7FF
CAN_MTU, CANFD_MTU = 16, 72
_CAN_FMT = "=IB3x8s"            # struct can_frame
_CANFD_FMT = "=IBBBB64s"        # struct canfd_frame


def _check_base(base: int) -> None:
    if not (0 <= base <= 0x7C0 and base % 0x40 == 0):
        raise ValueError("CAN id base must be a multiple of 0x40 in 0..0x7C0 (validator rule 40)")


def in_semmc_range(can_id: int, base: int = SEMMC_ID_BASE) -> bool:
    _check_base(base)
    return (can_id & SEMMC_ID_MASK) == base


def to_protocol_id(can_id: int, base: int = SEMMC_ID_BASE) -> int:
    return can_id - base + SEMMC_ID_BASE


def to_bus_id(msg_id: int, base: int = SEMMC_ID_BASE) -> int:
    _check_base(base)
    return msg_id - SEMMC_ID_BASE + base


def pack_classic(can_id: int, data: bytes) -> bytes:
    if not 0 <= can_id <= CAN_SFF_MASK or len(data) != 8:
        raise ValueError("semmc frames are 11-bit, 8 bytes")
    return struct.pack(_CAN_FMT, can_id, 8, bytes(data))


def unpack(raw: bytes) -> Optional[tuple[int, bytes, bool]]:
    """-> (11-bit id, payload, is_fd) or None for extended/RTR frames."""
    if len(raw) == CAN_MTU:
        can_id, dlc, data = struct.unpack(_CAN_FMT, raw)
        fd = False
    elif len(raw) == CANFD_MTU:
        can_id, dlc, _flags, _r0, _r1, data = struct.unpack(_CANFD_FMT, raw)
        fd = True
    else:
        return None
    if can_id & (CAN_EFF_FLAG | CAN_RTR_FLAG):
        return None
    return can_id & CAN_SFF_MASK, bytes(data[:dlc]), fd


def decode_frame(raw: bytes, base: int = SEMMC_ID_BASE) -> Optional[dict]:
    """Decode one SocketCAN read into a semmc message dict, or None if it is not one.
    Classic only; FD frames and identifiers outside the block are ignored.
    "id" is the bus identifier, "msg_id" the protocol's canonical number."""
    u = unpack(raw)
    if u is None:
        return None
    can_id, data, fd = u
    if fd or not in_semmc_range(can_id, base):
        return None
    msg_id = to_protocol_id(can_id, base)
    m = proto.BY_ID.get(msg_id)
    values, info = proto.decode(msg_id, data)
    return {"id": can_id, "msg_id": msg_id, "name": m["name"] if m else None, "status": info["status"], "seq": info.get("seq"),
            "values": values, "invalid": info.get("invalid", []), "out_of_range": info.get("out_of_range", [])}


class ReceiveOnlySocket:
    """A CAN socket that can only be read: `recv` and `close`, nothing that writes."""

    __slots__ = ("_s",)

    def __init__(self, sock):
        self._s = sock

    def recv(self, n: int) -> bytes:
        return self._s.recv(n)

    def close(self) -> None:
        self._s.close()


def open_socket(ifname: str = "can0", base: int = SEMMC_ID_BASE) -> ReceiveOnlySocket:  # pragma: no cover - needs a Linux CAN interface
    _check_base(base)
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FD_FRAMES, 1)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, struct.pack("=II", base, SEMMC_ID_MASK))
    s.bind((ifname,))
    return ReceiveOnlySocket(s)


def receive(sock, base: int = SEMMC_ID_BASE) -> Iterator[dict]:  # pragma: no cover - needs a Linux CAN interface
    while True:
        msg = decode_frame(sock.recv(CANFD_MTU), base)
        if msg is not None:
            yield msg
