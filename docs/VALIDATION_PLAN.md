# Validation plan v0.1

**Nothing in this repository has been run on hardware.** The automated tests verify software behaviour on a host, with a synthetic plant. They are prerequisites for hardware work, not substitutes for it. Energized tests are performed by qualified team members under their own lab safety procedures. They are never performed autonomously.

## 1. What exists today (host)

| Suite | Command | Scope |
|---|---|---|
| C unit/integration (6 suites, ASan+UBSan) | `cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build` | config, freshness, control primitives, state machine/arbiter, protocol golden vectors, closed-loop core + synthetic plant |
| Python (protocol, config parity, co-simulation, fault injection, replay, models, CSIA) | `python -m pytest` | see `tests/` |
| Cortex-M4F portability compile | `cmake -S firmware -B build-arm -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi-cortex-m4f.cmake -DSEMMC_PORTABLE_ONLY=ON` | compiles the core only; **no firmware image** |

## 2. Hardware validation stages (each gate needs the previous one passed and recorded)

| Stage | Purpose | Entry criteria | Key checks | Exit evidence |
|---|---|---|---|---|
| 0. Design review | schematic/layout review against `hardware/review/REVIEW_CHECKLIST.md` | all UNFROZEN items decided from measurements | creepage, current paths, thermal, protection independence, "SEM" etch | signed review |
| 1. Unpowered inspection | assembly quality | bare board + assembled | visual, continuity, shorts between rails and to the power plane, gate–source resistances, shunt values | photos + measured table |
| 2. Logic-only | MCU, rails, comms | current-limited **logic supply only**, no power-stage bus | rail voltages and quiescent currents (feeds H6), SWD, CAN loopback with the companion, blob load + hw validation, self-test path, watchdog trip disables driver ENABLE | logs |
| 3. Gates, power stage disabled | PWM and driver | bus not connected | gate waveforms per phase, dead time measured at the gate, break input (BKIN) latency, driver SPI config readback, nFAULT behaviour | scope captures |
| 4. Low-energy switching | first energized switching | **current-limited bench supply**, low voltage, resistive/inductive dummy load, double-pulse fixture | overshoot at the switch node and bus (sets `transient_margin_fraction`), hardware overcurrent trip threshold and latency, current-sense offset/gain calibration, precharge timing | measured margins replace synthetic ones |
| 5. Motor at limited current | commissioning | motor on a stand, wheel free, current limit low | hall table and offset, Rs/L/λ measurement, current-loop step response, fault injection on the bench (hall disconnect, phase-sense loss) | `vehicle.<name>.yaml` with `provenance: bench_measured` |
| 6. Loaded thermal and efficiency | maps and limits | dynamometer or loaded stand | battery-side power map P_batt(ω, T, V, θ), thermal derating curves, INA228 vs reference meter, ripple vs PWM frequency (H1), dead time (H2), coast consumption (H3) | measured loss map (`MeasuredLossMap` CSV) |
| 7. Shutdown and fault behaviour | protection independence | stage 6 passed | e-stop isolation with the controller powered, dead-man, brake override, bus-off, companion disconnect, controller reset mid-request (repeat the host fault list on hardware) | test record |
| 8. Vehicle integration and supervised track tests | in-vehicle | stage 7 passed; organizer and team safety process | manual first; ECO only after the hazard/latency analysis replaces provisional timing; CSIA in shadow | run logs |

## 3. Host fault list to repeat on hardware (stages 5–7)
Stale, repeated and reordered commands · counter wrap · source reboot · NaN/malformed payloads · missing and stuck speed · missing and biased current · controller reboot during an active request · CAN disconnect and bus-off · driver cancellation · gate-driver fault · temperature derating · PI saturation recovery · time-step variation · unsupported configurations · no output after invalid startup or fault recovery. Normal events that must not trip: cornering, acceleration, voltage sag, thermal drift, low-speed pulses, traction saturation, GNSS degradation.

## 4. Energy measurement calibration
* Calibrate the controller's INA228-class DC meter against an independent reference (calibrated shunt + DMM or power analyser) across the current range, including near-zero currents. Report gain and offset with uncertainty.
* Cross-check against the official joulemeter in static tests (if accessible) before relying on in-run comparisons.
* Never derive energy from phase shunts.

## 5. Energy-strategy validation (statistics)
* **Separate effects.** Controller-hardware improvements (H1–H3, H6) are measured on the **same strategy**. Strategy improvements (H4, H5) are measured on the **same hardware and configuration**.
* **Matched constraints.** Strategies are compared at the same finish-time target and reserve.
* **Unit of analysis: a run (attempt).** Thousands of samples from one lap are not independent trials.
* **Design.** Randomized or counterbalanced run order (e.g. ABBA blocks), the same driver where possible, and predefined exclusion reasons written down before testing. Failed runs are kept.
* **Covariates recorded per run:** battery SoC/voltage at start, battery and ambient temperature, vehicle mass, tyre type and pressure, wind (speed/direction), track condition, driver.
* **Sample size.** From pilot run-to-run variability s and a predefined minimum useful effect δ: n ≈ 2·(z₁₋α/₂ + z₁₋β)²·s²/δ² per arm, with paired designs where possible. Decide δ before seeing the data.
* **Report** the run-level mean difference with a 95 % CI (paired t or bootstrap), combined with the energy-measurement uncertainty from §4.

## 6. CSIA evidence gate (ADR-0008)
Before CSIA may **tighten** supervisory bounds (never command):
1. ≥ 10 h of in-vehicle shadow data, including every normal event class above.
2. A nuisance-alarm rate (suspect or ambiguous on normal events) below a pre-registered bound, e.g. < 1 per 10 h.
3. For each injected fault class: detection and isolation within a pre-registered latency, with zero misattributions; regime-bound latency documented.
4. Incremental benefit over B1 (freshness/range) and over calibrated residuals using the **same gates** (V3/V3v), measured on the same data. The synthetic held-out evaluation (`docs/csia/EVALUATION_RESULTS.md`) shows the method and the current state: the frozen adapter's false-alarm rate is 19.7/h on unseen synthetic scenarios, it has 9 misattributions, and it brings no false-alarm benefit over gated, debounced residuals. The 0-nuisance figure from the development run (`csia_comparison_synthetic.md`) was measured on tuning data and is not evidence of generalisation.
5. Timing on the **target** (or a float port validated against declared numerical tolerances). Host figures (mean 0.23 ms per tick, CPython, x86-64) are not target evidence.
6. A written owner license decision for vehicle use of the CSIA core.
7. A new ADR.
