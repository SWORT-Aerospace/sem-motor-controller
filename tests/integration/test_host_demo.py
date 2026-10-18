"""Host end-to-end demonstration and its parts: STLG log, telematics node, pit ingestion.

HOST SIMULATION only. The full demonstration runs once per session (about 30 s).
"""
import json
import math

import pytest

from host.pit import ingest
from host.telematics import stlg
from host.telematics.clocks import LocalClock, PpsModel, UtcEstimator
from host.telematics.node import SimLink
from host.telemetry_adapter.legacy_node import NodeConfig, SupervisedTelematicsNode as TelematicsNode
from host.telemetry_adapter.supervisor import Supervisor, SupervisorConfig, speed_hold_policy
from tools import run_host_demo


@pytest.fixture(scope="module")
def demo(build_dir, tmp_path_factory):
    return run_host_demo.run(tmp_path_factory.mktemp("host_demo"), build_dir, 120.0)


def test_every_demo_check_passes(demo):
    failed = [c for c in demo["checks"] if not c["pass"]]
    assert not failed, failed


def test_demo_reports_csia_relationship_failures_instead_of_hiding_them(demo):
    # The frozen v1 power balance does not fit this plant; the demo must say so.
    assert "E6_power_balance" in demo["csia"]["relationship_failures_outside_fault_window"]


# ---- STLG ------------------------------------------------------------------------------------
def _write(path, n=3000, capacity=8 * 1024 * 1024):
    w = stlg.Writer(path, {"run_id": "T1", "sensors": {}}, capacity)
    for k in range(n):
        w.add(1000 * k, stlg.CAN, stlg.body_can(0x318, bytes([k & 0xFF] * 8)))
    w.close()
    return w


def test_stlg_roundtrip(tmp_path):
    w = _write(tmp_path / "a.stlg")
    meta, recs, rep = stlg.read(tmp_path / "a.stlg")
    assert meta["run_id"] == "T1" and rep.meta_ok
    assert rep.records == w.records == 3000 and rep.blocks_corrupt == 0 and rep.truncated_tail_bytes == 0
    assert [r[2] for r in recs] == [1000 * k for k in range(3000)]
    assert recs[5][4]["data"] == bytes([5] * 8)


def test_stlg_temperature_record_roundtrip_and_pit_import(tmp_path):
    assert stlg.parse_body(stlg.TEMP, stlg.body_temp(1, 0, 41.237)) == {"channel": 1, "status": "ok", "deg_c": 41.24}
    assert stlg.parse_body(stlg.TEMP, stlg.body_temp(2, 1, None))["status"] == "crc_error"
    nan = stlg.parse_body(stlg.TEMP, stlg.body_temp(0, 0, float("nan")))           # "ok" without a value
    assert nan == {"channel": 0, "status": "out_of_range", "deg_c": None}
    assert stlg.parse_body(stlg.TEMP, stlg.body_temp(0, 0, 400.0))["deg_c"] is None   # beyond i16 centi-degC
    w = stlg.Writer(tmp_path / "t.stlg", {"run_id": "T2", "sensors": {"temp_channels": {"0": "battery_surface",
                                                                                      "1": "motor_case"}}}, 1 << 20)
    w.add(1_000_000, stlg.TEMP, stlg.body_temp(1, 0, 41.237))
    w.add(2_000_000, stlg.TEMP, stlg.body_temp(1, 2, None))                        # conversion timeout
    w.add(2_000_000, stlg.TEMP, stlg.body_temp(5, 0, 20.0))                        # channel without a name
    w.close()
    db = ingest.connect(tmp_path / "p.sqlite")
    ingest.import_log(db, tmp_path / "t.stlg")
    rows = db.execute("SELECT name, t_local_us, value FROM signals ORDER BY t_local_us, name").fetchall()
    assert rows == [("temp_motor_case", 1_000_000, 41.24), ("temp_5", 2_000_000, 20.0),
                    ("temp_motor_case", 2_000_000, None)]                          # invalid kept as NULL
    st = db.execute("SELECT status FROM records WHERE rtype=? ORDER BY idx", (stlg.TEMP,)).fetchall()
    assert [r[0] for r in st] == ["ok", "timeout", "ok"]


def test_stlg_corrupt_block_is_counted_and_skipped(tmp_path):
    _write(tmp_path / "b.stlg")
    raw = bytearray((tmp_path / "b.stlg").read_bytes())
    second = raw.find(b"BK", raw.find(b"BK") + stlg.BLK_HDR.size)   # header of block 1
    raw[second + stlg.BLK_HDR.size + 7] ^= 0x01     # one bit flipped inside block 1's payload
    (tmp_path / "b.stlg").write_bytes(bytes(raw))
    _meta, recs, rep = stlg.read(tmp_path / "b.stlg")
    assert rep.blocks_corrupt == 1 and rep.block_seq_gaps == 1 and 0 < rep.records < 3000


