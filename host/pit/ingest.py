"""Pit-side ingestion into one SQLite file (host software).

The telematics data-flow proposal: MQTT broker -> parsing service (Python,
parse + validate) -> SQLite (runs + samples); flash / SD / USB log files ->
log import -> the same database. This module is the parse/validate/store step.
Live messages reach it either from the in-process simulated broker of the host
demonstration (`ingest_live`) or from a real MQTT broker through
`host/pit/mqtt_ingest.py` (`ingest_payload`, one message at a time); logs come
from STLG files (`import_log`).

Rules:
  * a live message is validated before it is stored; a rejected message is
    recorded with its reason, never silently skipped or repaired;
  * every receipt is recorded in `rx` with its outcome (stored, duplicate,
    rejected), so duplicates and rejections are counted, not inferred;
  * every key is idempotent: re-delivered (replayed) live messages and a
    re-imported log add no rows;
  * unknown values stay NULL;
  * times are kept in the clock domain they were measured in (telematics
    microseconds, `t_local_ms` for live messages) next to the UTC derived from
    the logged PPS edges, with its quality ("pps" interpolated, "holdover"
    extrapolated, "none"). `received_s` is the receiver's clock: simulation
    seconds in the host demonstration, Unix seconds of the pit computer for a
    real broker.
"""
from __future__ import annotations

import json
import math
import pathlib
import sqlite3

from host.telematics import stlg
from host.telematics import controller_adapter, measurement, signals
from host.telematics.node import SCHEMAS_ACCEPTED
from host.telematics.wheel import EdgeRecord, WheelConfig, WheelEstimator
from protocol.generated import semmc_protocol as proto

DDL = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, meta_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS live (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, t_local_ms INTEGER NOT NULL, utc REAL, utc_q TEXT,
  payload TEXT NOT NULL, received_s REAL NOT NULL, replayed INTEGER NOT NULL, schema TEXT,
  PRIMARY KEY (run_id, seq));
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
CREATE TABLE IF NOT EXISTS measurements (
  run_id TEXT NOT NULL, record_id INTEGER NOT NULL, block INTEGER NOT NULL, idx INTEGER NOT NULL,
  source TEXT NOT NULL, signal TEXT NOT NULL, value REAL, unit TEXT NOT NULL, t_rx_us INTEGER NOT NULL,
  t_sample_us INTEGER, t_unc_us INTEGER, source_seq INTEGER, validity TEXT NOT NULL, provenance TEXT NOT NULL,
  upper REAL, utc REAL, utc_q TEXT NOT NULL,
  PRIMARY KEY (run_id, record_id));
