"""Wheel edge estimator, receive-only node, v4 live validation, log import and V x I energy (host)."""
import inspect
import json
import math

import pytest

from host.pit import energy, ingest
from host.telematics import stlg
from host.telematics.clocks import LocalClock
from host.telematics.controller_adapter import SimFixtureAdapter
from host.telematics.node import NodeConfig, SimLink, TelematicsNode, meta_fields
from host.telematics.wheel import FLAG_HEARTBEAT, FLAG_LINE_HIGH, EdgeAccumulator, EdgeRecord, WheelConfig, WheelEstimator
from protocol.generated import semmc_protocol as proto

CFG = WheelConfig(circumference_m=1.6, ppr=8)          # pitch 0.2 m


def _feed(est, recs):
    out = []
    for r in recs:
        out += est.feed(r)
    return out


def test_speed_over_complete_edge_intervals_is_exact():
    acc, est = EdgeAccumulator(0), WheelEstimator(CFG, "w")
    out = []
    period = 40_000                                     # 0.2 m / 0.04 s = 5 m/s
    for k in range(1, 41):
        acc.edge(k * period)
        if k % 3 == 0:
            out += est.feed(acc.take(k * period + 5, line_high=True))
    sp = [m for m in out if m.signal == "wheel.w.speed"]
    assert all(math.isclose(m.value, 5.0, rel_tol=1e-12) for m in sp)
    first = sp[0]                                        # first record: its own edges only, (n - 1) intervals
    assert first.t_sample_us == period + period and first.t_unc_us == period + 2
    later = sp[1]                                        # chained: from the previous record's last edge
    assert later.t_sample_us == 3 * period + (3 * period) // 2
    dist = [m for m in out if m.signal == "wheel.w.distance"][-1]
    assert math.isclose(dist.value, 39 * 0.2) and dist.validity == "valid"


def test_a_lost_record_loses_no_distance_but_an_overrun_makes_it_a_lower_bound():
    est = WheelEstimator(CFG, "w")
    out = _feed(est, [EdgeRecord(100_000, 0, 5, 80_000, 5, FLAG_LINE_HIGH, 0, 0),
                      EdgeRecord(300_000, 0, 5, 80_000, 15, FLAG_LINE_HIGH, 2, 0)])   # record 1 (5 edges) lost
    d = [m for m in out if m.signal.endswith("distance")]
    assert math.isclose(d[-1].value, 15 * 0.2) and d[-1].validity == "valid" and est.lost_records == 1
    sp = [m for m in out if m.signal.endswith("speed")]
    assert len(sp) == 2 and math.isclose(sp[1].value, 4 * 0.2 / 0.08)    # chain broken: own edges only
    out = est.feed(EdgeRecord(400_000, 0, 3, 40_000, 18, FLAG_LINE_HIGH | 0x02, 3, 2))
    d = [m for m in out if m.signal.endswith("distance")][0]
    assert d.validity == "unverified" and "lower bound" in d.provenance


def test_no_edge_is_no_evidence_with_a_bound_and_standstill_needs_the_line_held_active():
    est = WheelEstimator(CFG, "w")                       # active low: line_high False = magnet under the sensor
    assert _feed(est, [EdgeRecord(50_000, 0, 0, 0, 0, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 0, 0)])[0].validity == \
        "no_evidence"                                    # never an edge: nothing known
    _feed(est, [EdgeRecord(1_000_000, 0, 4, 120_000, 4, FLAG_LINE_HIGH, 1, 0)])
    assert _feed(est, [EdgeRecord(1_050_000, 0, 0, 0, 4, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 2, 0)]) == []  # between edges
    m = _feed(est, [EdgeRecord(2_000_000, 0, 0, 0, 4, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 3, 0)])[0]
    assert m.validity == "no_evidence" and m.value is None and math.isclose(m.upper, 0.2 / 1.0)
    # line low (magnet held under the sensor) for 2 s after a working sensor: standstill, 0 m/s with the bound
    _feed(est, [EdgeRecord(2_100_000, 0, 1, 0, 5, 0, 4, 0)])
    for k, t in enumerate(range(2_500_000, 4_700_000, 500_000)):   # held active from 2.1 s
        out = est.feed(EdgeRecord(t, 0, 0, 0, 5, FLAG_HEARTBEAT, 5 + k, 0))
    assert out[0].validity == "valid" and out[0].value == 0.0 and "standstill" in out[0].provenance


def _node(tmp_path, **kw):
    cfg = NodeConfig(wheel=CFG, wheel_channels=("w0",), **kw)
    a = SimFixtureAdapter()
    w = stlg.Writer(tmp_path / "r.stlg", meta_fields(cfg, a, "R-B0001", "R", 1), cfg.storage_bytes)
    return TelematicsNode(cfg, LocalClock(), w, SimLink(), a, "R-B0001", boot=1), w


def test_node_has_no_transmit_path():
    names = {n for n, _ in inspect.getmembers(TelematicsNode, inspect.isfunction)}
    assert not names & {"supervisor_tick", "tick", "transmit", "send_frame", "tx"}
    src = inspect.getsource(TelematicsNode)
    assert "supervisor" not in src.lower().replace("no supervisor", "")
    sig = inspect.signature(TelematicsNode.__init__)
    assert "supervisor" not in sig.parameters


