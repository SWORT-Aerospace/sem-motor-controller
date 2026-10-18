"""Vehicle context from the available evidence (telematics/schema/telemetry_schema.yaml, `contexts`).

A cross-domain relation is only meaningful in some operating conditions (a wheel and GNSS agree while cruising,
not during a launch with slip; the motor and the wheel agree only while the freewheel transmits torque). Every
relation therefore declares the contexts it is valid in, and this module says which context the evidence shows.

Contexts, and what each needs:

  STARTUP   the first `startup_s` after boot, or until any motion evidence is VALID
  STOPPED   a source that can measure zero (GNSS speed; motor speed only when the drivetrain has no freewheel)
            below `stop_mps`. A Hall wheel channel never shows STOPPED: a held line is not standstill
  LAUNCH    speed below `launch_ceiling_mps`, rising, with propulsion effort
  CRUISE    speed at or above `floor_mps`, |dv/dt| within `cruise_band_mps2`
  COAST     speed at or above `floor_mps`, no propulsion effort (known), decelerating
  UNKNOWN   none of these is shown by admissible evidence; the reason says what is missing

Acceleration is the derivative of the admissible speed when the caller has one, else the IMU's longitudinal axis.
BRAKE and READY are not determinable with the signals received (no brake signal; the controller's state codes
are undefined until the controller team states them) and are never reported. All thresholds are PROVISIONAL.
Only VALID evidence is used; every input and its state is kept with the result for the evidence receipt.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from host.telematics.evidence import Evidence

MODES = ("STARTUP", "STOPPED", "LAUNCH", "CRUISE", "COAST", "UNKNOWN")
NOT_DETERMINABLE = {"BRAKE": "no brake signal is received; deceleration alone cannot tell braking from grade or drag",
                    "READY": "the controller's state codes are not defined by the controller team"}


@dataclasses.dataclass(frozen=True)
class ContextConfig:                       # every value PROVISIONAL
    startup_s: float = 5.0
    stop_mps: float = 0.3
    floor_mps: float = 1.0
    launch_ceiling_mps: float = 3.0
    cruise_band_mps2: float = 0.15
    accel_threshold_mps2: float = 0.10
    effort_current_A: float = 2.0
    effort_torque_Nm: float = 0.5
    freewheel: Optional[bool] = None       # drivetrain parameter: None = unknown


@dataclasses.dataclass(frozen=True)
class Context:
    mode: str
    reason: str
    speed_mps: Optional[float]
    speed_source: Optional[str]
    accel_mps2: Optional[float]
    accel_source: Optional[str]
    effort: Optional[bool]
    inputs: dict                            # signal -> (state, value)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _v(ev: dict, sig: str) -> Optional[float]:
    e = ev.get(sig)
    return e.value if e is not None and e.admissible else None


def classify(ev: dict[str, Evidence], t_since_boot_s: float, accel_from_speed: Optional[float] = None,
             cfg: ContextConfig = ContextConfig()) -> Context:
    """`ev`: the latest evidence per signal (any of gnss.speed, wheel.<ch>.speed, ctrl.motor_speed, imu.ax,
    ctrl.dc_current, ctrl.torque_reference). `accel_from_speed`: a speed derivative the caller computed from
    admissible speeds, or None."""
    inputs = {s: (e.state, e.value) for s, e in ev.items()}
    gnss = _v(ev, "gnss.speed")
    wheels = sorted(v for s, e in ev.items() if s.startswith("wheel.") and s.endswith(".speed")
                    for v in [e.value] if e.admissible)
    motor = _v(ev, "ctrl.motor_speed")
    any_motion = gnss is not None or bool(wheels)
    if t_since_boot_s < cfg.startup_s or (not any_motion and motor is None and t_since_boot_s < 2 * cfg.startup_s):
        return Context("STARTUP", f"{t_since_boot_s:.1f} s after boot", None, None, None, None, None, inputs)
    # speed: GNSS can measure zero; a wheel cannot; the motor only without a freewheel
    if gnss is not None:
        speed, ssrc = gnss, "gnss.speed"
    elif wheels:
        speed, ssrc = wheels[len(wheels) // 2], "wheel (median of admissible channels)"
    else:
        speed, ssrc = None, None
    if gnss is not None and gnss < cfg.stop_mps:
        return Context("STOPPED", f"GNSS speed {gnss:.2f} m/s < {cfg.stop_mps}", gnss, "gnss.speed", None, None,
                       None, inputs)
    if cfg.freewheel is False and motor is not None and abs(motor) < 1e-3 and speed is None:
        return Context("STOPPED", "motor speed 0 and the drivetrain has no freewheel", 0.0, "ctrl.motor_speed",
                       None, None, None, inputs)
    if speed is None:
        why = "no admissible speed evidence (" + ", ".join(f"{s}: {st}" for s, (st, _v2) in sorted(inputs.items())
                                                            if "speed" in s) + ")"
        return Context("UNKNOWN", why, None, None, None, None, None, inputs)
    # the speed derivative first: the IMU also reads the road grade, and a context taken from the IMU alone would
    # let an IMU offset switch off every relation that needs CRUISE
    ax = _v(ev, "imu.ax")
    accel, asrc = (accel_from_speed, "speed derivative") if accel_from_speed is not None else \
        (ax, "imu.ax") if ax is not None else (None, None)
    cur, trq = _v(ev, "ctrl.dc_current"), _v(ev, "ctrl.torque_reference")
    if cur is None and trq is None:
        effort = None
    else:
        effort = (cur is not None and cur > cfg.effort_current_A) or (trq is not None and trq > cfg.effort_torque_Nm)
    if accel is None:
        return Context("UNKNOWN", f"speed {speed:.2f} m/s from {ssrc}, but no admissible acceleration", speed, ssrc,
                       None, None, effort, inputs)
    if speed < cfg.launch_ceiling_mps and accel > cfg.accel_threshold_mps2 and effort:
        return Context("LAUNCH", "low speed, accelerating, propulsion effort", speed, ssrc, accel, asrc, effort,
                       inputs)
    if speed >= cfg.floor_mps and abs(accel) <= cfg.cruise_band_mps2:
        return Context("CRUISE", f"|a| {abs(accel):.2f} <= {cfg.cruise_band_mps2} m/s^2", speed, ssrc, accel, asrc,
                       effort, inputs)
    if speed >= cfg.floor_mps and effort is False and accel < -cfg.accel_threshold_mps2:
        return Context("COAST", "no propulsion effort, decelerating", speed, ssrc, accel, asrc, effort, inputs)
    why = "transient" if effort is not None else "propulsion effort unknown (no admissible current or torque)"
    return Context("UNKNOWN", f"{why}: speed {speed:.2f} m/s, a {accel:.2f} m/s^2", speed, ssrc, accel, asrc, effort,
                   inputs)
