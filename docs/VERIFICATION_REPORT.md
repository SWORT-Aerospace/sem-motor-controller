# Verification report (v0.4)

Environment of every result here: x86-64 Linux host (Python 3.13.16, gcc 13.3, cmake 3.28, arm-none-eabi-gcc 13.2.1, KiCad 7.0.11) and GitHub-hosted ubuntu-24.04 runners (KiCad 8.0.9 for ERC). Nothing here was run on hardware. Commands are run from the repository root. Documentation and previously reported test counts were not taken as evidence: each line below was re-run.

## 1. Starting point

| Item | Value |
|---|---|
| Repository | `SWORT-Aerospace/sem-motor-controller` (moved from `andrefp-co/swort`, tree equality re-verified: `docs/MIGRATION.md`) |
| `main` | `19a327c` (v0.3) |
| Open pull request | `SWORT-Aerospace/sem-motor-controller#1` (`ci/declare-deps-run-kicad-gate`, head `c46faa8`): CI could not run, no runner was ever assigned |
| v0.4 work | branch `eng/v0.4-verification-integration`, based on `c46faa8` |

## 2. Baseline: clean checkout of `c46faa8`

`python3 tools/verify_all.py --full` in a fresh clone and virtual environment (2026-10-16): **26 PASS, 1 FAIL, 1 NOT AVAILABLE.**
* FAIL `kicad_drift`: regenerating the schematic changed 13 files by one line each. The generator stamped the current date, so the CI drift gate failed on any day after the commit day.
* NOT AVAILABLE `kicad_erc`: KiCad 7 has no `kicad-cli sch erc`.
* The full optimisation study and the frozen CSIA v1 evaluation reproduced their committed results exactly; only wall-clock fields (solve seconds, runtime) differed.

## 3. Discrepancy list

### 3.1 Implemented and independently reproduced
* Generators (configuration, protocol, DBC) current; configuration validation behaves as documented (synthetic valid for simulation; unconfigured hardware configuration rejected, 93 issues).
* C build and tests with ASan/UBSan; Cortex-M4F portable build (0 soft-float double calls in the fast step).
* pytest suite; host replay; control-contract report (0 violations).
* Optimisation study (numbers reproduced exactly); CSIA v1 held-out evaluation (reproduced exactly).
* KiCad connectivity (173 nets, 0 problems); pin-type rules (0 findings); timing budget; clock tree; hardware calculations; BOM pricing; telematics budget.

### 3.2 Implemented but failing (found in v0.4, now fixed; section 4)
* Schematic drift gate (date stamping).
* Session tag reused after a bus-off; rejected frame re-accepted on re-delivery; older frame accepted after the tracker went stale; freshness lock-out of up to 30 s and unbounded creeping delay.
* Measurements reported as healthy while flagged or before they existed; energy integrated across invalid samples without trace.
* Supervisor requesting propulsion from stale, duplicated or invalid speed.
* CSIA v1 power balance: no time alignment and no copper-loss term (35.7 false-alarm episodes per hour on the v2 generator).
* Three redundant no-connect flags (KiCad 8 ERC); TIM1_BKIN2 described as an over-current comparator; timing-budget inputs hard-coded while labelled as configuration values.

### 3.3 Simulated only
Everything about control, energy and monitoring: the controller core runs against a synthetic plant; the DP and strategies use synthetic vehicle, motor and inverter models; CSIA is evaluated on synthetic data; the telematics node, LTE, MQTT and the pit run as a host model.

### 3.4 Proposed but not implemented
* STM32G4 platform layer: timer and ADC configuration, CAN driver, precharge closing logic.
* Telematics firmware (only the host model of `host/telematics/` exists); a real MQTT broker connection.
* DP-schedule tracking with bounded pace correction in the supervisor; six-step commutation fallback.
* A minimum gate-off dwell or policy hysteresis (speed hold switched the gates 2752 times in 260 s on the host plant); a GNSS fix-quality gate in the B1 monitor; an independent over-current comparator.
* CSIA v3 candidates (endpoint corroboration excluding recently failed nodes, rotor observability).

