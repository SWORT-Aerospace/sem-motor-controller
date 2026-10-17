"""The evaluation harness is causal and keeps labels from the diagnostic; the reference diagnosis behaves
as specified on simple episodes."""
import dataclasses
import math

import numpy as np
import pytest

from research.bea import diagnosis as D
from research.bea import episode as E
from research.bea import harness as H
from research.bea.records import Record, sequence_gaps

FRAMES = ("motion", "currents", "cmd", "wheel")


@pytest.fixture(scope="module")
def ep_none():
    return H.run_vehicle(H.draw_episode(7, "test", "none", cycle="pulse_coast"))


@pytest.fixture(scope="module")
def ep_hb():
    spec = H.draw_episode(8, "test", "HB", cycle="pulse_coast")
    spec = dataclasses.replace(spec, fault=dataclasses.replace(spec.fault, size=0.3, onset_s=20.0))
    return H.run_vehicle(spec)


def test_access_is_causal(ep_none):
    acc = H.Access(ep_none)
    acc.advance(30.0)
    t_req = acc.now_true
    nl = acc.now_local()
    eta = acc.request(H.Request("buffer", FRAMES, nl - 10.0, nl + 10.0))      # asks for 10 s of future too
    L = ep_none.spec.link
    assert eta >= t_req + L.rtt_s
    _, early = acc.advance(eta - 0.05)
    assert early == []                                                        # nothing arrives before it can
    _, resp = acc.advance(eta + 0.01)
    t_vehicle_local = L.clock.local(t_req + L.rtt_s / 2)
    for ch, r in resp[0].records.items():
        assert np.all(r["t_rx"] <= t_vehicle_local + 1e-9), ch                # no record from after the request
        assert "t_true" not in r and "t_rx_true" not in r                    # scoring-only fields stripped
    with pytest.raises(ValueError):
        acc.advance(10.0)                                                     # time runs forward only


def test_capture_delivers_after_its_window(ep_none):
    acc = H.Access(ep_none)
    acc.advance(20.0)
    eta = acc.request(H.Request("capture", ("currents",), 0.0, 0.0, 5.0))
    assert eta >= 20.0 + ep_none.spec.link.rtt_s / 2 + 5.0


def test_summaries_arrive_in_time_order_and_carry_no_label(ep_none):
    acc = H.Access(ep_none)
    got, _ = acc.advance(ep_none.spec.duration_s + 5.0)
    assert len(got) > 100
    assert all("fault" not in m and "label" not in m for m in got)
    view_fields = {f.name for f in dataclasses.fields(E.View)}
    assert not view_fields & {"spec", "fault", "label", "plant"}


def test_transport_losses_are_visible_from_sequence_numbers(ep_none):
    """Every frame lost on the bus shows as a sequence gap in the log (none of the bursts reaches 128)."""
    sent = len(H.sensor_samples(ep_none.spec, ep_none.plant)["currents"]["t"])
    c = ep_none.log["currents"]
    received = len(np.unique(c["t_true"]))
    order = np.argsort(c["t_true"], kind="stable")
    recs = [Record("ctrl.bus_meter", "ibatt_A", float(c["ibatt_A"][i]), "A", float(c["t_rx"][i]), "telematics",
                   seq=int(c["seq"][i])) for i in order]
    recs = [r for k, r in enumerate(recs) if k == 0 or r.seq != recs[k - 1].seq]      # drop re-deliveries
    assert sent - received > 0                                                       # the episode has losses
    assert sum(n for _, n in sequence_gaps(recs)) == sent - received


def test_edge_refinement_uses_the_current():
    drive = np.array([1, 1, 1, 1, 1, 0, 0, 0], bool)
    iq = np.array([5, 5, 5, 0, 0, 0, 0, 0.0])
    assert D._refine_edges(drive, iq).tolist() == [True, True, True, False, False, False, False, False]
    hold = np.array([1, 1, 1, 1], bool)                      # gates on at zero torque stay "drive"
    assert D._refine_edges(hold, np.zeros(4)).tolist() == [True] * 4


def _frames(ep, t0, t1):
    acc = H.Access(ep)
    acc.advance(t1 + 1.0)
    clk = ep.spec.link.clock
    eta = acc.request(H.Request("buffer", FRAMES, clk.local(t0), clk.local(t1)))
    _, resp = acc.advance(eta + 0.01)
    recs = resp[0].records
    lo, hi = float(recs["currents"]["t_rx"].min()), float(recs["currents"]["t_rx"].max())
    return D.signals_from_frames(recs, lo, hi)


def test_nominal_frames_are_consistent_and_noise_is_calibrated(ep_none):
    sig = _frames(ep_none, 40.0, 54.0)
    d = D.diagnose(sig, {"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0}, timing_s=0.005)
    assert d.outcome == "consistent"
    assert abs(d.z["H0"]) < 3.0                              # snapped records keep the noise independent


def test_bias_after_onset_is_supported(ep_hb):
    sig = _frames(ep_hb, 25.0, 45.0)
    d = D.diagnose(sig, {"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0}, timing_s=0.005)
    assert d.outcome == "supported" and d.hypotheses == ("HB",)
    assert d.estimates["HB"]["b_A"] == pytest.approx(0.3, abs=0.03)


def test_no_evidence_is_never_reported_as_consistent():
    d = D.diagnose_blocks([], D.EngineConfig())
    assert d.outcome == "insufficient" and d.hypotheses == ()
