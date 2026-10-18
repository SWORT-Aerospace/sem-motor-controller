"""The telematics end-to-end demonstration (tools/run_telematics_demo.py), in-process and through a real broker.

The broker run needs a Mosquitto binary (docs/MQTT_SETUP.md); without one it is skipped, unless
SEMMC_REQUIRE_MQTT=1 (set in CI), which makes a missing broker a failure. Neither run builds or uses the
project's controller: the external controller is the Python stand-in host/telematics/sim_vehicle.py.
"""
import json
import os
import sqlite3

import pytest

from tools import mqtt_broker, run_telematics_demo as demo


@pytest.fixture(scope="module")
def in_process(tmp_path_factory):
    out = tmp_path_factory.mktemp("telematics_demo")
    return out, demo.run(out, in_process=True)


def test_every_in_process_check_passes(in_process):
    _out, res = in_process
    failed = [c for c in res["checks"] if not c["pass"]]
    assert not failed, failed
    assert {c["id"] for c in res["checks"]} >= {
        "receive_only_no_command_frames", "missing_or_invalid_data_is_null_never_zero",
        "every_dropped_record_accounted_for", "acquisition_continues_through_uplink_outage",
        "reingestion_creates_no_duplicates", "speed_and_distance_from_edge_timing",
        "energy_from_valid_aligned_v_and_i_at_two_boundaries", "telemetry_restart_is_a_new_session_and_a_reported_gap"}


def test_outputs_and_energy_boundaries(in_process):
    out, res = in_process
    for f in ("summary.md", "summary.json", "measurements.csv", "speed_distance.png", "power.png", "data_quality.png"):
        assert (out / f).exists(), f
    e = res["energy"]
    # battery energy includes the telematics unit and the auxiliaries: it exceeds the controller input energy
    assert e["boot1_battery"]["energy_J"] > e["boot1_controller_input"]["energy_J"] > 0
    assert e["boot1_controller_input"]["missing_s"] > 10.0          # silence, dropped message, invalid flag
    db = sqlite3.connect(out / "pit.sqlite")
    n = db.execute("SELECT COUNT(*) FROM measurements WHERE validity != 'valid' AND validity != 'unverified' AND value IS "
                   "NOT NULL").fetchone()[0]
    assert n == 0
    # no live message carries a value for a signal that is not valid, and none has a supervisor block
    for (p,) in db.execute("SELECT payload FROM live"):
        m = json.loads(p)
        assert "sup" not in m and "ctrl" not in m
        assert all(x["v"] is None for x in m["m"].values() if x["q"] not in ("valid", "unverified"))


@pytest.fixture(scope="module")
def mosquitto():
    if mqtt_broker.find_mosquitto() is None:
        msg = "no mosquitto binary (set SEMMC_MOSQUITTO or install it: docs/MQTT_SETUP.md)"
        if os.environ.get("SEMMC_REQUIRE_MQTT") == "1":
            pytest.fail(msg + "; SEMMC_REQUIRE_MQTT=1", pytrace=False)
        pytest.skip(msg)


def test_every_broker_check_passes(mosquitto, tmp_path):
    res = demo.run(tmp_path / "telematics_demo_mqtt", in_process=False, pace=6.0)
    failed = [c for c in res["checks"] if not c["pass"]]
    assert not failed, failed
    assert any(c["id"] == "live_messages_validated_before_storage" for c in res["checks"])