def test_stlg_power_loss_truncation_is_reported(tmp_path):
    _write(tmp_path / "c.stlg")
    raw = (tmp_path / "c.stlg").read_bytes()
    (tmp_path / "c.stlg").write_bytes(raw[:-100])   # last block cut short
    _meta, _recs, rep = stlg.read(tmp_path / "c.stlg")
    assert rep.truncated_tail_bytes > 0 and rep.blocks_corrupt == 0


def test_stlg_full_storage_drops_and_counts(tmp_path):
    w = _write(tmp_path / "d.stlg", n=3000, capacity=20_000)
    assert w.storage_full and w.dropped_storage > 0 and w.records + w.dropped_storage == 3000
    assert (tmp_path / "d.stlg").stat().st_size <= 20_000


# ---- telematics node -------------------------------------------------------------------------
def _node(tmp_path, **kw):
    w = stlg.Writer(tmp_path / "n.stlg", {"run_id": "N"}, 8 * 1024 * 1024)
    sup = Supervisor(SupervisorConfig(), speed_hold_policy(6.0, 1.5, 1.5, 10.0, 2.0))
    return TelematicsNode(NodeConfig(log_queue_capacity=50, log_drain_per_s=1000.0), LocalClock(), w,
                          SimLink(**kw.pop("link", {})), sup, "N", **kw), w


def test_flash_stall_drops_records_but_never_blocks_receive(tmp_path):
    node, w = _node(tmp_path, flash_stalls=((0.0, 1.0),))
    frame = bytes(8)
    for k in range(200):                              # 200 frames in 0.2 s while the writer is stalled
        node.on_can(k * 0.001, 0x7FF, frame)
        node.service(k * 0.001, 0.001)
    assert node.c["rx_frames"] == 200                 # every frame was received and timestamped
    assert node.c["log_dropped_queue"] == 150 and len(node.q) == 50
    node.close(2.0)
    assert w.records == 51                            # 50 queued + the final counters record


def test_uplink_backlog_is_bounded_and_flagged(tmp_path):
    node, _w = _node(tmp_path, link={"outages": ((0.0, 30.0),)})
    t = 0.0
    while t < 31.0:
        node.service(t, 0.01)
        t = round(t + 0.01, 6)
    msgs = [json.loads(p) for _t, _top, p in node.link.broker]
    assert node.c["uplink_dropped"] == 59 - 30       # 59 messages during the outage, 30 kept
    assert sum(m["replayed"] for m in msgs) == 30 and not msgs[-1]["replayed"]
    assert all(m["utc"] is None and m["utc_q"] == "none" for m in msgs)   # no PPS yet: UTC unknown, not 0


# ---- clocks ----------------------------------------------------------------------------------
def test_utc_estimator_quality_and_holdover_bound():
    clk, pps = LocalClock(), PpsModel()
    est = UtcEstimator()
    for te, u in pps.edges(0.0, 10.5):
        est.add_edge(clk.local(te), u)
    t_true = 10.2
    u, q, _ = est.utc(clk.local(t_true))
    assert q == "pps" and abs(u - (pps.utc_at_true_zero + t_true)) < 1e-6
    t_true = 25.0                                     # 15 s after the last edge
    u, q, bound = est.utc(clk.local(t_true))
    assert q == "holdover" and abs(u - (pps.utc_at_true_zero + t_true)) <= bound
    u, q, _ = UtcEstimator().utc(1.0)                 # no edges: unknown, not zero
    assert q == "none" and math.isnan(u)


# ---- pit -------------------------------------------------------------------------------------
def test_live_validation_rejects_with_reason():
    good = {"schema": "sem.telemetry.v1", "run_id": "R", "seq": 1, "t_local_ms": 5, "utc": None, "utc_q": "none",
            "ctrl": {"state": "READY", "vbus_V": 48.0}, "replayed": False}
    assert ingest.validate_live(json.dumps(good).encode())[1] is None
    bad = dict(good, ctrl={"state": "READY", "vbus_V": float("nan")})
    assert "vbus_V" in ingest.validate_live(json.dumps(bad).encode())[1]
    assert "unknown state" in ingest.validate_live(json.dumps(dict(good, ctrl={"state": "FLYING"})).encode())[1]
    assert "not JSON" in ingest.validate_live(b'{"schema": "sem.tel')[1]
    assert "seq" in ingest.validate_live(json.dumps(dict(good, seq="1")).encode())[1]


def test_live_ingest_deduplicates_replays(tmp_path):
    db = ingest.connect(tmp_path / "p.sqlite")
    m = {"schema": "sem.telemetry.v1", "run_id": "R", "seq": 3, "t_local_ms": 5, "utc": None, "utc_q": "none",
         "ctrl": {}, "replayed": False}
    broker = [(1.0, "sem/car/telemetry", json.dumps(m).encode()),
              (9.0, "sem/car/telemetry", json.dumps(dict(m, replayed=True)).encode())]
    rep = ingest.ingest_live(db, broker, "sem/car/telemetry")
    assert rep["stored"] == 1 and rep["duplicates"] == 1
