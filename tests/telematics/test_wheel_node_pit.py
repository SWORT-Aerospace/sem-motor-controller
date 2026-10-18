"""Wheel edge estimator, receive-only node, v4 live validation, log import and V x I energy (host)."""
import inspect
import json
import math
import pathlib

import pytest

from host.pit import energy, ingest
from host.telematics import signals, stlg
from host.telematics.clocks import LocalClock
from host.telematics.controller_adapter import SimFixtureAdapter
from host.telematics.node import NodeConfig, SimLink, TelematicsNode, meta_fields
from host.telematics.wheel import (FLAG_HEARTBEAT, FLAG_LINE_HIGH, EdgeAccumulator, EdgeRecord, WheelConfig,
                                   WheelEstimator, WheelGroup)
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


def test_no_edge_is_no_evidence_and_a_held_line_never_proves_standstill():
    est = WheelEstimator(CFG, "w")                       # active low: line_high False = magnet under the sensor
    assert _feed(est, [EdgeRecord(50_000, 0, 0, 0, 0, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 0, 0)])[0].validity == \
        "no_evidence"                                    # never an edge: nothing known
    _feed(est, [EdgeRecord(1_000_000, 0, 4, 120_000, 4, FLAG_LINE_HIGH, 1, 0)])
    assert _feed(est, [EdgeRecord(1_050_000, 0, 0, 0, 4, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 2, 0)]) == []  # between edges
    m = _feed(est, [EdgeRecord(2_000_000, 0, 0, 0, 4, FLAG_LINE_HIGH | FLAG_HEARTBEAT, 3, 0)])[0]
    assert m.validity == "no_evidence" and m.value is None and math.isclose(m.upper, 0.2 / 1.0)
    assert "only for a working sensor" in m.provenance and "line inactive" in m.provenance
    # the line held at the active level for a long time after a working sensor: still no evidence, never 0
    # (a magnet under a stopped wheel, a short to ground and a failed sensor read the same)
    _feed(est, [EdgeRecord(2_100_000, 0, 1, 0, 5, 0, 4, 0)])
    outs = [est.feed(EdgeRecord(t, 0, 0, 0, 5, FLAG_HEARTBEAT, 5 + k, 0))
            for k, t in enumerate(range(2_500_000, 30_000_000, 500_000))]
    sp = [x for o in outs for x in o if x.signal == "wheel.w.speed"]
    assert sp and all(x.validity == "no_evidence" and x.value is None for x in sp)
    assert "line active" in sp[-1].provenance


def _group(names=("w0", "w1", "w2"), active_high=False):
    return WheelGroup(WheelConfig(circumference_m=1.6, ppr=8, active_high=active_high), dict(enumerate(names)))


def _drive(g, until_us, period_us, lines, t_from=50_000, step=50_000, accs=None, nexts=None):
    """Run record periods up to until_us: channel ch has an edge every period_us[ch] (0: none), its line
    level is lines[ch]; returns (time, channel, state, measurements) per record, as the node does it."""
    accs = accs if accs is not None else {ch: EdgeAccumulator(ch) for ch in g.names}
    nexts = nexts if nexts is not None else {ch: t_from for ch in g.names}
    out = []
    for t in range(t_from, until_us + 1, step):
        recs = []
        for ch, acc in accs.items():
            while period_us[ch] and nexts[ch] <= t:
                acc.edge(nexts[ch])
                nexts[ch] += period_us[ch]
            recs.append(acc.take(t, line_high=lines[ch]))
        for r in recs:
            g.update(r)
        for r in recs:
            s, ref = g.classify(r.channel, t)
            out.append((t, r.channel, s, ref, g.estimate(r, s, ref)))
    return out, accs, nexts


def _speeds(rows, ch, t0=0):
    return [m for t, c, _s, _r, ms in rows if c == ch and t >= t0 for m in ms if m.signal.endswith(".speed")]


