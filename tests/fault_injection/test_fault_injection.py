"""Fault injection through the C core with the synthetic plant (host only).

Each test builds a semmc-log scenario (or drives the lockstep co-simulation),
runs the real C core, and checks the controller's own logged behaviour.
SYNTHETIC plant and configuration: these are software-behaviour tests, not
hardware validation.
"""
from __future__ import annotations

import csv
import math
import pathlib
import subprocess

import pytest

from host.logger.semmc_log import Event, can_event, io_event, kv_event, write_log
from host.telemetry_adapter.e2e import Scenario, run
from protocol.generated import semmc_protocol as proto

ROOT = pathlib.Path(__file__).resolve().parents[2]
US = 1_000_000
F_SEMMC_STALL = 17  # MC_F_ROTOR_STALL bit index


def run_log(host_exe, cal, tmp_path, events, extra=()):
    log = write_log(tmp_path / "scn.log", events)
    out = tmp_path / "out.csv"
    r = subprocess.run([str(host_exe), "--cal", str(cal), "--log", str(log), "--out", str(out), "--decimate", "1",
                        "--frames", str(tmp_path / "tx.log"), *extra], capture_output=True, text=True, check=True)
    with out.open() as f:
        rows = list(csv.DictReader(f))
    return rows, r.stdout


def at(rows, t_s):
    return min(rows, key=lambda r: abs(float(r["t_s"]) - t_s))


def manual_drive(t_end_s, throttle=0.5):
    return [io_event(0, arm=False, throttle=0.0), io_event(int(0.1 * US), arm=True),
            io_event(int(0.2 * US), throttle=throttle), Event(int(t_end_s * US), "END")]