CREATE INDEX IF NOT EXISTS measurements_by_signal ON measurements (run_id, signal, t_rx_us);
CREATE TABLE IF NOT EXISTS imports (run_id TEXT NOT NULL, source TEXT NOT NULL, report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rx (
  rx INTEGER PRIMARY KEY AUTOINCREMENT, received_s REAL NOT NULL, topic TEXT NOT NULL, dup_flag INTEGER,
  outcome TEXT NOT NULL, run_id TEXT, seq INTEGER, reason TEXT);
"""

# controller states of the semmc protocol (simulation fixture), for v1 to v3 messages of the legacy simulation;
# the same list as host/telemetry_adapter/legacy_node.py STATES, kept here so the pit imports no supervisor code
STATES = ["BOOT", "SELF_TEST", "DISARMED", "READY", "MANUAL", "ECO_ASSIST", "DERATED", "FAULT_LATCHED"]

# controller fields kept as signals (name -> (message, field))
CTRL_SIGNALS = {
    "rotor": ("ctrl_motion", "speed_mech_rad_s"), "iq": ("ctrl_motion", "iq_A"), "vbus": ("ctrl_motion", "vbus_V"),
    "ibatt": ("ctrl_currents", "ibatt_A"), "kcl": ("ctrl_currents", "kcl_residual_A"),
    "kcl_available": ("ctrl_currents", "kcl_available"), "p_dc": ("ctrl_energy", "p_batt_W"),
    "energy_J": ("ctrl_energy", "energy_J"), "energy_integrated_s": ("ctrl_energy_quality", "integrated_s"),
    "energy_gap_s": ("ctrl_energy_quality", "gap_s"), "requested_Nm": ("ctrl_cmd_trace", "requested_Nm"),
    "accepted_Nm": ("ctrl_cmd_trace", "accepted_Nm"), "reason": ("ctrl_cmd_trace", "reason"),
    "state": ("ctrl_status", "state"), "sup_torque_Nm": ("sup_torque_req", "torque_Nm"),
    "t_fet": ("ctrl_thermal", "t_fet_degC"), "t_motor": ("ctrl_thermal", "t_motor_degC"),
}
RANGES = {"speed_mech_rad_s": (-1000.0, 1000.0), "iq_A": (-200.0, 200.0), "vbus_V": (0.0, 100.0),
          "p_batt_W_mean": (-5000.0, 5000.0), "energy_J": (-1e9, 1e9)}


WHEEL_RANGE_MPS = (0.0, 60.0)
# plausibility bounds of a live temperature, wider than the -55..125 degC of common digital probes and NTCs;
# PROVISIONAL until the probe part is selected. A value outside them is rejected as corrupted.
TEMP_RANGE_DEGC = (-55.0, 200.0)


def connect(path: pathlib.Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.executescript(DDL)
    # databases created before the v2 live message have no `schema` column: add it (old rows stay NULL = v1)
    cols = {r[1] for r in db.execute("PRAGMA table_info(live)")}
    if "schema" not in cols:
        db.execute("ALTER TABLE live ADD COLUMN schema TEXT")
        db.commit()
    return db


# ---------------------------------------------------------------- live (MQTT)
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)        # JSON true/false are not integers here


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


LIVE_Q = tuple(measurement.VALIDITY) + ("stale", "missing")


def _validate_common(m: dict) -> str | None:
    if m.get("utc_q") not in ("pps", "holdover", "none"):
        return "bad utc_q"
    if m.get("utc") is not None and not _is_num(m["utc"]):
        return "utc not a finite number or null"
    if m["utc_q"] == "none" and m.get("utc") is not None:
        return "utc given with utc_q none"
    if m.get("utc_err_s") is not None and not (_is_num(m["utc_err_s"]) and m["utc_err_s"] >= 0):
        return "utc_err_s not a non-negative number or null"
    c = m.get("counters")
    if c is not None and not (isinstance(c, dict) and all(_is_int(v) and v >= 0 for v in c.values())):
        return "counters not an object of non-negative integers"
    return None


def _validate_v4(m: dict) -> str | None:
    """sem.telemetry.v4 (host/telematics/node.py): the latest measurement per registry signal."""
    for k, ok, what in (("run_id", lambda v: isinstance(v, str) and v != "", "a non-empty string"),
                        ("boot", _is_int, "an integer"), ("seq", _is_int, "an integer"),
                        ("t_local_ms", _is_int, "an integer"), ("adapter", lambda v: isinstance(v, dict), "an object"),
                        ("m", lambda v: isinstance(v, dict), "an object"),
                        ("replayed", lambda v: isinstance(v, bool), "a boolean")):
        if not ok(m.get(k)):
            return f"field {k} missing or not {what}"
    for k in ("boot", "seq", "t_local_ms"):
        if m[k] < 0:
            return f"negative {k}"
    for k in ("sup", "ctrl"):
        if k in m:
            return f"v4 message with a {k!r} block: the receive-only node has none"
    a = m["adapter"]
    if not isinstance(a.get("id"), str) or not isinstance(a.get("fixture"), bool):
        return "adapter.id or adapter.fixture missing"
    if a.get("silent_ms") is not None and not (_is_int(a["silent_ms"]) and a["silent_ms"] >= 0):
        return "adapter.silent_ms not a non-negative integer or null"
    for sid, e in m["m"].items():
        reg = signals.lookup(sid)
        if reg is None:
            return f"m.{sid}: not a registry signal"
        if not isinstance(e, dict):
            return f"m.{sid} not an object"
        if e.get("u") != reg.unit:
            return f"m.{sid}: unit {e.get('u')!r}, the registry says {reg.unit!r}"
        q, v, age = e.get("q"), e.get("v"), e.get("age_ms")
        if q not in LIVE_Q:
            return f"m.{sid}: unknown q {q!r}"
        if q in ("valid", "unverified"):
            if not (_is_num(v) and reg.lo <= v <= reg.hi):
                return f"m.{sid}.v={v!r} outside [{reg.lo}, {reg.hi}] or missing for q {q}"
            if not (_is_int(age) and 0 <= age <= reg.stale_s * 1000 + 1):
                return f"m.{sid}: q {q} with age_ms {age!r} (stale after {reg.stale_s} s)"
        elif v is not None:
            return f"m.{sid}: a value with q {q}: a missing or invalid value must be null"
        if q == "missing" and age is not None:
            return f"m.{sid}: missing with an age"
        if q != "missing" and not (_is_int(age) and age >= 0):
            return f"m.{sid}: age_ms not a non-negative integer"
        if e.get("seq") is not None and not (_is_int(e["seq"]) and 0 <= e["seq"] < 2**32):
            return f"m.{sid}: seq not an unsigned integer or null"
        if e.get("ts") not in ("sample", "rx", None):
            return f"m.{sid}: ts {e.get('ts')!r}"
        if "upper" in e and not (_is_num(e["upper"]) and e["upper"] >= 0):
            return f"m.{sid}: upper not a non-negative number"
    return _validate_common(m)


def validate_live(payload: bytes) -> tuple[dict | None, str | None]:
    """Parse and check one live message. Returns (message, None) or (None, reason)."""
    try:
        m = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"not JSON ({type(e).__name__})"
    if not isinstance(m, dict) or m.get("schema") not in SCHEMAS_ACCEPTED:
        return None, "wrong or missing schema"
    if m["schema"] == "sem.telemetry.v4":
        why = _validate_v4(m)
        return (None, why) if why else (m, None)
    for k, ok, what in (("run_id", lambda v: isinstance(v, str) and v != "", "a non-empty string"),
                        ("seq", _is_int, "an integer"), ("t_local_ms", _is_int, "an integer"),
                        ("ctrl", lambda v: isinstance(v, dict), "an object"),
                        ("replayed", lambda v: isinstance(v, bool), "a boolean")):
        if not ok(m.get(k)):
            return None, f"field {k} missing or not {what}"
    if m["seq"] < 0:
        return None, "negative seq"
    if m["t_local_ms"] < 0:
        return None, "negative t_local_ms"
    st = m["ctrl"].get("state")
    if st is not None and st not in STATES:
        return None, f"unknown state {st!r}"
    for k, (lo, hi) in RANGES.items():
        v = m["ctrl"].get(k)
        if v is None:
            continue
        if not _is_num(v) or not lo <= v <= hi:
            return None, f"ctrl.{k}={v!r} outside [{lo}, {hi}]"
    why = _validate_common(m)
    if why:
        return None, why
    if m["schema"] in ("sem.telemetry.v2", "sem.telemetry.v3"):
        w = m.get("wheel")
        if not isinstance(w, dict) or not isinstance(w.get("speed_mps"), dict):
            return None, f"{m['schema'][-2:]} message without a wheel.speed_mps object"
        lo, hi = WHEEL_RANGE_MPS
        for ch, v in w["speed_mps"].items():
            if v is not None and not (_is_num(v) and lo <= v <= hi):
                return None, f"wheel.speed_mps.{ch}={v!r} outside [{lo}, {hi}]"
    if m["schema"] == "sem.telemetry.v3":
        tp = m.get("temp")
        if not isinstance(tp, dict) or not isinstance(tp.get("probe_degC"), dict):
            return None, "v3 message without a temp.probe_degC object"
        lo, hi = TEMP_RANGE_DEGC
        vals = [(k, tp.get(k)) for k in ("ctrl_fet_degC", "ctrl_motor_degC")]
        vals += [(f"probe_degC.{ch}", v) for ch, v in tp["probe_degC"].items()]
        for k, v in vals:
            if v is not None and not (_is_num(v) and lo <= v <= hi):
                return None, f"temp.{k}={v!r} outside [{lo}, {hi}]"
    return m, None


def ingest_payload(db: sqlite3.Connection, received_s: float, topic: str, payload: bytes,
                   dup_flag: bool | None = None, commit: bool = True) -> tuple[str, str | None]:
    """Validate and store one live message; record the receipt in `rx`.

    Returns (outcome, reason): outcome is "stored", "duplicate" (same run_id
    and seq already stored; nothing changes) or "rejected" (reason given).
    `dup_flag` is the MQTT DUP bit when the transport reports it (None otherwise).
    """
    m, why = validate_live(payload)
    if m is None:
        run_id = None
        try:
            j = json.loads(payload)
            run_id = j.get("run_id") if isinstance(j, dict) and isinstance(j.get("run_id"), str) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        db.execute("INSERT INTO rejected VALUES (?,?,?,?)",
                   (run_id, "live", why, payload[:120].decode("utf-8", "replace")))
        db.execute("INSERT INTO rx (received_s, topic, dup_flag, outcome, run_id, seq, reason) VALUES (?,?,?,?,?,?,?)",
                   (received_s, topic, None if dup_flag is None else int(dup_flag), "rejected", run_id, None, why))
        outcome = "rejected"
    else:
        cur = db.execute("INSERT OR IGNORE INTO live (run_id, seq, t_local_ms, utc, utc_q, payload, received_s, "
                         "replayed, schema) VALUES (?,?,?,?,?,?,?,?,?)",
                         (m["run_id"], m["seq"], m["t_local_ms"], m.get("utc"), m["utc_q"],
                          json.dumps(m, sort_keys=True), received_s, int(m["replayed"]), m["schema"]))
        outcome = "stored" if cur.rowcount else "duplicate"
        db.execute("INSERT INTO rx (received_s, topic, dup_flag, outcome, run_id, seq, reason) VALUES (?,?,?,?,?,?,?)",
                   (received_s, topic, None if dup_flag is None else int(dup_flag), outcome, m["run_id"], m["seq"],
                    None))
    if commit:
        db.commit()
    return outcome, why


def ingest_live(db: sqlite3.Connection, broker: list[tuple[float, str, bytes]], topic: str) -> dict:
    """Ingest every message of the in-process simulated broker (host demonstration)."""
    rep = {"messages": 0, "stored": 0, "duplicates": 0, "rejected": 0, "replayed_stored": 0, "reasons": {}}
    for t, top, payload in sorted(broker, key=lambda x: x[0]):
        if top != topic:
            continue
        rep["messages"] += 1
        outcome, why = ingest_payload(db, t, top, payload, commit=False)
        if outcome == "rejected":
            rep["rejected"] += 1
            rep["reasons"][why] = rep["reasons"].get(why, 0) + 1
        elif outcome == "stored":
            rep["stored"] += 1
            rep["replayed_stored"] += int(json.loads(payload)["replayed"])
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


def _rid(block: int, idx: int, k: int) -> int:
    """Measurement record id at import: from the record's place in the log (block, index) and its position
    in the record, so a second import of the same log gives the same ids and adds nothing."""
    return (block << 20) | (idx << 4) | k


def _meas_row(run_id, blk, idx, m, u, q):
    return (run_id, m.record_id, blk, idx, m.source, m.signal, m.value, m.unit, m.t_rx_us, m.t_sample_us, m.t_unc_us,
            m.source_seq, m.validity, m.provenance, m.upper, u, q)


def import_log(db: sqlite3.Connection, path: pathlib.Path, mapping_dir: pathlib.Path | None = None) -> dict:
    """Import one STLG log: every record into `records`, every measurement into `measurements` (decoded with
    the controller adapter the log names, `controller_adapter` in its metadata; a log without one is a semmc
    simulation log and uses the simulation fixture), and the legacy `signals` rows the shadow replay reads."""
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
    tchan = {int(k): v for k, v in sens.get("temp_channels", {}).items()}
    adapter = controller_adapter.from_meta(meta.get("controller_adapter") or {"id": "semmc-sim-fixture"}, mapping_dir)
    wcfg = WheelConfig(C, ppr, active_high=bool(sens.get("wheel_active_high"))) if C and ppr else None
    west = {}
    rep = {"run_id": run_id, "blocks_ok": rr.blocks_ok, "blocks_corrupt": rr.blocks_corrupt,
           "block_seq_gaps": rr.block_seq_gaps, "truncated_tail_bytes": rr.truncated_tail_bytes,
           "records": rr.records, "new_records": 0, "frames_bad_crc": 0, "frames": {}, "utc_quality": {},
           "adapter": adapter.id, "boot": None, "last_counters": None, "final_counters": False,
           "wheel_lost_records": 0, "wheel_lost_edges": 0, "measurements": 0, "validity": {}}
    rows, sig, meas = [], [], []
    for n_rec, (blk, idx, t, rtype, f) in enumerate(recs):
        u, q = utc_of(t)
        rep["utc_quality"][q] = rep["utc_quality"].get(q, 0) + 1
        can_id = msg = seq = status = None
        made = []
        if rtype in (stlg.CAN, stlg.CAN2):
            can_id = f["can_id"]
            k = iter(range(16))
            adapter.rid = lambda: _rid(blk, idx, next(k))   # noqa: B023  (ids from the record's place)
            res = adapter.decode(t, controller_adapter.Frame(can_id, f["data"], f.get("extended", False),
                                                             f.get("fd", False)))
            rep["frames"][res.kind] = rep["frames"].get(res.kind, 0) + 1
            msg, status = res.message, ("ok" if res.kind in ("decoded", "ignored") else
                                        res.detail if res.kind == "invalid" else "unknown_id")
            made = res.measurements
            seq = made[0].source_seq if made else None
            if res.kind == "invalid" and res.detail == "bad_crc":
                rep["frames_bad_crc"] += 1
            if adapter.id == controller_adapter.SimFixtureAdapter.id and res.kind in ("decoded", "ignored"):
                values, info = proto.decode(can_id, f["data"])
                seq = info.get("seq")
                for name, (mn, fld) in CTRL_SIGNALS.items():
                    if mn == msg:
                        v = values[fld]
                        v = float(v) if isinstance(v, (int, float, bool)) else None
                        sig.append((run_id, blk, idx, name, t, u, v if v is None or math.isfinite(v) else None,
                                    seq, "controller" if msg != "sup_torque_req" else "supervisor"))
        elif rtype == stlg.WHEEL and C and ppr:
            v = f["counts"] * C / (ppr * f["window_ms"] / 1000.0)
            sig.append((run_id, blk, idx, chan.get(f["channel"], f"wheel_{f['channel']}"), t, u, v, None, "telematics"))
        elif rtype == stlg.WHEEL_EDGES:
            name = chan.get(f["channel"], f"wheel_{f['channel']}")
            if wcfg is not None:
                k = iter(range(16))
                est = west.setdefault(f["channel"], WheelEstimator(wcfg, name))
                est.rid = lambda: _rid(blk, idx, next(k))   # noqa: B023
                made = est.feed(EdgeRecord(t, f["channel"], f["n"], f["span_us"], f["total"], f["flags"], f["rec_seq"],
                                           f["lost"]))
                for m in made:
                    if m.signal.endswith(".speed") and m.usable:
                        sig.append((run_id, blk, idx, name, t, u, m.value, None, "telematics"))
            status = "heartbeat" if f["n"] == 0 else "edges"
        elif rtype == stlg.TEMP:
            # an invalid reading is stored as NULL with the record kept, so a missing value is visible
            name = tchan.get(f["channel"], str(f["channel"]))
            sig.append((run_id, blk, idx, "temp_" + name, t, u, f["deg_c"], None, "telematics"))
            status = f["status"]
            made = [measurement.checked(_rid(blk, idx, 0), "temp", f"temp.{name}", f["deg_c"], "degC", t,
                                        provenance=f"temp-probe:ch{f['channel']} {f['status']}",
                                        invalid=f["deg_c"] is None)]
        elif rtype == stlg.GNSS:
            v = f["speed_mps"] if f["fix"] and math.isfinite(f["speed_mps"]) else None
            sig.append((run_id, blk, idx, "gnss", t, u, v, None, "gnss"))
            sig.append((run_id, blk, idx, "gnss_sacc", t, u, f["sacc_mps"] if f["fix"] else None, None, "gnss"))
            sig.append((run_id, blk, idx, "gnss_num_sv", t, u, float(f["num_sv"]), None, "gnss"))
            made = [measurement.checked(_rid(blk, idx, 0), "gnss", "gnss.speed", v, "m/s", t, provenance="gnss",
                                        invalid=v is None),
                    measurement.checked(_rid(blk, idx, 1), "gnss", "gnss.speed_acc",
                                        f["sacc_mps"] if f["fix"] else None, "m/s", t, provenance="gnss",
                                        invalid=not f["fix"]),
                    measurement.checked(_rid(blk, idx, 2), "gnss", "gnss.num_sv", f["num_sv"], "1", t,
                                        provenance="gnss")]
        elif rtype == stlg.IMU:
            sig.append((run_id, blk, idx, "imu_ax", t, u, f["ax_mps2"], None, "imu"))
            sig.append((run_id, blk, idx, "imu_gz", t, u, f["gz_rad_s"], None, "imu"))
            made = [measurement.checked(_rid(blk, idx, 0), "imu", "imu.ax", f["ax_mps2"], "m/s^2", t, provenance="imu"),
                    measurement.checked(_rid(blk, idx, 1), "imu", "imu.gz", f["gz_rad_s"], "rad/s", t, provenance="imu")]
        elif rtype == stlg.BATT:
            status = f["status"]
            made = [measurement.checked(_rid(blk, idx, k2), "batt", sig, f[fld], unit, t,
                                        provenance=f"battery-monitor {f['status']}", invalid=f[fld] is None)
                    for k2, (sig, fld, unit) in enumerate((("batt.voltage", "voltage_V", "V"),
                                                           ("batt.current", "current_A", "A")))]
        elif rtype in (stlg.COUNTERS, stlg.COUNTERS2):
            for k2, v in f.items():
                sig.append((run_id, blk, idx, "cnt_" + k2, t, u, float(v), None, "telematics"))
            rep["last_counters"] = {"record": n_rec, "t_us": t, **f}
            rep["final_counters"] = n_rec == len(recs) - 1
        elif rtype == stlg.BOOT:
            rep["boot"] = f
        for m in made:
            meas.append(_meas_row(run_id, blk, idx, m, u, q))
            rep["validity"][m.validity] = rep["validity"].get(m.validity, 0) + 1
        rows.append((run_id, blk, idx, t, u, q, rtype, can_id, msg, seq, status))
    for est in west.values():
        rep["wheel_lost_records"] += est.lost_records
        rep["wheel_lost_edges"] += est.lost_edges
    rep["measurements"] = len(meas)
    lc = rep["last_counters"]
    if lc and "log_records" in lc:
        # every record the unit wrote before its last counters record must be in the file; with an orderly
        # shutdown that record is the last one and counts itself
        rep["accounting"] = {"records_in_file": rr.records, "unit_log_records": lc["log_records"],
                             "dropped_queue": lc.get("log_dropped_queue"), "dropped_storage": lc.get("log_dropped_storage"),
                             # records the unit moved into blocks that the storage then refused are in
                             # dropped_storage, not in the file
                             "missing_from_file": max(0, lc["log_records"] - (lc.get("log_dropped_storage") or 0)
                                                      - (rr.records if rep["final_counters"] else lc["record"] + 1)),
                             "after_last_counters": "none (orderly close)" if rep["final_counters"] else
                             "unknown: the session ended without a final counters record (restart or power loss)"}
    before = db.total_changes
    db.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    rep["new_records"] = db.total_changes - before
    db.executemany("INSERT OR IGNORE INTO signals VALUES (?,?,?,?,?,?,?,?,?)", sig)
    before = db.total_changes
    db.executemany("INSERT OR IGNORE INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", meas)
    rep["new_measurements"] = db.total_changes - before
    db.execute("INSERT INTO imports VALUES (?,?,?)", (run_id, str(path.name), json.dumps(rep, sort_keys=True)))
    db.commit()
    return rep
