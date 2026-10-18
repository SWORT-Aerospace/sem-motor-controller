"""Signal registry: identity, unit, role and plausible range of every quantity the telematics unit reports.

A measurement (measurement.py) names one of these signals. The registry is the single list that the node,
the controller adapters, the pit validation and the energy analysis share, so a unit or a range is defined
once. Signals that come from the external motor controller are `origin: controller`; the controller team
decides what they broadcast (docs/CONTROLLER_INTERFACE_REQUEST.md), so every one of them may be absent.

Roles:
  energy_essential     needed for controller input energy (DC voltage and DC current at the controller input)
  energy_total         needed for total battery energy (battery-side voltage and current: our own monitor,
                       which also sees the telematics unit and every auxiliary load)
  diagnostic_optional  useful for diagnostics and the shadow-mode monitors; nothing depends on them
  motion               speed, distance and attitude from the unit's own sensors
  environment          temperatures from the unit's own probes

The unit's own health (queue high water, drops, restarts) is not a measurement: it is in the counters
(stlg COUNTERS2) and the live message's `counters` block.

`stale_s` is how old a value may be before a live summary reports it as stale (value null). The values for
controller signals assume the broadcast periods of the simulation fixture and are PROVISIONAL until the
controller team states its periods.
"""
from __future__ import annotations

import dataclasses
import fnmatch

ROLES = ("energy_essential", "energy_total", "diagnostic_optional", "motion", "environment")


@dataclasses.dataclass(frozen=True)
class Signal:
    id: str                 # may contain one "*" for a channel name, e.g. "wheel.*.speed"
    unit: str
    origin: str             # "controller" (external, through an adapter) or "telematics" (our own sensor)
    role: str
    lo: float
    hi: float
    stale_s: float
    description: str


REGISTRY: tuple[Signal, ...] = (
    # ---- external controller (through an adapter); every one may be absent
    Signal("ctrl.dc_voltage", "V", "controller", "energy_essential", 0.0, 100.0, 0.3,
           "DC voltage at the controller input"),
    Signal("ctrl.dc_current", "A", "controller", "energy_essential", -400.0, 400.0, 0.3,
           "DC current into the controller input, positive when the battery discharges"),
    Signal("ctrl.dc_power", "W", "controller", "diagnostic_optional", -20000.0, 20000.0, 0.5,
           "DC input power as the controller computes it"),
    Signal("ctrl.energy_counter", "J", "controller", "diagnostic_optional", -1e9, 1e9, 0.5,
           "energy integrated by the controller since its own reset"),
    Signal("ctrl.energy_integrated_time", "s", "controller", "diagnostic_optional", 0.0, 1e6, 0.5,
           "time the controller's energy counter has integrated"),
    Signal("ctrl.energy_gap_time", "s", "controller", "diagnostic_optional", 0.0, 1e6, 0.5,
           "time the controller's energy counter could not integrate"),
    Signal("ctrl.motor_speed", "rad/s", "controller", "diagnostic_optional", -2000.0, 2000.0, 0.3,
           "mechanical rotor speed"),
    Signal("ctrl.phase_current_q", "A", "controller", "diagnostic_optional", -400.0, 400.0, 0.3,
           "q-axis phase current"),
    Signal("ctrl.phase_current_d", "A", "controller", "diagnostic_optional", -400.0, 400.0, 0.3,
           "d-axis phase current"),
    Signal("ctrl.kcl_residual", "A", "controller", "diagnostic_optional", -50.0, 50.0, 0.3,
           "sum of the three measured phase currents"),
    Signal("ctrl.torque_reference", "N*m", "controller", "diagnostic_optional", -200.0, 200.0, 0.3,
           "torque the controller is applying as its reference"),
    Signal("ctrl.fet_temp", "degC", "controller", "diagnostic_optional", -55.0, 200.0, 1.0,
           "power-stage temperature"),
    Signal("ctrl.motor_temp", "degC", "controller", "diagnostic_optional", -55.0, 200.0, 1.0,
           "motor winding or case temperature"),
    Signal("ctrl.state", "1", "controller", "diagnostic_optional", 0.0, 255.0, 0.5,
           "controller state code (meaning defined by the controller team)"),
    Signal("ctrl.fault_code", "1", "controller", "diagnostic_optional", 0.0, 255.0, 3.0,
           "controller fault code (meaning defined by the controller team)"),
    # ---- the unit's own sensors
    Signal("wheel.*.speed", "m/s", "telematics", "motion", 0.0, 60.0, 0.3,
           "wheel speed from Hall-switch edge periods"),
    Signal("wheel.*.distance", "m", "telematics", "motion", 0.0, 1e7, 1.0,
           "distance from counted Hall-switch edges since the unit started"),
    Signal("gnss.speed", "m/s", "telematics", "motion", 0.0, 60.0, 0.5, "GNSS ground speed"),
    Signal("gnss.speed_acc", "m/s", "telematics", "motion", 0.0, 100.0, 0.5, "GNSS speed accuracy estimate"),
    Signal("gnss.num_sv", "1", "telematics", "motion", 0.0, 255.0, 0.5, "satellites used in the fix"),
    Signal("imu.ax", "m/s^2", "telematics", "motion", -160.0, 160.0, 0.1, "longitudinal acceleration"),
    Signal("imu.gz", "rad/s", "telematics", "motion", -35.0, 35.0, 0.1, "yaw rate"),
    Signal("temp.*", "degC", "telematics", "environment", -55.0, 200.0, 3.0, "temperature probe"),
    Signal("batt.voltage", "V", "telematics", "energy_total", 0.0, 100.0, 0.3,
           "battery terminal voltage (battery-side monitor, optional hardware)"),
    Signal("batt.current", "A", "telematics", "energy_total", -400.0, 400.0, 0.3,
           "battery current, positive on discharge (battery-side monitor, optional hardware)"),
)


def lookup(signal_id: str) -> Signal | None:
    for s in REGISTRY:
        if s.id == signal_id or ("*" in s.id and fnmatch.fnmatchcase(signal_id, s.id) and "." in signal_id):
            return s
    return None


def in_range(signal_id: str, value: float) -> bool:
    s = lookup(signal_id)
    return s is not None and s.lo <= value <= s.hi


def by_role(role: str) -> list[Signal]:
    return [s for s in REGISTRY if s.role == role]
