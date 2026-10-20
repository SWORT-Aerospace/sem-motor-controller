"""The evidence model: schema, evidence states, stream timing, lineage and vehicle context (HOST-TESTED).

These tests run on the host with synthetic inputs. They show what the analysis code does with each kind of
evidence; they say nothing about the sensors or the firmware on hardware.
"""
import copy

import pytest

from host.telematics import evidence, lineage, signals, stlg
from host.telematics import context as C
from host.telematics.measurement import Measurement, checked
from host.telematics.timing import StreamTiming
from host.telematics.wheel import EdgeRecord, WheelConfig, WheelGroup
from tools import telematics_schema as TS


def m(signal, value, t, validity="valid", unc=1_000, source=None, seq=None, upper=None, basis="measured"):
    unit = signals.lookup(signal).unit
    return Measurement(1, source or signal.split(".")[0], signal, value, unit, t, None, unc, seq, validity, "test",
                       upper, None if unc is None else basis)


# ---------------------------------------------------------------- schema and versioning
def test_schema_is_consistent_with_the_code_and_keeps_the_registry_hash():
    d = TS.load()
    assert TS.check(d) == []
    assert d["registry_id"] == signals.REGISTRY_ID == "reg-cbac7dc42d28"     # live messages and old logs still decode
    assert isinstance(d["schema_version"], int) and d["schema_version"] >= 1
    assert [s.id for s in signals.REGISTRY] == [e["id"] for e in d["signals"]]   # the registry is the schema's list


@pytest.mark.parametrize("mutate, expect", [
    (lambda d: d["signals"][0].__setitem__("unit", "mV"), "registry_id"),
    (lambda d: d["evidence_states"]["STALE"].__setitem__("admissible", True), "only VALID"),
    (lambda d: d["validity_to_state"].pop("no_evidence"), "validity_to_state"),
    (lambda d: next(e for e in d["signals"] if e["id"] == "ctrl.dc_voltage")["encoding"]["semmc"].__setitem__("scale", 0.5),
     "scale"),
    (lambda d: d["sources"]["imu"]["depends_on"].append("bus:nonexistent"), "bus:nonexistent"),
])
def test_schema_check_catches_a_changed_contract(mutate, expect):
    d = copy.deepcopy(TS.load())
    if expect == "registry_id":
        # a unit change alters the registry hash the schema states: the check refuses until both are bumped
        d["registry_id"] = "reg-000000000000"
    else:
        mutate(d)
    err = TS.check(d)
    assert err and any(expect in e for e in err), err


# ---------------------------------------------------------------- evidence states
def test_every_validity_has_one_state_and_only_valid_is_admissible():
    states = evidence.states()
    assert set(states) == TS.STATES
    assert {evidence.state_of(v) for v in ("valid", "unverified", "invalid", "out_of_range", "decode_error",
                                           "no_evidence")} <= set(states)
    for v in ("unverified", "invalid", "out_of_range", "decode_error", "no_evidence"):
        e = evidence.assess("ctrl.dc_voltage" if v != "no_evidence" else "wheel.wheel_l.speed",
                            m("ctrl.dc_voltage" if v != "no_evidence" else "wheel.wheel_l.speed",
                              48.0 if v == "unverified" else None, 0, v), 0)
        assert not e.admissible and e.reason


def test_missing_unsupported_stale_and_timing_are_distinct_and_never_zero():
    t = 10_000_000
    assert evidence.assess("ctrl.dc_voltage", None, t).state == "MISSING"
    u = evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t), t, supported=False)
    assert u.state == "UNSUPPORTED" and u.value is None
    old = evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t - 5_000_000), t)
    assert old.state == "STALE" and old.value is None and "age" in old.reason
    fresh = evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t - 10_000), t)
    assert fresh.state == "VALID" and fresh.value == 48.0 and fresh.lineage
    assert evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t, unc=None), t,
                           timing_tol_us=50_000).state == "TIMING_UNCERTAIN"
    assert evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t, unc=200_000), t,
                           timing_tol_us=50_000).state == "TIMING_UNCERTAIN"
    for e in (u, old):
        assert e.value is None                       # not 0, not False, not NaN


