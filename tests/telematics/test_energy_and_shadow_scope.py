"""Energy and shadow-mode diagnostics in the telematics scope: relationships disabled when the external
controller lacks their inputs, no simulator data in a vehicle report, the frozen evaluation unchanged."""
import hashlib
import json
import pathlib

from host.csia_adapter.adapter import AdapterParams
from host.pit import energy, ingest, shadow_replay

ROOT = pathlib.Path(__file__).resolve().parents[2]
P = AdapterParams(wheel_radius_m=1.5 / 6.283185307179586, gear_ratio=10.0, freewheel=False, kt_Nm_per_A=0.06)


def _db(tmp_path, meta, names):
    db = ingest.connect(tmp_path / "pit.sqlite")
    db.execute("INSERT INTO runs VALUES (?,?)", (meta["run_id"], json.dumps(meta)))
    rows = []
    for k in range(80):
        t = 1_000_000 + k * 100_000
        for j, (name, v) in enumerate(names.items()):
            rows.append((meta["run_id"], 1, len(names) * k + j, name, t, None, v, None, "x"))
    db.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    return db


def test_relationships_without_inputs_are_disabled_and_reported(tmp_path):
    # an external controller that broadcasts only DC voltage and current: no rotor, iq, kcl or p_dc
    meta = {"run_id": "VEH-1", "kind": "BENCH - external controller", "sensors": {}}
    db = _db(tmp_path, meta, {"vbus": 48.0, "ibatt": 2.0, "wheel_l": 5.0, "wheel_r": 5.0, "gnss": 5.0, "imu_gz": 0.0,
                              "imu_ax": 0.0})
    res = shadow_replay.run(db, "VEH-1", P, 0.06, 0.05)
    st = {r: v["status"] for r, v in res["relationships"].items()}
    assert st["E6_power_balance"].startswith("disabled") and "ctrl.dc_power" in st["E6_power_balance"]
    assert st["E1_rotor_wheeldrive"].startswith("disabled") and "ctrl.motor_speed" in st["E1_rotor_wheeldrive"]
    assert st["P_phase_current"].startswith("disabled")
    assert st["E2_wheel_lr_yaw"] == "enabled" and st["E3a_gnss_wheel_l"] == "enabled"
    assert st["E4_imu_wheel_l"].startswith("disabled") and "grade" in st["E4_imu_wheel_l"]   # vehicle run: not assumed
    assert any("E6_power_balance disabled" in x for x in res["insufficient"])
    assert res["provenance"]["data_class"] == "measured (vehicle)"


def test_a_vehicle_report_ignores_simulator_fields(tmp_path):
    meta = {"run_id": "VEH-2", "kind": "vehicle", "sensors": {},
            "injected_faults": [{"kind": "wheel_dropout", "node": "wheel_l", "t_local_s": [2.0, 4.0]}],
            "plant": {"freewheel": False}}
    db = _db(tmp_path, meta, {"wheel_l": 5.0, "wheel_r": 5.0, "gnss": 5.0, "imu_gz": 0.0})
    res = shadow_replay.run(db, "VEH-2", P, 0.06, 0.05)
    assert res["scoring"] is None                               # no ground truth taken from a simulator
    assert any("simulator fields" in x and "injected_faults" in x for x in res["insufficient"])


def test_energy_boundaries_are_stated():
    assert set(energy.BOUNDARIES) == {"controller_input", "battery"}
    assert "excludes the telematics unit" in energy.BOUNDARIES["controller_input"][2]
    assert "includes the controller, the telematics unit" in energy.BOUNDARIES["battery"][2]


FROZEN = {  # SHA-256 at the v0.6 baseline (92682c1); the telematics work does not touch them
    "docs/csia/V2_FREEZE.json": "02c87c845b2134c65425ea0398e1b76062475797b9abb847c9d0b549cdb80069",
    "docs/csia/EVALUATION_RESULTS_v2.md": "a0bdab9de372591092af73a90adfe4db8fd49574ebb9272bdb15524305266984",
    "host/csia_adapter/adapter_v2.py": "d00215fdb0331d0b237ec66f91b999f643f87e402e7dd409ccef88623122f45a",
    "host/csia_adapter/evaluation_v2.py": "ad90979ac1bd433274a3b0701f982c34fc6c9c780e6ad35cc278ca2aa9c2c71b",
}


def test_frozen_evaluation_files_unchanged_and_r3v_result_kept():
    for f, digest in FROZEN.items():
        assert hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == digest, f
    assert "R3v" in (ROOT / "docs" / "csia" / "EVALUATION_RESULTS_v2.md").read_text()
