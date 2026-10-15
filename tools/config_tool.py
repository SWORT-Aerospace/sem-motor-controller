#!/usr/bin/env python3
"""Configuration loader, validator and calibration-blob encoder.

    python3 tools/config_tool.py validate config/vehicle.synthetic.yaml --mode sim
    python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw
    python3 tools/config_tool.py blob config/vehicle.synthetic.yaml --mode sim -o build/cal.bin

Exit status 0 = valid for the requested mode, 1 = invalid, 2 = usage/IO error.

The same rule set is implemented in firmware/src/calibration/mc_config.c; the
test tests/integration/test_config_parity.py feeds identical mutated
configurations to both and requires identical rule codes. Rule codes are
stable numbers (never renumber).

Policy (docs/decisions/ADR-0006): unknown values stay null; null is never
replaced by a default. A "hw" validation fails if any required value is null,
if provenance is not bench_measured, or if supervision timing has not been
hazard-analysed.
"""
from __future__ import annotations

import argparse
import math
import pathlib
import struct
import sys
import zlib
from dataclasses import dataclass

import jsonschema
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools.config_registry import ROOT, load_registry  # noqa: E402

SCHEMA_PATH = ROOT / "config" / "vehicle.schema.json"

BLOB_MAGIC = b"SMCB"
BLOB_FORMAT_VERSION = 1
BLOB_HEADER = struct.Struct("<4sHHBBH16sI")   # 32 bytes
BLOB_ENTRY = struct.Struct("<HBBf")           # 8 bytes
KIND_CODE = {"real": 0, "int": 1, "bool": 2, "enum": 3}

# ---- stable rule codes (mirror of mc_config.h MC_CFG_E_*) -----------------
E = {
    "MISSING_REQUIRED": 1, "NONFINITE": 2, "OUT_OF_RANGE": 3, "NOT_INTEGER": 4,
    "BAD_ENUM": 5, "BLOB_FORMAT": 6,
    "BATT_VOLTAGE_ORDER": 10, "CELL_VOLTAGE_IMPLAUSIBLE": 11, "BUS_RATING_MARGIN": 12,
    "OV_TRIP_RANGE": 13, "UV_ORDER": 14, "CURRENT_TRIP_ORDER": 15,
    "CURRENT_SENSE_RANGE": 16, "BATT_CURRENT_LIMIT": 17, "REGEN_DEFERRED": 18,
    "TORQUE_LIMIT_ORDER": 19, "TORQUE_UNACHIEVABLE": 20, "SPEED_ORDER": 21,
    "BACKEMF_EXCEEDS_MIN_BUS": 22, "BACKEMF_EXCEEDS_RATING": 23, "TEMP_ORDER": 24,
    "SLEW_ORDER": 25, "THROTTLE_THRESH_ORDER": 26, "DUTY_ORDER": 27,
    "SUPERVISION_TIMING": 28, "SUPERVISION_NOT_HAZARD_ANALYSED": 29,
    "ARCH_MOTOR_TYPE": 30, "ROTOR_SENSOR_UNSUPPORTED": 31, "HALL_TABLE": 32,
    "PROVENANCE": 33, "CURRENT_LOOP_BANDWIDTH": 34, "DEADTIME_TOO_LONG": 35,
    "PHASE_CURRENT_RMS_PEAK": 36, "VBUS_SENSE_RANGE": 37, "ENVELOPE_RAMP_DEADLINE": 38, "SAMPLING_WINDOW": 39, "CAN_ID_BASE": 40,
    # Python-only (strings are not in the blob):
    "STRING_MISSING": 100, "SCHEMA": 101,
}
PYTHON_ONLY_CODES = {100, 101}
CODE_NAME = {v: k for k, v in E.items()}


@dataclass(frozen=True)
class Issue:
    code: int
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code:3d} {CODE_NAME[self.code]}] {self.where}: {self.message}"


