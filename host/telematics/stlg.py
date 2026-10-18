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
  9 WHEEL_EDGES u8 channel | u8 flags | u16 n_edges | u32 span_us | u32 total_edges | u16 rec_seq | u16 lost
              edges captured since the channel's previous record (v0.7, telematics/firmware tm_wheel.c and
              host/telematics/wheel.py). The record time is the last edge, or the evaluation time when
              n_edges is 0 (a heartbeat); span_us is last minus first edge; total_edges counts every edge since
              start (so a lost record loses no distance); flags bit 0 line high, bit 1 capture overrun, bit 2
              heartbeat; rec_seq counts the channel's records (a gap is a lost record); lost counts edges lost
              to capture overrun since the previous record.
 13 BATT      u8 status | f32 voltage_V | f32 current_A    battery-side monitor sample (v0.7; status 0 ok,
              1 bus error, 2 overflow; values NaN unless ok)
 10 COUNTERS2 u8 count | count x (u8 id | u32 value)    named counters (v0.7; ids in COUNTER2_IDS), so a
              counter is added without changing the record and a missing one is absent, not zero
 11 CAN2      u32 id_flags | u8 len | data[len]           received frame (v0.7): id in bits 0-28, bit 31
              extended identifier, bit 30 FD frame, bit 29 bit-rate switch; len up to 64
 12 BOOT      u32 boot_count | u32 reset_flags | u8 cause_len | cause (ASCII)   first record of a session:
              restart reason from the MCU's reset flags (RCC_CSR on the STM32U5)

Unknown record types are kept as raw bytes by every reader, so a log with newer types still reads.
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
WHEEL_EDGES, COUNTERS2, CAN2, BOOT, BATT = 9, 10, 11, 12, 13
BATT_STATUS = ("ok", "bus_error", "overflow")
# COUNTERS2 ids; the firmware's table (telematics/firmware/include/tm_counters.h) must match
COUNTER2_IDS = {
    1: "rx_frames", 2: "log_records", 3: "log_dropped_queue", 4: "log_dropped_storage", 5: "queue_high_water",
    6: "uplink_sent", 7: "uplink_dropped", 8: "uplink_queue_high_water", 9: "frames_decoded",
    10: "frames_ignored", 11: "frames_unknown", 12: "frames_invalid", 13: "companion_frames_seen",
    14: "wheel_edges_lost", 15: "wheel_records", 16: "storage_blocks_written", 17: "storage_stall_events",
    18: "can_rx_overrun", 19: "can_bus_errors", 20: "log_queue_capacity", 21: "uplink_queue_capacity",
    22: "storage_write_errors", 23: "uptime_s",
}
COUNTER2_BY_NAME = {v: k for k, v in COUNTER2_IDS.items()}
CAN2_EXT, CAN2_FD, CAN2_BRS = 1 << 31, 1 << 30, 1 << 29
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


def body_wheel_edges(channel: int, flags: int, n: int, span_us: int, total: int, rec_seq: int, lost: int) -> bytes:
    return struct.pack("<BBHIIHH", channel, flags, min(n, 0xFFFF), min(span_us, 0xFFFFFFFF), total & 0xFFFFFFFF,
                       rec_seq & 0xFFFF, min(lost, 0xFFFF))


def body_batt(status: int, volts, amps) -> bytes:
    ok = status == 0 and volts is not None and amps is not None and math.isfinite(volts) and math.isfinite(amps)
    return struct.pack("<Bff", status if status else (0 if ok else 2), volts if ok else math.nan,
                       amps if ok else math.nan)


def body_counters2(c: dict) -> bytes:
    items = [(COUNTER2_BY_NAME[k], min(int(v), 0xFFFFFFFF)) for k, v in c.items() if k in COUNTER2_BY_NAME]
    return struct.pack("<B", len(items)) + b"".join(struct.pack("<BI", i, v) for i, v in items)


def body_can2(can_id: int, data: bytes, extended: bool = False, fd: bool = False, brs: bool = False) -> bytes:
    flags = (CAN2_EXT if extended else 0) | (CAN2_FD if fd else 0) | (CAN2_BRS if brs else 0)
    return struct.pack("<IB", (can_id & 0x1FFFFFFF) | flags, len(data)) + data


def body_boot(boot_count: int, reset_flags: int, cause: str) -> bytes:
    c = cause.encode("ascii", "replace")[:200]
    return struct.pack("<IIB", boot_count, reset_flags, len(c)) + c


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
    if rtype == WHEEL_EDGES:
        ch, fl, n, span, tot, rs, lost = struct.unpack("<BBHIIHH", body)
        return {"channel": ch, "flags": fl, "n": n, "span_us": span, "total": tot, "rec_seq": rs, "lost": lost}
    if rtype == BATT:
        st, v, a = struct.unpack("<Bff", body)
        ok = st == 0 and math.isfinite(v) and math.isfinite(a)
        return {"status": BATT_STATUS[st] if st < len(BATT_STATUS) else f"status_{st}",
                "voltage_V": v if ok else None, "current_A": a if ok else None}
    if rtype == COUNTERS2:
        (k,) = struct.unpack_from("<B", body)
        out = {}
        for j in range(k):
            i, v = struct.unpack_from("<BI", body, 1 + 5 * j)
            out[COUNTER2_IDS.get(i, f"counter_{i}")] = v
        return out
    if rtype == CAN2:
        idf, ln = struct.unpack_from("<IB", body)
        return {"can_id": idf & 0x1FFFFFFF, "extended": bool(idf & CAN2_EXT), "fd": bool(idf & CAN2_FD),
                "brs": bool(idf & CAN2_BRS), "data": body[5:5 + ln]}
    if rtype == BOOT:
        bc, rf, ln = struct.unpack_from("<IIB", body)
        return {"boot_count": bc, "reset_flags": rf, "cause": body[9:9 + ln].decode("ascii", "replace")}
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
