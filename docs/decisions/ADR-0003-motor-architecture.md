# ADR-0003: Motor-dependent architecture

**Decision.** Path A (frozen if C1 holds): three-phase MOSFET inverter, three low-side shunts, hall sensors, sensored FOC with `id = 0`.

**Alternatives recorded so that no motor-specific hardware is built before the motor is known.**
* Path B, brushed DC: an H-bridge or single-quadrant buck, one shunt, armature current loop. The state machine, arbiter, protocol, freshness, config validation and CSIA adapter are reused unchanged. Only `mc_foc`/`mc_hall` and the power-stage sheets change.
* Path C, BLDC with trapezoidal back-EMF: six-step commutation may beat FOC at light load. This is **not assumed** either way (EFFICIENCY_RESEARCH H4/H5). It would add a six-step modulator behind the same current reference.
* Path D, sensorless: requires an observer and a start-up strategy, and reopens rotor sensing.

**Enforcement.** The config validator rejects any `motor.type` other than `pmsm_sinusoidal` (`ARCH_MOTOR_TYPE`) and any rotor sensor other than hall (`ROTOR_SENSOR_UNSUPPORTED`), so a hardware build cannot silently proceed on an unsupported motor.