def _get(cfg: dict, path: str):
    node = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def flatten(cfg: dict, reg=None) -> dict[int, float]:
    """Return {blob_id: float} for every non-null parameter element.

    Enums become their integer code, bools 0/1. Unknown enum names raise
    ValueError (schema validation catches them first)."""
    reg = reg or load_registry()
    out: dict[int, float] = {}
    for p in reg.params:
        raw = _get(cfg, p.path)
        if raw is None:
            continue
        values = raw if p.array else [raw]
        for k, v in enumerate(values):
            if v is None:
                continue
            if p.kind == "enum":
                out[p.id + k] = float(reg.enums[p.enum][v])
            elif p.kind == "bool":
                out[p.id + k] = 1.0 if v else 0.0
            else:
                out[p.id + k] = to_f32(float(v))
    return out


def to_f32(x: float) -> float:
    """Round to IEEE single precision, exactly as the calibration blob stores it.

    Validation always runs on the f32-rounded values so the Python verdict is
    the verdict on the deployed blob (and matches the C validator)."""
    if math.isfinite(x) and abs(x) > 3.4028234663852886e38:
        return math.copysign(math.inf, x)
    return struct.unpack("<f", struct.pack("<f", x))[0]


def validate_values(vals: dict[int, float], mode: str, reg=None) -> list[Issue]:
    """Validate a flat {id: value} map. Identical semantics to mc_config_validate()."""
    reg = reg or load_registry()
    assert mode in ("sim", "hw")
    issues: list[Issue] = []
    ok: dict[int, float] = {}
    for eid, p, k in reg.element_paths():
        where = p.path + (f"[{k}]" if k is not None else "")
        required = p.req_hw if mode == "hw" else p.req_sim
        if eid not in vals:
            if required:
                issues.append(Issue(E["MISSING_REQUIRED"], where, "required value is null/unset"))
            continue
        v = vals[eid]
        if not math.isfinite(v):
            issues.append(Issue(E["NONFINITE"], where, f"value {v} is not finite"))
            continue
        if p.kind in ("int", "enum", "bool") and v != math.floor(v):
            issues.append(Issue(E["NOT_INTEGER"], where, f"value {v} is not integral"))
            continue
        if p.kind == "enum":
            if int(v) not in reg.enums[p.enum].values():
                issues.append(Issue(E["BAD_ENUM"], where, f"code {int(v)} not in enum {p.enum}"))
                continue
        elif p.kind == "bool":
            if v not in (0.0, 1.0):
                issues.append(Issue(E["BAD_ENUM"], where, f"bool must be 0/1, got {v}"))
                continue
        elif not (p.min <= v <= p.max):
            issues.append(Issue(E["OUT_OF_RANGE"], where, f"{v} outside [{p.min}, {p.max}]"))
            continue
        ok[eid] = v
    issues += _cross_rules(ok, mode, reg)
    return issues


