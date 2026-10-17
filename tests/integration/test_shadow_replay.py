"""Pit-side shadow replay of R3v and CSIA2 (host/pit/shadow_replay.py, tools/run_pit_replay.py)."""
import ast
import json
import pathlib
import subprocess
import sys

from host.csia_adapter.adapter import AdapterParams
from host.pit import ingest, shadow_replay

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
P = AdapterParams(wheel_radius_m=1.5 / 6.283185307179586, gear_ratio=10.0, freewheel=False, kt_Nm_per_A=0.06)


def _db(tmp_path, meta, n=60):
    db = ingest.connect(tmp_path / "pit.sqlite")
    db.execute("INSERT INTO runs VALUES (?,?)", (meta["run_id"], json.dumps(meta)))
    rows = []
    for k in range(n):                                   # 6 s of rotor and p_dc only: most inputs missing
        t = 1_000_000 + k * 100_000
        rows.append((meta["run_id"], 1, 2 * k, "rotor", t, None, 250.0, k % 256, "controller"))
        rows.append((meta["run_id"], 1, 2 * k + 1, "p_dc", t, None, 60.0, k % 256, "controller"))
    db.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    return db


def test_data_class_follows_the_run_metadata():
    assert shadow_replay.classify({"kind": "HOST SIMULATION - not a vehicle run"})["synthetic"]
    assert shadow_replay.classify({"calibration": {"provenance": "synthetic"}})["synthetic"]
    m = shadow_replay.classify({"kind": "vehicle", "calibration": {"provenance": "bench_measured"},
                                "vehicle_config": {"path": "config/vehicle.car1.yaml"}})
    assert not m["synthetic"] and m["data_class"] == "measured (vehicle)"


def test_measured_run_with_missing_signals_reports_insufficient_evidence(tmp_path):
    meta = {"run_id": "CAR-1", "kind": "vehicle", "calibration": {"provenance": "bench_measured"},
            "vehicle_config": {"path": "config/vehicle.car1.yaml"}}
    res = shadow_replay.run(_db(tmp_path, meta), "CAR-1", P, 0.06, 0.47, tmp_path / "out")
    notes = " ".join(res["insufficient"])
    assert res["ticks"] > 0 and not res["provenance"]["synthetic"]
    assert "frozen synthetic" in notes                    # parameters and E6 model not identified on this vehicle
    assert "signal wheel_l" in notes and "signal gnss" in notes
    assert "no ground truth" in notes and res["scoring"] is None
    assert (tmp_path / "out" / "report.md").exists() and (tmp_path / "out" / "timeline.csv").exists()
    assert "INSUFFICIENT" not in res["provenance"]["data_class"]


def test_cli_reports_a_missing_run(tmp_path):
    ingest.connect(tmp_path / "empty.sqlite").close()
    r = subprocess.run([sys.executable, "tools/run_pit_replay.py", "--db", str(tmp_path / "empty.sqlite"),
                        "--run", "NOPE", "--out", str(tmp_path / "o")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "NOT AVAILABLE" in r.stdout


def test_shadow_replay_has_no_command_path():
    """Shadow mode by construction: no CAN, MQTT, socket or controller imports in the replay modules."""
    for rel in ("host/pit/shadow_replay.py", "host/pit/csia_replay.py", "host/pit/energy.py", "tools/run_pit_replay.py"):
        tree = ast.parse((ROOT / rel).read_text())
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not {m for m in mods if m.split(".")[0] in ("paho", "socket", "can", "serial")}, rel
        assert not {m for m in mods if m.startswith(("host.telematics", "host.vcu_bridge", "host.telemetry_adapter"))}, rel


def test_cli_writes_configuration_notes_into_the_report(tmp_path):
    meta = {"run_id": "CAR-2", "kind": "vehicle", "calibration": {"provenance": "bench_measured"},
            "vehicle_config": {"path": "config/vehicle.synthetic.yaml", "sha256": "0" * 64},
            "sensors": {"wheel_ppr": 32}}
    _db(tmp_path, meta).close()
    r = subprocess.run([sys.executable, "tools/run_pit_replay.py", "--db", str(tmp_path / "pit.sqlite"),
                        "--run", "CAR-2", "--out", str(tmp_path / "o")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    report = (tmp_path / "o" / "report.md").read_text()
    assert "changed since the run" in report and "counting window not in the run metadata" in report
    assert "changed since the run" in " ".join(json.loads((tmp_path / "o" / "report.json").read_text())["insufficient"])
