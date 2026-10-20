"""CSIA vehicle adapter (shadow mode) - synthetic multi-sensor scenarios."""
import collections
import math
import pathlib

import pytest

from host.csia_adapter.adapter import Explain, Sample, SignalTracker, VehicleCsiaAdapter
from host.csia_adapter.baselines import ResidualThreshold
from host.csia_adapter.synthetic import Fault, Scenario, generate, params, run
from host.telemetry_adapter.e2e import Scenario as E2EScenario, run as run_e2e
from protocol.generated import semmc_protocol as proto

ROOT = pathlib.Path(__file__).resolve().parents[2]


def adapter():
    return VehicleCsiaAdapter(params())


@pytest.fixture(scope="module")
def nominal():
    return run(adapter, Scenario())


def test_pinned_csia_core_is_used():
    ad = adapter()
    assert ad.csia_version == "0.8.0"
    assert ".deps" in ad.csia_path or "SEMMC_CSIA_PATH" in str(ad.csia_path) or ad.csia_path
    assert not ad.restriction_permitted()        # shadow mode only (ADR-0008)


def test_normal_events_are_not_faults(nominal):
    # cornering, start slip, freewheel decoupling, grade, GNSS degradation, low speed
    assert not [s for s in nominal if s.suspects]
    assert not [s for s in nominal if s.ambiguous]
    # the 20 ms tick budget is wall-clock time on the host running the test (one scheduler or GC pause on a
    # shared CI runner trips it); every other monitor note is deterministic. Host timing: test_host_tick_time_recorded
    assert not [n for s in nominal for n in s.monitor_notes if not n.startswith("tick took")]
    assert sum(s.monitor_ok for s in nominal) >= 0.99 * len(nominal)
    codes = collections.Counter(s.explanation for s in nominal)
    assert codes[Explain.OK_CONSISTENT] > 0.9 * len(nominal)


def test_gnss_degradation_is_gated_not_blamed(nominal):
    deg = [s for s in nominal if 61.0 <= s.t <= 79.0]
    assert all(math.isnan(s.lambdas["E3a_gnss_wheel_l"]) for s in deg)   # evidence withdrawn
    assert all("gnss" not in s.suspects for s in deg)


@pytest.mark.parametrize("fault,node,max_latency", [
    (Fault("wheel_l_dropout", 40, 60), "wheel_l", 0.5),
    (Fault("gnss_offset", 30, 50, 1.5), "gnss", 0.5),
    (Fault("imu_bias", 30, 50, 0.8), "imu", 5.0),
    (Fault("current_bias", 30, 50, 0.8), "phase_current", 0.5),
    (Fault("rotor_stuck", 40, 70), "rotor", 10.0),     # observable only while driving (next pulse at ~48 s)
    (Fault("dc_gain", 40, 70, 1.4), "dc_meter", 12.0),  # idem
])
def test_fault_attributed_correctly_never_misattributed(fault, node, max_latency):
    st = run(adapter, Scenario(faults=(fault,)))
    first = next((s.t for s in st if s.t >= fault.t0 and node in s.suspects), None)
    assert first is not None and first - fault.t0 <= max_latency
    wrong = {x for s in st for x in s.suspects if x != node}
    assert not wrong, wrong


def test_disagreement_without_corroboration_is_ambiguous():
    # Only the two front wheels remain as mutual witnesses: no GNSS, no IMU.
    st = run(adapter, Scenario(faults=(Fault("wheel_l_dropout", 40, 60),), gnss_available=False, imu_available=False))
    window = [s for s in st if 40.5 <= s.t < 60]
    assert not any(s.suspects for s in window)  # never forced single-sensor blame
    # with no IMU there is no yaw correction, so E2 is gated: the fault is unobservable, and says so
    assert all(s.observability in (2, 3) or s.explanation in (Explain.NO_EVIDENCE, Explain.REGIME_GATED,
                                                               Explain.DISAGREE_AMBIGUOUS) for s in window)


