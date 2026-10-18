"""Synthetic sensors of the telematics unit (HOST SIMULATION).

The telematics proposal lists hall pulse inputs for wheel speed, a GNSS receiver
(u-blox NEO-M9N or similar, UART + PPS) and a 6-axis IMU. These models produce
what those inputs would deliver, from the simulated vehicle speed. The noise
levels are illustrative, not part data.

Temperature probes (off unless SensorConfig.temp_period_s is set): digital probes on the telematics
unit, one sample per channel per period, with a synthetic first-order warm-up from ambient. The placements
in TEMP_CHANNELS are a PROPOSAL (docs/TELEMETRY_INTEGRATION.md); the probe part is not selected.

Faults can be injected per channel to exercise the pit-side analysis:
  ("wheel_dropout", channel, t0, t1)   hall edges lost: counts read 0
  ("gnss_outage", t0, t1)              no fix (handled by PpsModel.outages too)
  ("temp_crc", channel, t0, t1)        probe reads fail their CRC: status 1, no value
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

WHEEL_CHANNELS = {0: "wheel_l", 1: "wheel_r", 2: "wheel_drive"}   # front left, front right, rear driven
TEMP_CHANNELS = {0: "battery_surface", 1: "motor_case", 2: "ambient"}   # PROPOSED probe placements
# synthetic warm-up per channel: (start degC, final degC, time constant s); illustrative, not vehicle data
_TEMP_MODEL = {0: (24.0, 31.0, 400.0), 1: (24.0, 46.0, 250.0), 2: (24.0, 24.5, 1000.0)}


@dataclasses.dataclass
class SensorConfig:
    wheel_circumference_m: float
    wheel_ppr: int = 32               # PROVISIONAL: magnets per wheel revolution; vehicle team to confirm
    wheel_window_s: float = 0.1
    gnss_period_s: float = 0.1
    imu_period_s: float = 0.01
    gnss_sigma_mps: float = 0.05
    imu_ax_sigma: float = 0.05
    imu_gz_sigma: float = 0.005
    temp_period_s: float | None = None    # probe sampling period; None: no probes
    temp_sigma_degC: float = 0.05
    seed: int = 11
    faults: tuple = ()


class Sensors:
    def __init__(self, cfg: SensorConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.dist = {ch: 0.0 for ch in WHEEL_CHANNELS}
        self.counted = {ch: 0 for ch in WHEEL_CHANNELS}
        self.next_wheel = cfg.wheel_window_s
        self.next_gnss = cfg.gnss_period_s / 2
        self.next_imu = 0.0
        self.prev_v = 0.0
        self.prev_t = 0.0
        self.temp_rng = np.random.default_rng(cfg.seed + 1)   # separate stream: probes leave the others unchanged
        self.next_temp = cfg.temp_period_s if cfg.temp_period_s else math.inf

    def _fault(self, kind, t, channel=None):
        for f in self.cfg.faults:
            if f[0] != kind:
                continue
            if kind in ("wheel_dropout", "temp_crc") and f[1] == channel and f[2] <= t < f[3]:
                return True
            if kind == "gnss_outage" and f[1] <= t < f[2]:
                return True
        return False

    def step(self, t: float, v: float, gnss_fix: bool) -> list[tuple[str, tuple]]:
        """Advance to controller time t with vehicle speed v [m/s]; return samples due:
        ("wheel", (channel, counts, window_ms)), ("gnss", (speed, sacc, num_sv, fix)), ("imu", (ax, gz)),
        ("temp", (channel, status, degC or None))."""
        c = self.cfg
        out = []
        dt = t - self.prev_t
        a = (v - self.prev_v) / dt if dt > 0 else 0.0
        for ch in WHEEL_CHANNELS:
            self.dist[ch] += v * dt
        self.prev_t, self.prev_v = t, v
        while t + 1e-9 >= self.next_wheel:
            for ch in WHEEL_CHANNELS:
                edges = math.floor(self.dist[ch] * c.wheel_ppr / c.wheel_circumference_m)
                counts = edges - self.counted[ch]
                self.counted[ch] = edges
                if self._fault("wheel_dropout", t, ch):
                    counts = 0
                out.append(("wheel", (ch, counts, int(round(c.wheel_window_s * 1000)))))
            self.next_wheel += c.wheel_window_s
        while t + 1e-9 >= self.next_gnss:
            fix = gnss_fix and not self._fault("gnss_outage", t)
            if fix:
                out.append(("gnss", (v + self.rng.normal(0, c.gnss_sigma_mps), 0.08, 11, True)))
            else:
                out.append(("gnss", (math.nan, math.nan, 3, False)))
            self.next_gnss += c.gnss_period_s
        while t + 1e-9 >= self.next_imu:
            out.append(("imu", (a + self.rng.normal(0, c.imu_ax_sigma), self.rng.normal(0, c.imu_gz_sigma))))
            self.next_imu += c.imu_period_s
        while t + 1e-9 >= self.next_temp:
            for ch in TEMP_CHANNELS:
                if self._fault("temp_crc", t, ch):
                    out.append(("temp", (ch, 1, None)))
                    continue
                t0, t1, tau = _TEMP_MODEL[ch]
                deg = t1 + (t0 - t1) * math.exp(-self.next_temp / tau) + self.temp_rng.normal(0, c.temp_sigma_degC)
                out.append(("temp", (ch, 0, deg)))
            self.next_temp += c.temp_period_s
        return out
