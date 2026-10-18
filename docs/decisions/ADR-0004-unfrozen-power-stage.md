# ADR-0004: Power stage stays unfrozen

**Decision.** MOSFET ratings and parallel count, driver order code, shunts, CSA gain, DC-link C, copper, thermal path, PWM frequency, dead time, thresholds, connectors and fuses are **not frozen**. The parameterised calculations (`models/inverter/losses.py`, `tools/run_electrical_calcs.py`) show the selection is dominated by **unmeasured** inputs: the drive-cycle phase-current distribution, maximum pack voltage and measured overshoot, motor inductance, and amplifier offset. Two examples: the light-load efficiency ranking of the candidate MOSFETs inverts relative to their RDS(on) ranking, and an uncalibrated 3 mV CSA offset on a 1 mΩ shunt is a 3 A error against a ~2 A cruise current (synthetic numbers, snippet data).

**Consequence.** `config/vehicle.unconfigured.yaml` keeps these fields null, and the hardware CMake configure step fails until they are measured.
