"""End-to-end SYNTHETIC co-simulation through both codecs, the C core and the plant."""
import math
import pathlib

import pytest

from host.telemetry_adapter.e2e import Scenario, run
from tools import config_tool as ct

ROOT = pathlib.Path(__file__).resolve().parents[2]
CFG = ct.load_yaml(ROOT / "config" / "vehicle.synthetic.yaml")


@pytest.fixture(scope="module")
def eco_run(build_dir):
    return run(Scenario(), build_dir, build_dir / "e2e")


def _first(steps, pred):
    return next((s for s in steps if pred(s)), None)


def test_all_controller_frames_decode(eco_run):
    assert eco_run.tx_frames, "controller sent nothing"
    bad = [f for f in eco_run.tx_frames if f[3]["status"] != "ok"]
    assert not bad, bad[:3]
    names = {f[1] for f in eco_run.tx_frames}
    for required in ("ctrl_status", "ctrl_cmd_trace", "ctrl_motion", "ctrl_currents", "ctrl_energy",
                     "ctrl_thermal", "ctrl_validity", "ctrl_fault", "ctrl_identity", "ctrl_session",
                     "driver_controls"):
        assert required in names


def test_handshake_then_eco_engages_after_driver_edge(eco_run):
    steps = eco_run.steps
    assert all(s.accepted_Nm == 0.0 for s in steps if s.t_us < 300_000), "torque before eco selection"
    eco = _first(steps, lambda s: s.state == "ECO_ASSIST")
    assert eco is not None and 0.3e6 <= eco.t_us <= 0.4e6
    assert eco_run.supervisor.tag != 0


def test_supervised_speed_and_bounds(eco_run):
    steps = [s for s in eco_run.steps if 1.0e6 <= s.t_us < 20.0e6]
    assert all(s.state == "ECO_ASSIST" for s in steps), {s.state for s in steps}
    lim = CFG["limits"]["max_motor_torque_Nm"]
    assert all(0.0 <= s.accepted_Nm <= lim + 1e-6 for s in steps)
    late = [s.v_mps for s in steps if s.t_us > 15e6]
    assert abs(sum(late) / len(late) - 6.0) < 0.5
    # sequence counters wrapped (50 Hz * 20 s = 1000 frames) without dropping ECO
    assert eco_run.supervisor.seq["sup_torque_req"] < 255 and len(eco_run.supervisor.log) > 600


def test_supervisor_loss_returns_to_ready_within_timeout(eco_run):
    last_req = max(e["t_s"] for e in eco_run.supervisor.log)
    lost = _first(eco_run.steps, lambda s: s.t_us > 1e6 and s.state == "READY")
    assert lost is not None
    timeout = CFG["supervision"]["timeout_s"]
    dt = lost.t_us / 1e6 - last_req
    assert timeout - 0.001 <= dt <= timeout + 0.021  # +1 supervisory step of observation granularity
    after = [s for s in eco_run.steps if s.t_us >= lost.t_us]
    assert all(s.accepted_Nm == 0.0 for s in after)


def test_requested_vs_accepted_logged_with_reasons(eco_run):
    traces = [f for f in eco_run.tx_frames if f[1] == "ctrl_cmd_trace"]
    assert len(traces) > 1000
    # While accelerating from rest, the slew limiter must be visible in the reasons.
    assert any(f[2]["reason"] & 0x1000 for f in traces)
    for _t, _n, v, _i in traces:
        # Accepted may exceed the CURRENT request only while slewing down toward it.
        if v["accepted_Nm"] > max(v["requested_Nm"], 0.0) + 0.0021:  # 1 LSB
            assert v["reason"] & 0x1000, v


def test_energy_accounting_consistent(eco_run):
    last = eco_run.csv_rows[-1]
    e_ctrl, e_plant = float(last["energy_ctrl_J"]), float(last["energy_plant_J"])
    assert e_plant > 100.0
    assert abs(e_ctrl - e_plant) / e_plant < 0.02
    energy_frames = [f for f in eco_run.tx_frames if f[1] == "ctrl_energy"]
    assert abs(energy_frames[-1][2]["energy_J"] - e_ctrl) < 0.02 * e_ctrl + 1.0


def test_no_fault_and_no_rectification(eco_run):
    assert all(s.faults == 0 for s in eco_run.steps)
    assert all(r["rectifying"] == "0" for r in eco_run.csv_rows)
