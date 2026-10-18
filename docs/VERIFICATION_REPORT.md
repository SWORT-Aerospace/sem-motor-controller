# Verification report (v0.4; v0.5 in section 7; v0.6 in section 8; v0.7 in section 9)

Environment of every result here: x86-64 Linux host (Python 3.13.16, gcc 13.3, cmake 3.28, arm-none-eabi-gcc 13.2.1, KiCad 7.0.11) and GitHub-hosted ubuntu-24.04 runners (KiCad 8.0.9 for the ERC, and from v0.6 also for the connectivity gate and drift check). Nothing here was run on hardware. Commands are run from the repository root. Documentation and previously reported test counts were not taken as evidence: each line below was re-run.

## 1. Starting point

| Item | Value |
|---|---|
| Repository | `SWORT-Aerospace/sem-motor-controller` (moved from `andrefp-co/swort`, tree equality re-verified: `docs/archive/MIGRATION.md`) |
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

`docs/generated/verification/verification.md` (and `.json`; logs not committed): every check of `tools/verify_all.py --full`, run in a fresh clone and a new virtual environment at `75f1b24` (v0.5). The previous record (v0.4, `4c8b5bf`: 31 PASS, 0 FAIL, 1 NOT AVAILABLE) is replaced.

Result: **37 PASS, 0 FAIL, 1 NOT AVAILABLE.** The NOT AVAILABLE check is `kicad_erc`, because the verification host has KiCad 7; the ERC runs in CI on KiCad 8 instead (0 errors, 9 warnings). The full studies regenerated five tracked files, and their numbers matched the committed results exactly. Only wall-clock fields differed, so those files were not committed again:
* the optimisation `solve_s` and the table's seconds column;
* the CSIA v1 re-run's `runtime_s`;
* the host tick-time line of the CSIA development study.

## 7. v0.5: telemetry integration, README and procurement

