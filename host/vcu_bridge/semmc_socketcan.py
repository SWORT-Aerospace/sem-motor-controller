"""VCU-side bridge for the semmc controller on the Cornell CHUDS CAN-FD bus.

PROPOSAL for the receiving software. It is not merged into the vehicle team's
repository and has not been run on the vehicle.

Why it is needed: CHUDS transports drop classic CAN frames as ForeignFrame
(urban-concept@c422c0f cev-lib/chuds/socketcan_transport.hpp:197-210,
mcp_transport.hpp:134-136). semmc v1 uses classic 8-byte frames in
0x300-0x33F, so the CHUDS library never delivers them. A separate raw
SocketCAN socket on the same interface does:

* CAN_RAW_FD_FRAMES is enabled, so the socket coexists with CHUDS FD traffic.
  It reads both frame sizes; FD frames are ignored here.
* CAN_RAW_FILTER passes only 0x300-0x33F (id 0x300, mask 0x7C0).
* Frames are decoded with the generated, golden-vector-tested codec
  (protocol/generated/semmc_protocol.py).
* The supervisor's frames (sup_hello, sup_limits, sup_torque_req) are sent as
  classic 16-byte can_frames, which CHUDS nodes ignore.

Linux only (AF_CAN). The pure functions (pack/unpack, filter) are unit-tested
without a CAN interface.
"""
from __future__ import annotations

import socket
import struct
from typing import Iterator, Optional

from protocol.generated import semmc_protocol as proto

SEMMC_ID_BASE = 0x300
SEMMC_ID_MASK = 0x7C0           # 0x300-0x33F
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_SFF_MASK = 0x7FF
CAN_MTU, CANFD_MTU = 16, 72
_CAN_FMT = "=IB3x8s"            # struct can_frame
_CANFD_FMT = "=IBBBB64s"        # struct canfd_frame


def in_semmc_range(can_id: int) -> bool:
    return (can_id & SEMMC_ID_MASK) == SEMMC_ID_BASE


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


def decode_frame(raw: bytes) -> Optional[dict]:
    """Decode one SocketCAN read into a semmc message dict, or None if it is not one.
    Classic only; FD frames (CHUDS) and out-of-range IDs are ignored."""
    u = unpack(raw)
    if u is None:
        return None
    can_id, data, fd = u
    if fd or not in_semmc_range(can_id):
        return None
    m = proto.BY_ID.get(can_id)
    values, info = proto.decode(can_id, data)
    return {"id": can_id, "name": m["name"] if m else None, "status": info["status"], "seq": info.get("seq"),
            "values": values, "invalid": info.get("invalid", []), "out_of_range": info.get("out_of_range", [])}


def open_socket(ifname: str = "can0"):  # pragma: no cover - needs a Linux CAN interface
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FD_FRAMES, 1)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, struct.pack("=II", SEMMC_ID_BASE, SEMMC_ID_MASK))
    s.bind((ifname,))
    return s


def receive(sock) -> Iterator[dict]:  # pragma: no cover - needs a Linux CAN interface
    while True:
        msg = decode_frame(sock.recv(CANFD_MTU))
        if msg is not None:
            yield msg


def send(sock, name: str, values: dict, seq: int) -> None:  # pragma: no cover
    data, _sat, _inv = proto.encode(name, values, seq)
    sock.send(pack_classic(proto.MESSAGES[name]["id"], data))