def _cross_rules(v: dict[int, float], mode: str, reg) -> list[Issue]:
    P = {p.path: p.id for p in reg.params}
    en = reg.enums
    out: list[Issue] = []

    def have(*paths):
        return all(P[x] in v for x in paths)

    def g(path, k=0):
        return v[P[path] + k]

    def add(name, where, msg):
        out.append(Issue(E[name], where, msg))

    # R20 provenance / physical output
    if have("calibration.provenance", "calibration.physical_output_permitted"):
        prov, phys = int(g("calibration.provenance")), g("calibration.physical_output_permitted")
        if prov == en["provenance"]["synthetic"] and phys != 0.0:
            add("PROVENANCE", "calibration", "synthetic configuration cannot enable a physical output")
        if mode == "hw" and prov != en["provenance"]["bench_measured"]:
            add("PROVENANCE", "calibration.provenance", "hardware build requires bench_measured provenance")
        if mode == "hw" and phys != 1.0:
            add("PROVENANCE", "calibration.physical_output_permitted", "hardware build requires an explicit true")
    # R1, R2 battery voltages
    if have("battery.min_voltage_V", "battery.nominal_voltage_V", "battery.max_charged_voltage_V"):
        vmin, vnom, vmax = g("battery.min_voltage_V"), g("battery.nominal_voltage_V"), g("battery.max_charged_voltage_V")
        if not (vmin < vnom < vmax):
            add("BATT_VOLTAGE_ORDER", "battery", f"need min < nominal < max ({vmin}, {vnom}, {vmax})")
        if have("battery.series_cells"):
            n = g("battery.series_cells")
            if not (2.0 <= vmax / n <= 4.5 and 1.5 <= vmin / n <= 4.3):
                add("CELL_VOLTAGE_IMPLAUSIBLE", "battery", f"per-cell {vmin/n:.3f}..{vmax/n:.3f} V implausible")
    # R3 bus rating with transient margin
    if have("battery.max_charged_voltage_V", "inverter.transient_margin_fraction", "inverter.bus_voltage_rating_V"):
        need = g("battery.max_charged_voltage_V") * (1.0 + g("inverter.transient_margin_fraction"))
        if need > g("inverter.bus_voltage_rating_V"):
            add("BUS_RATING_MARGIN", "inverter.bus_voltage_rating_V",
                f"max charged x (1+margin) = {need:.2f} V exceeds rating {g('inverter.bus_voltage_rating_V')} V")
    # R4 OV trip
    if have("limits.overvoltage_trip_V", "battery.max_charged_voltage_V", "inverter.bus_voltage_rating_V"):
        ov = g("limits.overvoltage_trip_V")
        if not (g("battery.max_charged_voltage_V") < ov <= g("inverter.bus_voltage_rating_V")):
            add("OV_TRIP_RANGE", "limits.overvoltage_trip_V", "need max_charged < ov_trip <= bus rating")
    # R5 UV order
    if have("limits.undervoltage_trip_V", "limits.undervoltage_derate_V", "battery.min_voltage_V",
            "battery.nominal_voltage_V"):
        uvt, uvd = g("limits.undervoltage_trip_V"), g("limits.undervoltage_derate_V")
        if not (g("battery.min_voltage_V") <= uvt <= uvd <= g("battery.nominal_voltage_V")):
            add("UV_ORDER", "limits", "need battery.min <= uv_trip <= uv_derate <= nominal")
    # R6 current trips
    if have("limits.max_phase_current_A", "motor.peak_phase_current_A", "limits.software_overcurrent_A",
            "inverter.hw_overcurrent_trip_A"):
        imax, ipk = g("limits.max_phase_current_A"), g("motor.peak_phase_current_A")
        isw, ihw = g("limits.software_overcurrent_A"), g("inverter.hw_overcurrent_trip_A")
        if not (imax <= ipk and imax < isw < ihw):
            add("CURRENT_TRIP_ORDER", "limits", "need max_phase <= motor peak, max_phase < sw_oc < hw_oc")
    if have("inverter.hw_overcurrent_trip_A", "inverter.adc_vref_V", "inverter.amp_gain_V_per_V", "inverter.shunt_ohm"):
        i_fs = 0.5 * g("inverter.adc_vref_V") / (g("inverter.amp_gain_V_per_V") * g("inverter.shunt_ohm"))
        if g("inverter.hw_overcurrent_trip_A") >= i_fs:
            add("CURRENT_SENSE_RANGE", "inverter.hw_overcurrent_trip_A",
                f"trip {g('inverter.hw_overcurrent_trip_A')} A not below bidirectional full scale {i_fs:.2f} A")
    # R7 battery current
    if have("limits.battery_current_limit_A", "battery.bms_max_discharge_current_A"):
        if g("limits.battery_current_limit_A") > g("battery.bms_max_discharge_current_A"):
            add("BATT_CURRENT_LIMIT", "limits.battery_current_limit_A", "exceeds BMS continuous discharge limit")
    # R8 regen deferred in v0.1
    if have("limits.regen_enabled") and g("limits.regen_enabled") != 0.0:
        add("REGEN_DEFERRED", "limits.regen_enabled", "active regeneration is deferred in v0.1 (ADR-0007)")
    # R9 torque limits
    if have("limits.manual_max_torque_Nm", "limits.max_motor_torque_Nm"):
        if g("limits.manual_max_torque_Nm") > g("limits.max_motor_torque_Nm"):
            add("TORQUE_LIMIT_ORDER", "limits.manual_max_torque_Nm", "exceeds max_motor_torque")
    if have("limits.max_motor_torque_Nm", "motor.pole_pairs", "motor.flux_linkage_Wb", "limits.max_phase_current_A"):
        kt = 1.5 * g("motor.pole_pairs") * g("motor.flux_linkage_Wb")
        if g("limits.max_motor_torque_Nm") > kt * g("limits.max_phase_current_A") * 1.0001:
            add("TORQUE_UNACHIEVABLE", "limits.max_motor_torque_Nm",
                f"exceeds Kt*Imax = {kt * g('limits.max_phase_current_A'):.3f} N*m (non-salient estimate)")
    # R10 speeds
    if have("motor.rated_mech_speed_rad_s", "motor.max_mech_speed_rad_s", "limits.overspeed_trip_rad_s",
            "limits.speed_taper_start_rad_s"):
        if not (g("motor.rated_mech_speed_rad_s") <= g("motor.max_mech_speed_rad_s")
                and g("limits.speed_taper_start_rad_s") < g("limits.overspeed_trip_rad_s") <= g("motor.max_mech_speed_rad_s")):
            add("SPEED_ORDER", "limits", "need rated <= max_mech, taper_start < overspeed_trip <= max_mech")
    # R11 back-EMF
    if have("motor.flux_linkage_Wb", "motor.pole_pairs", "limits.overspeed_trip_rad_s", "battery.min_voltage_V"):
        e_ll = math.sqrt(3.0) * g("motor.flux_linkage_Wb") * g("motor.pole_pairs") * g("limits.overspeed_trip_rad_s")
        if e_ll >= g("battery.min_voltage_V"):
            add("BACKEMF_EXCEEDS_MIN_BUS", "limits.overspeed_trip_rad_s",
                f"line-line back-EMF peak {e_ll:.2f} V at overspeed trip >= battery min {g('battery.min_voltage_V')} V "
                "(uncontrolled rectification possible with gates off)")
    if have("motor.flux_linkage_Wb", "motor.pole_pairs", "motor.max_mech_speed_rad_s", "inverter.bus_voltage_rating_V"):
        e_ll = math.sqrt(3.0) * g("motor.flux_linkage_Wb") * g("motor.pole_pairs") * g("motor.max_mech_speed_rad_s")
        if e_ll >= g("inverter.bus_voltage_rating_V"):
            add("BACKEMF_EXCEEDS_RATING", "motor.max_mech_speed_rad_s",
                f"line-line back-EMF peak {e_ll:.2f} V at max speed >= inverter rating")
    # R12 temperatures
    t_bad = False
    if have("inverter.fet_temp_derate_start_degC", "inverter.fet_temp_trip_degC"):
        t_bad |= not (g("inverter.fet_temp_derate_start_degC") < g("inverter.fet_temp_trip_degC"))
    if have("limits.motor_temp_derate_start_degC", "limits.motor_temp_trip_degC", "motor.max_winding_temp_degC"):
        t_bad |= not (g("limits.motor_temp_derate_start_degC") < g("limits.motor_temp_trip_degC")
                      <= g("motor.max_winding_temp_degC"))
    if t_bad:
        add("TEMP_ORDER", "temperatures", "need derate_start < trip (<= motor max winding temperature)")
    # R13..R15
    if have("limits.torque_slew_down_fast_Nm_s", "limits.torque_slew_down_Nm_s"):
        if g("limits.torque_slew_down_fast_Nm_s") < g("limits.torque_slew_down_Nm_s"):
            add("SLEW_ORDER", "limits.torque_slew_down_fast_Nm_s", "fast down-slew below normal down-slew")
    if have("limits.max_motor_torque_Nm", "limits.torque_slew_down_fast_Nm_s", "supervision.timeout_s"):
        if g("limits.max_motor_torque_Nm") / g("limits.torque_slew_down_fast_Nm_s") > g("supervision.timeout_s"):
            add("ENVELOPE_RAMP_DEADLINE", "limits.torque_slew_down_fast_Nm_s",
                "envelope ramp-down (max torque / fast down-slew) longer than the supervision timeout")
    if have("limits.throttle_release_threshold", "limits.throttle_engage_threshold"):
        if not g("limits.throttle_release_threshold") < g("limits.throttle_engage_threshold"):
            add("THROTTLE_THRESH_ORDER", "limits", "need throttle release < engage threshold")
    if have("inverter.voltage_limit_fraction", "inverter.current_sample_settle_s", "inverter.deadtime_s",
            "inverter.pwm_frequency_Hz"):
        d2 = 0.5 + 0.4330127018922193 * g("inverter.voltage_limit_fraction")
        dwin = 1.0 - 2.0 * (g("inverter.deadtime_s") + g("inverter.current_sample_settle_s")) * g("inverter.pwm_frequency_Hz")
        if d2 > dwin:
            add("SAMPLING_WINDOW", "inverter.voltage_limit_fraction",
                "two phases are not sampleable at every SVPWM angle; lower the voltage limit or the PWM frequency")
    if have("supervision.can_id_base") and g("supervision.can_id_base") % 64 != 0:
        add("CAN_ID_BASE", "supervision.can_id_base", "CAN id base must be a multiple of 0x40 (one filter mask)")
    if have("inverter.duty_min", "inverter.duty_max"):
        if not g("inverter.duty_min") < g("inverter.duty_max"):
            add("DUTY_ORDER", "inverter", "need duty_min < duty_max")
    # R16 supervision
    if have("supervision.timeout_s", "supervision.update_period_s"):
        if g("supervision.timeout_s") < 2.0 * g("supervision.update_period_s"):
            add("SUPERVISION_TIMING", "supervision.timeout_s", "timeout must be >= 2 update periods")
    if mode == "hw" and have("supervision.timing_status"):
        if int(g("supervision.timing_status")) != en["timing_status"]["hazard_analysed"]:
            add("SUPERVISION_NOT_HAZARD_ANALYSED", "supervision.timing_status",
                "provisional simulation timing cannot be used in a hardware build")
    # R17, R18 architecture
    if have("motor.type") and int(g("motor.type")) != en["motor_type"]["pmsm_sinusoidal"]:
        add("ARCH_MOTOR_TYPE", "motor.type",
            "firmware v0.1 implements sinusoidal sensored FOC only; other motor types require a recorded architecture change")
    if have("motor.rotor_sensor") and int(g("motor.rotor_sensor")) != en["rotor_sensor"]["hall"]:
        add("ROTOR_SENSOR_UNSUPPORTED", "motor.rotor_sensor", "firmware v0.1 implements hall sensors only")
    # R19 hall table
    hid = P["motor.hall_code_to_sector"]
    if all(hid + k in v for k in range(8)):
        tab = [int(v[hid + k]) for k in range(8)]
        legal = [s for s in tab if s >= 0]
        if tab[0] != -1 or tab[7] != -1 or sorted(legal) != [0, 1, 2, 3, 4, 5]:
            add("HALL_TABLE", "motor.hall_code_to_sector", "codes 0 and 7 must be -1 and sectors 0..5 appear once")
    # R21 current-loop bandwidth vs PWM
    if have("inverter.current_kp_V_per_A", "motor.q_inductance_H", "motor.d_inductance_H", "inverter.pwm_frequency_Hz"):
        lmin = min(g("motor.q_inductance_H"), g("motor.d_inductance_H"))
        wc = g("inverter.current_kp_V_per_A") / lmin
        if wc > 2.0 * math.pi * g("inverter.pwm_frequency_Hz") / 10.0:
            add("CURRENT_LOOP_BANDWIDTH", "inverter.current_kp_V_per_A",
                f"kp/L = {wc:.0f} rad/s exceeds 1/10 of the PWM rate")
    # R22 dead time
    if have("inverter.deadtime_s", "inverter.pwm_frequency_Hz"):
        if g("inverter.deadtime_s") > 0.05 / g("inverter.pwm_frequency_Hz"):
            add("DEADTIME_TOO_LONG", "inverter.deadtime_s", "dead time exceeds 5 % of the PWM period")
    # R24
    if have("motor.continuous_phase_current_A_rms", "motor.peak_phase_current_A"):
        if g("motor.continuous_phase_current_A_rms") * math.sqrt(2.0) > g("motor.peak_phase_current_A") * 1.0001:
            add("PHASE_CURRENT_RMS_PEAK", "motor", "continuous RMS x sqrt(2) exceeds peak phase current")
    # vbus sense range
    if have("inverter.adc_vref_V", "inverter.vbus_divider_ratio", "limits.overvoltage_trip_V"):
        if g("inverter.adc_vref_V") * g("inverter.vbus_divider_ratio") < 1.05 * g("limits.overvoltage_trip_V"):
            add("VBUS_SENSE_RANGE", "inverter.vbus_divider_ratio", "bus-voltage ADC full scale below 1.05 x OV trip")
    return out


