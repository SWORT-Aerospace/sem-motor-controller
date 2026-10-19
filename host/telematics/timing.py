"""Receive timing of one evidence stream (one controller message, one wheel channel, one sensor).

Timing is evidence, not housekeeping: two values processed in the same loop are not simultaneous. For each stream
this tracks what the unit can observe:

  receive time      the telematics clock at reception (always)
  producer time     the source's own timestamp when it sends one (the semmc fixture does not)
  sequence          the source's counter when it has one, `seq_bits` wide, so wraparound is handled
  inter-arrival     min, mean, max of the receive-time differences; jitter = their standard deviation
  late arrivals     an inter-arrival longer than `late_factor` x the expected period
  bursts            an inter-arrival shorter than `burst_factor` x the expected period (frames queued, then
                    delivered together)
  wait bound        for a late arrival, and for each frame of the burst that follows it, the receive time no
                    longer bounds the sample time: the frame may have waited since the previous in-time arrival.
                    `Arrival.wait_bound_us` is that interval; the pit widens the value's timestamp bound with it, so
                    a delayed value becomes TIMING_UNCERTAIN for a consumer with a tighter tolerance instead of
                    being compared as if it were fresh. From the receive side alone a paused source and a queued
                    one look the same; the bound covers both
  gaps              forward sequence jumps: the frames between are counted as lost
  duplicates        the same sequence again
  reordered         a sequence behind the last one (within half the counter range): an older frame arrived late
  ambiguous         a silence longer than half the counter range: a counter cannot tell how many frames were lost,
                    so the loss is estimated from the elapsed time and the expected period, and marked as such
  non-monotonic rx  the receive time went backwards: the local clock, not the source, is in doubt
  latency           absolute latency needs a producer timestamp and a stated relation between the producer's clock
                    and the unit's, with an uncertainty bound; with a producer timestamp on an unrelated clock only
                    its variation is observable (receive minus producer time, minus its minimum). Without either the
                    sample age is unknown

Nothing here runs on hardware. The firmware logs every frame with its receive time, so the pit applies this to
the log (host/pit/ingest.py: source_timing).
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional


@dataclasses.dataclass
class Arrival:
    kind: str                     # first | in_order | gap | duplicate | reordered | ambiguous | no_sequence
    lost: int = 0                 # frames estimated lost before this one
    late: bool = False
    burst: bool = False
    wrapped: bool = False
    rx_backwards: bool = False
    wait_bound_us: Optional[int] = None   # set when the receive time does not bound the sample time (see above)


class StreamTiming:
    def __init__(self, name: str, expected_period_us: Optional[int] = None, seq_bits: Optional[int] = None,
                 late_factor: float = 2.0, burst_factor: float = 0.25):
        self.name = name
        self.period = expected_period_us
        self.seq_bits = seq_bits
        self.late_factor = late_factor
        self.burst_factor = burst_factor
        self.count = 0
        self.first_rx: Optional[int] = None
        self.last_rx: Optional[int] = None
        self.last_seq: Optional[int] = None
        self.dts: list[int] = []
        self.lost = 0
        self.lost_estimated = 0          # part of `lost` estimated from time (ambiguous sequence)
        self.gaps = 0
        self.duplicates = 0
        self.reordered = 0
        self.ambiguous = 0
        self.wraps = 0
        self.late = 0
        self.bursts = 0
        self.rx_backwards = 0
        self._release_from: Optional[int] = None   # previous in-time arrival before a late one
        self.wait_bounded = 0
        self._lat0: Optional[int] = None
        self.latency_var_max_us: Optional[int] = None

    # ---------------------------------------------------------------- observation
    def observe(self, t_rx_us: int, seq: Optional[int] = None, t_src_us: Optional[int] = None) -> Arrival:
        a = Arrival("no_sequence" if seq is None else "in_order")
        self.count += 1
        if self.first_rx is None:
            self.first_rx = t_rx_us
        dt = None if self.last_rx is None else t_rx_us - self.last_rx
        if dt is not None and dt < 0:
            a.rx_backwards = True
            self.rx_backwards += 1
        elif dt is not None:
            self.dts.append(dt)
            if self.period:
                if dt > self.late_factor * self.period:
                    a.late = True
                    self.late += 1
                    self._release_from = self.last_rx if self._release_from is None else self._release_from
                elif dt < self.burst_factor * self.period:
                    a.burst = True
                    self.bursts += 1
                else:
                    self._release_from = None
                if (a.late or a.burst) and self._release_from is not None:
                    a.wait_bound_us = t_rx_us - self._release_from
                    self.wait_bounded += 1
        if seq is not None and self.seq_bits:
            a = self._sequence(a, seq, dt)
        if t_src_us is not None:
            d = t_rx_us - t_src_us
            self._lat0 = d if self._lat0 is None else min(self._lat0, d)
            var = d - self._lat0
            self.latency_var_max_us = var if self.latency_var_max_us is None else max(self.latency_var_max_us, var)
        if self.last_rx is None or t_rx_us >= self.last_rx:
            self.last_rx = t_rx_us
        if self.count == 1:
            a.kind = "first" if seq is not None else "no_sequence"
        return a

    def _sequence(self, a: Arrival, seq: int, dt: Optional[int]) -> Arrival:
        mod = 1 << self.seq_bits
        seq &= mod - 1
        if self.last_seq is None:
            self.last_seq = seq
            return a
        d = (seq - self.last_seq) % mod
        half = mod // 2
        # a silence longer than half the counter range makes the counter ambiguous: estimate from time
        if self.period and dt is not None and dt > half * self.period:
            est = max(0, int(round(dt / self.period)) - 1)
            a.kind, a.lost = "ambiguous", est
            self.ambiguous += 1
            self.lost += est
            self.lost_estimated += est
            self.wraps += dt // (mod * self.period)
            self.last_seq = seq
            return a
        if d == 0:
            a.kind = "duplicate"
            self.duplicates += 1
            return a
        if d >= half:
            a.kind = "reordered"
            self.reordered += 1
            return a                                    # an older frame: the newest sequence stays
        if seq < self.last_seq:
            a.wrapped = True
            self.wraps += 1
        if d > 1:
            a.kind, a.lost = "gap", d - 1
            self.gaps += 1
            self.lost += d - 1
        self.last_seq = seq
        return a

    # ---------------------------------------------------------------- results
    def age_us(self, now_us: int) -> Optional[int]:
        return None if self.last_rx is None else now_us - self.last_rx

    def jitter_us(self) -> Optional[float]:
        if len(self.dts) < 2:
            return None
        m = sum(self.dts) / len(self.dts)
        return math.sqrt(sum((x - m) ** 2 for x in self.dts) / (len(self.dts) - 1))

    def report(self, now_us: Optional[int] = None) -> dict:
        mean = sum(self.dts) / len(self.dts) if self.dts else None
        return {"stream": self.name, "received": self.count, "expected_period_us": self.period,
                "seq_bits": self.seq_bits,
                "inter_arrival_us": None if not self.dts else
                {"min": min(self.dts), "mean": round(mean, 1), "max": max(self.dts)},
                "jitter_us": None if self.jitter_us() is None else round(self.jitter_us(), 1),
                "late": self.late, "bursts": self.bursts, "lost": self.lost, "lost_estimated_from_time":
                    self.lost_estimated, "gaps": self.gaps, "duplicates": self.duplicates,
                "reordered": self.reordered, "ambiguous_silences": self.ambiguous, "wraps": self.wraps,
                "wait_bounded": self.wait_bounded,
                "rx_backwards": self.rx_backwards,
                "latency": "variation only (producer clock differs)" if self.latency_var_max_us is not None
                else "not observable: no producer timestamp",
                "latency_variation_max_us": self.latency_var_max_us,
                "age_us": None if now_us is None else self.age_us(now_us)}

    def state(self, now_us: int, stale_us: int) -> str:
        """MISSING (never received), STALE (older than `stale_us`), or VALID timing."""
        if self.last_rx is None:
            return "MISSING"
        return "STALE" if now_us - self.last_rx > stale_us else "VALID"
