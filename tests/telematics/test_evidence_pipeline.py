"""The evidence chain on simulated sessions: log -> import -> evidence rows -> review -> receipts (HOST-TESTED).

Every session here is a HOST SIMULATION (host/telematics/sim_session.py): the node is the host model of the
firmware, the controller a Python stand-in. The tests show what the pit software does with such logs; they are not
evidence about the vehicle, the firmware on hardware or a real network.
"""
import json

import pytest

from host.assurance import review, verdicts
from host.pit import ingest
from host.telematics import evidence, sim_session
from host.telematics.sim_vehicle import Faults
from tools import run_vehicle_experiment as X

PARAMS = dict(X.SIM_PARAMS)


def _session(tmp_path, faults=Faults(), duration=20.0, **kw):
    sim = sim_session.simulate(tmp_path, faults, duration, **kw)
    db = ingest.connect(tmp_path / "pit.sqlite")
    reps = [ingest.import_log(db, p) for _rid, p in sim["runs"]]
    return sim, db, reps


def test_every_measurement_has_one_evidence_row_with_raw_bytes_and_schema_version(tmp_path):
    _sim, db, reps = _session(tmp_path)
    rid = reps[0]["run_id"]
    n_meas = db.execute("SELECT COUNT(*) FROM measurements WHERE run_id=?", (rid,)).fetchone()[0]
    n_ev = db.execute("SELECT COUNT(*) FROM evidence WHERE run_id=?", (rid,)).fetchone()[0]
    assert n_meas == n_ev > 1000
    rows = db.execute("SELECT raw, state, schema_version, source FROM evidence_records WHERE run_id=? AND "
                      "signal='ctrl.dc_voltage' ORDER BY t_rx_us", (rid,)).fetchall()
    # before the first ctrl_validity frame the voltage is not confirmed by its flag: SOURCE_UNVERIFIED, not VALID
    assert rows[0][1] == "SOURCE_UNVERIFIED" and rows[-1][1] == "VALID"
    assert all(len(bytes.fromhex(r[0])) == 8 and r[2] == 1 and r[3] == "controller" for r in rows)
    states = {s for (s,) in db.execute("SELECT DISTINCT state FROM evidence WHERE run_id=?", (rid,))}
    assert "VALID" in states and states <= set(evidence.states()) - {"STALE", "MISSING", "UNSUPPORTED"}
    streams = {s for (s,) in db.execute("SELECT stream FROM source_timing WHERE run_id=?", (rid,))}
    assert {"can:ctrl_motion", "imu", "gnss", "wheel:wheel_l"} <= streams
    t = json.loads(db.execute("SELECT report_json FROM source_timing WHERE run_id=? AND stream='can:ctrl_motion'",
                              (rid,)).fetchone()[0])
    assert t["lost"] == 0 and t["duplicates"] == 0 and t["latency"].startswith("not observable")
    assert ingest.import_log(db, _sim["runs"][0][1])["new_measurements"] == 0          # idempotent


def test_review_receipts_are_complete_and_the_data_class_is_never_vehicle_by_default(tmp_path):
    _sim, db, reps = _session(tmp_path, Faults(wheel_scale=((0, 10.0, 18.0, 0.85),)))
    rid = reps[0]["run_id"]
    res = review.run(db, rid, dict(PARAMS), wheel_pairs=X.PAIRS)
    assert res["data_class"] == "SIMULATED" and res["receipts"] > 0
    n = 0
    for (js,) in db.execute("SELECT snapshot_json FROM receipt_snapshots WHERE run_id=?", (rid,)):
        r = json.loads(js)
        assert verdicts.receipt_problems(r) == [], verdicts.receipt_problems(r)
        n += 1
    assert n > 0
    for (js,) in db.execute("SELECT receipt_json FROM receipts WHERE run_id=? AND kind='localization'", (rid,)):
        j = json.loads(js)
        assert j["changed"]["verdict"] == "AMBIGUOUS" and all(o["relation"] in j["changed"]["basis"]
                                                              for o in j["observations"])
    assert review.data_class({"kind": "HOST SIMULATION - x"}) == "SIMULATED"
    assert review.data_class({"kind": "BENCH - NUCLEO"}) == "BENCH"
    assert review.data_class({}) == "UNKNOWN"
    assert review.data_class({"kind": "a drive on the vehicle"}) == "UNKNOWN"     # VEHICLE only when stated first