def validate_config(cfg: dict, mode: str, reg=None) -> list[Issue]:
    reg = reg or load_registry()
    schema = __import__("json").loads(SCHEMA_PATH.read_text())
    issues: list[Issue] = []
    for err in sorted(jsonschema.Draft202012Validator(schema).iter_errors(cfg), key=str):
        loc = ".".join(str(x) for x in err.absolute_path) or "<root>"
        issues.append(Issue(E["SCHEMA"], loc, err.message))
    if issues:
        return issues  # structure must be right before values are meaningful
    for s in reg.strings:
        required = s.req_hw if mode == "hw" else s.req_sim
        if required and not _get(cfg, s.path):
            issues.append(Issue(E["STRING_MISSING"], s.path, "required text field is null/empty"))
    issues += validate_values(flatten(cfg, reg), mode, reg)
    return issues


# ---- calibration blob -------------------------------------------------------
def encode_blob(cfg: dict, reg=None) -> bytes:
    reg = reg or load_registry()
    vals = flatten(cfg, reg)
    kinds = {eid: KIND_CODE[p.kind] for eid, p, _ in reg.element_paths()}
    cal_id = (_get(cfg, "calibration.id") or "").encode("ascii")[:15].ljust(16, b"\0")
    prov = int(vals.get(reg.by_path["calibration.provenance"].id, 0))
    version = int(vals.get(reg.by_path["calibration.version"].id, 0))
    hdr = BLOB_HEADER.pack(BLOB_MAGIC, BLOB_FORMAT_VERSION, int(cfg.get("schema_version", 0)), prov, 0,
                           len(vals), cal_id, version)
    body = b"".join(BLOB_ENTRY.pack(eid, kinds[eid], 0, vals[eid]) for eid in sorted(vals))
    data = hdr + body
    return data + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)


