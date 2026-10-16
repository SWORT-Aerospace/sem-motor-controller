"""Pit-side ingestion into one SQLite file (HOST SIMULATION of the proposed pipeline).

The telematics data-flow proposal: MQTT broker -> parsing service (Python,
parse + validate) -> SQLite (runs + samples); flash / SD / USB log files ->
log import -> the same database. This module is that service, without a
network: live messages are read from the simulated broker, logs from STLG files.

Rules:
  * a live message is validated before it is stored; a rejected message is
    recorded with its reason, never silently skipped or repaired;
  * every key is idempotent: re-delivered (replayed) live messages and a
    re-imported log add no rows;
  * unknown values stay NULL;
  * times are kept in the clock domain they were measured in (telematics
    microseconds) next to the UTC derived from the logged PPS edges, with its
    quality ("pps" interpolated, "holdover" extrapolated, "none").
"""
from __future__ import annotations

import json
import math
import pathlib
import sqlite3

from host.telematics import stlg
from host.telematics.node import SCHEMA, STATES
from protocol.generated import semmc_protocol as proto

DDL = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, meta_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, t_local_ms INTEGER NOT NULL, utc REAL, utc_q TEXT,
  payload TEXT NOT NULL, received_s REAL NOT NULL, replayed INTEGER NOT NULL, PRIMARY KEY (run_id, seq));
