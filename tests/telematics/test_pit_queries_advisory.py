"""Pit evidence queries, advisory energy, the pulse-to-database chain and the CSIA shadow boundary (HOST-TESTED).

All inputs are host simulations. The tests show the pit software's behaviour on them; nothing here is a bench or
vehicle result.
"""
import contextlib
import io
import json
import subprocess
import sys

import pytest

from host.assurance import csia_boundary
from host.pit import advisory, energy, ingest, queries
from host.telematics import sim_session
from host.telematics.sim_vehicle import Faults
from tools import pit_query, run_bench_chain


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("q")
    sim = sim_session.simulate(d, Faults(gnss_outage=((20.0, 23.0),)), 40.0)
    db = ingest.connect(d / "pit.sqlite")
    for _rid, p in sim["runs"]:
        ingest.import_log(db, p)
    return db, sim["runs"][0][0], sim["clock"], d / "pit.sqlite"


def test_aligned_rows_carry_states_and_never_fill_a_gap(run):
    db, rid, clock, _p = run
    t_out = int(clock.local(21.5) * 1e6)
    rows = queries.aligned(db, rid, ["gnss.speed", "wheel.wheel_l.speed"], t_out - 3_000_000, t_out, 0.5)
    by_t = {r["t_us"]: r for r in rows}
    inside = by_t[t_out]["gnss.speed"]
    assert inside["state"] == "INVALID" and inside["value"] is None             # no fix: invalid, not 0, not old
    assert by_t[t_out]["wheel.wheel_l.speed"]["state"] == "VALID"
    assert rows[0]["gnss.speed"]["state"] == "VALID"


def test_intervals_list_missing_and_invalid_spans(run):
    db, rid, clock, _p = run
    iv = queries.intervals(db, rid, "gnss.speed")
    assert iv[0]["state"] == "MISSING"
    bad = [x for x in iv if x["state"] == "INVALID"]
    assert len(bad) == 1 and abs(bad[0]["t0_us"] / 1e6 - clock.local(20.0)) < 0.15 and \
        abs(bad[0]["t1_us"] / 1e6 - clock.local(23.0)) < 0.15
    never = queries.intervals(db, rid, "ctrl.torque_reference")
    assert never[0]["state"] == "MISSING" and "never" in never[0]["reason"]


def test_window_and_pre_post(run):
    db, rid, clock, _p = run
    t = int(clock.local(20.0) * 1e6)
    w = queries.window(db, rid, t, 1.0, 1.0, ["gnss.speed"])
    states = {r["state"] for r in w["evidence"]}
    assert states == {"VALID", "INVALID"} and all(r["raw"] for r in w["evidence"])
    assert "can:ctrl_motion" in w["source_timing"]
    pp = queries.pre_post(db, rid, "gnss.speed", t, 1.0, 1.0)
    assert pp["before"]["n"] >= 9 and pp["after"]["n"] == 0 and pp["after"]["not_admissible"] >= 9


def test_query_cli_prints_states_not_numbers_for_missing_values(run):
    _db, rid, clock, path = run
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pit_query.main(["--db", str(path), "aligned", "--run", rid, "--signal", "gnss.speed", "--from",
                        f"{clock.local(21.0):.3f}", "--to", f"{clock.local(22.0):.3f}", "--step", "0.5"])
    lines = [ln for ln in buf.getvalue().splitlines() if not ln.startswith("#")]
    assert lines[0] == "t_s\tgnss.speed" and all(ln.endswith("INVALID") for ln in lines[1:])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pit_query.main(["--db", str(path), "gaps", "--run", rid, "--signal", "gnss.speed"])
    assert "INVALID" in buf.getvalue() and "MISSING" in buf.getvalue()


