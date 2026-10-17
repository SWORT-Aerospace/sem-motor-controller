"""STLG v1: the telematics unit's local run log (format reference implementation).

Layout (little-endian):

  file header   b"STLG" | u16 version=1 | u32 meta_len | meta (UTF-8 JSON) | u32 crc32(meta)
  block         b"BK" | u32 block_seq | u64 base_us | u16 n | u32 crc32(payload) | payload (n bytes)
  record        u8 type | u8 len | u32 dt_us (from the block's base_us) | body (len bytes)

Times are telematics-clock microseconds (see clocks.py). Blocks are written
whole, at most BLOCK_BYTES of payload, matching a 4 KiB flash sector; a power
loss can lose only the block being written, and the reader reports it.

Record types and bodies:
  1 CAN       u16 can_id | u8 dlc | data[dlc]          every received/sent frame
  2 PPS       u32 utc_s                                 PPS edge, timestamped locally
  3 GNSS      f32 speed_mps | f32 sacc_mps | u8 num_sv | u8 fix
  4 IMU       f32 ax_mps2 | f32 gz_rad_s
  5 WHEEL     u8 channel | u16 counts | u16 window_ms   hall edges in the window
  6 COUNTERS  u32 x 8: rx_frames, log_records, log_dropped_queue, log_dropped_storage,
              uplink_sent, uplink_dropped, queue_high_water, supervisor_overruns
  7 EVENT     u8 code | text (ASCII)
  8 TEMP      u8 channel | u8 status | i16 centi_degC      one temperature-probe sample (added in v0.6;
              status 0 ok, 1 CRC error, 2 conversion timeout, 3 out of range; the value is -32768 unless ok;
              the record time is the end of the conversion). Channel names are in the metadata
              `sensors.temp_channels`. Readers older than v0.6 keep the record as raw bytes.
"""
from __future__ import annotations

import dataclasses
import json
import math
import pathlib
import struct
import zlib
from typing import Iterator

MAGIC = b"STLG"
VERSION = 1
BLOCK_BYTES = 4096 - 20          # payload per block; the 20-byte block header fills the 4 KiB sector
REC_HDR = struct.Struct("<BBI")
BLK_HDR = struct.Struct("<2sIQHI")

CAN, PPS, GNSS, IMU, WHEEL, COUNTERS, EVENT, TEMP = 1, 2, 3, 4, 5, 6, 7, 8
TEMP_STATUS = ("ok", "crc_error", "timeout", "out_of_range")
TEMP_INVALID = -32768
COUNTER_NAMES = ("rx_frames", "log_records", "log_dropped_queue", "log_dropped_storage", "uplink_sent",
                 "uplink_dropped", "queue_high_water", "supervisor_overruns")


def body_can(can_id: int, data: bytes) -> bytes:
    return struct.pack("<HB", can_id, len(data)) + data


def body_pps(utc_s: int) -> bytes:
    return struct.pack("<I", utc_s)


def body_gnss(speed: float, sacc: float, num_sv: int, fix: bool) -> bytes:
    return struct.pack("<ffBB", speed, sacc, num_sv, int(fix))


def body_imu(ax: float, gz: float) -> bytes:
    return struct.pack("<ff", ax, gz)


def body_wheel(channel: int, counts: int, window_ms: int) -> bytes:
    return struct.pack("<BHH", channel, counts, window_ms)


def body_temp(channel: int, status: int, deg_c) -> bytes:
    ok = status == 0 and deg_c is not None and math.isfinite(deg_c) and -327.67 <= deg_c <= 327.67
    if status == 0 and not ok:
        status = 3                       # a reading without a usable value is out of range, never ok
    return struct.pack("<BBh", channel, status, int(round(deg_c * 100)) if ok else TEMP_INVALID)


def body_counters(c: dict) -> bytes:
    return struct.pack("<8I", *(min(int(c[k]), 0xFFFFFFFF) for k in COUNTER_NAMES))


def body_event(code: int, text: str) -> bytes:
    return struct.pack("<B", code) + text.encode("ascii", "replace")[:200]


def parse_body(rtype: int, body: bytes) -> dict:
    if rtype == CAN:
        cid, dlc = struct.unpack_from("<HB", body)
        return {"can_id": cid, "data": body[3:3 + dlc]}
    if rtype == PPS:
        return {"utc_s": struct.unpack("<I", body)[0]}
    if rtype == GNSS:
        s, a, n, f = struct.unpack("<ffBB", body)
        return {"speed_mps": s, "sacc_mps": a, "num_sv": n, "fix": bool(f)}
    if rtype == IMU:
        ax, gz = struct.unpack("<ff", body)
        return {"ax_mps2": ax, "gz_rad_s": gz}
    if rtype == WHEEL:
        ch, n, w = struct.unpack("<BHH", body)
        return {"channel": ch, "counts": n, "window_ms": w}
    if rtype == COUNTERS:
        return dict(zip(COUNTER_NAMES, struct.unpack("<8I", body)))
    if rtype == EVENT:
        return {"code": body[0], "text": body[1:].decode("ascii", "replace")}
    if rtype == TEMP:
        ch, st, v = struct.unpack("<BBh", body)
        return {"channel": ch, "status": TEMP_STATUS[st] if st < len(TEMP_STATUS) else f"status_{st}",
                "deg_c": v / 100.0 if st == 0 and v != TEMP_INVALID else None}
    return {"raw": body}


