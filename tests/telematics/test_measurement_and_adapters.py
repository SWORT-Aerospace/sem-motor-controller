"""Measurement model, signal registry and controller receive adapters (host/telematics)."""
import math
import pathlib

import pytest
import yaml

from host.telematics import controller_adapter as ca
from host.telematics import signals
from host.telematics.measurement import LatestTable, Measurement, checked
from protocol.generated import semmc_protocol as proto

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _m(**kw):
    base = dict(record_id=1, source="controller", signal="ctrl.dc_voltage", value=48.0, unit="V", t_rx_us=1000,
                t_sample_us=None, t_unc_us=10_000, source_seq=3, validity="valid", provenance="test",
                t_unc_basis="assumed")
    base.update(kw)
    return Measurement(**base)


def test_measurement_refuses_values_that_hide_missing_data():
    with pytest.raises(ValueError):
        _m(validity="invalid")                       # an invalid measurement carries no value
    with pytest.raises(ValueError):
        _m(value=None)                               # a valid one needs a value
    with pytest.raises(ValueError):
        _m(value=math.nan)
    with pytest.raises(ValueError):
        _m(unit="mV")                                # the registry fixes the unit
    with pytest.raises(ValueError):
        _m(signal="ctrl.unknown")
    m = _m()
    assert m.t_ref_us == 1000 and m.age_us(4000) == 3000      # no sample time: the receive time is the reference
    assert _m(t_sample_us=900).t_ref_us == 900


def test_checked_classifies_sentinels_ranges_and_flags():
    assert checked(1, "controller", "ctrl.dc_voltage", 999.0, "V", 0, provenance="t").validity == "out_of_range"
    assert checked(1, "controller", "ctrl.dc_voltage", math.nan, "V", 0, provenance="t").validity == "invalid"
    assert checked(1, "controller", "ctrl.dc_voltage", 48.0, "V", 0, provenance="t", confirmed=None).validity == "unverified"
    assert checked(1, "controller", "ctrl.dc_voltage", 48.0, "V", 0, provenance="t", confirmed=False).value is None
    assert signals.lookup("wheel.front_left.speed").unit == "m/s"
    assert signals.lookup("temp.ambient").role == "environment"
    roles = {s.role for s in signals.REGISTRY}
    assert set(signals.ROLES) == roles
    assert {s.id for s in signals.by_role("energy_essential")} == {"ctrl.dc_voltage", "ctrl.dc_current"}


def test_latest_table_reports_missing_and_stale_as_null():
    t = LatestTable()
    t.put(_m(t_rx_us=0))
    out = t.summary(200_000, ["ctrl.dc_voltage", "ctrl.dc_current"])
    assert out["ctrl.dc_voltage"]["v"] == 48.0 and out["ctrl.dc_voltage"]["q"] == "valid"
    assert out["ctrl.dc_current"] == {"v": None, "u": "A", "q": "missing", "age_ms": None, "seq": None, "ts": None}
    stale = t.summary(400_000, ["ctrl.dc_voltage"])["ctrl.dc_voltage"]        # stale after 0.3 s
    assert stale["q"] == "stale" and stale["v"] is None and stale["age_ms"] == 400
    t.put(_m(t_rx_us=410_000, value=None, validity="invalid"))                # a newer invalid value replaces it
    assert t.summary(420_000, ["ctrl.dc_voltage"])["ctrl.dc_voltage"]["q"] == "invalid"


def _frame(name, values, seq=0):
    data, _s, _i = proto.encode(name, values, seq)
    return ca.Frame(proto.MESSAGES[name]["id"], data)


MOTION = {"speed_mech_rad_s": 120.0, "iq_A": 10.0, "vbus_V": 49.5}
VALID = {k: True for k in ("v_speed", "v_ia", "v_ib", "v_ic", "v_vbus", "v_ibatt", "v_t_fet", "v_t_motor", "v_throttle",
                           "v_sup_req", "v_sup_limits", "v_hall")}


def test_sim_fixture_takes_sequence_from_the_protocol_and_invents_no_sample_time():
    a = ca.SimFixtureAdapter()
    r = a.decode(1_000, _frame("ctrl_motion", MOTION, seq=17))
    assert r.kind == "decoded" and r.message == "ctrl_motion"
    by = {m.signal: m for m in r.measurements}
    v = by["ctrl.dc_voltage"]
    assert v.source_seq == 17 and v.t_sample_us is None and v.t_rx_us == 1_000
    assert v.t_unc_us == 10_000                         # one ctrl_motion period: ASSUMED latency bound
    assert v.validity == "unverified"                   # no ctrl_validity received yet
    assert by["ctrl.phase_current_q"].validity == "valid"   # no validity flag defined for iq in the fixture
    assert [m.record_id for m in r.measurements] == [1, 2, 3]   # local record ids, unrelated to the source's seq
    a.decode(2_000, _frame("ctrl_validity", VALID))
    assert {m.signal: m for m in a.decode(3_000, _frame("ctrl_motion", MOTION, 18)).measurements}[
        "ctrl.dc_voltage"].validity == "valid"
    # the flag goes stale after 0.3 s: unverified again, never silently valid
    later = {m.signal: m for m in a.decode(400_000, _frame("ctrl_motion", MOTION, 19)).measurements}
    assert later["ctrl.dc_voltage"].validity == "unverified"


