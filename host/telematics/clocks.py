"""Clock domains of the host demonstration (HOST SIMULATION).

Three clocks take part (docs/ICD.md, section "Timestamps and clock domains"):

  controller  free-running microsecond timer of the motor controller, from its
              boot. The simulation's reference time ("true" time) is this clock.
              Controller frames carry no timestamp; they carry a sequence counter.
  telematics  monotonic clock of the telematics unit (the STM32U575 in the
              telematics proposal). It timestamps every received frame and every
              sensor sample, and it stamps the supervisor's src_time_ms. Modelled
              as an offset (it boots before the controller) and a rate error.
  utc         GNSS time. The receiver's PPS edge marks each UTC second; the unit
              timestamps the edge in its own clock. A least-squares fit over the
              recent edges maps telematics time to UTC. Without PPS the mapping
              is held (holdover) and its error bound grows with the rate
              uncertainty.

The numbers below (offset, drift, jitter) are illustrative values for the
simulation, not measurements of any part.
"""
from __future__ import annotations

import dataclasses
import math


@dataclasses.dataclass
class LocalClock:
    """telematics_time = offset + controller_time + integral of the rate error.

    The rate error is drift_ppm plus a slow wander (temperature), so a linear
    fit extrapolated through a PPS outage does accumulate error, as a real
    crystal's would."""
    offset_s: float = 1.732
    drift_ppm: float = 40.0
    wander_ppm: float = 3.0
    wander_period_s: float = 200.0

    def local(self, t_true: float) -> float:
        w = 2.0 * math.pi / self.wander_period_s
        integral = self.drift_ppm * t_true + self.wander_ppm * (1.0 - math.cos(w * t_true)) / w
        return self.offset_s + t_true + integral * 1e-6

    def true(self, t_local: float) -> float:
        t = t_local - self.offset_s
        for _ in range(4):                      # Newton; the rate is 1 + O(1e-4)
            t -= (self.local(t) - t_local) / (1.0 + (self.drift_ppm + self.wander_ppm) * 1e-6)
        return t


@dataclasses.dataclass
class PpsModel:
    """GNSS PPS: an edge at every whole UTC second while the receiver has a fix."""
    utc_at_true_zero: float = 1_792_141_200.25   # 2026-10-16T09:00:00.25Z, illustrative
    jitter_s: float = 30e-9
    outages: tuple = ()                          # ((t0, t1), ...) in controller time: no fix, no PPS

    def has_fix(self, t_true: float) -> bool:
        return not any(a <= t_true < b for a, b in self.outages)

    def edges(self, t0_true: float, t1_true: float, rng=None):
        """Yield (t_true_of_edge, utc_second) for edges in [t0, t1); with rng, the edge
        time carries the receiver's PPS jitter."""
        u0 = math.ceil(self.utc_at_true_zero + t0_true)
        u = u0
        while True:
            t = u - self.utc_at_true_zero
            if t >= t1_true:
                return
            if t >= t0_true and self.has_fix(t):
                yield (t + (rng.normal(0.0, self.jitter_s) if rng is not None else 0.0)), u
            u += 1


class UtcEstimator:
    """Telematics time -> UTC from timestamped PPS edges.

    Fit utc = a + b * local over the last `window` edges. Quality:
      "pps"       last edge younger than `holdover_after_s`
      "holdover"  older: the fit is extrapolated; error bound = rate_bound * age
      "none"      fewer than two edges seen
    """

    def __init__(self, window: int = 8, holdover_after_s: float = 2.5, rate_bound_ppm: float = 50.0):
        self.window = window
        self.holdover_after_s = holdover_after_s
        self.rate_bound = rate_bound_ppm * 1e-6
        self.edges: list[tuple[float, int]] = []
        self.a = math.nan
        self.b = math.nan

    def add_edge(self, t_local: float, utc_s: int) -> None:
        self.edges.append((t_local, utc_s))
        self.edges = self.edges[-self.window:]
        if len(self.edges) >= 2:
            n = len(self.edges)
            mx = sum(x for x, _ in self.edges) / n
            my = sum(y for _, y in self.edges) / n
            sxx = sum((x - mx) ** 2 for x, _ in self.edges)
            sxy = sum((x - mx) * (y - my) for x, y in self.edges)
            self.b = sxy / sxx
            self.a = my - self.b * mx

    def utc(self, t_local: float) -> tuple[float, str, float]:
        """(utc or nan, quality, error bound in s or nan)."""
        if len(self.edges) < 2:
            return math.nan, "none", math.nan
        age = t_local - self.edges[-1][0]
        u = self.a + self.b * t_local
        if age <= self.holdover_after_s:
            return u, "pps", 1e-6
        return u, "holdover", 1e-6 + self.rate_bound * age