Branch `eng/v0.5-telemetry-integration`, based on `0b7255e` (the head of SWORT-Aerospace/sem-motor-controller#2, open). Host software and documents only; nothing was built, energised or tested on the vehicle.

### 7.1 Found and fixed

| Defect | Found by | Fix |
|---|---|---|
| Pit validation accepted JSON `true`/`false` as integers for `seq` and `t_local_ms` (Python `bool` is an `int`) | `test_validation_rejects_boolean_and_inconsistent_fields`; injected in the MQTT demo | integers checked as non-boolean; also `utc` vs `utc_q`, `utc_err_s`, counters, empty `run_id` |
| The host demo's summary pointed at a CSIA document that does not exist (`CSIA_EVALUATION_v2.md` in `docs/`) | `tools/check_links.py` (paths in current documents) | points at `docs/csia/EVALUATION_PROTOCOL_v2.md` and `EVALUATION_RESULTS_v2.md` |
| A refused hand-over to the uplink would have lost the message (the simulated link never refused, so this path had never run) | the real MQTT link (a client can refuse when its buffer is full) | the message returns to the bounded backlog; a test covers it |
| Mosquitto started as root dropped privileges, could not write its persistence, and after a crash acknowledged messages that no subscriber received | MQTT smoke test (session lost: `session_present=False`) | `tools/mqtt_broker.py` keeps the starting user when root; the general behaviour stays as a test (`test_broker_acknowledgement_is_not_end_to_end_delivery`) |
| `run_optimization.py --quick` (CI, `verify_all.py` quick mode) overwrote the committed full-resolution study results with coarse-grid ones | folder-guide review of `tools/` and `models/` | `--quick` writes to `build/optimization_quick/`; `--out DIR` added; a quick run leaves `docs/generated/` unchanged (checked) |
| `run_pit_replay.py` added its configuration notes (changed configuration hash, missing counting window) after the report was written, so they reached only the console | folder-guide review of `host/` | `shadow_replay.run(..., notes=...)` writes them into the evidence list; test `test_cli_writes_configuration_notes_into_the_report` |
| The C test of the identifier block listed 15 of the 16 messages (`ctrl_energy_quality`, 0x323, missing) | folder-guide review of `protocol/` | listed, and the count is checked |
| `telematics_budget.py` labelled the controller traffic as 11 messages; its 394 frames/s count 12 | same | label corrected, report regenerated |
| `resistive_force_np` was documented as tested for equality with `resistive_force`, but no test compared them | folder-guide review of `models/` | `test_vectorised_resistive_force_equals_scalar_form` |
| Generated check reports and records still said the KiCad ERC had not run or remained a blocker (`CONNECTIVITY_CHECK.md`, `PIN_TYPE_CHECK.md`, `PINOUT_VERIFICATION.md`, `HARDWARE_ARCHITECTURE.md`); it has run in CI since v0.4 | folder-guide review of `hardware/` | generator texts and records corrected; historical records (`REVIEW_v0.3.md`, `CHECKPOINT_v0.2.md`) carry a banner instead of being rewritten |
| `docs/CONTROL_CONTRACT.md` 4 cited a timing file, MCU_TIMING_ALLOCATION.md, that does not exist | folder-guide review of `firmware/` | points at `hardware/timing/timing_budget.md` |
| Stale counts in current documents (MQTT demonstration "ten checks", host demonstration "nine checks") | review | 12 and 10, as the summaries show |
| The quick start creates `.venv/` in the repository, which `.gitignore` did not ignore | review of the quick start | `.venv/` ignored |

### 7.2 Design findings (not defects)

* DRV5032 (any variant in SLVSDC7F) cannot count wheel magnets at vehicle speed: sampled every 27 to 75 ms with the output latched between samples (`generated/wheel_sensor_check.md`).
* The telematics proposal's BQ25622E charger implies an on-board battery; 2026 Article 57b allows no accessory battery on a Battery Electric vehicle.
* Telemetry energy counts in the official result (Article 56d).
* An unmodelled 0.1 % grade biases a one-direction coast-down by 40 % in rolling resistance (`generated/coastdown_sensitivity.md`).
* **Rules edition.** A 2027 Chapter I is listed on the organisers' global-rules page (web search, 2026-10-17); neither the page nor the PDF could be accessed, so the 2027 text was not read. Every 2026 finding is to be re-checked against the governing edition (`RULES_COMPLIANCE.md`).
* **Controller behaviours recorded for review, not changed** (`firmware/README.md` 9; `DESIGN_DECISIONS.md` D9): a `SELFTEST` fault is cleared by a fault reset without a new self-test before the next arming; a `HALL_INVALID` fault cannot be cleared by the fault-reset input; `sup_hello` freshness is tracked but nothing reads it, so the ICD's 3 s hello window has no effect; `ctrl_fault` is sent early only on entering or leaving `FAULT_LATCHED`; `rx_len_fail` is never incremented (length errors count as `rx_crc_fail`); `ctrl_identity` always sends hardware revision 0.
* **Documentation and code disagreements recorded, not changed:**
  * the code numbers the arbiter layers L0 to L4, while the documents say four layers;
  * `mc_state_machine.h` lists invariants I1 to I9, while other files say I1 to I7;
  * `firmware/platform/stm32g4/README.md` quotes about 29.5 kB of text; the last build measured 31,955 bytes;
  * `protocol/protocol.yaml` cites a hand-calculation test file that is `test_protocol_python.py` (changing the comment changes the spec hash);
  * the frozen `host/csia_adapter/eval_set.py` cites `DEV_SET_FREEZE.md` for `DEV_SET_FREEZE.json` (a frozen file: not edited);
  * `hardware/kicad/semmc_schematic_DRAFT.pdf` predates the last sheet change;
  * `COMPONENT_SELECTION.md` calls the INA228 pins placeholders, while the generator uses KiCad-library numbers;
  * `docs/generated/verification/verification.md` contains absolute temporary paths;
  * `docs/generated/bus_load.md` is written by no tool;
  * CI detects stale committed outputs only for the tools with a `--check` form and the schematic `git diff` gate (`tools/README.md` 2).
* **Research provenance.** The v0.5 research used GitHub-hosted copies of manufacturer documents and GitHub code search, which reaches repositories outside this project; those copies were used as read-only evidence. One DRV5032 copy (revision H) that was obtained through the Git LFS media host after a refusal is excluded from the evidence; the facts used come from revision F (`TELEMETRY_CANDIDATES.md`).

### 7.3 Commands run and results

| Where | Command | Result |
|---|---|---|
| fresh clone of `042044a`, new virtual environment, Mosquitto 2.0.18 (Ubuntu package extracted locally) | the README "Getting started" commands, in order | ctest 8/8 passed; pytest 249 passed; host demo 9/9; MQTT demo 10/10 |
| working tree | `tools/run_host_demo.py` before and after the refactor | the 70506 log records are identical (NaN-aware comparison); only the dirty-tree flag in the metadata differs |
| working tree | `python3 -m pytest tests/integration/test_mqtt_pipeline.py` with `SEMMC_REQUIRE_MQTT=1` | 7 passed |
| fresh clone of `35871e0`, new virtual environment, Mosquitto 2.0.18 through `SEMMC_MOSQUITTO` | the README section F commands, verbatim, in order | ctest 8/8 passed; pytest 269 passed, 0 skipped, 0 failed; host demo 10/10; pit replay report and `energy.json` written; MQTT demo 12/12; `git status` empty afterwards |
| working tree | the three README diagrams rendered with `@mermaid-js/mermaid-cli` 11.4.0 (Chromium) | all three render; diagram 1 reordered so the driver controls do not appear to pass through the protection block |
| working tree | README budget table parsed independently and summed per category | every category's TBD and not-counted counts match the subtotal table; rounded rows sum to at most $1 more than the subtotal (the subtotal is rounded after summing; noted under the table); the total estimate equals `budget.json` S1 `complete_buying_equipment` ($415 to $1,189) |
| working tree | `tests/integration/test_pit_energy.py` | the README worked example recomputed by independent arithmetic and by the model functions |
| working tree | `python3 tools/run_optimization.py --quick` | writes `build/optimization_quick/`; `docs/generated/` and `docs/figures/` unchanged |
| GitHub-hosted CI | runs 38985549136 (push) and 38985552327 (pull request) on `e1b59a6` | success (`host` and `erc`) |

## 8. v0.6: vehicle engineering package

Branch `eng/v0.6-vehicle-package`. Three milestones are tracked separately and none is claimed beyond its evidence: (1) engineering design ready for review, (2) fabrication-ready hardware and buildable target firmware, (3) bench-validated integrated hardware. Status: the design is reviewable with the open items of [`BLOCKERS.md`](BLOCKERS.md); the target firmware builds and links but has not run on a board; the hardware is **not** fabrication-ready (release gate [`generated/release_gate.md`](generated/release_gate.md): FAIL); nothing has been bench-tested.

### 8.1 Repository reconciliation (2026-10-17)

| Branch | Head | Content | Pull request | CI on that head | In the delivery branch |
|---|---|---|---|---|---|
| `main` | `3a80039` | v0.3 (`19a327c`) plus one team edit of the v0.3 questionnaire (2026-10-16) | none | run 38990669982: success | yes (merged into v0.5; the edit survives in `archive/PHYSICAL_TEAM_QUESTIONNAIRE.md`) |
| `ci/declare-deps-run-kicad-gate` | `e7a0b57` | CI dependencies, connectivity gate, drift guard | SWORT-Aerospace/sem-motor-controller#1 into `main`, open | runs 38933753179, 38933760570: success | its first two commits are ancestors; the third is contained as the equivalent commit `d0f22a5` (`git cherry`) |
| `eng/v0.4-verification-integration` | `0b7255e` | v0.4: verification, safety-property fixes, host data chain, CSIA v2, ICD v1.0, hardware checks | SWORT-Aerospace/sem-motor-controller#2 into `main`, open | runs 38947078278, 38947182903: success | yes (ancestor) |
| `eng/v0.5-telemetry-integration` | `76f4cfc` | v0.5: telemetry through a real MQTT broker, team documentation, procurement, the robust MQTT timing check | SWORT-Aerospace/sem-motor-controller#3 into `main`, open | runs 39070286030, 39070288670: success | yes (ancestor) |
| `research/evidence-acquisition` | `73b23c2` | the pre-registered evidence-acquisition research (host simulation) | SWORT-Aerospace/sem-motor-controller#4 into the v0.5 branch, open | runs 39007984139, 39008556098: success | no: kept separate and not extended while the vehicle delivery is blocked |
| `ci-probe/runner-start` | `51f940c` | a temporary runner diagnostic, labelled "to be deleted" in its commit | none | not relevant | no |
| `eng/v0.6-vehicle-package` | see 8.3 | v0.5 plus the v0.6 commits | opened for review into `main` | 8.3 | (this branch) |

**Why the default README showed v0.3.** GitHub shows `main`, and no pull request had been merged: every later release was on a branch built on the previous one. The delivery branch contains `main`, PR #1's changes, v0.4 and v0.5, so its pull request alone brings `main` up to date and makes #1 to #3 redundant; #4 stays separate.

**Which reported improvements are committed.** Every item of sections 4, 7 and 8.2 is a commit on the delivery branch (`git log origin/main..eng/v0.6-vehicle-package`). Statements found obsolete and corrected with their evidence: "ERC never run" and "warnings are library-version differences" (now the run, revision and per-warning review, then 0 warnings; `hardware/README.md` 6, `hardware/review/DESIGN_REVIEW.md`); "STM32G4 platform layer not written" (the linked image, `firmware/platform/stm32g4/README.md`); "readable in KiCad 7 or newer" (the project release is KiCad 8.0.9); "no record type for temperature probes" (STLG `TEMP`, ICD 8); the v0.5 bring-up checklist (superseded by [`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md), archived).

### 8.2 Closed in this revision

| Item | Evidence |
|---|---|
| Flaky MQTT step-timing check on v0.5 | criterion on blocking behaviour, negative test; `76f4cfc`, runs 39070286030 and 39070288670 |
| KiCad ERC warnings | 9 `lib_symbol_issues` reviewed one by one; cause removed (pinned 8.0.9 libraries); run 39078886365 on `40b3dfa`: 0 errors, 0 warnings |
| Two KiCad versions | both CI jobs on KiCad 8.0.9 with the SHA-256-pinned libraries; the generator's output equals the committed schematic in run 39078886365 |
| Over-voltage comparator hysteresis acted on the TL431's low-impedance node (found in review) | 10 k input and 390 k hysteresis resistors, `a9a378c`; `DESIGN_REVIEW.md` item 6 |
| A fast-loop overcurrent raised during the slow step could be erased (found in review) | `1479d16`; `firmware/tests/test_core_preemption.c` fails on the old code |
| No target image | `c3f716b`: startup, linker script, clock, PWM and break inputs, ADC with DMA, hall capture, CAN with bus-off, watchdogs, precharge sequencing, calibration store, event log; image built in CI (artifact `semmc-stm32g474-image`); power stage inhibited |
| MCU alternate functions unchecked | `tools/gen_board_pins.py`: 45 functions, 0 errors against ST's pin database |
| Temperature logging | STLG `TEMP` record and live summary `sem.telemetry.v3`, producer and consumer tests, host demonstration check with an injected probe fault |
| Budget categories and scenarios | nine categories, three builds against $500 and $1,000 ([`PROCUREMENT.md`](PROCUREMENT.md)) |

Open items, each with its missing input and closure criterion: [`BLOCKERS.md`](BLOCKERS.md).

### 8.3 CI on the delivery branch

| Run | Commit | Result |
|---|---|---|
| 39071741661 | `1b799bb` | failure: `test_file_index_covers_every_tracked_file` (vendored headers not yet in the file index); fixed in the next commits |
| 39078886365 | `40b3dfa` | success: `host` (generated files, C tests with sanitizers, connectivity gate and drift check on KiCad 8.0.9, Python tests, both demonstrations, Cortex-M4F core, STM32G474 image) and `erc` (0 errors, 0 warnings) |

### 8.4 Fresh-clone verification of `d7131d5`

A fresh clone of `d7131d5`, x86-64 Linux host: Python 3.13.16, gcc 13.3.0, CMake 3.28.3, Ninja 1.11.1, arm-none-eabi-gcc 13.2.1, kicad-cli 7.0.11, Mosquitto 2.0.18 through `SEMMC_MOSQUITTO`. The `git status` was empty after every step.

| Step | Command | Result |
|---|---|---|
| dependencies | `tools/fetch_csia.py`, `tools/fetch_kicad_symbols.py` | pinned commit and 17 libraries verified |
| generated files | the `--check` forms of `gen_config`, `gen_protocol`, `gen_dbc`, `gen_procurement`, `gen_board_pins`, `blockers`, `acceptance render`, `wheel_sensor_check`, `coastdown_sensitivity`; `check_links.py` | all current; links 121 files, 0 broken |
| configurations | `config_tool.py validate` | synthetic valid in sim mode; unconfigured refused in hw mode (107 issues) |
| C tests | `ctest` (ASan/UBSan) | 10/10 passed |
| schematic | `gen_kicad_schematic.py --check` | connectivity 0 problems; no drift |
| Python tests | `pytest -rs` with `SEMMC_REQUIRE_MQTT=1`, `SEMMC_REQUIRE_ARM=1` | 290 passed, 0 skipped, 0 failed |
| demonstrations | `run_host_demo.py`, `run_pit_replay.py`, `run_mqtt_demo.py` | 11/11; report written; 12/12 |
| Cortex-M4F | portable core; `SEMMC_TARGET_STM32G474=ON` | both link. `semmc_stm32g474.elf`: text 49,400 B, data 96 B, bss 7,672 B. `semmc_stm32g474_pwmtest.elf`: text 49,648 B |
| emulated core | `emulate_core_timing.py --ms 300` | fast step with current control: at most 1,039 instructions; slow step: at most 1,452 instructions. Exploratory instruction counts only: not timing on silicon, and not a bound on it (corrected 2026-10-18: an earlier version of this row called count / frequency a lower bound, which IT folding contradicts) |
| hardware checks | `hw_consistency.py`, `pin_type_check.py` | 14 PASS, 0 FAIL, 4 OPEN; 174 nets, 0 findings |
| release gate | `release_gate.py` | **FAIL**, G1 to G7 all failing (41 UNRESOLVED lines; no footprints; 12 register rows open; no PCB; no local ERC report; reviews unsigned; no hardware-valid configuration). No package built |

Image checksums from this host (SHA-256; a CI build with another toolchain patch level may differ):

| File | SHA-256 |
|---|---|
| `semmc_stm32g474.elf` | `84065aa759d984428578132889c7004233c191a65713daf2e42ff9e0cd909953` |
| `semmc_stm32g474.bin` | `c18d880a19555d5543e18acc293adf92aa565a7b1d2fa3f158722b65534fe920` |
| `semmc_stm32g474.hex` | `775eb89b38006a06da56425a19e9f791f7fca85e6bc4c32435c709788431aba9` |
| `semmc_stm32g474_pwmtest.elf` | `a9a726b05eeab7416e34efdbe727e452da30a7ab9276ee2ae894e5f031f194ee` |

Nothing was flashed, energised or measured.

### 8.5 Baseline for the continued v0.6 work (2026-10-18)

| Item | Value |
|---|---|
| Pull request | SWORT-Aerospace/sem-motor-controller#5, `eng/v0.6-vehicle-package` into `main`, open, no review threads |
| Head | `ed05e72` |
| Push run on the head | 39080454276: attempt 1 failed in the toolchain step before any test (Launchpad HTTP 500 while adding the KiCad PPA); attempt 2 succeeded (`host`, `erc`) |
| Pull-request run on the head | 39081023928: succeeded (`host`, `erc`) |
| Ancestry | `main` (`3a80039`, including the team's questionnaire edit), v0.4 (`0b7255e`) and v0.5 (`76f4cfc`) are ancestors of the head |
| Manufacturer documents | none in the repository; the manufacturers' sites are refused by the build environment's network policy (CONNECT 403, checked once). The download list: [`reference/datasheets/README.md`](reference/datasheets/README.md) |


### 8.6 Continued v0.6 work: what changed and how it was checked (2026-10-18)

| Area | Result | Evidence |
|---|---|---|
| Concurrency | fast-loop events counted with single-writer atomics; an overcurrent during the slow step's acknowledgment is kept | `firmware/tests/test_core_preemption.c` (fails on the old code); DMB in both handlers (`test_fast_slow_handoff_compiles_to_ordered_atomics`) |
| Start-up sequence | `mc_startup`: bypass closes only on fresh samples that agree with the resistor current; driver woken after the bypass (VM is the link); offsets with the driver awake; attempts limited, then LOCKOUT | `firmware/tests/test_drivers.c`, 139 checks; ten safety properties each removed once and caught by them |
| Gate driver and battery meter | driver logic written against verified descriptions; the image passes none, so both stay UNVERIFIED and DRV_ENABLE low | `test_target_image_keeps_the_gate_driver_and_meter_inhibited` |
| Over-voltage trip | worst-case tool; resistor-only spread trip +0.57 % to +1.00 %, release -2.74 % to -2.26 % of the set point; device terms pending (B-OVTRIP) | `hardware/calculations/ov_trip_worst_case.md` |
| Footprints | 82 of 122 BOM lines assigned (68 verified, 14 waiting for the manufacturer's drawing), 40 with a stated reason; before: 0 | `hardware/footprints/FOOTPRINT_CHECK.md`, 0 failed checks |
| ERC | KiCad 8.0.9, 0 errors, 0 warnings with the footprints assigned, recorded against the SHA-256 of the schematic inputs | run 39085951988 (`8e230d8`), `hardware/kicad/ERC_RECORD.yaml` |
| Bench gate-disable path | BP1 to BP4 PASS on the netlist, with mutation tests; BP5 (driver behaviour disabled or unpowered) OPEN | `hardware/review/CONSISTENCY_CHECK.md` |
| Budget | minimum build (protection and local recording) fully priced: $385 to $1,018 with equipment owned, $489 to $1,382 if bought; full scope not established (2 lines unpriced) | `docs/PROCUREMENT.md` |
| Release gate | G5 PASS; G1 to G4, G6, G7 FAIL; no fabrication outputs | `docs/generated/release_gate.md` |

Local verification of `e0d7593` (this environment, not a fresh clone): ctest 11/11; pytest 312 passed, 0 skipped, with the
broker and the ARM toolchain required; target images linked: `semmc_stm32g474.elf` 54 624 + 96 bytes flash, 8 120
bytes RAM, SHA-256 `99f41e9b...77bdd`; `semmc_stm32g474_pwmtest.elf` `4672013d...0aeebba`;
`semmc_stm32g474_timing.elf` `610ff5da...1b7758`. The MQTT latency maxima and deadline-miss counts of the committed
demonstration samples were not regenerated. Nothing was flashed, energised or measured.

## 9. v0.7: telematics delivery

Scope: the telematics unit and the pit software; the motor controller is another team's ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)). Branch `eng/v0.7-telematics`, stacked on `eng/v0.6-vehicle-package` (SWORT-Aerospace/sem-motor-controller#5, unchanged at `92682c1`). **Nothing was flashed, connected to a bus, energised or measured.**

### 9.1 What was reused, written and kept

| Kind | Items |
|---|---|
| Reused from earlier releases | STLG v1 format and reader (`host/telematics/stlg.py`, extended with record types 9 to 13), clock and UTC estimator, MQTT link and pit ingestion service, broker helper, pit database, shadow replay and the frozen CSIA v2 files, the semmc codec (now a simulation fixture), cantools for the DBC adapter |
| Written for v0.7 (host) | measurement model, signal registry, controller adapters, wheel estimator from edge timing, simulated external controller, receive-only node with `sem.telemetry.v4`, pit measurements and accounting, energy at two boundaries, shadow-input gating, independent demonstration, log import tool, BOM tool, scope classification |
| Written for v0.7 (target, NUCLEO-U575ZI-Q) | startup and vector table, linker script, clock, TIM2 wheel capture, bounded queue, STLG blocks in internal flash bank 2, reset causes, counters, IWDG, console, FDCAN1 bus-monitoring receive, SPI1 and I2C1 transports with the W25Q, IMU and TMP117 drivers (`telematics/firmware/`) |
| Host only (no target code) | GNSS with PPS, the LTE modem and live uplink, microSD, the battery-side monitor |
| Kept, deferred | the controller core, STM32G474 port, power-stage schematic and the ECO supervisor (legacy mode, `--legacy-supervised`), with their own suite and CI job |

### 9.2 Fresh-clone verification of `c2f9816` (2026-10-18)

Clone of the branch head into an empty directory; this environment's tools (Python 3.13.16, gcc 13.3.0, CMake 3.28.3, Ninja 1.11.1, arm-none-eabi-gcc 13.2.1, Mosquitto 2.0.18 from Ubuntu's package). The tree had no changes after the run.

| Check | Command | Result |
|---|---|---|
| Generated files current | `tools/scope.py --check`, `tools/blockers.py --check`, `tools/telematics_bom.py --check`, `tools/gen_procurement.py --check`, `tools/gen_protocol.py --check`, `tools/gen_dbc.py --check` | all exit 0 |
| Links | `tools/check_links.py` | 135 Markdown files, 0 broken |
| Firmware unit tests (host, ASan and UBSan) | `cmake -S telematics/firmware -B build-telematics -G Ninja`, build, `ctest` | 1/1 test program: 451 + 22 checks, 0 failed |
| Target images | README section 3 (`-DTM_TARGET_U575=ON`, MinSizeRel) | `tm_u575.elf` 15 808 B flash, 59 200 B RAM; `tm_u575_can.elf` 16 824 B flash, 59 208 B RAM; log region empty in the image. SHA-256: `tm_u575.bin` `a91e261e...e817f9`, `tm_u575_can.bin` `e49d2689...aadaf9` |
| Telematics and reference suites | `SEMMC_REQUIRE_MQTT=1 SEMMC_REQUIRE_ARM=1 SEMMC_BUILD_DIR=/nonexistent-controller-build python3 -m pytest -rs -m "telematics or reference"` | 132 passed, 0 skipped, 216 deselected (90 s); the controller build directory was not created |
| Demonstration | `tools/run_telematics_demo.py --out build/telematics_demo` (real broker) | 9/9 checks: 46 143 frames on the bus, all from the external controller; boot 1: 54 627 records logged, 451 queue drops counted, 156 records lost in the restart and reported; 11 oldest live messages dropped on the car during the outage and counted; second import adds 0 records; wheel speed RMS error 0.0003 m/s; controller input 1.773 Wh, battery 2.095 Wh, each within 0.384 % of the simulated energy over the covered intervals |
| Deferred controller suite | `python3 tools/fetch_kicad_symbols.py`, `python3 tools/check_footprints.py --fetch`, then `SEMMC_REQUIRE_MQTT=1 SEMMC_REQUIRE_ARM=1 python3 -m pytest -rs -m controller` | 216 passed, 0 skipped (115 s). A first run without the two fetch steps had 1 failure and 5 skips, all for the missing pinned KiCad libraries (`test_hardware_tools.py`, `test_footprints.py`), as CI fetches them first |
| Legacy supervised demonstrations | `tools/run_host_demo.py --legacy-supervised`, `tools/run_mqtt_demo.py --legacy-supervised`, `tools/run_pit_replay.py` on the host demonstration's database | 11/11 and 12/12 checks; replay report written. Without `--legacy-supervised` the host demonstration refuses to run (exit 2) |

Linker note: both images warn that newlib's `nosys` stubs `_close`, `_lseek`, `_read` and `_write` always fail. They are pulled in by `snprintf`; the firmware writes through its own UART driver and calls no stdio output, so the warning has no effect, and it is recorded rather than silenced.

### 9.3 What these results do not show

* That the firmware runs on the board: no image has been flashed, and the host tests do not show it. The first physical test is [`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md) B1 to B7.
* That any pin, level or solder bridge in the connection table is right: taken from ST's board files and not checked on a board; the STM32U575 manuals were not readable here (T-U5-DOCS).
* Electrical noninterference with a vehicle bus: the firmware sends nothing, but checks E1 to E6 are still to be run.
* Anything about the real controller's frames: it is simulated; its team has not answered [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md).
* Vehicle energy: every number above comes from simulation.