### 3.5 Blocked by missing physical inputs
Motor type and parameters; battery and BMS limits; a measured battery-power map and coast-down; the event rules; the vehicle CAN bus parameters and identifier block; driver-control electrics; connectors and harness; wheel-sensor pulses per revolution; STM32U575 feasibility measurements; datasheets; live quotes. Prioritised in `docs/INPUT_SHEET.md`.

## 4. Defects fixed in v0.4

| Defect | Reproduced first by | Fix (commit) |
|---|---|---|
| Schematic and netlist not reproducible (date, absolute path) | baseline `kicad_drift` FAIL | revision date, normalised netlist (`d0f22a5`) |
| Bus-off recovery re-issued the same session tag; a queued pre-bus-off request was accepted | `test_core.c::test_bus_off_recovery_rejects_frames_from_before` (17 failed checks), property P5 | tag = per-boot offset + issued count (`1d4c265`) |
| Rejected frame re-accepted on re-delivery | `test_freshness.c::test_rejected_frame_redelivered_is_duplicate`, P5 | exact re-delivery of the last frame seen is a duplicate (`1d4c265`) |
| Older frame accepted after the tracker went stale | `test_older_frame_rejected_after_stale`, 100 × 30 s soak | ordering floor in every branch (`1d4c265`) |
| Freshness lock-out up to 30 s after a delayed sample; delay creeping by the tolerance per frame; delayed first sample locks the stream | `test_fresh_samples_after_a_delayed_one_are_accepted`, `test_creeping_delay_is_bounded`, `test_delayed_first_sample_is_reanchored`, property P8 (2464 failed checks on the old code) | telescoping lag reference with candidate re-anchoring (`1d4c265`) |
| vbus reported while flagged; validity nibble of another field | `test_flagged_vbus_is_reported_invalid_not_healthy` | (`1d4c265`) |
| Zeros reported before any measurement existed | `test_no_measurement_reported_before_it_exists` | NaN / MISSING (`1d4c265`) |
| Energy integrated across invalid samples and late steps without trace | `test_energy_gaps_are_counted_not_hidden` | gap accounting, `ctrl_energy_quality` (protocol 1.1) (`1d4c265`) |
| Supervisor used stale, duplicated or NaN speed | `tests/integration/test_supervisor.py` | sequence-checked, age-limited speed (`48b09b5`) |
| CSIA power balance (no alignment, no I²R term) | host demonstration: 507 E6 failures in 1200 ticks outside the fault | v2 adapter, frozen protocol, untouched evaluation (`b44e781`, `4207051`) |
| BKIN2 described as an over-current comparator | `tools/hw_consistency.py` review | description corrected at the generator (`3d98c2e`) |
| Timing budget "configuration" inputs hard-coded | review while writing `hw_consistency.py` | read from configuration (`3d98c2e`) |
| Redundant no-connect flags (3 + 3 ERC warnings) | KiCad 8.0.9 ERC in CI run 38942663476 | no flag on library no-connect pins (`3a1c496`) |

A measurement error in a new tool was caught before publication: the first version of `tools/run_policy_comparison.py` compared windows ending at different speeds (one configuration appeared 1.7 % better than speed hold). It now integrates over whole cycles and reports the residual kinetic-energy change (≤ 0.01 J/m).

## 5. CI on GitHub-hosted runners

