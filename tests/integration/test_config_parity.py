"""Python and C validators must agree on every rule code for the same blob."""
import copy
import math
import pathlib
import subprocess

import pytest

from tools import config_tool as ct

ROOT = pathlib.Path(__file__).resolve().parents[2]
SYN = ct.load_yaml(ROOT / "config" / "vehicle.synthetic.yaml")
UNC = ct.load_yaml(ROOT / "config" / "vehicle.unconfigured.yaml")


def _set(cfg, path, value):
    node = cfg
    parts = path.split(".")
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value


MUTATIONS = [
    ("baseline", None, None),
    ("nan", "motor.phase_resistance_ohm", float("nan")),
    ("inf", "motor.flux_linkage_Wb", float("inf")),
    ("range_units", "motor.d_inductance_H", 150.0),
    ("not_integer", "motor.pole_pairs", 4.5),
    ("brushed", "motor.type", "brushed_dc"),
    ("trapezoidal", "motor.type", "bldc_trapezoidal"),
    ("encoder", "motor.rotor_sensor", "encoder"),
    ("vorder", "battery.nominal_voltage_V", 60.0),
    ("cells", "battery.series_cells", 30),
    ("busrating", "inverter.bus_voltage_rating_V", 55.0),
    ("hwtrip_order", "inverter.hw_overcurrent_trip_A", 50.0),
    ("hwtrip_range", "inverter.hw_overcurrent_trip_A", 90.0),
    ("battlimit", "limits.battery_current_limit_A", 45.0),
    ("regen", "limits.regen_enabled", True),
    ("torque_unachievable", "limits.max_motor_torque_Nm", 5.0),
    ("manual_gt_max", "limits.manual_max_torque_Nm", 2.1),
    ("backemf", "motor.flux_linkage_Wb", 0.02),
    ("speed_order", "limits.speed_taper_start_rad_s", 460.0),
    ("temp", "limits.motor_temp_trip_degC", 130.0),
    ("slew", "limits.torque_slew_down_fast_Nm_s", 1.0),
    ("envelope_ramp", "limits.torque_slew_down_fast_Nm_s", 15.0),
    ("sampling_window", "inverter.current_sample_settle_s", 3.0e-6),
    ("vlimit_high", "inverter.voltage_limit_fraction", 1.0),
    ("can_id_base_unaligned", "supervision.can_id_base", 784),
    ("can_id_base_range", "supervision.can_id_base", 2048),
    ("throttle", "limits.throttle_release_threshold", 0.2),
    ("duty", "inverter.duty_max", 0.8),
    ("timing", "supervision.timeout_s", 0.03),
    ("hall", "motor.hall_code_to_sector", [0, 0, 2, 1, 4, 5, 3, -1]),
    ("bandwidth", "inverter.current_kp_V_per_A", 5.0),
    ("deadtime", "inverter.deadtime_s", 3.0e-6),
    ("rms_peak", "motor.continuous_phase_current_A_rms", 30.0),
    ("vbus_sense", "inverter.vbus_divider_ratio", 10.0),
    ("synthetic_physical", "calibration.physical_output_permitted", True),
    ("missing", "motor.flux_linkage_Wb", None),
    ("uv_order", "limits.undervoltage_trip_V", 39.0),
    ("ov", "limits.overvoltage_trip_V", 80.0),
]


def _c_codes(cfgcheck_exe, blob_path, mode):
    r = subprocess.run([str(cfgcheck_exe), str(blob_path), mode], capture_output=True, text=True)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("CODES")][0]
    codes = sorted(int(x.split(":")[0]) for x in line.split()[1:])
    return r.returncode, codes


@pytest.mark.parametrize("mode", ["sim", "hw"])
@pytest.mark.parametrize("name,path,value", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_parity(tmp_path, cfgcheck_exe, name, path, value, mode):
    cfg = copy.deepcopy(SYN)
    if path:
        _set(cfg, path, value)
    blob = tmp_path / "c.bin"
    # Encode without schema checks (we want the VALUE rules compared).
    blob.write_bytes(ct.encode_blob(cfg))
    _hdr, vals = ct.decode_blob(blob.read_bytes())
    py = sorted(i.code for i in ct.validate_values(vals, mode))
    rc, c = _c_codes(cfgcheck_exe, blob, mode)
    assert py == c, f"{name}/{mode}: python {py} != C {c}"
    assert (rc == 0) == (not py)
    if name == "baseline" and mode == "sim":
        assert py == []


def test_unconfigured_fails_both_modes(tmp_path, cfgcheck_exe):
    blob = tmp_path / "u.bin"
    blob.write_bytes(ct.encode_blob(UNC))
    for mode in ("sim", "hw"):
        rc, codes = _c_codes(cfgcheck_exe, blob, mode)
        assert rc == 1 and ct.E["MISSING_REQUIRED"] in codes
    assert ct.validate_config(UNC, "hw")


def test_hardware_cmake_configure_refuses_unconfigured(tmp_path):
    """A hardware-enabled build must fail at configure time on missing ratings."""
    r = subprocess.run(["cmake", "-S", str(ROOT / "firmware"), "-B", str(tmp_path / "hw"),
                        "-DSEMMC_HARDWARE_BUILD=ON"], capture_output=True, text=True)
    assert r.returncode != 0
    assert "Hardware build refused" in (r.stdout + r.stderr)
    assert "MISSING_REQUIRED" in (r.stdout + r.stderr)


def test_hardware_cmake_configure_refuses_synthetic(tmp_path):
    r = subprocess.run(["cmake", "-S", str(ROOT / "firmware"), "-B", str(tmp_path / "hw2"),
                        "-DSEMMC_HARDWARE_BUILD=ON",
                        f"-DSEMMC_VEHICLE_CONFIG={ROOT / 'config' / 'vehicle.synthetic.yaml'}"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "PROVENANCE" in (r.stdout + r.stderr)


def test_schema_rejects_typo_and_wrong_convention():
    cfg = copy.deepcopy(SYN)
    cfg["motor"]["flux_linkage_wb"] = 0.01  # wrong case: unknown key
    issues = ct.validate_config(cfg, "sim")
    assert any(i.code == ct.E["SCHEMA"] for i in issues)
    cfg = copy.deepcopy(SYN)
    cfg["conventions"]["battery_current_positive"] = "charge"
    assert any(i.code == ct.E["SCHEMA"] for i in ct.validate_config(cfg, "sim"))


def test_f32_rounding_is_what_gets_validated():
    assert ct.to_f32(0.1) != 0.1
    assert math.isclose(ct.to_f32(0.1), 0.1, rel_tol=1e-7)
    assert ct.to_f32(1e40) == math.inf