def test_invalid_temperature_is_invalid_and_out_of_range_is_withheld():
    bad = checked(1, "temp", "temp.motor_case", None, "degC", 0, provenance="temp-probe:ch1 crc_error", invalid=True)
    e = evidence.assess("temp.motor_case", bad, 0)
    assert e.state == "INVALID" and e.value is None and "crc_error" in e.reason
    hot = checked(1, "temp", "temp.motor_case", 900.0, "degC", 0, provenance="temp-probe:ch1 ok")
    e = evidence.assess("temp.motor_case", hot, 0)
    assert e.state == "OUT_OF_RANGE" and e.value is None
    assert stlg.TEMP_STATUS[1] == "crc_error" and stlg.TEMP_STATUS[4] == "bus_error"


# ---------------------------------------------------------------- Hall: zero speed is never "no data"
def _group():
    return WheelGroup(WheelConfig(1.5, 8), {0: "wheel_l", 1: "wheel_r"})


def test_hall_no_edge_is_unknown_with_a_bound_not_zero():
    g, period = _group(), 50_000
    out = []
    for k in range(1, 6):                                 # 2 edges per record: moving
        out += g.feed(EdgeRecord(k * period, 0, 2, period // 2, 2 * k, 0, k - 1, 0))
        g.feed(EdgeRecord(k * period, 1, 2, period // 2, 2 * k, 0, k - 1, 0))
    assert out[-2].signal.endswith(".speed") and out[-2].validity == "valid" and out[-2].value > 0
    # then no edge on channel 0 for 1 s while channel 1 keeps moving: first UNKNOWN with a bound, then INVALID
    states = []
    for k in range(6, 30):
        r0 = g.feed(EdgeRecord(k * period, 0, 0, 0, 10, stlg_flags(high=True), k - 1, 0))
        g.feed(EdgeRecord(k * period, 1, 2, period // 2, 2 * k, 0, k - 1, 0))
        states += [(evidence.assess(x.signal, x, k * period).state, x.value, x.upper) for x in r0
                   if x.signal.endswith(".speed")]
    assert states[0][0] == "UNKNOWN" and states[0][1] is None and states[0][2] > 0      # v < pitch / dt
    assert states[-1][0] == "INVALID" and states[-1][1] is None                      # suspect: disconnected
    assert all(v is None for _s, v, _u in states)                                    # never 0 m/s


def test_hall_channel_that_never_moved_gives_no_speed_and_no_standstill():
    g = _group()
    out = g.feed(EdgeRecord(50_000, 0, 0, 0, 0, stlg_flags(high=False), 0, 0))
    speeds = [x for x in out if x.signal.endswith(".speed")]
    assert all(x.value is None and x.validity != "valid" for x in speeds)
    ev = {"wheel.wheel_l.speed": evidence.assess("wheel.wheel_l.speed", speeds[0] if speeds else None, 50_000)}
    ctx = C.classify(ev, 30.0)
    assert ctx.mode != "STOPPED"                                                      # a held line is not standstill


def stlg_flags(high: bool) -> int:
    from host.telematics.wheel import FLAG_HEARTBEAT, FLAG_LINE_HIGH
    return FLAG_HEARTBEAT | (FLAG_LINE_HIGH if high else 0)


# ---------------------------------------------------------------- stream timing
def test_timing_in_order_gap_duplicate_reorder_and_wrap():
    s = StreamTiming("can:x", 10_000, 8)
    kinds = [s.observe(t * 10_000, q).kind for t, q in enumerate([250, 251, 252, 255, 255, 254, 0, 1])]
    assert kinds == ["first", "in_order", "in_order", "gap", "duplicate", "reordered", "in_order", "in_order"]
    r = s.report()
    assert (r["lost"], r["gaps"], r["duplicates"], r["reordered"], r["wraps"]) == (2, 1, 1, 1, 1)


def test_timing_late_burst_and_wait_bound():
    s = StreamTiming("can:x", 10_000, 8)
    for k in range(5):
        assert s.observe(k * 10_000, k).wait_bound_us is None
    late = s.observe(100_000, 5)                     # 60 ms after the previous: late
    assert late.late and late.wait_bound_us == 60_000
    b = s.observe(100_500, 6)                        # released queue: a burst, bounded from the last in-time frame
    assert b.burst and b.wait_bound_us == 60_500
    n = s.observe(110_500, 7)                        # back to normal
    assert n.wait_bound_us is None and not n.late
    assert s.report()["late"] == 1 and s.report()["bursts"] == 1 and s.report()["wait_bounded"] == 2


def test_timing_long_silence_is_ambiguous_not_a_small_gap():
    s = StreamTiming("can:x", 10_000, 8)
    s.observe(0, 10)
    a = s.observe(3_000_000, 12)                     # 3 s silence: the 8-bit counter wrapped about once
    assert a.kind == "ambiguous" and a.lost == 299
    assert s.report()["lost_estimated_from_time"] == 299


def test_timing_missing_stale_and_backwards_receive_time():
    s = StreamTiming("gnss", 100_000)
    assert s.state(5_000_000, 500_000) == "MISSING"
    s.observe(1_000_000)
    assert s.state(1_200_000, 500_000) == "VALID" and s.state(2_000_000, 500_000) == "STALE"
    assert s.observe(900_000).rx_backwards and s.report()["rx_backwards"] == 1
    assert s.report()["latency"].startswith("not observable")      # no producer timestamp


def test_timing_latency_variation_needs_a_producer_timestamp():
    s = StreamTiming("x", 10_000)
    for k, lat in enumerate((500, 700, 2_500)):
        s.observe(k * 10_000 + lat, t_src_us=k * 10_000)
    assert s.report()["latency_variation_max_us"] == 2_000


def test_record_times_in_a_log_are_monotonic_per_source(tmp_path):
    from host.telematics import sim_session
    from host.telematics.sim_vehicle import Faults
    r = sim_session.simulate(tmp_path, Faults(), 8.0)
    _meta, recs, rr = stlg.read(r["runs"][0][1])
    assert rr.blocks_corrupt == 0
    last = {}
    for _b, _i, t, rtype, f in recs:
        key = (rtype, f.get("channel")) if rtype == stlg.WHEEL_EDGES else rtype
        if rtype in (stlg.WHEEL_EDGES, stlg.IMU, stlg.GNSS, stlg.COUNTERS2):
            assert t >= last.get(key, 0), (rtype, t)
            last[key] = t


# ---------------------------------------------------------------- lineage
def test_lineage_separates_same_source_from_shared_path():
    assert lineage.raw_sources("wheel.wheel_l.speed") == {"wheel:wheel_l.edges"}
    ok, cav = lineage.independent_witnesses("wheel.wheel_l.speed", "wheel.wheel_r.speed")
    assert ok and any("power:sensor_supply" in c for c in cav)          # independent sensors, one shared supply
    ok, _ = lineage.independent_witnesses("wheel.wheel_l.speed", "gnss.speed")
    assert ok
    assert not lineage.independent_witnesses("ctrl.motor_speed", "speed.from_motor")[0]   # one witness, not two
    assert "bus:i2c1" in lineage.shared_paths("imu.ax", "temp.motor_case")
    c = lineage.contributors(["energy.per_distance"])
    assert "wheel.circumference_m" in c["parameters"] and "unit:recorder" in c["shared_paths"]
    assert "power:unit_supply" in lineage.paths_of("imu.ax")                  # 3.3 V is fed by the unit supply


# ---------------------------------------------------------------- context
def _ev(**vals):
    out = {}
    for sig, v in vals.items():
        sig = sig.replace("__", ".")
        out[sig] = evidence.assess(sig, m(sig, v, 0), 0)
    return out


def test_context_needs_admissible_evidence_and_never_guesses_brake():
    assert C.classify({}, 1.0).mode == "STARTUP"
    assert C.classify(_ev(gnss__speed=0.1), 30.0).mode == "STOPPED"
    assert C.classify(_ev(wheel__wheel_l__speed=6.0), 30.0, 0.0).mode == "CRUISE"
    assert C.classify(_ev(wheel__wheel_l__speed=6.0), 30.0).mode == "UNKNOWN"          # no acceleration evidence
    coast = C.classify(_ev(gnss__speed=6.0, ctrl__dc_current=0.1), 30.0, -0.4)
    assert coast.mode == "COAST" and coast.effort is False
    unk = C.classify(_ev(gnss__speed=6.0), 30.0, -0.4)
    assert unk.mode == "UNKNOWN" and "effort unknown" in unk.reason
    assert set(C.NOT_DETERMINABLE) == {"BRAKE", "READY"} and "BRAKE" not in C.MODES
    stale = {"gnss.speed": evidence.assess("gnss.speed", m("gnss.speed", 0.0, 0), 10_000_000)}
    assert C.classify(stale, 30.0).mode == "UNKNOWN"                                # a stale zero is not STOPPED


def test_motor_speed_shows_stopped_only_without_a_freewheel():
    ev = _ev(ctrl__motor_speed=0.0)
    assert C.classify(ev, 30.0).mode == "UNKNOWN"
    assert C.classify(ev, 30.0, cfg=C.ContextConfig(freewheel=False)).mode == "STOPPED"


# ---------------------------------------------------------------- timing basis
def test_an_assumed_timestamp_bound_is_not_a_bound_for_measured_data():
    t = 1_000_000
    meas = m("ctrl.dc_voltage", 48.0, t, unc=10_000, basis="assumed")
    e = evidence.assess("ctrl.dc_voltage", meas, t, timing_tol_us=250_000)
    assert e.state == "TIMING_UNCERTAIN" and "only assumed" in e.reason and not e.sample_age_known
    e = evidence.assess("ctrl.dc_voltage", meas, t, timing_tol_us=250_000, accept_assumed_timing=True)
    assert e.state == "VALID" and e.t_unc_basis == "assumed" and not e.sample_age_known
    for basis in ("measured", "documented"):
        e = evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t, basis=basis), t, timing_tol_us=250_000)
        assert e.state == "VALID" and e.sample_age_known
    e = evidence.assess("ctrl.dc_voltage", m("ctrl.dc_voltage", 48.0, t, unc=None), t, timing_tol_us=250_000)
    assert e.state == "TIMING_UNCERTAIN" and "sample age unknown" in e.reason
    with pytest.raises(ValueError):                     # a bound must say where it comes from
        Measurement(1, "ctrl", "ctrl.dc_voltage", 48.0, "V", t, None, 10_000, None, "valid", "test")


def test_producers_state_the_basis_of_their_bounds():
    from host.telematics.controller_adapter import Frame, SimFixtureAdapter
    from protocol.generated import semmc_protocol as proto
    data, _s, _i = proto.encode("ctrl_motion", {"speed_mech_rad_s": 10.0, "iq_A": 1.0, "vbus_V": 48.0}, 0)
    res = SimFixtureAdapter().decode(1000, Frame(proto.MESSAGES["ctrl_motion"]["id"], data))
    assert res.measurements and all(x.t_unc_basis == "assumed" for x in res.measurements)
    g = _group()
    out = []
    for k in range(1, 4):
        out += g.feed(EdgeRecord(k * 50_000, 0, 2, 25_000, 2 * k, 0, k - 1, 0))
    assert out and all(x.t_unc_basis == "measured" for x in out if x.t_unc_us is not None)
