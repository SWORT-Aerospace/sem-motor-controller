# ADR-0006 — Unknowns are never defaulted

Unknown parameters are **null** in `config/vehicle.unconfigured.yaml`. Validation has two modes:
* `sim` accepts `provenance: synthetic` but forbids `physical_output_permitted: true`.
* `hw` requires every rating and calibration, `provenance: bench_measured`, explicit `physical_output_permitted: true`, recorded measurement metadata, a hazard-analysis reference, and `timing_status: hazard_analysed`.

Defense in depth:
1. The CMake option `SEMMC_HARDWARE_BUILD=ON` fails at configure time (tested).
2. The firmware re-validates the blob at boot. A hardware build with an invalid or synthetic blob stays in `FAULT_LATCHED(CONFIG_INVALID)` (tested).
3. `mc_config_permits_physical_output()` is the only gate for physical outputs and always returns false on a host build.
