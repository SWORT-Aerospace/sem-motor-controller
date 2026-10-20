"""UBX-NAV-PVT messages of a u-blox M9 class GNSS receiver, encoded for simulation and tests.

The firmware parses these bytes (telematics/firmware/src/tm_gnss.c); this encoder is written separately from that
parser, so a simulation that feeds it through the firmware checks one against the other. Only the fields the
firmware reads are set: UTC date and time with their validity flags, fix type and gnssFixOK, satellites, ground
speed and speed accuracy. Field offsets follow the u-blox M9 UBX protocol (a document check before the bench).
"""
from __future__ import annotations

import datetime
import math
import struct

NAV_PVT_LEN = 92


def nav_pvt(utc_s: int, nano: int, valid: int, fix_type: int, flags: int, num_sv: int, gspeed_mm_s: int,
            sacc_mm_s: int) -> bytes:
    """One UBX-NAV-PVT message: sync, class 0x01, id 0x07, length 92, payload, Fletcher checksum."""
    d = datetime.datetime.fromtimestamp(utc_s, datetime.timezone.utc)
    p = bytearray(NAV_PVT_LEN)
    struct.pack_into("<HBBBBBB", p, 4, d.year, d.month, d.day, d.hour, d.minute, d.second, valid)
    struct.pack_into("<i", p, 16, nano)
    p[20], p[21], p[23] = fix_type, flags, num_sv
    struct.pack_into("<i", p, 60, gspeed_mm_s)
    struct.pack_into("<I", p, 68, sacc_mm_s)
    body = bytes([0x01, 0x07]) + struct.pack("<H", len(p)) + bytes(p)
    a = b = 0
    for x in body:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return b"\xb5\x62" + body + bytes([a, b])


def from_sample(utc: float, speed: float, sacc: float, num_sv: int, fix: bool) -> bytes:
    """A NAV-PVT for a simulated GNSS sample (host/telematics/sim_vehicle.py): a 3D fix with valid, fully resolved
    UTC, or no fix (no valid time either)."""
    sec = int(math.floor(utc))
    nano = int(round((utc - sec) * 1e9))
    if nano >= 1_000_000_000:
        sec, nano = sec + 1, nano - 1_000_000_000
    if not fix or not math.isfinite(speed):
        return nav_pvt(sec, nano, 0x00, 0, 0x00, num_sv, 0, 20_000)
    return nav_pvt(sec, nano, 0x07, 3, 0x01, num_sv, int(round(speed * 1000)), int(round(sacc * 1000)))