def test_stuck_low_while_another_wheel_turns_is_suspect_active():
    # w0 turns at 5 m/s (40 ms period); w1's signal is shorted to ground (line low = active level, no edges)
    g = _group()
    rows, _a, _n = _drive(g, 3_000_000, {0: 40_000, 1: 0, 2: 40_000}, {0: True, 1: False, 2: True})
    st1 = {t: s for t, c, s, _r, _m in rows if c == 1}
    assert st1[950_000] == "N" and st1[1_050_000] == "A"              # 1 s and 8 periods: suspect, not before
    sp = _speeds(rows, 1, 1_050_000)
    assert sp and all(m.validity == "invalid" and m.value is None and m.upper is None for m in sp)
    assert "stuck active" in sp[0].provenance and "(w0)" in sp[0].provenance
    assert g.episodes == {"A": 1, "I": 0}
    assert all(m.validity == "valid" for m in _speeds(rows, 0, 200_000))


def test_disconnected_or_stuck_high_while_another_wheel_turns_is_suspect_inactive():
    # w2 disconnected from the start (open wire: the pull-up holds the line at the inactive level) and w1 shorted
    # to the supply (the same level): electrically the same, both suspect inactive
    g = _group()
    rows, _a, _n = _drive(g, 2_000_000, {0: 40_000, 1: 0, 2: 0}, {0: True, 1: True, 2: True})
    assert {c: s for t, c, s, _r, _m in rows if t == 2_000_000} == {0: "M", 1: "I", 2: "I"}
    sp = _speeds(rows, 2, 1_100_000)
    assert sp and all(m.validity == "invalid" for m in sp) and "disconnected" in sp[0].provenance
    # an active-high sensor reads the same levels the other way round
    g = _group(active_high=True)
    rows, _a, _n = _drive(g, 2_000_000, {0: 40_000, 1: 0, 2: 0}, {0: False, 1: True, 2: False})
    assert {c: s for t, c, s, _r, _m in rows if t == 2_000_000} == {0: "M", 1: "A", 2: "I"}


def test_disconnection_mid_run_then_recovery():
    g = _group()
    per, lines = {0: 50_000, 1: 50_000, 2: 50_000}, {0: True, 1: True, 2: True}
    rows, accs, nexts = _drive(g, 2_000_000, per, lines)
    assert all(m.validity == "valid" for m in _speeds(rows, 1, 300_000))
    per[1] = 0                                                      # w1 pulled off at 2 s: no edges, line high
    rows2, accs, nexts = _drive(g, 4_000_000, per, lines, t_from=2_050_000, accs=accs, nexts=nexts)
    st = {t: s for t, c, s, _r, _m in rows2 if c == 1}
    assert st[2_300_000] == "S"                                     # not yet: could be a slow wheel
    assert st[3_100_000] == "I"                                     # 1 s of silence while w0 and w2 turn
    per[1], nexts[1] = 50_000, 4_050_000                            # reconnected
    rows3, _a, _n = _drive(g, 5_000_000, per, lines, t_from=4_050_000, accs=accs, nexts=nexts)
    assert {s for t, c, s, _r, _m in rows3 if c == 1 and t >= 4_300_000} == {"M"}
    assert all(m.validity == "valid" for m in _speeds(rows3, 1, 4_300_000))
    d = [m for t, c, _s, _r, ms in rows3 if c == 1 for m in ms if m.signal.endswith("distance")][-1]
    assert d.validity == "unverified" and "channel was suspect" in d.provenance   # edges may be missing


def test_everything_stopped_is_silent_with_no_evidence_whatever_the_lines():
    g = _group()
    per, lines = {0: 40_000, 1: 40_000, 2: 40_000}, {0: False, 1: True, 2: False}
    rows, accs, nexts = _drive(g, 1_000_000, per, lines)
    rows2, _a, _n = _drive(g, 20_000_000, {0: 0, 1: 0, 2: 0}, lines, t_from=1_050_000, accs=accs, nexts=nexts)
    assert {s for t, c, s, _r, _m in rows2 if t > 2_000_000} == {"S"}
    sp = [m for ch in range(3) for m in _speeds(rows2, ch, 2_000_000)]
    assert sp and all(m.validity == "no_evidence" and m.value is None for m in sp)
    assert g.episodes == {"A": 0, "I": 0}


