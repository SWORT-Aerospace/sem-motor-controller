"""Host replay of the SYNTHETIC recorded log tests/simulation/replay_sample.semmc.log.

If the controller's session-tag derivation changes, regenerate the sample with
`python3 tools/make_replay_sample.py` (it learns the tag from ctrl_session).
"""
import pathlib

import pytest

from host.replay.replay import run_replay

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "tests" / "simulation" / "replay_sample.semmc.log"


@pytest.fixture(scope="module")
def replay(build_dir, synthetic_blob):
    return run_replay(LOG, synthetic_blob, build_dir / "replay_test", exe=build_dir / "semmc_host")


def _row(rows, t):
    return min(rows, key=lambda r: abs(r["t_s"] - t))


def test_transitions(replay):
    states = [s for _t, s in replay["transitions"]]
    assert states == ["SELF_TEST", "DISARMED", "READY", "ECO_ASSIST", "READY", "ECO_ASSIST", "READY", "DERATED"]
    times = dict((s, t) for t, s in reversed(replay["transitions"]))
    assert abs(times["ECO_ASSIST"] - 0.30) < 0.03


def test_duplicates_and_reordered_frames_have_no_effect(replay):
    rows = replay["commands"]
    for t in (2.0, 2.01, 2.02, 2.5, 2.52):
        assert _row(rows, t)["state"] == "ECO_ASSIST"
    assert abs(_row(rows, 2.52)["accepted_Nm"] - 0.8) < 0.21  # the late 1.5 N*m frame was not applied


def test_stale_gap_ends_eco_and_needs_new_edge(replay):
    rows = replay["commands"]
    assert _row(rows, 3.12)["state"] == "READY"
    assert "SUPERVISOR_INVALID" in _row(rows, 3.10)["reasons"]
    assert _row(rows, 3.45)["state"] == "READY"  # supervisor back at 3.2 s, but no driver edge yet
    assert _row(rows, 3.62)["state"] == "ECO_ASSIST"


def test_nan_request_ends_eco(replay):
    rows = replay["commands"]
    r = _row(rows, 5.0)
    assert r["state"] == "READY" and r["accepted_Nm"] == 0.0


def test_manual_with_sag_and_heat_is_derated_not_faulted(replay):
    rows = replay["commands"]
    r = _row(rows, 6.5)
    assert r["state"] == "DERATED" and "CLAMP_DERATE" in r["reasons"]
    assert r["accepted_Nm"] < r["requested_Nm"]
    r = _row(rows, 7.6)
    assert r["state"] == "DERATED"


def test_brake_zeroes_torque(replay):
    rows = replay["commands"]
    assert _row(rows, 8.02)["accepted_Nm"] == 0.0
    assert "BRAKE_OVERRIDE" in _row(rows, 8.02)["reasons"]
