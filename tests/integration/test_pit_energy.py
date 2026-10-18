"""Energy per distance at the pit (host/pit/energy.py) and the worked example of docs/ENERGY_METHODS.md 0.4."""
import json
import math
import pathlib
import re
import subprocess
import sys

from host.pit import energy, ingest
from models.vehicle import longitudinal as lon

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
README = (ROOT / "docs" / "ENERGY_METHODS.md").read_text()   # the worked example lives there since v0.7


def test_formulas():
    assert energy.wheel_speed_mps(13, 1.5, 32, 0.1) == 13 * 1.5 / (32 * 0.1)      # same as the node and the import
    assert math.isclose(energy.wheel_speed_mps(149, 1.5, 32, 1.0), 1.5 * 149 / 32)
    assert energy.energy_wh(3600.0) == 1.0
    assert math.isclose(energy.wh_per_km(3600.0, 1000.0), 1.0)
    assert energy.nominal_pack_wh(48.0, 10.0) == 480.0


def _row(step):
    m = re.search(r"^\| " + re.escape(step) + r" \| [^|]+ \| ([^|]+) \|$", README, re.M)
    assert m, step
    return m.group(1).strip()


def _num(text):
    return float(re.match(r"[-0-9.]+", text).group(0))


def test_readme_worked_example_matches_independent_arithmetic_and_the_model():
    m, g, crr, cda, rho, v = 100.0, 9.80665, 0.0025, 0.035, 1.20, 7.0
    C, G, eta, kt, N, Tw = 1.5, 10.0, 0.95, 0.06, 32, 0.1
    th = math.atan(0.01)
    r = C / (2 * math.pi)
    f_grade, f_roll, f_aero = m * g * math.sin(th), crr * m * g * math.cos(th), 0.5 * rho * cda * v * v
    F = f_grade + f_roll + f_aero
    T = F * r / (G * eta)
    # independent arithmetic against the numbers printed in the README
    assert math.isclose(_num(_row("Grade force")), f_grade, abs_tol=5e-5)
    assert math.isclose(_num(_row("Rolling resistance")), f_roll, abs_tol=5e-5)
    assert math.isclose(_num(_row("Aerodynamic drag")), f_aero, abs_tol=5e-5)
    assert math.isclose(_num(_row("Total force")), F, abs_tol=5e-5)
    assert math.isclose(_num(_row("Power at the wheel")), F * v, abs_tol=5e-4)
    assert math.isclose(_num(_row("Motor torque")), T, abs_tol=5e-6)
    assert math.isclose(_num(_row("q-axis current")), T / kt, abs_tol=5e-4)
    counts = v * N / C * Tw
    assert f"{counts:.2f} pulses per 100 ms window" in README
    assert math.floor(counts) == 14 and math.ceil(counts) == 15
    assert "6.5625 or 7.0313 m/s" in _row("Wheel pulses")
    assert energy.wheel_speed_mps(14, C, N, Tw) == 6.5625 and math.isclose(energy.wheel_speed_mps(15, C, N, Tw), 7.03125)
    E_J = 48.0 * 2.5 * (1000.0 / v)
    assert "4.762 Wh, so 4.762 Wh/km (210 km/kWh)" in _row("Energy over 1 km")
    assert math.isclose(energy.wh_per_km(E_J, 1000.0), 4.7619, abs_tol=5e-5)
    assert round(1000.0 / energy.wh_per_km(E_J, 1000.0)) == 210
    assert _row("Instantaneous efficiency") == f"{100 * F * v / 120:.1f} %"
    # the model functions give the same numbers once their extra terms are removed
    p = lon.VehicleParams(mass_kg=m, wheel_radius_m=r, gear_ratio=G, crr=crr, cda_m2=cda, rho_air=rho,
                          drivetrain_eff=eta)
    assert math.isclose(lon.resistive_force(p, v, grade=th), F, rel_tol=1e-12)
    assert math.isclose(lon.motor_torque_for_force(p, F), T, rel_tol=1e-12)
    assert math.isclose(lon.tractive_force(p, T), F, rel_tol=1e-12)
    # and the synthetic vehicle (with its 0.3 N drivetrain drag) gives the figure quoted under the example
    syn = lon.SYNTHETIC_VEHICLE
    assert f"{lon.resistive_force(syn, v, grade=0.01):.3f} N" == "13.587 N" and "13.587 N" in README