def test_advisory_energy_is_labelled_and_refuses_without_evidence(run):
    db, rid, _clock, _p = run
    rows = advisory.rolling(db, rid, "wheel_l", 10.0, 5.0)
    assert rows and all(r["advisory_only"] for r in rows)
    assert any(r["Wh_per_km"] is not None for r in rows)
    assert all(r["Wh_per_km"] is None and r["reason"] for r in rows[:1])               # before any distance
    tab = advisory.speed_table(db, rid, "wheel_l")
    adv = advisory.cruise_advice(tab, 50.0)
    assert adv["advisory_only"] and adv["band_mps"] and "not a setpoint" in adv["reason"]
    e = energy.vi_energy(db, rid)
    rem = advisory.remaining(e["energy_Wh"])
    assert rem["nominal_Wh"] == 480.0 and "NOMINAL" in rem["basis"] and "team-reported" in rem["basis"]
    assert advisory.cruise_advice([], 50.0)["band_mps"] is None
    # no wheel parameters: no distance, so no Wh/km at all
    assert all(r["Wh_per_km"] is None for r in advisory.rolling(db, rid, "wheel_nonexistent", 10.0, 5.0))


def test_advisory_module_has_no_way_to_reach_the_vehicle():
    import ast
    import inspect
    src = inspect.getsource(advisory)
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)} | \
            {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not names & {"socket", "can", "paho", "serial", "SimLink", "MqttLink"}


def test_bench_chain_host_mode_passes(tmp_path, telematics_build):
    r = subprocess.run([sys.executable, "tools/run_bench_chain.py", "--out", str(tmp_path / "chain"), "--build",
                        str(telematics_build)], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BENCH CHAIN" in r.stdout and "(SIMULATED): PASS" in r.stdout
    for c in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"):
        assert f"PASS {c}" in r.stdout
    assert run_bench_chain.SEGMENTS[1][2] == 0.0                                     # a stop is part of the train
    assert (tmp_path / "chain" / "import").glob("*_speed_distance.png")


def test_minimal_rehearsal_runs_the_bench_command_and_the_wrong_boot_fails(tmp_path, telematics_build):
    """The rehearsal reads the simulated DUMP text back with the bench's own arguments (no pulse count): the data class
    stays SIMULATED, the review stores complete receipts, and the session after the power cycle (no pulses) fails."""
    out = tmp_path / "m"
    assert run_bench_chain.main(["--rehearse-minimal", "--out", str(out), "--build", str(telematics_build)]) == 0
    res = json.loads((out / "chain.json").read_text())
    ids = [c["id"] for c in res["checks"]]
    assert res["data_class"] == "SIMULATED" and res["boot"] == 1 and len(res["sessions"]) == 2
    assert not any(i.startswith("C1 ") for i in ids)                  # the bench cannot count its pulses
    assert "C4 distance = the log's edge total x pitch" in ids and res["pass"]
    assert res["review"]["receipts"] > 0 and res["review"]["problems"] == []
    assert res["review"]["timing_policy"].startswith("assumed timestamp bounds accepted: simulated")
    assert (out / res["plot"]).exists()
    cap = out / "capture_M3_SIMULATED.txt"
    text = cap.read_text()
    assert text.startswith("DUMP BEGIN 256") and text.rstrip().endswith("DUMP END")
    again = ["--uart-capture", str(cap), "--pulse-hz", "100", "--circumference", "0.1", "--ppr", "1"]
    assert run_bench_chain.main(again + ["--boot", "2", "--out", str(tmp_path / "b2")]) == 1
    b2 = json.loads((tmp_path / "b2" / "chain.json").read_text())
    assert not next(c for c in b2["checks"] if c["id"].startswith("C2 median"))["pass"]
    assert run_bench_chain.main(again + ["--boot", "7", "--out", str(tmp_path / "b7")]) == 1


def test_bench_stop_check_needs_a_stop_and_rejects_a_zero_speed():
    """C3 on a bench log: every sample without edges must be UNKNOWN (bounded after the first edge), never 0."""
    ok = [(1, None, "no_evidence", None), (2, 10.0, "valid", None), (3, None, "no_evidence", 1.0)]
    assert run_bench_chain.stop_check(ok)["pass"]
    assert not run_bench_chain.stop_check(ok + [(4, 0.0, "valid", None)])["pass"]              # a speed of 0
    assert not run_bench_chain.stop_check(ok + [(4, None, "no_evidence", None)])["pass"]      # unbounded after edges
    assert not run_bench_chain.stop_check(ok[:2])["pass"]                                      # no stop in the log


def test_csia_boundary_passes_only_valid_evidence_and_withholds_trust(run):
    db, rid, _clock, _p = run
    r = csia_boundary.run(db, rid, None, 10.0)
    assert r["verdict"] == "UNSUPPORTED" and "wheel radius" in r["reason"]
    pytest.importorskip("numpy")
    try:
        r = csia_boundary.run(db, rid, 1.5 / 6.283185307, 10.0, False)
    except ImportError as e:                                       # the pinned core is fetched by tools/fetch_csia.py
        pytest.skip(str(e))
    assert r["advisory_only"] and set(r["verdicts"]) <= {"SUPPORTED", "AMBIGUOUS", "UNSUPPORTED"}
    assert r["gate"]["withheld"].get("gnss.speed", {}).get("INVALID", 0) >= 25      # the outage did not cross
    assert "iq_ref" in r["gate"]["not_passed"] and "iq_ref" not in r["gate"]["passed"]
    assert set(r["withheld_numbers"]) == {"trust", "aggregate_trust", "lambdas"}
    assert r["data_class"] == "SIMULATED" and r["gate"]["passed"].get("rotor", 0) > 0
    # stated as a bench run, the controller, GNSS and IMU samples have only assumed bounds and do not cross
    import json
    meta = json.loads(db.execute("SELECT meta_json FROM runs WHERE run_id=?", (rid,)).fetchone()[0])
    db.execute("UPDATE runs SET meta_json=? WHERE run_id=?", (json.dumps({**meta, "kind": "BENCH - relabel"}), rid))
    try:
        b = csia_boundary.run(db, rid, 1.5 / 6.283185307, 10.0, False)
    finally:
        db.execute("UPDATE runs SET meta_json=? WHERE run_id=?", (json.dumps(meta), rid))
    assert b["data_class"] == "BENCH" and "rotor" not in b["gate"]["passed"]
    assert b["gate"]["withheld"]["ctrl.motor_speed"].get("TIMING_UNCERTAIN", 0) > 0
    assert b["gate"]["passed"].get("wheel_l", 0) > 0                     # measured bounds still cross
    for x in r["transitions"]:
        assert "trust" not in x and not any(w in x["statement"].lower() for w in ("fault", "failed"))


def test_csia_boundary_withholds_power_inputs_without_a_torque_constant(run):
    db, rid, _clock, _p = run
    pytest.importorskip("numpy")
    try:
        r = csia_boundary.run(db, rid, 1.5 / 6.283185307, 10.0, False)
    except ImportError as e:
        pytest.skip(str(e))
    assert "p_dc" not in r["gate"]["passed"] and "iq" not in r["gate"]["passed"]
    assert r["gate"]["withheld"]["ctrl.phase_current_q"]["no torque constant"] > 0
    assert r["adapter_defaults"]["kt_Nm_per_A"] == 0.06                  # listed as a default, not used for E6
    k = csia_boundary.run(db, rid, 1.5 / 6.283185307, 10.0, False, kt_Nm_per_A=0.2)
    assert k["gate"]["passed"].get("p_dc", 0) > 0 and "kt_Nm_per_A" not in k["adapter_defaults"]


def test_csia_clean_run_case_reproduces_and_isolates_the_power_balance(tmp_path):
    pytest.importorskip("numpy")
    from tools import csia_disagreement_case as K
    try:
        a = K.clean_run(tmp_path / "case")
    except ImportError as e:
        pytest.skip(str(e))
    assert a["ticks"] == 550 and a["explanations"]["DISAGREE_AMBIGUOUS"] == 328
    assert a["failing"] == {"E6_power_balance": 328}
    pt = K.steady_point(6.5)
    e, lam = K.minimal(pt)                                  # constant, simultaneous inputs: no timing effect
    assert e == "DISAGREE_AMBIGUOUS" and lam > 9.0
    now = K.boundary_now(tmp_path / "case")
    assert "AMBIGUOUS" not in now["verdicts"]
