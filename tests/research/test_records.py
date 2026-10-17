"""Measurement records: acquisition intervals and the loss, duplicate and stale checks."""
import pytest

from research.bea.records import Record, alignment_bound, duplicates, sequence_gaps, stale_runs


def rec(t_rx, seq, value=1.0, **kw):
    return Record("ctrl.bus_meter", "ibatt_A", value, "A", t_rx, "telematics", seq=seq, **kw)


def test_receipt_stamped_interval_uses_transport_bounds():
    r = rec(10.0, 1, delay_lo_s=0.001, delay_hi_s=0.004)
    assert r.acq_interval() == pytest.approx((9.996, 9.999))


def test_window_mean_refers_to_window_centre():
    r = rec(10.0, 1, window_s=0.5)            # the 2 Hz summary's mean power
    assert r.acq_estimate() == pytest.approx(9.75)


def test_source_stamp_widened_by_offset_and_drift():
    r = Record("tu.imu", "ax", 0.0, "m/s^2", 5.0, "telematics", t_acq=4.99, acq_clock="telematics",
               clock_offset_unc_s=0.001, clock_drift_ppm=40.0, since_sync_s=100.0)
    assert r.clock_bound_s() == pytest.approx(0.001 + 0.004)
    assert r.acq_interval() == pytest.approx((4.985, 4.995))


def test_gaps_duplicates_and_wrap():
    rs = [rec(0.00, 254), rec(0.01, 255), rec(0.02, 0), rec(0.05, 3), rec(0.05, 3)]
    assert sequence_gaps(rs) == [(3, 2)]       # 1 and 2 lost across the wrap
    assert duplicates(rs) == [4]


def test_stale_run_needs_advancing_sequence():
    rs = [rec(0.0, 1, 2.0), rec(0.01, 2, 2.0), rec(0.02, 3, 2.0), rec(0.03, 4, 2.5)]
    assert stale_runs(rs, min_len=3) == [(0, 3)]
    assert stale_runs([rec(0.0, 1, 2.0), rec(0.0, 1, 2.0)], min_len=2) == []   # a re-delivery is not staleness


def test_flags_and_bounds_validated():
    with pytest.raises(ValueError):
        rec(0.0, 1, flags=frozenset({"made_up"}))
    with pytest.raises(ValueError):
        rec(0.0, 1, delay_lo_s=0.005, delay_hi_s=0.001)


def test_alignment_bound():
    assert alignment_bound(0.1, 40.0) == pytest.approx(0.05)
    assert alignment_bound(0.1, 40.0, "hold") == pytest.approx(4.0)
