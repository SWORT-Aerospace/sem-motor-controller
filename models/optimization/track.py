"""Track description for optimisation. The default track is SYNTHETIC."""
from __future__ import annotations

import dataclasses
import math

import numpy as np


@dataclasses.dataclass
class Track:
    lap_length_m: float
    laps: int
    # piecewise definitions over ONE lap: lists of (start_m, end_m, value)
    grade_segments: list[tuple[float, float, float]]       # grade angle [rad]
    curvature_segments: list[tuple[float, float, float]]   # 1/R [1/m]
    stop_positions_m: list[float] = dataclasses.field(default_factory=list)  # per lap
    a_lat_max: float = 1.5            # lateral acceleration limit for corner speed [m/s^2]
    v_max_global: float = 12.0        # [m/s]
    label: str = "SYNTHETIC"

    @property
    def length_m(self) -> float:
        return self.lap_length_m * self.laps

    def _lookup(self, segs, s):
        x = s % self.lap_length_m
        for a, b, val in segs:
            if a <= x < b:
                return val
        return 0.0

    def grade(self, s: float) -> float:
        return self._lookup(self.grade_segments, s)

    def curvature(self, s: float) -> float:
        return self._lookup(self.curvature_segments, s)

    def v_limit(self, s: float) -> float:
        k = abs(self.curvature(s))
        v = self.v_max_global
        if k > 0:
            v = min(v, math.sqrt(self.a_lat_max / k))
        return v

    def is_stop(self, s: float, ds: float) -> bool:
        x = s % self.lap_length_m
        return any(abs(x - p) < 0.5 * ds for p in self.stop_positions_m)

    def sample(self, ds: float):
        n = int(round(self.length_m / ds))
        s = np.arange(n + 1) * (self.length_m / n)
        return s, np.array([self.grade(x) for x in s]), np.array([self.curvature(x) for x in s]), \
            np.array([self.v_limit(x) for x in s])


def synthetic_track() -> Track:
    """1.5 km lap, 4 laps; a 300 m climb at 1 % and descent at 1 %; four corners.
    Invented for software development: NOT any real SEM circuit."""
    g = math.atan(0.01)
    return Track(
        lap_length_m=1500.0, laps=4,
        grade_segments=[(200.0, 500.0, g), (700.0, 1000.0, -g)],
        curvature_segments=[(150.0, 190.0, 1 / 25.0), (560.0, 620.0, 1 / 40.0), (1050.0, 1090.0, 1 / 20.0),
                            (1380.0, 1440.0, 1 / 35.0)],
    )
