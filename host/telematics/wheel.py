"""Wheel speed and distance from Hall-switch edge timestamps (reference for the firmware, telematics/firmware).

The firmware captures the time of every edge with a timer (1 us resolution, extended to 64 bits across
timer overflow) and, every `record_period_us`, writes one WHEEL_EDGES record per channel (stlg.py):
the number of edges since the previous record, the time of the last edge (the record time), the span from
the first to the last of those edges, the line level, a per-channel record counter and a count of edges
lost to capture overrun. A channel without edges still gets a record (a heartbeat, n = 0) at the
evaluation time, so silence is recorded, not inferred.

From those records:

  distance   pitch x total edges since start, pitch = circumference / pulses per revolution; uncertainty one
             pitch. The total is in every record, so a lost record loses no distance; edges lost to capture
             overrun make it a lower bound (validity unverified)
  speed      over complete edge intervals only: from the last edge of the previous record to the last edge
             of this one there are n intervals, so v = n x pitch / (t_last - t_prev_last). The window starts
             and ends on an edge, so there is no counting-window quantisation (the old fixed-window
             estimate, counts x C / (ppr x window), is +-1 count per window). The sample time is the middle
             of the interval and its uncertainty half the interval. After a break in the chain (a lost
             record, capture overrun, the first record) only the record's own edges are used, n >= 2:
             v = (n - 1) x pitch / span.
  no edge    when the time since the last edge exceeds `stale_factor` x the last edge period (or there was
             never an edge), the wheel has moved less than one pitch since that edge: the speed is not
             known, only bounded, v < pitch / dt. The result is `no_evidence` with that bound, never 0:
             a disconnected sensor and a stopped wheel look the same on the edges alone.
  standstill reported as 0 only with positive evidence: the line has been held at the sensor's active
             level (a magnet under the sensor) for at least `standstill_after_us`, and the channel has
             produced at least one edge since start (the sensor works). A line stuck at the active level by
             a short to ground would also read as standstill; the bench check in
             telematics/firmware/BENCH.md covers it.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from host.telematics import signals
from host.telematics.measurement import Measurement

FLAG_LINE_HIGH = 0x01        # line level at the record time
FLAG_OVERRUN = 0x02          # an edge was captured before the previous one was read: edges lost
FLAG_HEARTBEAT = 0x04        # no edge since the previous record


@dataclasses.dataclass(frozen=True)
class WheelConfig:
    circumference_m: float
    ppr: int                                  # edges counted per revolution (one edge per magnet pass)
    active_high: bool = False                 # open-collector Hall switch with pull-up: low when a magnet is near
    stale_factor: float = 3.0
    standstill_after_us: int = 2_000_000
    max_period_us: int = 2_000_000            # a longer edge period than this is not a speed sample

    @property
    def pitch_m(self) -> float:
        return self.circumference_m / self.ppr


@dataclasses.dataclass(frozen=True)
class EdgeRecord:
    t_us: int                # time of the last edge (n > 0) or of the evaluation (heartbeat)
    channel: int
    n: int
    span_us: int             # last edge - first edge in this record
    total: int               # edges since start, wraps at 2**32
    flags: int
    rec_seq: int             # per-channel, wraps at 65536
    lost: int                # edges lost to capture overrun since the previous record


class EdgeAccumulator:
    """One channel's edge accumulator: what the capture interrupt updates and the record task drains.
    The firmware (tm_wheel.c) does the same in C; tests compare the two on the same edges."""

    def __init__(self, channel: int):
        self.channel = channel
        self.n = 0
        self.t_first = None
        self.t_last = None
        self.lost = 0
        self.overrun = False
        self.rec_seq = 0
        self.total = 0

    def edge(self, t_us: int) -> None:
        if self.n == 0:
            self.t_first = t_us
        self.t_last = t_us
        self.n += 1
        self.total = (self.total + 1) & 0xFFFFFFFF

    def overrun_edge(self) -> None:
        self.lost += 1
        self.overrun = True

    def take(self, t_now_us: int, line_high: bool) -> EdgeRecord:
        flags = (FLAG_LINE_HIGH if line_high else 0) | (FLAG_OVERRUN if self.overrun else 0)
        if self.n:
            r = EdgeRecord(self.t_last, self.channel, self.n, self.t_last - self.t_first, self.total, flags,
                           self.rec_seq, self.lost)
        else:
            r = EdgeRecord(t_now_us, self.channel, 0, 0, self.total, flags | FLAG_HEARTBEAT, self.rec_seq, self.lost)
        self.n, self.t_first, self.t_last, self.lost, self.overrun = 0, None, None, 0, False
        self.rec_seq = (self.rec_seq + 1) & 0xFFFF
        return r


class WheelEstimator:
    """Records of one channel in, measurements out (speed and distance)."""

    def __init__(self, cfg: WheelConfig, name: str, record_id=None, t_unc_capture_us: int = 2):
        self.cfg = cfg
        self.name = name
        self.rid = record_id or (lambda: 0)
        self.t_unc_capture_us = t_unc_capture_us
        self.edges = 0
        self.total0: Optional[int] = None         # the first record's total minus its edges (a restart begins at 0)
        self.last_edge: Optional[int] = None      # time of the latest edge seen
        self.last_period: Optional[int] = None
        self.chain_ok = False                     # the previous record's last edge is the edge before this one
        self.expect_seq: Optional[int] = None
        self.ever_edge = False
        self.active_since: Optional[int] = None   # start of the current hold at the active level
        self.lost_edges = 0
        self.lost_records = 0

    def _m(self, signal: str, value, t_rx: int, t_sample, t_unc, validity: str, prov: str, upper=None):
        return Measurement(self.rid(), "wheel", f"wheel.{self.name}.{signal}", value,
                           "m/s" if signal == "speed" else "m", t_rx, t_sample, t_unc, None, validity, prov, upper)

    def feed(self, r: EdgeRecord) -> list[Measurement]:
        cfg, out = self.cfg, []
        if self.expect_seq is not None and r.rec_seq != self.expect_seq:
            self.lost_records += (r.rec_seq - self.expect_seq) & 0xFFFF
            self.chain_ok = False
        self.expect_seq = (r.rec_seq + 1) & 0xFFFF
        if r.lost or r.flags & FLAG_OVERRUN:
            self.lost_edges += r.lost
            self.chain_ok = False
        line_active = bool(r.flags & FLAG_LINE_HIGH) == cfg.active_high
        prov = f"wheel-edges:ch{r.channel}"
        if r.n > 0:
            t_first = r.t_us - r.span_us
            v = None
            if self.chain_ok and self.last_edge is not None and r.t_us - self.last_edge <= cfg.max_period_us * r.n:
                dt = r.t_us - self.last_edge
                v, t_mid, half = r.n * cfg.pitch_m * 1e6 / dt, self.last_edge + dt // 2, dt // 2
            elif r.n >= 2 and r.span_us > 0:
                v, t_mid, half = (r.n - 1) * cfg.pitch_m * 1e6 / r.span_us, t_first + r.span_us // 2, r.span_us // 2
            if v is not None:
                ok = signals.in_range(f"wheel.{self.name}.speed", v)
                out.append(self._m("speed", v if ok else None, r.t_us, t_mid, half + self.t_unc_capture_us,
                                   "valid" if ok else "out_of_range", prov))
            if r.n >= 2:
                self.last_period = r.span_us // (r.n - 1)
            elif self.last_edge is not None and self.chain_ok:
                self.last_period = r.t_us - self.last_edge
            if self.total0 is None:
                self.total0 = (r.total - r.n) & 0xFFFFFFFF
            self.edges = (r.total - self.total0) & 0xFFFFFFFF
            self.last_edge = r.t_us
            self.ever_edge = True
            self.chain_ok = True
            self.active_since = None if not line_active else r.t_us
            # after an edge lost to capture overrun the count is a lower bound: unverified, not valid
            exact = self.lost_edges == 0
            out.append(self._m("distance", self.edges * cfg.pitch_m, r.t_us, r.t_us, self.t_unc_capture_us,
                               "valid" if exact else "unverified",
                               prov if exact else prov + " lower bound: edges lost"))
            return out
        # heartbeat: no edge since the previous record
        if line_active:
            if self.active_since is None:
                self.active_since = r.t_us
        else:
            self.active_since = None
        since = None if self.last_edge is None else r.t_us - self.last_edge
        upper = cfg.pitch_m * 1e6 / since if since else None
        if (self.ever_edge and self.active_since is not None
                and r.t_us - self.active_since >= cfg.standstill_after_us):
            # positive evidence first: a magnet held under a working sensor means the wheel is not turning
            out.append(self._m("speed", 0.0, r.t_us, r.t_us, 0, "valid", prov + " standstill: line held active",
                               upper))
            return out
        expected = None if self.last_period is None else cfg.stale_factor * self.last_period
        if since is not None and expected is not None and since <= expected:
            return out                                       # between edges: the latest speed still stands
        out.append(self._m("speed", None, r.t_us, None, None, "no_evidence", prov + " no edge", upper))
        return out