def test_unsupported_parameters_make_relations_insufficient_not_guessed(tmp_path):
    _sim, db, reps = _session(tmp_path)
    res = review.run(db, reps[0]["run_id"], {}, write=False)
    assert res["parameters"]["drivetrain.gear_ratio"] is None
    tl = res["timeline"]
    assert all(r != "CONSISTENT" and r != "INCONSISTENT" for _t, r in tl["B2:wheel_l"])
    assert all(r != "CONSISTENT" and r != "INCONSISTENT" for _t, r in tl["A1"])


def test_local_logging_continues_through_a_network_outage(tmp_path):
    """The uplink is down for the whole session: the pit gets no live message, the log is complete and the review
    runs from the log alone."""
    sim, db, reps = _session(tmp_path, link_outages=((0.0, 1e9),))
    rep = reps[0]
    link = sim["links"][rep["run_id"]]
    assert link.broker == []
    acc = rep["accounting"]
    assert rep["final_counters"] and acc["missing_from_file"] == 0 and acc["dropped_queue"] == 0
    last = rep["last_counters"]
    assert last["uplink_sent"] == 0 and last["uplink_dropped"] > 0 and last["wheel_records"] > 0
    assert review.run(db, rep["run_id"], dict(PARAMS), write=False)["counts"]["results"].get("CONSISTENT", 0) > 0


def test_a_storage_stall_is_counted_and_reviewed_as_a_recorder_event(tmp_path):
    _sim, db, reps = _session(tmp_path, duration=25.0, storage_stalls=((10.0, 12.0),))
    rep = reps[0]
    assert rep["last_counters"]["log_dropped_queue"] > 0                 # dropped and counted, not hidden
    res = review.run(db, rep["run_id"], dict(PARAMS), write=False)
    cc = [c for c in res["common_cause"] if c["verdict"] == "SUPPORTED"]
    assert cc and all("unit:recorder" in c["statement"] for c in cc)


def test_flood_of_frames_keeps_the_units_own_records(tmp_path):
    """Host model of the firmware's own-record reserve (the C test is test_can_flood in test_tm.c)."""
    import random
    from host.telematics import stlg
    from host.telematics.clocks import LocalClock
    from host.telematics.controller_adapter import SimFixtureAdapter
    from host.telematics.node import NodeConfig, SimLink, TelematicsNode, meta_fields
    from host.telematics.wheel import WheelConfig
    cfg = NodeConfig(wheel=WheelConfig(1.5, 8), log_drain_per_s=500.0)
    ad = SimFixtureAdapter()
    w = stlg.Writer(tmp_path / "f.stlg", meta_fields(cfg, ad, "F-B0001", "F", 1), cfg.storage_bytes)
    node = TelematicsNode(cfg, LocalClock(), w, SimLink(), ad, "F-B0001", boot=1)
    rnd = random.Random(7)
    t, dt = 0.0, 0.01
    for _k in range(300):
        t = round(t + dt, 6)
        for j in range(40):                                              # 4,000 frames per second
            node.on_can(t + j * 0.00025, rnd.randrange(0x800), bytes(rnd.randrange(256) for _ in range(8)))
        node.service(t, dt)
    node.close(t)
    c = node.c
    assert c["can_not_logged"] > 0 and c["log_dropped_queue"] == 0 and c["rx_frames"] == 12_000
    _m, recs, _rr = stlg.read(tmp_path / "f.stlg")
    assert sum(1 for r in recs if r[3] == stlg.WHEEL_EDGES) == c["wheel_records"] > 0


@pytest.fixture(scope="module")
def experiments(tmp_path_factory):
    out = tmp_path_factory.mktemp("vehicle_experiments")
    return [X.run_variant(v, out) for v in X.VARIANTS]


def test_simulated_protocol_prechecks_pass_and_say_so(experiments):
    for r in experiments:
        assert r["data_class"] == "SIMULATED"
        assert r["pass"], [c for c in r["checks"] if not c["pass"]]
    exps = {r["experiment"] for r in experiments}
    assert exps == {"EXP-01", "EXP-02", "EXP-03", "EXP-04"}
    md = X.render(experiments)
    assert "SIMULATED" in md and "not the vehicle" in md
    roles = {c["role"] for r in experiments for c in r["checks"]}
    assert {"signature", "falsifier", "limitation"} <= roles


def test_exp01_separates_a_corrupted_wheel_from_a_real_slowdown(experiments):
    by = {r["variant"]: r for r in experiments}
    assert any(k == "localization:wheel.wheel_l.speed" for k in by["wheel_corruption"]["ambiguous"])
    assert not by["real_slowdown"]["ambiguous"]
