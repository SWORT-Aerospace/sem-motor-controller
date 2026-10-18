"""SIMULATION FIXTURE: a vehicle whose motor controller belongs to another team, and the telematics unit's own
sensors. Nothing here is this project's controller: the "external controller" is a small Python stand-in that
broadcasts the semmc fixture protocol (protocol/protocol.yaml) at its message periods, never listens, and has
no relation to the controller core in firmware/. Its numbers (efficiency, resistances, auxiliary load) are
illustrative, not part data.

What it produces, all in controller ("true") time:
  * CAN frames of the external controller: ctrl_motion, ctrl_currents, ctrl_energy, ctrl_energy_quality,
    ctrl_thermal, ctrl_validity, ctrl_status, ctrl_fault, each with its own sequence counter;
  * wheel Hall edges per channel (edge times interpolated within the step) and the sensor line level;
  * GNSS speed (10 Hz), IMU (100 Hz), temperature probes (1 Hz), and, when fitted, a battery-side monitor
    (10 Hz) that sees the controller plus the telematics unit and the other auxiliary loads;
  * ground truth for the tests: distance, controller input energy, battery energy.

Faults the demonstration injects (`Faults`): controller silence, corrupted frames (bad CRC), a message that
stops (a missing signal), a validity flag cleared, a wheel sensor disconnected, a GNSS outage.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

from models.vehicle.longitudinal import SYNTHETIC_VEHICLE, resistive_force
from protocol.generated import semmc_protocol as proto

PERIODS = {n: proto.MESSAGES[n]["period_s"] for n in (
    "ctrl_motion", "ctrl_currents", "ctrl_energy", "ctrl_energy_quality", "ctrl_thermal", "ctrl_validity",
    "ctrl_status", "ctrl_fault")}
READY = 3          # semmc ctrl_status state code READY (the fixture's state list)


@dataclasses.dataclass
class Faults:
    silence: tuple = ()             # ((t0, t1), ...): the controller sends nothing
    corrupt: tuple = ()             # ((t0, t1), ...): every frame's CRC byte flipped
    drop_message: tuple = ()        # ((name, t0, t1), ...): that message is not sent
    vbus_invalid: tuple = ()        # ((t0, t1), ...): ctrl_validity.v_vbus cleared
    wheel_disconnect: tuple = ()    # ((channel, t0, t1), ...): no edges, line idle
    gnss_outage: tuple = ()         # ((t0, t1), ...)


def _in(t, windows) -> bool:
    return any(a <= t < b for a, b in windows)


@dataclasses.dataclass
class VehicleSimConfig:
    wheel_circumference_m: float = 1.50
    wheel_ppr: int = 8                       # magnets per wheel (PROVISIONAL)
    wheel_channels: int = 3
    magnet_window: float = 0.15              # share of the pitch with the line held active
    pack_ocv_V: float = 50.4                 # 48 V nominal pack near full (team-reported nominal 48 V, 10 Ah)
    pack_capacity_Ah: float = 10.0
    pack_r_ohm: float = 0.12                 # illustrative
    harness_r_ohm: float = 0.01
    drive_efficiency: float = 0.82           # battery-side DC to wheel, illustrative
    controller_idle_W: float = 4.0
    aux_W: float = 3.5                       # telematics unit + other auxiliary loads on the battery
    seed: int = 21


def default_profile(t: float) -> float:
    """Target speed [m/s]: launch, cruise at 6.5 m/s, coast, cruise, stop and park."""
    if t < 2.0:
        return 0.0
    if t < 60.0:
        return 6.5
    if t < 75.0:
        return 4.0
    if t < 140.0:
        return 6.5
    return 0.0


class VehicleSim:
    def __init__(self, cfg: VehicleSimConfig = VehicleSimConfig(), faults: Faults = Faults(), profile=default_profile):
        self.cfg = cfg
        self.f = faults
        self.profile = profile
        self.rng = np.random.default_rng(cfg.seed)
        self.p = SYNTHETIC_VEHICLE
        self.v = 0.0
        self.dist = 0.0
        self.charge_As = 0.0
        self.e_ctrl_J = 0.0            # true controller input energy
        self.e_batt_J = 0.0            # true battery energy (controller + auxiliaries)
        self.ctrl_counter_J = 0.0      # what the controller's own counter integrates (it may differ)
        self.seq = {n: 0 for n in PERIODS}
        self.next_tx = {n: 0.003 * k for k, n in enumerate(PERIODS)}
        self.wheel_d = [0.0] * cfg.wheel_channels
        self.wheel_k = [0] * cfg.wheel_channels
        self.i_ctrl = 0.0
        self.v_bus = cfg.pack_ocv_V
        self.v_batt = cfg.pack_ocv_V
        self.i_batt = 0.0
        self.t_fet = 25.0
        self.t_motor = 25.0
        self.ax = 0.0
        self.next_gnss, self.next_imu, self.next_temp, self.next_batt = 0.05, 0.0, 1.0, 0.0

    # ---- plant --------------------------------------------------------------------------
    def step(self, t: float, dt: float) -> dict:
        """Advance by dt to time t; returns what the sensors and the controller broadcast see."""
        c = self.cfg
        target = self.profile(t)
        f_res = resistive_force(self.p, self.v) if self.v > 0 else 0.0
        a_cmd = max(-0.4, min(0.6, 0.8 * (target - self.v)))
        f_trac = max(0.0, self.p.mass_kg * a_cmd + f_res) if target > 0 else 0.0   # no regeneration
        a = (f_trac - f_res) / self.p.mass_kg if self.v > 0 or f_trac > f_res else 0.0
        if target == 0.0 and self.v > 0:
            a = -0.6                                                              # driver brakes
        v_new = max(0.0, self.v + a * dt)
        d_step = (self.v + v_new) / 2 * dt
        p_wheel = f_trac * (self.v + v_new) / 2
        p_ctrl = p_wheel / c.drive_efficiency + c.controller_idle_W
        ocv = c.pack_ocv_V - 6.0 * self.charge_As / (c.pack_capacity_Ah * 3600.0)
        # battery current from the total load at the terminal: P = (ocv - R I) I
        p_total = p_ctrl + c.aux_W
        disc = ocv * ocv - 4 * c.pack_r_ohm * p_total
        self.i_batt = (ocv - math.sqrt(max(disc, 0.0))) / (2 * c.pack_r_ohm)
        self.v_batt = ocv - c.pack_r_ohm * self.i_batt
        self.i_ctrl = self.i_batt * p_ctrl / p_total
        self.v_bus = self.v_batt - c.harness_r_ohm * self.i_ctrl
        self.e_ctrl_J += self.v_bus * self.i_ctrl * dt
        self.e_batt_J += self.v_batt * self.i_batt * dt
        if not _in(t, self.f.silence):
            self.ctrl_counter_J += self.v_bus * self.i_ctrl * dt
        self.charge_As += self.i_batt * dt
        self.t_fet += dt * (0.02 * self.i_ctrl * self.i_ctrl * 0.05 - (self.t_fet - 25.0) / 300.0)
        self.t_motor += dt * (0.01 * self.i_ctrl * self.i_ctrl * 0.05 - (self.t_motor - 25.0) / 600.0)
        edges = self._wheel(t, dt, d_step)
        self.ax = a
        self.v = v_new
        self.dist += d_step
        return {"edges": edges}

    def _wheel(self, t: float, dt: float, d_step: float) -> list[tuple[float, int]]:
        c = self.cfg
        pitch = c.wheel_circumference_m / c.wheel_ppr
        out = []
        for ch in range(c.wheel_channels):
            d0 = self.wheel_d[ch]
            self.wheel_d[ch] = d0 + d_step
            while (self.wheel_k[ch] + 1) * pitch <= self.wheel_d[ch]:
                self.wheel_k[ch] += 1
                frac = ((self.wheel_k[ch] * pitch) - d0) / d_step if d_step > 0 else 1.0
                te = t - dt + frac * dt
                if not any(w[0] == ch and w[1] <= te < w[2] for w in self.f.wheel_disconnect):
                    out.append((te, ch))
        return out

    def line_high(self, ch: int, t: float) -> bool:
        """Sensor line level (open-collector switch with pull-up): low while a magnet is near, high otherwise;
        high when the sensor is disconnected."""
        if any(w[0] == ch and w[1] <= t < w[2] for w in self.f.wheel_disconnect):
            return True
        pitch = self.cfg.wheel_circumference_m / self.cfg.wheel_ppr
        phase = (self.wheel_d[ch] - self.wheel_k[ch] * pitch) / pitch
        return phase > self.cfg.magnet_window

    # ---- external controller broadcast -------------------------------------------------------
    def frames(self, t: float) -> list[tuple[float, int, bytes]]:
        """Frames due by time t, (time, id, 8 bytes), in transmit order."""
        out = []
        for name in PERIODS:
            while self.next_tx[name] <= t + 1e-9:
                tx = self.next_tx[name]
                self.next_tx[name] += PERIODS[name]
                if _in(tx, self.f.silence) or any(d[0] == name and d[1] <= tx < d[2] for d in self.f.drop_message):
                    continue
                data, _sat, _inv = proto.encode(name, self._values(name, tx), self.seq[name])
                self.seq[name] = (self.seq[name] + 1) & 0xFF
                if _in(tx, self.f.corrupt):
                    data = bytes([data[0] ^ 0x5A]) + data[1:]
                out.append((tx, proto.MESSAGES[name]["id"], data))
        out.sort(key=lambda x: x[0])
        return out

    def _values(self, name: str, t: float) -> dict:
        g = self.p.gear_ratio
        r = self.p.wheel_radius_m
        if name == "ctrl_motion":
            return {"speed_mech_rad_s": self.v / r * g, "iq_A": self.i_ctrl * 0.9, "vbus_V": self.v_bus}
        if name == "ctrl_currents":
            return {"id_A": 0.0, "ibatt_A": self.i_ctrl, "measured_mask": 7, "reconstructed_mask": 0,
                    "kcl_available": True, "reserved": 0, "kcl_residual_A": 0.0}
        if name == "ctrl_energy":
            return {"energy_J": self.ctrl_counter_J, "p_batt_W": self.v_bus * self.i_ctrl}
        if name == "ctrl_energy_quality":
            return {"integrated_s": t, "gap_s": sum(min(b, t) - a for a, b in self.f.silence if a < t)}
        if name == "ctrl_thermal":
            return {"t_fet_degC": self.t_fet, "t_motor_degC": self.t_motor, "derate": 0.0, "derate_reasons": 0}
        if name == "ctrl_validity":
            v = {k: True for k in ("v_speed", "v_ia", "v_ib", "v_ic", "v_vbus", "v_ibatt", "v_t_fet", "v_t_motor",
                                   "v_throttle", "v_sup_req", "v_sup_limits", "v_hall")}
            v["v_vbus"] = not _in(t, self.f.vbus_invalid)
            return v
        if name == "ctrl_status":
            return {"state": READY, "owner": 0, "sup_link": 0, "session_tag": 0, "boot_id": 1, "build_is_sim": True,
                    "cal_provenance": 0, "output_permitted": True, "pwm_enabled": self.v > 0, "derating": False,
                    "hw_trip": False, "reserved": 0, "last_transition": 0}
        if name == "ctrl_fault":
            return {"latched": 0, "first_fault": 0xFF, "reset_reason": 0, "fault_count": 0}
        raise KeyError(name)

    # ---- the unit's own sensors -----------------------------------------------------------
    def sensors(self, t: float) -> list[tuple[str, tuple]]:
        out = []
        while self.next_gnss <= t + 1e-9:
            if _in(self.next_gnss, self.f.gnss_outage):
                out.append(("gnss", (math.nan, math.nan, 3, False)))
            else:
                out.append(("gnss", (max(0.0, self.v + self.rng.normal(0, 0.05)), 0.08, 12, True)))
            self.next_gnss += 0.1
        while self.next_imu <= t + 1e-9:
            out.append(("imu", (self.ax + self.rng.normal(0, 0.05), self.rng.normal(0, 0.005))))
            self.next_imu += 0.01
        while self.next_temp <= t + 1e-9:
            for ch, base in enumerate((24.0 + 0.002 * self.e_batt_J / 100, 24.0 + (self.t_motor - 25.0) * 0.6, 24.0)):
                out.append(("temp", (ch, 0, base + self.rng.normal(0, 0.05))))
            self.next_temp += 1.0
        while self.next_batt <= t + 1e-9:
            out.append(("batt", (self.v_batt + self.rng.normal(0, 0.01), self.i_batt + self.rng.normal(0, 0.02))))
            self.next_batt += 0.1
        return out
