"""Measurement records as the diagnostic sees them, with their timing kept explicit.

A record is one value of one channel. It carries what is known about when the
value was acquired, separately from when it was received, because the vehicle's
controller frames carry no source timestamp (docs/ICD.md): the telemetry unit
stamps them on receipt.

Six timing phenomena are kept apart (research/IDENTIFIABILITY.md section 4);
each has its own field or check and its own signature in a residual:

  transport delay      t_rx - t_acq: bounded by [delay_lo_s, delay_hi_s] for the
                       record's path. Known and bounded: it widens the acquisition
                       interval, it is not a fault.
  wrong source stamp   t_acq is present but offset from the truth (clock offset,
                       stamp taken at the window end instead of its centre).
                       Hypothesis HT when it exceeds the stated uncertainty.
  response delay       the sensor or the physics lags the quantity (an averaging
                       filter, a capacitor). A property of the channel
                       (response_tau_s), not of the record's stamp; its effect
                       differs from a pure delay at frequencies near 1/tau.
  sampling rate        channels sampled at different periods; aligning them
                       adds a bounded interpolation error (alignment_bound).
  clock drift          the stamping clock's rate error: the offset grows with
                       time since the last synchronisation (clock_drift_ppm).
  loss / stale         a missing sequence number is a lost record; a repeated
                       payload with a new sequence number is stale. Both are
                       found from seq and value (sequence_gaps, stale_runs),
                       never inferred from timing alone.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Iterable, Optional, Sequence

QUALITY_FLAGS = ("missing", "stale", "invalid", "saturated", "replayed", "interpolated")


@dataclasses.dataclass(frozen=True)
class Record:
    source: str                    # physical source identity, e.g. "ctrl.bus_meter", "ctrl.phase_shunts", "tu.wheel_drive"
    channel: str                   # e.g. "ibatt_A"
    value: float
    unit: str
    t_rx: float                    # receipt time in the receiving clock [s]
    rx_clock: str                  # clock domain of t_rx, e.g. "telematics"
    seq: Optional[int] = None      # per-message sequence counter as transmitted (wraps at seq_mod)
    seq_mod: int = 256
    t_acq: Optional[float] = None  # source acquisition time, if the source sends one, in acq_clock
    acq_clock: Optional[str] = None
    window_s: float = 0.0          # 0: instantaneous; > 0: mean over [t_ref - window_s, t_ref]
    delay_lo_s: float = 0.0        # transport delay bounds of this record's path
    delay_hi_s: float = 0.0
    clock_offset_unc_s: float = 0.0   # bound on the stamping clock's offset from the reference clock
    clock_drift_ppm: float = 0.0      # bound on its rate error
    since_sync_s: float = 0.0         # time since that clock was last synchronised
    flags: frozenset = frozenset()
    calib_id: Optional[str] = None    # calibration identity (blob hash) the value was computed with

    def __post_init__(self):
        bad = set(self.flags) - set(QUALITY_FLAGS)
        if bad:
            raise ValueError(f"unknown quality flags {sorted(bad)}")
        if self.delay_hi_s < self.delay_lo_s or self.delay_lo_s < 0:
            raise ValueError("transport delay bounds must satisfy 0 <= lo <= hi")
        if self.window_s < 0:
            raise ValueError("window_s must be >= 0")

    def clock_bound_s(self) -> float:
        """Bound on the stamping clock's error at this record: offset plus accumulated drift."""
        return self.clock_offset_unc_s + abs(self.clock_drift_ppm) * 1e-6 * self.since_sync_s

    def acq_interval(self) -> tuple[float, float]:
        """Interval that contains the reference time of the value, in the receiving clock.

        With a source stamp it is that stamp widened by the clock bound. Without one
        (controller frames) it is the receipt time minus the transport-delay bounds,
        widened by the receiving clock's own bound. For a window mean, the reference
        time is the window centre (t_ref - window_s / 2)."""
        cb = self.clock_bound_s()
        half = self.window_s / 2.0
        if self.t_acq is not None:
            return (self.t_acq - half - cb, self.t_acq - half + cb)
        return (self.t_rx - self.delay_hi_s - half - cb, self.t_rx - self.delay_lo_s - half + cb)

    def acq_estimate(self) -> float:
        lo, hi = self.acq_interval()
        return 0.5 * (lo + hi)

    def timing_unc_s(self) -> float:
        lo, hi = self.acq_interval()
        return 0.5 * (hi - lo)


def sequence_gaps(records: Sequence[Record]) -> list[tuple[int, int]]:
    """(index, n_missing) for each gap in the sequence counter of one message stream, in receipt order.

    A difference of 0 is a duplicate (reported by duplicates()), and a difference
    larger than half the modulus is treated as reordering, not as loss."""
    out = []
    for i in range(1, len(records)):
        a, b = records[i - 1].seq, records[i].seq
        if a is None or b is None:
            continue
        d = (b - a) % records[i].seq_mod
        if 1 < d <= records[i].seq_mod // 2:
            out.append((i, d - 1))
    return out


def duplicates(records: Sequence[Record]) -> list[int]:
    """Indices of exact re-deliveries (same seq and value as the previous record)."""
    return [i for i in range(1, len(records))
            if records[i].seq is not None and records[i].seq == records[i - 1].seq
            and records[i].value == records[i - 1].value]


def stale_runs(records: Sequence[Record], min_len: int = 2) -> list[tuple[int, int]]:
    """(start, length) of runs where the value repeats exactly under advancing sequence numbers.

    A repeated value is evidence of staleness only for a channel whose quantisation
    step is small against its noise; the caller decides which channels qualify."""
    out, start = [], 0
    for i in range(1, len(records) + 1):
        same = (i < len(records) and records[i].value == records[i - 1].value
                and records[i].seq is not None and records[i].seq != records[i - 1].seq)
        if not same:
            if i - start >= min_len:
                out.append((start, i - start))
            start = i
    return out


def alignment_bound(period_s: float, max_abs_d2: float, method: str = "linear") -> float:
    """Bound on the error of reconstructing a channel between its samples.

    linear interpolation: |e| <= max|f''| * T^2 / 8; zero-order hold: |e| <= max|f'| * T
    (pass max|f'| as max_abs_d2 for 'hold')."""
    if method == "linear":
        return max_abs_d2 * period_s ** 2 / 8.0
    if method == "hold":
        return max_abs_d2 * period_s
    raise ValueError(method)


def values(records: Iterable[Record]) -> list[float]:
    return [r.value for r in records]


def finite(x: Optional[float]) -> bool:
    return x is not None and math.isfinite(x)
