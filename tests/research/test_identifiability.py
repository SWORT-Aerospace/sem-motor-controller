"""Exact claims of research/IDENTIFIABILITY.md, checked on the synthetic study model.

Each test names the proposition it checks. The numbers are synthetic; what is
tested is structure (a separation that must be zero, or must not be) and the
closed-form cases."""
import math

import numpy as np
import pytest

from research.bea import identifiability as I

ST = I.Study()


@pytest.fixture(scope="module")
def trs():
    return {k: I.simulate(k, ST) for k in ("cruise", "coast", "pulse_coast", "sine")}


def W(tr, rels, **kw):
    return I.whiten(I.build_window(tr, ST, rels, **kw))


def test_truth_follows_the_electrical_boundary(trs):
    """The bus meter sees no auxiliary load: with the gates off its true current is zero (PROTOCOL.md section 4)."""
    tr = trs["pulse_coast"]
    assert np.all(tr.P[~tr.drive] == 0.0)
    assert np.all(tr.P[tr.drive] > 0.0)


@pytest.mark.parametrize("fs", [2.0, 10.0, 100.0])
@pytest.mark.parametrize("size", [0.05, 0.4])
def test_p1_timing_error_unobservable_at_steady_power(trs, fs, size):
    """P1: with dP/dt = 0 on the window the shifted power equals the power: d = 0 at every rate and size."""
    w = W(trs["cruise"], {"R1": fs, "R2": min(fs, 10.0)})
    assert I.separation(w, "HT", size, "H0", "known") == pytest.approx(0.0, abs=1e-9)
    assert I.separation(w, "HT", size, "HB", "known") == pytest.approx(0.0, abs=1e-9)


def test_p3_coast_current_closed_form(trs):
    """P3: on R3 alone, d(HB -> H0) = (|b| - Ioff_max) * sqrt(n) / sigma_I exactly."""
    w = W(trs["coast"], {"R3": 10.0})
    b, ioff = 0.05, I.NUISANCE["known"]["Ioff_A"]
    expected = (b - ioff) * math.sqrt(w.n) / ST.sigma_ibatt_A
    assert I.separation(w, "HB", b, "H0", "known") == pytest.approx(expected, rel=1e-6)
    assert I.separation(w, "HB", 0.004, "H0", "known") == pytest.approx(0.0, abs=1e-9)   # inside the offset bound


def test_p3_coast_separates_bias_from_timing_and_load(trs):
    w = W(trs["pulse_coast"], I.EVIDENCE["frames_100Hz"][0])
    for g in ("HT", "HL"):
        assert I.separation(w, "HB", 0.2, g, "known") >= I.SEPARABLE_SIGMA


@pytest.mark.parametrize("cond", ["cruise", "coast", "pulse_coast"])
@pytest.mark.parametrize("fs", [2.0, 10.0])
def test_p6_grade_and_drag_collinear_without_imu(trs, cond, fs):
    """P6: in R2 and R4 the extra force and the grade have the same signature: d = 0 at any rate."""
    w = W(trs[cond], {"R1": fs, "R2": fs, "R3": fs, "R4": fs})
    assert I.is_collinear(w, "HL", 12.0, "HL_grade", "known")
    assert I.is_collinear(w, "HL_grade", 0.04, "HL", "known")


@pytest.mark.parametrize("cond", ["cruise", "coast"])
def test_p6_imu_separates_grade_from_drag(trs, cond):
    """P6: the IMU's specific force carries the drag but almost no grade, so R5 separates them."""
    w = W(trs[cond], I.EVIDENCE["frames_imu"][0])
    assert I.separation(w, "HL", 12.0, "HL_grade", "known") >= I.SEPARABLE_SIGMA
    assert I.separation(w, "HL_grade", 0.04, "HL", "known") >= I.SEPARABLE_SIGMA


def test_p7_drag_and_headwind_not_separable_at_constant_speed(trs):
    """P7: at constant speed a headwind adds a constant force: same signature as drag, IMU included."""
    w = W(trs["cruise"], I.EVIDENCE["frames_imu"][0])
    assert I.separation(w, "HL_wind", 3.0, "HL", "known") < 1.0
    assert I.separation(w, "HL", 3.0, "HL_wind", "known") < 1.0


def test_p8_dependent_torque_makes_bias_and_load_collinear(trs):
    """P8: torque computed from the bus current carries the bias into R2; at constant speed it looks like a load."""
    rels = I.EVIDENCE["frames_100Hz"][0]
    dep = W(trs["cruise"], rels, torque_source="ibatt")
    ind = W(trs["cruise"], rels, torque_source="iq")
    assert "R1" not in dep.blocks
    assert I.separation(dep, "HB", 0.2, "HL", "known") < 1.0
    assert I.separation(ind, "HB", 0.2, "HL", "known") >= I.SEPARABLE_SIGMA


def test_timing_kinds_separable_only_with_fast_content(trs):
    """A delay, a first-order response and an averaging window differ only near their own time scale."""
    edge, smooth = trs["pulse_coast"], trs["sine"]
    assert I.timing_kind_distance(edge, ST, 100.0, "lag", 0.04, "delay") >= I.SEPARABLE_SIGMA
    assert I.timing_kind_distance(smooth, ST, 100.0, "lag", 0.04, "delay") < I.SEPARABLE_SIGMA


def test_hypotheses_are_bound_changes_of_h0():
    """Every hypothesis frees only its own parameter; H0 fixes the fault sizes at zero."""
    names = list(I.PARAMS)
    lo, hi, d = I.bounds_for("H0", names, "known")
    for f in I.FAULTS:
        assert lo[names.index(f)] == hi[names.index(f)] == 0.0
    assert d == (-I.TIMING["known"], I.TIMING["known"])
    lo2, hi2, d2 = I.bounds_for("HL", names, "known")
    changed = [n for n, a, b, c, e in zip(names, lo, hi, lo2, hi2) if (a, b) != (c, e)]
    assert changed == ["dF_N"] and d2 == d