def test_sim_fixture_flags_sentinels_crc_errors_and_companion_frames():
    a = ca.SimFixtureAdapter()
    a.decode(0, _frame("ctrl_validity", dict(VALID, v_vbus=False)))
    by = {m.signal: m for m in a.decode(1, _frame("ctrl_motion", dict(MOTION, iq_A=math.nan))).measurements}
    assert by["ctrl.phase_current_q"].validity == "invalid" and by["ctrl.phase_current_q"].value is None
    assert by["ctrl.dc_voltage"].validity == "invalid" and by["ctrl.dc_voltage"].value is None
    f = _frame("ctrl_motion", MOTION)
    bad = ca.Frame(f.can_id, bytes([f.data[0] ^ 1]) + f.data[1:])
    r = a.decode(2, bad)
    assert r.kind == "invalid" and r.measurements == [] and r.detail == "bad_crc"
    assert a.decode(3, ca.Frame(f.can_id, f.data[:7])).kind == "invalid"
    assert a.decode(4, ca.Frame(0x123, bytes(8))).kind == "unknown_id"
    assert a.decode(5, ca.Frame(f.can_id, f.data, extended=True)).kind == "unknown_id"
    sup, _s, _i = proto.encode("sup_torque_req", {"session_tag": 1, "limits_ref": 0, "coast_request": False,
                                                 "reserved": 0, "torque_Nm": 1.0, "src_time_ms": 5}, 0)
    r = a.decode(6, ca.Frame(proto.MESSAGES["sup_torque_req"]["id"], sup))
    assert r.kind == "ignored" and r.measurements == [] and a.companion_frames == 1


def _mapping(tmp_path, unit="V"):
    m = {"adapter_id": "semmc-dbc-crosscheck", "status": "test: the semmc DBC read through the generic DBC path",
         "dbc": str(ROOT / "protocol" / "generated" / "semmc_base0x300.dbc"),
         "sequence": {"ctrl_motion": "seq", "ctrl_currents": "seq"},
         "signals": [{"message": "ctrl_motion", "signal": "vbus_V", "dbc_unit": unit, "to": "ctrl.dc_voltage",
                      "invalid_raw": [65535], "latency_bound_ms": 10},
                     {"message": "ctrl_motion", "signal": "speed_mech_rad_s", "dbc_unit": "rad/s",
                      "to": "ctrl.motor_speed", "invalid_raw": [-32768]},
                     {"message": "ctrl_currents", "signal": "ibatt_A", "dbc_unit": "A", "to": "ctrl.dc_current",
                      "invalid_raw": [-32768]}]}
    p = tmp_path / "mapping.yaml"
    p.write_text(yaml.safe_dump(m))
    return p


def test_dbc_adapter_matches_the_fixture_on_the_same_frames(tmp_path):
    pytest.importorskip("cantools")
    a = ca.DbcAdapter(_mapping(tmp_path))
    f = ca.SimFixtureAdapter()
    fr = _frame("ctrl_motion", MOTION, seq=42)
    d = {m.signal: m for m in a.decode(5, fr).measurements}
    s = {m.signal: m for m in f.decode(5, fr).measurements}
    assert math.isclose(d["ctrl.dc_voltage"].value, s["ctrl.dc_voltage"].value, abs_tol=1e-9)
    assert math.isclose(d["ctrl.motor_speed"].value, s["ctrl.motor_speed"].value, abs_tol=1e-9)
    assert d["ctrl.dc_voltage"].source_seq == 42 and d["ctrl.dc_voltage"].t_sample_us is None
    assert d["ctrl.dc_voltage"].t_unc_us == 10_000
    nan = _frame("ctrl_motion", dict(MOTION, vbus_V=math.nan))
    assert {m.signal: m for m in a.decode(6, nan).measurements}["ctrl.dc_voltage"].validity == "invalid"
    assert a.decode(7, ca.Frame(0x7FF, bytes(8))).kind == "unknown_id"
    assert a.decode(8, _frame("ctrl_thermal", {"t_fet_degC": 30.0, "t_motor_degC": 30.0, "derate": 0.0,
                                               "derate_reasons": 0})).kind == "ignored"


def test_dbc_adapter_refuses_a_unit_mismatch(tmp_path):
    pytest.importorskip("cantools")
    with pytest.raises(ValueError, match="unit"):
        ca.DbcAdapter(_mapping(tmp_path, unit="mV"))