| Run | Commit | Result |
|---|---|---|
| 38933061949 (first run ever assigned a runner) | `0b40193` | success |
| 38933753179, 38933760570 (PR #1, push and pull request) | `e7a0b57` (PR #1 with the drift fix) | success |
| 38942663476 (first run with ERC) | `3d98c2e` | success; ERC 0 errors, 215 warnings |
| 38943419930 | `3a1c496` | success; ERC 0 errors, 9 warnings (library-version differences: symbols embedded from the KiCad 7 library, checked against KiCad 8) |
| 38944073133 | `4c8b5bf` | success (`host` and `erc`); ERC 0 errors, 9 warnings as above |

Later runs of this branch are listed on the pull request.

## 6. Full verification record

`docs/generated/verification/verification.md` (and `.json`; logs not committed): every check of `tools/verify_all.py --full`, run in a fresh clone and a new virtual environment at `4c8b5bf`. The commit that adds the record changes only this report and the record itself.

Result: **31 PASS, 0 FAIL, 1 NOT AVAILABLE.** The NOT AVAILABLE check is `kicad_erc`, because this host has KiCad 7. ERC runs in CI on KiCad 8.0.9 instead (run 38944073133). The full studies regenerated five tracked files, and their numbers matched the committed results exactly. Only wall-clock fields differed:
* the optimisation `solve_s` and the table's seconds column;
* the CSIA v1 re-run's `runtime_s`;
* the host tick-time line of the CSIA development study.

## 7. v0.5: telemetry integration, README and procurement

Branch `eng/v0.5-telemetry-integration`, based on `0b7255e` (the head of SWORT-Aerospace/sem-motor-controller#2, open). Host software and documents only; nothing was built, energised or tested on the vehicle.

### 7.1 Found and fixed

| Defect | Found by | Fix |
|---|---|---|
| Pit validation accepted JSON `true`/`false` as integers for `seq` and `t_local_ms` (Python `bool` is an `int`) | `test_validation_rejects_boolean_and_inconsistent_fields`; injected in the MQTT demo | integers checked as non-boolean; also `utc` vs `utc_q`, `utc_err_s`, counters, empty `run_id` |
| The host demo's summary pointed at a missing `docs/CSIA_EVALUATION_v2.md` | `tools/check_links.py` (paths in current documents) | points at `docs/csia/EVALUATION_PROTOCOL_v2.md` and `EVALUATION_RESULTS_v2.md` |
| A refused hand-over to the uplink would have lost the message (the simulated link never refused, so this path had never run) | the real MQTT link (a client can refuse when its buffer is full) | the message returns to the bounded backlog; a test covers it |
| Mosquitto started as root dropped privileges, could not write its persistence, and after a crash acknowledged messages that no subscriber received | MQTT smoke test (session lost: `session_present=False`) | `tools/mqtt_broker.py` keeps the starting user when root; the general behaviour stays as a test (`test_broker_acknowledgement_is_not_end_to_end_delivery`) |

### 7.2 Design findings (not defects)

* DRV5032 (any variant in SLVSDC7F) cannot count wheel magnets at vehicle speed: sampled every 27 to 75 ms with the output latched between samples (`generated/wheel_sensor_check.md`).
* The telematics proposal's BQ25622E charger implies an on-board battery; 2026 Article 57b allows no accessory battery on a Battery Electric vehicle.
* Telemetry energy counts in the official result (Article 56d).
* An unmodelled 0.1 % grade biases a one-direction coast-down by 40 % in rolling resistance (`generated/coastdown_sensitivity.md`).

### 7.3 Commands run and results

| Where | Command | Result |
|---|---|---|
| fresh clone of `042044a`, new virtual environment, Mosquitto 2.0.18 (Ubuntu package extracted locally) | the README "Getting started" commands, in order | ctest 8/8 passed; pytest 249 passed; host demo 9/9; MQTT demo 10/10 |
| working tree | `tools/run_host_demo.py` before and after the refactor | the 70506 log records are identical (NaN-aware comparison); only the dirty-tree flag in the metadata differs |
| working tree | `python3 -m pytest tests/integration/test_mqtt_pipeline.py` with `SEMMC_REQUIRE_MQTT=1` | 7 passed |