def test_python_rule_equals_the_firmware_constants():
    import re
    from host.telematics import wheel
    h = (pathlib.Path(__file__).resolve().parents[2] / "telematics/firmware/include/tm_wheel.h").read_text()
    for name in ("MOVING_PERIODS", "MOVING_MIN_US", "SUSPECT_PERIODS", "SUSPECT_MIN_US", "MAX_PERIOD_US"):
        assert int(re.search(rf"#define TM_WHEEL_{name} (\d+)u", h).group(1)) == getattr(wheel, name), name


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
    # frames may fill the queue only up to its own-record reserve (1/8: 5 of 40): BOOT + 34 frames, 26 counted
    assert node.c["can_not_logged"] == 60 - 34 and node.c["queue_high_water"] == 35
    assert node.c["log_dropped_queue"] == 0 and node.c["rx_frames"] == 60
    node.service(0.5, 0.5)
    msg = node.message(0.5)
    m, why = ingest.validate_live(json.dumps(msg).encode())
    assert why is None, why
    assert msg["m"]["ctrl.dc_current"] == [None, "missing", None, None, None]
    assert msg["m"]["ctrl.dc_voltage"][:2] == [None, "stale"]   # last frame 0.44 s ago
    assert len(json.dumps(msg)) < 2000                          # compact entries
    node.close(1.0)
    _meta, recs, rep = stlg.read(w.path)
    kinds = [r[3] for r in recs]
    assert kinds[0] == stlg.BOOT and stlg.CAN2 in kinds and kinds[-1] == stlg.COUNTERS2
    # the record task's wheel records found room in the reserve: none of the unit's own records was dropped
    assert recs[-1][4]["log_dropped_queue"] == node.c["log_dropped_queue"] == 0
    assert recs[-1][4]["can_not_logged"] == 26 and sum(1 for k in kinds if k == stlg.CAN2) == 34
    assert any(k == stlg.WHEEL_EDGES for k in kinds)
    assert recs[-1][4]["log_records"] == len(recs)


def _v4(**kw):
    m = {"schema": "sem.telemetry.v4", "run_id": "R", "boot": 1, "seq": 0, "t_local_ms": 10, "utc": None,
         "utc_q": "none", "utc_err_s": None, "replayed": False, "adapter": {"id": "x", "fixture": True, "silent_ms": None},
         "registry": signals.REGISTRY_ID, "m": {"ctrl.dc_voltage": [48.0, "valid", 12, 4, "r"]},
         "counters": {"rx_frames": 3}}
    m.update(kw)
    return json.dumps(m).encode()


def test_v4_validation():
    assert ingest.validate_live(_v4())[1] is None
    bad = {
        "not an entry": {"ctrl.dc_voltage": {"v": 48.0, "q": "valid"}},
        "value with q stale": {"ctrl.dc_voltage": [0.0, "stale", 900, None, "r"]},
        "outside": {"ctrl.dc_voltage": [480.0, "valid", 1, None, "r"]},
        "age_ms": {"ctrl.dc_voltage": [48.0, "valid", 5000, None, "r"]},
        "registry": {"ctrl.torque_request": [1.0, "valid", 1, None, "r"]},
        "time reference": {"ctrl.dc_voltage": [48.0, "valid", 1, None, "x"]},
    }
    for what, mm in bad.items():
        assert ingest.validate_live(_v4(m=mm))[1] is not None, what
    assert "registry" in ingest.validate_live(_v4(registry="reg-000000000000"))[1]   # units unknown to this pit
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