def decode_blob(blob: bytes) -> tuple[dict, dict[int, float]]:
    if len(blob) < BLOB_HEADER.size + 4:
        raise ValueError("blob too short")
    if struct.unpack_from("<I", blob, len(blob) - 4)[0] != zlib.crc32(blob[:-4]) & 0xFFFFFFFF:
        raise ValueError("blob CRC mismatch")
    magic, fmt, schema, prov, _flags, n, cal_id, version = BLOB_HEADER.unpack_from(blob, 0)
    if magic != BLOB_MAGIC or fmt != BLOB_FORMAT_VERSION:
        raise ValueError("bad magic/format")
    if len(blob) != BLOB_HEADER.size + n * BLOB_ENTRY.size + 4:
        raise ValueError("blob length mismatch")
    vals: dict[int, float] = {}
    for i in range(n):
        eid, _kind, _r, val = BLOB_ENTRY.unpack_from(blob, BLOB_HEADER.size + i * BLOB_ENTRY.size)
        if eid in vals:
            raise ValueError(f"duplicate id {eid}")
        vals[eid] = val
    header = {"schema_version": schema, "provenance": prov, "cal_id": cal_id.rstrip(b"\0").decode(),
              "cal_version": version}
    return header, vals


def load_yaml(path: str | pathlib.Path) -> dict:
    return yaml.safe_load(pathlib.Path(path).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "blob"):
        sp = sub.add_parser(name)
        sp.add_argument("config")
        sp.add_argument("--mode", choices=("sim", "hw"), required=True)
        if name == "blob":
            sp.add_argument("-o", "--output", required=True)
            sp.add_argument("--allow-invalid", action="store_true",
                            help="emit even if invalid (for negative tests only)")
    args = ap.parse_args(argv)
    try:
        cfg = load_yaml(args.config)
    except (OSError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    issues = validate_config(cfg, args.mode)
    for i in issues:
        print(i)
    status = "VALID" if not issues else f"INVALID ({len(issues)} issue(s))"
    print(f"{args.config}: {status} for mode={args.mode}")
    if args.cmd == "blob" and (not issues or args.allow_invalid):
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(encode_blob(cfg))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