# ---------------------------------------------------------------- hardware faults
def test_gate_driver_fault_immediate(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(2.0) + [kv_event(int(1.0 * US), "FAULT", gdf=True)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    before = at(rows, 0.99)
    assert before["state"] == "MANUAL" and float(before["accepted_Nm"]) > 0.5
    after = [r for r in rows if float(r["t_s"]) >= 1.001]
    assert after[0]["state"] == "FAULT_LATCHED"
    assert all(float(r["accepted_Nm"]) == 0.0 and r["pwm_enable"] == "0" for r in after)


def test_hw_overcurrent_trip_overrides_everything(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(1.5) + [kv_event(int(1.0 * US), "FAULT", hw_oc=True)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    after = [r for r in rows if float(r["t_s"]) >= 1.001]
    assert after[0]["state"] == "FAULT_LATCHED"
    assert all(r["pwm_enable"] == "0" for r in after)


def test_missing_speed_hall_disconnected(host_exe, synthetic_blob, tmp_path):
    # Pull-ups on a disconnected hall harness read 111 (illegal).
    ev = manual_drive(2.0) + [kv_event(int(1.0 * US), "FAULT", hall_stuck=True, hall_code=7)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    r = at(rows, 1.05)
    assert r["state"] == "FAULT_LATCHED"
    assert int(r["faults_latched"]) & (1 << 10)  # MC_F_HALL_INVALID


def test_stuck_speed_detected_as_stall(host_exe, synthetic_blob, tmp_path):
    # Hall stuck at a LEGAL code while the driver demands torque: the code alone
    # cannot reveal it; the stall check (high iq, no edge for 1 s) must.
    ev = manual_drive(4.0, throttle=0.9) + [kv_event(int(1.5 * US), "FAULT", hall_stuck=True, hall_code=1)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    tripped = [r for r in rows if int(r["faults_latched"]) & (1 << F_SEMMC_STALL)]
    assert tripped, "stuck hall not detected"
    t_trip = float(tripped[0]["t_s"])
    assert 2.4 <= t_trip <= 3.2


def test_low_speed_crawl_is_not_a_stall(host_exe, synthetic_blob, tmp_path):
    # Normal event: crawling at low speed produces slow hall pulses, no fault.
    ev = manual_drive(6.0, throttle=0.12)
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    assert all(int(r["faults_latched"]) == 0 for r in rows)
    assert 0.05 < float(rows[-1]["v_mps"]) < 3.0


def test_two_phase_currents_missing_is_a_fault(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(2.0) + [kv_event(int(1.0 * US), "FAULT", miss_a=True, miss_b=True)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    r = at(rows, 1.01)
    assert r["state"] == "FAULT_LATCHED"
    assert int(r["faults_latched"]) & (1 << 11)  # MC_F_CURRENT_SENSE_INVALID


def test_biased_current_visible_in_kcl_residual(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(2.0) + [kv_event(int(1.0 * US), "FAULT", bias_a=0.6)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    assert all(r["state"] == "MANUAL" for r in rows if float(r["t_s"]) > 1.0)
    frames = [ln.split() for ln in (tmp_path / "tx.log").read_text().splitlines() if " CAN 319 " in ln]
    resid = []
    for t, _k, cid, hx in frames:
        v, info = proto.decode(int(cid, 16), bytes.fromhex(hx))
        if int(t) > 1.2 * US and v["kcl_available"]:
            resid.append(v["kcl_residual_A"])
    assert resid, "no KCL residual frames with three valid shunts"
    mean = sum(resid) / len(resid)
    assert 0.4 < mean < 0.8  # the 0.6 A bias shows up; it is NOT silently absorbed


def test_temperature_derating_then_trip(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(4.0, throttle=1.0) + [kv_event(int(1.5 * US), "FAULT", tfet_offset=65.0),
                                            kv_event(int(3.0 * US), "FAULT", tfet_offset=90.0)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    mid = at(rows, 2.5)
    assert mid["state"] == "DERATED" and float(mid["derate"]) < 1.0 and int(mid["faults_latched"]) == 0
    end = at(rows, 3.1)
    assert end["state"] == "FAULT_LATCHED" and int(end["faults_latched"]) & (1 << 8)


def test_temperature_sensor_lost_derates_not_trips(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(2.5, throttle=1.0) + [kv_event(int(1.5 * US), "FAULT", tmotor_nan=True)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    r = at(rows, 2.4)
    assert int(r["faults_latched"]) == 0
    assert math.isclose(float(r["derate"]), 0.5, abs_tol=1e-3)


def test_bus_voltage_sensor_nan_faults(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(2.0) + [kv_event(int(1.0 * US), "FAULT", vbus_nan=True)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    r = at(rows, 1.01)
    assert r["state"] == "FAULT_LATCHED" and int(r["faults_latched"]) & (1 << 12)


def test_hill_climb_acceleration_is_not_a_fault(host_exe, synthetic_blob, tmp_path):
    # Normal event: hard acceleration up a 3 % grade with battery sag.
    ev = manual_drive(6.0, throttle=1.0) + [kv_event(int(2.0 * US), "FAULT", grade=0.03)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    assert all(int(r["faults_latched"]) == 0 for r in rows)
    assert all(r["rectifying"] == "0" for r in rows)


# ---------------------------------------------------------------- driver / startup
def test_driver_cancel_and_brake_override(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(3.0, throttle=0.8) + [io_event(int(1.5 * US), brake=True), io_event(int(2.0 * US), brake=False)]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    assert float(at(rows, 1.499)["accepted_Nm"]) > 1.0
    assert float(at(rows, 1.501)["accepted_Nm"]) == 0.0  # immediate, no slew
    # Brake released with pedal held: torque resumes only by slew from zero (manual owner kept).
    assert float(at(rows, 2.05)["accepted_Nm"]) < 0.4


def test_invalid_startup_never_outputs(host_exe, tmp_path):
    unconf = tmp_path / "unconf.bin"
    subprocess.run(["python3", str(ROOT / "tools" / "config_tool.py"), "blob",
                    str(ROOT / "config" / "vehicle.unconfigured.yaml"), "--mode", "sim", "--allow-invalid",
                    "-o", str(unconf)], capture_output=True, check=False)
    ev = [io_event(0, arm=False), io_event(int(0.1 * US), arm=True), io_event(int(0.2 * US), throttle=1.0),
          io_event(int(0.5 * US), reset=True), Event(int(1.0 * US), "END")]
    rows, out = run_log(host_exe, unconf, tmp_path, ev, extra=["--no-plant"])
    assert "config_ok=0" in out
    assert all(float(r["accepted_Nm"]) == 0.0 and r["pwm_enable"] == "0" for r in rows)
    assert rows[-1]["state"] == "FAULT_LATCHED"


def test_hardware_build_with_synthetic_never_outputs(host_exe, synthetic_blob, tmp_path):
    ev = manual_drive(1.0, throttle=1.0)
    rows, out = run_log(host_exe, synthetic_blob, tmp_path, ev, extra=["--build", "hardware"])
    assert "config_ok=0" in out
    assert all(float(r["accepted_Nm"]) == 0.0 and r["pwm_enable"] == "0" for r in rows)


def test_fault_recovery_does_not_resume(host_exe, synthetic_blob, tmp_path):
    ev = [io_event(0, arm=False, throttle=0.0), io_event(int(0.1 * US), arm=True),
          io_event(int(0.2 * US), throttle=0.7),
          kv_event(int(1.0 * US), "FAULT", gdf=True), kv_event(int(1.2 * US), "FAULT", gdf=False),
          io_event(int(1.4 * US), throttle=0.0), io_event(int(1.5 * US), reset=True),
          io_event(int(1.6 * US), reset=False, throttle=0.7),  # pedal pressed again, arm switch still ON
          Event(int(3.0 * US), "END")]
    rows, _ = run_log(host_exe, synthetic_blob, tmp_path, ev)
    assert at(rows, 1.55)["state"] == "DISARMED"
    assert all(float(r["accepted_Nm"]) == 0.0 for r in rows if float(r["t_s"]) >= 1.0)
    assert rows[-1]["state"] == "DISARMED"


# ---------------------------------------------------------------- supervisory link
def test_repeated_cached_sample_does_not_keep_eco_alive(build_dir, tmp_path):
    def freeze(t_s, sup, hc):
        if 5.0 <= t_s and sup.frozen is None:
            sup.frozen = (1.0, False, int(round(t_s * 1000)) & 0xFFFF)
    r = run(Scenario(duration_s=6.0, supervisor_off_at_s=None, on_step=freeze), build_dir, tmp_path)
    lost = next(s for s in r.steps if s.t_us > 1e6 and s.state != "ECO_ASSIST")
    assert lost.state == "READY"
    assert 5.08e6 <= lost.t_us <= 5.14e6  # 100 ms after the last NEW sample (+ step granularity)


def test_supervisor_reboot_ends_eco_and_needs_new_edge(build_dir, tmp_path):
    def reboot(t_s, sup, hc):
        if abs(t_s - 4.0) < 1e-9:
            sup.cfg.session_id = 0xBADC0DE5  # companion rebooted: new session
            sup.tag = 0
            sup.next_hello = t_s
    r = run(Scenario(duration_s=8.0, supervisor_off_at_s=None, on_step=reboot), build_dir, tmp_path)
    before = [s for s in r.steps if 1e6 < s.t_us < 4e6]
    after = [s for s in r.steps if s.t_us > 4.2e6]
    assert all(s.state == "ECO_ASSIST" for s in before)
    assert all(s.state == "READY" for s in after)
    assert all(s.accepted_Nm == 0.0 for s in after)
    assert r.supervisor.tag != 0  # re-handshake completed, but no automatic re-engagement


def test_controller_reboot_during_active_request(build_dir, tmp_path):
    def reset(t_s, sup, hc):
        if abs(t_s - 3.0) < 1e-9:
            hc.send([Event(int(t_s * US), "RESET")])
    r = run(Scenario(duration_s=6.0, supervisor_off_at_s=None, on_step=reset), build_dir, tmp_path)
    after = [s for s in r.steps if s.t_us > 3.0e6]
    assert all(s.accepted_Nm == 0.0 for s in after)
    assert {s.state for s in after} <= {"BOOT", "SELF_TEST", "DISARMED"}
    assert "rx_tag_mismatch=" in r.summary


def test_bus_off_and_reordered_frames(host_exe, synthetic_blob, build_dir, tmp_path):
    # Reordered: deliver an older request after a newer one; the controller ignores it.
    seen = {}

    def reorder(t_s, sup, hc):
        if abs(t_s - 2.0) < 1e-9:
            data, _, _ = proto.encode("sup_torque_req", {"session_tag": sup.tag, "limits_ref": sup.limits_seq & 0xF,
                                                         "coast_request": False, "reserved": 0, "torque_Nm": 2.0,
                                                         "src_time_ms": int(1990)}, (sup.seq["sup_torque_req"] - 3) & 0xFF)
            hc.send([can_event(int(t_s * US), proto.MESSAGES["sup_torque_req"]["id"], data)])
        if abs(t_s - 4.0) < 1e-9:
            hc.send([Event(int(t_s * US), "BUSOFF", "1")])
            seen["busoff"] = True
    r = run(Scenario(duration_s=4.5, supervisor_off_at_s=None, on_step=reorder), build_dir, tmp_path)
    mid = [s for s in r.steps if 1.0e6 < s.t_us < 4.0e6]
    assert all(s.state == "ECO_ASSIST" for s in mid)
    end = [s for s in r.steps if s.t_us >= 4.02e6]
    assert all(s.state == "READY" and s.accepted_Nm == 0.0 for s in end)


def test_malformed_frames_rejected_without_side_effects(build_dir, tmp_path):
    def garbage(t_s, sup, hc):
        if 2.0 <= t_s < 3.0:
            good, _, _ = proto.encode("sup_torque_req", {"session_tag": sup.tag, "limits_ref": sup.limits_seq & 0xF,
                                                         "coast_request": False, "reserved": 0, "torque_Nm": 2.0,
                                                         "src_time_ms": int(round(t_s * 1000)) + 5}, 77)
            bad = bytearray(good)
            bad[4] ^= 0x40  # corrupted torque bits
            hc.send([can_event(int(t_s * US), proto.MESSAGES["sup_torque_req"]["id"], bytes(bad)),
                     can_event(int(t_s * US), proto.MESSAGES["sup_limits"]["id"], bytes(8))])
    r = run(Scenario(duration_s=4.0, supervisor_off_at_s=None, on_step=garbage), build_dir, tmp_path)
    mid = [s for s in r.steps if 1.0e6 < s.t_us < 4.0e6]
    assert all(s.state == "ECO_ASSIST" for s in mid)
    assert "rx_crc_fail=" in r.summary and "rx_crc_fail=0" not in r.summary


def test_nan_request_exits_eco(build_dir, tmp_path):
    def nanreq(t_s, sup, hc):
        if t_s >= 2.0:
            sup.policy = lambda t, tel: (float("nan"), False)
    r = run(Scenario(duration_s=3.0, supervisor_off_at_s=None, on_step=nanreq), build_dir, tmp_path)
    after = [s for s in r.steps if s.t_us >= 2.05e6]
    assert all(s.state == "READY" and s.accepted_Nm == 0.0 for s in after)