def _db(tmp_path, energy_J, wheel, gap=None):
    db = ingest.connect(tmp_path / "pit.sqlite")
    rows = []
    for k, (t, e) in enumerate(energy_J):
        rows.append(("R", 1, k, "energy_J", t, None, e, None, "controller"))
    for k, (t, gs) in enumerate(gap or []):
        rows.append(("R", 2, k, "energy_gap_s", t, None, gs, None, "controller"))
    for k, (t, v) in enumerate(wheel):
        rows.append(("R", 3, k, "wheel_l", t, None, v, None, "telematics"))
    db.executemany("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    return db


def test_run_summary_energy_distance_and_notes(tmp_path):
    e = [(0, 1000.0), (10_000_000, 8200.0)]                   # 7200 J = 2 Wh over 10 s
    w = [(k * 100_000, 10.0) for k in range(1, 101)]          # 100 windows of 0.1 s at 10 m/s = 100 m
    res = energy.run_summary(_db(tmp_path, e, w, gap=[(0, 0.0), (10_000_000, 0.0)]), "R", "wheel_l", 0.1)
    assert math.isclose(res["energy_Wh"], 2.0) and math.isclose(res["distance_m"], 100.0)
    assert math.isclose(res["Wh_per_km"], 20.0) and res["energy_gap_s"] == 0.0
    assert any("joulemeter" in n for n in res["notes"])


def test_run_summary_reports_what_is_missing(tmp_path):
    e = [(0, 0.0), (1_000_000, 360.0)]
    w = [(500_000, 5.0), (1_000_000, None)]
    res = energy.run_summary(_db(tmp_path, e, w, gap=[(0, 0.0), (1_000_000, 0.2)]), "R", "wheel_l", 0.1)
    notes = " ".join(res["notes"])
    assert "gaps" in notes and "lower bound" in notes and "1 wheel windows without a value" in notes
    (tmp_path / "x").mkdir()
    res = energy.run_summary(_db(tmp_path / "x", e, w), "R", "wheel_l", None)
    assert res["Wh_per_km"] is None and any("window" in n for n in res["notes"])


def test_channel_cross_check_flags_a_short_channel():
    s = [{"channel": "wheel_l", "distance_m": 635.0}, {"channel": "wheel_r", "distance_m": 695.9}]
    out = energy.compare_channels(s)
    assert len(out) == 1 and "wheel_l" in out[0] and "8.8 %" in out[0]
    assert "no cross-check" in energy.compare_channels(s[:1])[0]


def test_pit_replay_cli_writes_energy_per_channel(tmp_path):
    meta = {"run_id": "R", "kind": "HOST SIMULATION - not a vehicle run", "calibration": {"provenance": "synthetic"},
            "vehicle_config": {"path": "config/vehicle.synthetic.yaml"},
            "sensors": {"wheel_ppr": 32, "wheel_window_s": 0.1, "wheel_channels": {"0": "wheel_l"}}}
    db = _db(tmp_path, [(0, 0.0), (10_000_000, 3600.0)], [(k * 100_000, 6.0) for k in range(1, 101)])
    db.execute("INSERT INTO runs VALUES (?,?)", ("R", json.dumps(meta)))
    db.commit()
    db.close()
    r = subprocess.run([sys.executable, "tools/run_pit_replay.py", "--db", str(tmp_path / "pit.sqlite"), "--run", "R",
                        "--out", str(tmp_path / "o")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads((tmp_path / "o" / "energy.json").read_text())
    ch = out["channels"][0]
    assert ch["channel"] == "wheel_l" and math.isclose(ch["distance_m"], 60.0) and math.isclose(ch["energy_Wh"], 1.0)
    assert "REPLAY ENERGY: 1.000 Wh over 60.0 m (wheel_l)" in r.stdout