def test_freshness_separate_from_trust():
    ad = adapter()
    data = generate(Scenario(duration_s=30.0))
    for t_rx, name, s in data:
        if t_rx <= 20.0:
            ad.ingest(name, s)
    for j in range(1, 201):
        st = ad.tick(j * 0.1)
    trust_before = dict(st.trust)
    later = None
    for j in range(201, 260):            # inputs stop at 20 s
        later = ad.tick(j * 0.1)
    # CSIA holds its Beta belief without evidence (absence is not 0.5)...
    assert later.trust["rotor"] == pytest.approx(trust_before["rotor"], abs=1e-9)
    # ...so the adapter reports separately that it is not current
    assert not later.trust_current["rotor"] and not any(later.fresh.values())
    assert later.explanation == Explain.STALE_INPUTS
    vals = ad.advisory_values(later)
    assert math.isnan(vals["trust"]) and vals["evidence_fresh"] is False
    data_ok, _, _ = proto.encode("csia_advisory", vals, 1)  # NaN encodes as the sentinel
    assert proto.decode("csia_advisory", data_ok)[0]["trust"] != proto.decode("csia_advisory", data_ok)[0]["trust"]


def test_repeated_cached_sample_does_not_renew():
    tr = SignalTracker(window_s=0.1)
    s = Sample(5.0, 0.1, src_t=1.0, clock="c", rx_t=1.0, seq=1)
    assert tr.update(s)
    assert not tr.update(Sample(5.0, 0.1, 1.0, "c", 1.05, 1))       # duplicate
    assert not tr.update(Sample(5.0, 0.1, 1.0, "c", 1.08, 2))       # new seq, same source time
    assert not tr.fresh(1.15)
    assert tr.update(Sample(5.1, 0.1, 1.2, "c", 1.2, 3))
    assert tr.fresh(1.25)


def test_reconstructed_phase_is_not_kcl_evidence():
    ad = adapter()
    t = 0.0
    for k in range(30):
        t = 0.01 * k
        ad.ingest("kcl", Sample(2.5, 0.1, t, "controller", t, k, 1, {"kcl_available": False}))
        ad.ingest("iq", Sample(0.0, 0.15, t, "controller", t, k, 1))
    st = ad.tick(0.3)
    assert "phase_current" not in st.suspects
    assert st.evidence["phase_current"] == 0


def test_conventional_baseline_has_nuisance_alarms_adapter_does_not(nominal):
    b2 = ResidualThreshold(params())
    data = generate(Scenario())
    k, alarms = 0, 0
    for j in range(1, 1200):
        t = j * 0.1
        while k < len(data) and data[k][0] <= t:
            b2.ingest(data[k][1], data[k][2])
            k += 1
        alarms += bool(b2.tick(t))
    assert alarms > 100
    assert sum(1 for s in nominal if s.suspects or s.ambiguous) == 0


def test_host_tick_time_recorded(nominal):
    mean = sum(s.elapsed_s for s in nominal) / len(nominal)
    assert mean < 0.02  # host benchmark only - not a target timing claim


def test_shadow_mode_never_changes_controller_commands(build_dir, tmp_path):
    """Same co-simulation with and without (hostile) advisory frames: identical commands."""
    def hostile(t_s, sup):
        if sup.tag == 0:
            return None
        data, _, _ = proto.encode("csia_advisory", {"trust": 0.0, "mode": 2, "observability": 2, "monitor_ok": False,
                                                    "evidence_fresh": True, "reserved": 0, "evidence_mask": 0xFF,
                                                    "explanation": int(Explain.SUSPECT_ROTOR_SPEED),
                                                    "src_time_ms": int(t_s * 1000) & 0xFFFF}, int(t_s * 50) & 0xFF)
        return data
    a = run_e2e(E2EScenario(duration_s=6.0, supervisor_off_at_s=None), build_dir, tmp_path / "a")
    b = run_e2e(E2EScenario(duration_s=6.0, supervisor_off_at_s=None, advisory=hostile), build_dir, tmp_path / "b")
    assert [s.accepted_Nm for s in a.steps] == [s.accepted_Nm for s in b.steps]
    assert [s.state for s in a.steps] == [s.state for s in b.steps]