class Writer:
    """Accumulates records into blocks; `capacity_bytes` models the flash size.

    When the next block would not fit, it is not written: its records are
    counted in `dropped_storage` and `storage_full` is set. Nothing blocks."""

    def __init__(self, path: pathlib.Path, meta: dict, capacity_bytes: int):
        self.path = pathlib.Path(path)
        self.f = self.path.open("wb")
        m = json.dumps(meta, sort_keys=True).encode()
        hdr = MAGIC + struct.pack("<HI", VERSION, len(m)) + m + struct.pack("<I", zlib.crc32(m))
        self.f.write(hdr)
        self.bytes = len(hdr)
        self.capacity = capacity_bytes
        self.block_seq = 0
        self.base_us = None
        self.buf = bytearray()
        self.n_in_buf = 0
        self.records = 0
        self.dropped_storage = 0
        self.storage_full = False

    def add(self, t_us: int, rtype: int, body: bytes) -> None:
        if self.base_us is None:
            self.base_us = t_us
        dt = t_us - self.base_us
        # Records keep receive order; a timestamp before the block base (or too far
        # after it, or a full block) starts a new block.
        if dt < 0 or dt >= 1 << 32 or len(self.buf) + REC_HDR.size + len(body) > BLOCK_BYTES:
            self.flush()
            self.base_us = t_us
            dt = 0
        self.buf += REC_HDR.pack(rtype, len(body), dt) + body
        self.n_in_buf += 1

    def flush(self) -> None:
        if not self.buf:
            return
        payload = bytes(self.buf)
        blk = BLK_HDR.pack(b"BK", self.block_seq, self.base_us, len(payload), zlib.crc32(payload)) + payload
        if self.bytes + len(blk) > self.capacity:
            self.storage_full = True
            self.dropped_storage += self.n_in_buf
        else:
            self.f.write(blk)
            self.bytes += len(blk)
            self.records += self.n_in_buf
            self.block_seq += 1
        self.buf = bytearray()
        self.n_in_buf = 0
        self.base_us = None

    def close(self) -> None:
        self.flush()
        self.f.close()


@dataclasses.dataclass
class ReadReport:
    meta_ok: bool = False
    blocks_ok: int = 0
    blocks_corrupt: int = 0
    block_seq_gaps: int = 0
    truncated_tail_bytes: int = 0
    records: int = 0


def read(path: pathlib.Path) -> tuple[dict, list[tuple[int, int, int, int, dict]], ReadReport]:
    """(meta, [(block_seq, index, t_us, type, fields)], report). Corrupt blocks are
    skipped and counted; a truncated last block is reported, not guessed."""
    raw = pathlib.Path(path).read_bytes()
    rep = ReadReport()
    if raw[:4] != MAGIC:
        raise ValueError("not an STLG file")
    ver, mlen = struct.unpack_from("<HI", raw, 4)
    if ver != VERSION:
        raise ValueError(f"STLG version {ver} not supported")
    m = raw[10:10 + mlen]
    (mcrc,) = struct.unpack_from("<I", raw, 10 + mlen)
    rep.meta_ok = zlib.crc32(m) == mcrc
    meta = json.loads(m) if rep.meta_ok else {}
    pos = 14 + mlen
    out = []
    expect = 0
    while pos < len(raw):
        if len(raw) - pos < BLK_HDR.size:
            rep.truncated_tail_bytes = len(raw) - pos
            break
        mg, seq, base, n, crc = BLK_HDR.unpack_from(raw, pos)
        if mg != b"BK":
            rep.blocks_corrupt += 1
            nxt = raw.find(b"BK", pos + 1)   # resynchronise on the next block marker
            if nxt < 0:
                rep.truncated_tail_bytes = len(raw) - pos
                break
            pos = nxt
            continue
        if pos + BLK_HDR.size + n > len(raw):
            rep.truncated_tail_bytes = len(raw) - pos
            break
        payload = raw[pos + BLK_HDR.size: pos + BLK_HDR.size + n]
        pos += BLK_HDR.size + n
        if zlib.crc32(payload) != crc:
            rep.blocks_corrupt += 1
            continue
        if seq != expect:
            rep.block_seq_gaps += 1
        expect = seq + 1
        rep.blocks_ok += 1
        q, idx = 0, 0
        while q < len(payload):
            rtype, ln, dt = REC_HDR.unpack_from(payload, q)
            body = payload[q + REC_HDR.size: q + REC_HDR.size + ln]
            q += REC_HDR.size + ln
            out.append((seq, idx, base + dt, rtype, parse_body(rtype, body)))
            idx += 1
    rep.records = len(out)
    return meta, out, rep


def iter_records(path) -> Iterator[tuple[int, int, int, int, dict]]:
    _, recs, _ = read(path)
    yield from recs