def test_node_logs_raw_frames_and_reports_missing_as_null(tmp_path):
    node, w = _node(tmp_path, log_queue_capacity=40)
    data, _s, _i = proto.encode("ctrl_motion", {"speed_mech_rad_s": 10.0, "iq_A": 1.0, "vbus_V": 48.0}, 0)
    for k in range(60):                                  # more frames than the queue holds before the writer runs
        node.on_can(0.001 * k, proto.MESSAGES["ctrl_motion"]["id"], data)
    assert node.c["log_dropped_queue"] == 60 + 1 - 40 and node.c["queue_high_water"] == 40
    node.service(0.5, 0.5)
    msg = node.message(0.5)
    m, why = ingest.validate_live(json.dumps(msg).encode())
    assert why is None, why
    assert msg["m"]["ctrl.dc_current"]["q"] == "missing" and msg["m"]["ctrl.dc_current"]["v"] is None
    assert msg["m"]["ctrl.dc_voltage"]["q"] == "stale"   # last frame 0.44 s ago
    node.close(1.0)
    _meta, recs, rep = stlg.read(w.path)
    kinds = [r[3] for r in recs]
    assert kinds[0] == stlg.BOOT and stlg.CAN2 in kinds and kinds[-1] == stlg.COUNTERS2
    # 21 frames, then the record task's wheel record, found the queue full before the writer ran
    assert recs[-1][4]["log_dropped_queue"] == node.c["log_dropped_queue"] == 22
    assert recs[-1][4]["log_records"] == len(recs)


def _v4(**kw):
    m = {"schema": "sem.telemetry.v4", "run_id": "R", "boot": 1, "seq": 0, "t_local_ms": 10, "utc": None,
         "utc_q": "none", "utc_err_s": None, "replayed": False, "adapter": {"id": "x", "fixture": True, "silent_ms": None},
         "m": {"ctrl.dc_voltage": {"v": 48.0, "u": "V", "q": "valid", "age_ms": 12, "seq": 4, "ts": "rx"}},
         "counters": {"rx_frames": 3}}
    m.update(kw)
    return json.dumps(m).encode()


def test_v4_validation():
    assert ingest.validate_live(_v4())[1] is None
    bad = {
        "unit": {"ctrl.dc_voltage": {"v": 48.0, "u": "mV", "q": "valid", "age_ms": 1, "seq": None, "ts": "rx"}},
        "value with q stale": {"ctrl.dc_voltage": {"v": 0.0, "u": "V", "q": "stale", "age_ms": 900, "seq": None,
                                                   "ts": "rx"}},
        "outside": {"ctrl.dc_voltage": {"v": 480.0, "u": "V", "q": "valid", "age_ms": 1, "seq": None, "ts": "rx"}},
        "age_ms": {"ctrl.dc_voltage": {"v": 48.0, "u": "V", "q": "valid", "age_ms": 5000, "seq": None, "ts": "rx"}},
        "registry": {"ctrl.torque_request": {"v": 1.0, "u": "N*m", "q": "valid", "age_ms": 1, "seq": None, "ts": "rx"}},
    }
    for what, mm in bad.items():
        assert ingest.validate_live(_v4(m=mm))[1] is not None, what
    assert "'sup' block" in ingest.validate_live(_v4(sup={"torque_Nm": 1.0}))[1]
    assert "boot" in ingest.validate_live(_v4(boot=-1))[1]


def test_import_is_idempotent_and_energy_reports_missing_intervals(tmp_path):
    node, w = _node(tmp_path)
    cid_m, cid_c = proto.MESSAGES["ctrl_motion"]["id"], proto.MESSAGES["ctrl_currents"]["id"]
    valid = {k: True for k in ("v_speed", "v_ia", "v_ib", "v_ic", "v_vbus", "v_ibatt", "v_t_fet", "v_t_motor",
                               "v_throttle", "v_sup_req", "v_sup_limits", "v_hall")}
    seq = 0
    for k in range(1, 1001):                              # 10 s at 100 Hz: 50 V, 2 A = 100 W, silent 4-5 s
        t = k * 0.01
        if k % 10 == 0:
            d, _s, _i = proto.encode("ctrl_validity", valid, seq % 256)
            node.on_can(t, proto.MESSAGES["ctrl_validity"]["id"], d)
        if not 4.0 <= t < 5.0:
            d, _s, _i = proto.encode("ctrl_motion", {"speed_mech_rad_s": 1.0, "iq_A": 1.0, "vbus_V": 50.0}, seq % 256)
            node.on_can(t, cid_m, d)
            d, _s, _i = proto.encode("ctrl_currents", {"id_A": 0.0, "ibatt_A": 2.0, "measured_mask": 7,
                                                       "reconstructed_mask": 0, "kcl_available": True, "reserved": 0,
                                                       "kcl_residual_A": 0.0}, seq % 256)
            node.on_can(t, cid_c, d)
            seq += 1
        node.service(t, 0.01)
    node.close(10.0)
    db = ingest.connect(tmp_path / "pit.sqlite")
    rep = ingest.import_log(db, w.path)
    again = ingest.import_log(db, w.path)
    assert rep["new_measurements"] > 0 and again["new_records"] == 0 and again["new_measurements"] == 0
    assert rep["final_counters"] and rep["accounting"]["missing_from_file"] == 0
    e = energy.vi_energy(db, "R-B0001")
    assert e["boundary"] == "controller_input" and len(e["missing_intervals"]) >= 1
    assert any(3.9 < a < 4.1 and 4.9 < b < 5.1 for a, b, _c in
               [(x - LocalClock().local(0), y - LocalClock().local(0), c) for x, y, c in e["missing_intervals"]])
    assert math.isclose(e["energy_J"], 100.0 * e["covered_s"], rel_tol=1e-9)
    assert e["missing_energy_bound_J"] == pytest.approx(100.0 * e["missing_s"])
    assert energy.vi_energy(db, "R-B0001", "battery")["energy_J"] is None   # no battery monitor: no battery energy