CREATE TABLE IF NOT EXISTS rejected (
  run_id TEXT, source TEXT NOT NULL, reason TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS records (
  run_id TEXT NOT NULL, block INTEGER NOT NULL, idx INTEGER NOT NULL, t_local_us INTEGER NOT NULL,
  utc REAL, utc_q TEXT NOT NULL, rtype INTEGER NOT NULL, can_id INTEGER, msg TEXT, seq INTEGER, status TEXT,
  PRIMARY KEY (run_id, block, idx));
CREATE TABLE IF NOT EXISTS signals (
  run_id TEXT NOT NULL, block INTEGER NOT NULL, idx INTEGER NOT NULL, name TEXT NOT NULL,
  t_local_us INTEGER NOT NULL, utc REAL, value REAL, seq INTEGER, src TEXT NOT NULL,
  PRIMARY KEY (run_id, block, idx, name));
CREATE INDEX IF NOT EXISTS signals_by_name ON signals (run_id, name, t_local_us);
CREATE TABLE IF NOT EXISTS imports (run_id TEXT NOT NULL, source TEXT NOT NULL, report_json TEXT NOT NULL);
"""

# controller fields kept as signals (name -> (message, field))
CTRL_SIGNALS = {
    "rotor": ("ctrl_motion", "speed_mech_rad_s"), "iq": ("ctrl_motion", "iq_A"), "vbus": ("ctrl_motion", "vbus_V"),
    "ibatt": ("ctrl_currents", "ibatt_A"), "kcl": ("ctrl_currents", "kcl_residual_A"),
    "kcl_available": ("ctrl_currents", "kcl_available"), "p_dc": ("ctrl_energy", "p_batt_W"),
    "energy_J": ("ctrl_energy", "energy_J"), "energy_integrated_s": ("ctrl_energy_quality", "integrated_s"),
    "energy_gap_s": ("ctrl_energy_quality", "gap_s"), "requested_Nm": ("ctrl_cmd_trace", "requested_Nm"),
    "accepted_Nm": ("ctrl_cmd_trace", "accepted_Nm"), "reason": ("ctrl_cmd_trace", "reason"),
    "state": ("ctrl_status", "state"), "sup_torque_Nm": ("sup_torque_req", "torque_Nm"),
}
RANGES = {"speed_mech_rad_s": (-1000.0, 1000.0), "iq_A": (-200.0, 200.0), "vbus_V": (0.0, 100.0),
          "p_batt_W_mean": (-5000.0, 5000.0), "energy_J": (-1e9, 1e9)}


def connect(path: pathlib.Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.executescript(DDL)
    return db


# ---------------------------------------------------------------- live (MQTT)
def validate_live(payload: bytes) -> tuple[dict | None, str | None]:
    try:
        m = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"not JSON ({type(e).__name__})"
    if not isinstance(m, dict) or m.get("schema") != SCHEMA:
        return None, "wrong or missing schema"
    for k, typ in (("run_id", str), ("seq", int), ("t_local_ms", int), ("ctrl", dict), ("replayed", bool)):
        if not isinstance(m.get(k), typ):
            return None, f"field {k} missing or not {typ.__name__}"
    if m["seq"] < 0:
        return None, "negative seq"
    st = m["ctrl"].get("state")
    if st is not None and st not in STATES:
        return None, f"unknown state {st!r}"
    for k, (lo, hi) in RANGES.items():
        v = m["ctrl"].get(k)
        if v is None:
            continue
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            return None, f"ctrl.{k}={v!r} outside [{lo}, {hi}]"
    if m.get("utc_q") not in ("pps", "holdover", "none"):
        return None, "bad utc_q"
    return m, None


def ingest_live(db: sqlite3.Connection, broker: list[tuple[float, str, bytes]], topic: str) -> dict:
    rep = {"messages": 0, "stored": 0, "duplicates": 0, "rejected": 0, "replayed_stored": 0, "reasons": {}}
    for t, top, payload in sorted(broker, key=lambda x: x[0]):
        if top != topic:
            continue
        rep["messages"] += 1
        m, why = validate_live(payload)
        if m is None:
            rep["rejected"] += 1
            rep["reasons"][why] = rep["reasons"].get(why, 0) + 1
            db.execute("INSERT INTO rejected VALUES (?,?,?,?)", (None, "live", why, payload[:120].decode("utf-8", "replace")))
            continue
        cur = db.execute("INSERT OR IGNORE INTO live VALUES (?,?,?,?,?,?,?,?)",
                         (m["run_id"], m["seq"], m["t_local_ms"], m.get("utc"), m["utc_q"],
                          json.dumps(m, sort_keys=True), t, int(m["replayed"])))
        if cur.rowcount:
            rep["stored"] += 1
            rep["replayed_stored"] += int(m["replayed"])
        else:
            rep["duplicates"] += 1
    db.commit()
    return rep


# ---------------------------------------------------------------- offline (STLG)
def _utc_mapper(pps: list[tuple[int, int]], holdover_after_us: int = 2_500_000):
    """Offline telematics-us -> UTC: piecewise-linear between the two PPS edges
    around t (interpolation); outside or across a gap longer than
    holdover_after_us, the nearest fit is extrapolated and marked holdover."""
    pps = sorted(pps)

    def fit(i, j):
        (x0, y0), (x1, y1) = pps[i], pps[j]
        b = (y1 - y0) / (x1 - x0)
        return lambda x: y0 + b * (x - x0)

    import bisect
    xs = [p[0] for p in pps]

    def utc(t_us: int):
        if len(pps) < 2:
            return None, "none"
        k = bisect.bisect_right(xs, t_us)
        if 0 < k < len(pps) and xs[k] - xs[k - 1] <= holdover_after_us:
            return fit(k - 1, k)(t_us), "pps"
        if k == 0:
            return fit(0, 1)(t_us), "holdover"
        if k >= len(pps):
            return fit(len(pps) - 2, len(pps) - 1)(t_us), ("pps" if t_us - xs[-1] <= holdover_after_us else "holdover")
        return fit(max(k - 2, 0), k - 1)(t_us), "holdover"   # inside a PPS gap: extrapolate the fit before it
    return utc


def import_log(db: sqlite3.Connection, path: pathlib.Path) -> dict:
    meta, recs, rr = stlg.read(path)
    run_id = meta.get("run_id")
    if not run_id:
        raise ValueError("log without run_id in its metadata")
    db.execute("INSERT OR IGNORE INTO runs VALUES (?,?)", (run_id, json.dumps(meta, sort_keys=True)))
    pps = [(t, f["utc_s"]) for _b, _i, t, rt, f in recs if rt == stlg.PPS]
    utc_of = _utc_mapper(pps)
    sens = meta.get("sensors", {})
    C = sens.get("wheel_circumference_m")
    ppr = sens.get("wheel_ppr")
    chan = {int(k): v for k, v in sens.get("wheel_channels", {}).items()}
    rep = {"run_id": run_id, "blocks_ok": rr.blocks_ok, "blocks_corrupt": rr.blocks_corrupt,
           "block_seq_gaps": rr.block_seq_gaps, "truncated_tail_bytes": rr.truncated_tail_bytes,
           "records": rr.records, "new_records": 0, "frames_bad_crc": 0, "utc_quality": {}}
    rows, sig = [], []
    for blk, idx, t, rtype, f in recs:
        u, q = utc_of(t)
        rep["utc_quality"][q] = rep["utc_quality"].get(q, 0) + 1
        can_id = msg = seq = status = None
        if rtype == stlg.CAN:
            can_id = f["can_id"]
            m = proto.BY_ID.get(can_id)
            if m is not None:
                values, info = proto.decode(can_id, f["data"])
                msg, status, seq = m["name"], info["status"], info.get("seq")
                if status != "ok":
                    rep["frames_bad_crc"] += 1
                else:
                    for name, (mn, fld) in CTRL_SIGNALS.items():
                        if mn == msg:
                            v = values[fld]
                            v = float(v) if isinstance(v, (int, float, bool)) else None
                            sig.append((run_id, blk, idx, name, t, u, v if v is None or math.isfinite(v) else None,
                                        seq, "controller" if msg != "sup_torque_req" else "supervisor"))
            else:
                status = "unknown_id"
        elif rtype == stlg.WHEEL and C and ppr:
            v = f["counts"] * C / (ppr * f["window_ms"] / 1000.0)
            sig.append((run_id, blk, idx, chan.get(f["channel"], f"wheel_{f['channel']}"), t, u, v, None, "telematics"))
        elif rtype == stlg.GNSS:
            v = f["speed_mps"] if f["fix"] and math.isfinite(f["speed_mps"]) else None
            sig.append((run_id, blk, idx, "gnss", t, u, v, None, "gnss"))
            sig.append((run_id, blk, idx, "gnss_sacc", t, u, f["sacc_mps"] if f["fix"] else None, None, "gnss"))
            sig.append((run_id, blk, idx, "gnss_num_sv", t, u, float(f["num_sv"]), None, "gnss"))
        elif rtype == stlg.IMU:
            sig.append((run_id, blk, idx, "imu_ax", t, u, f["ax_mps2"], None, "imu"))
            sig.append((run_id, blk, idx, "imu_gz", t, u, f["gz_rad_s"], None, "imu"))
        elif rtype == stlg.COUNTERS:
            for k, v in f.items():
                sig.append((run_id, blk, idx, "cnt_" + k, t, u, float(v), None, "telematics"))
        rows.append((run_id, blk, idx, t, u, q, rtype, can_id, msg, seq, status))
    before = db.total_changes
    db.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    rep["new_records"] = db.total_changes - before
    db.executemany("INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?,?,?,?)", sig)
    db.execute("INSERT INTO imports VALUES (?,?,?)", (run_id, str(path.name), json.dumps(rep, sort_keys=True)))
    db.commit()
    return rep
