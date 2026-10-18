# Status in detail

The README keeps a short status; this page holds the detail. "Works" always names the environment in which it was shown. Host simulation is not embedded firmware, a passing host test does not show that the firmware runs on the board, and nothing here has been flashed, connected to a bus or tested on the vehicle.

**Scope (v0.7).** The deliverable is the telematics unit and the pit software; the motor controller is built by another team ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)). Section 1 is the current status. Sections 2 onwards record the earlier controller-and-telemetry work as it stood; the controller parts of it are deferred controller development.

## 1. Telematics (v0.7)

| Function | On the target (NUCLEO-U575ZI-Q firmware, built) | Host only | Bench-tested |
|---|---|---|---|
| Wheel pulses: TIM2 input capture on three channels, 1 µs, extended to 64 bits across the 32-bit overflow; edge count and span per record; no edge is no evidence (never 0); a channel silent while another turns is flagged suspect (stuck active, or stuck inactive / disconnected), the same rule in C and Python | yes (`telematics/firmware/src/tm_wheel.c`, `platform/u575/main_u575.c`) | the speed and distance estimate (`host/telematics/wheel.py`, pit) | no |
| Bounded log queue with drop counters and high-water mark; STLG records and blocks; the log on a W25Q NOR on SPI1 when one answers its JEDEC id (4096 slots of 4 KiB for a 16 MiB part), else internal flash bank 2 (256 slots); sparse logging (wheel and counters every 10 s) once only the reserve is left; restart reasons and a BOOT record; counters every second | yes (`tm_queue.c`, `tm_stlg.c`, `tm_flashlog.c`, `tm_w25q.c`, `spi_u575.c`, `tm_reset.c`, `tm_app.c`, `flash_u575.c`) | W25Q bus model (`platform/host/tm_fakew25q.c`); recording durations measured on it ([`generated/telematics_storage.md`](generated/telematics_storage.md)) | no |
| Console: status line, `DUMP` of the log, `ERASE YES` | yes (`uart_u575.c`, `main_u575.c`) | | no |
| CAN receive: FDCAN1 in bus-monitoring mode (sends nothing, not even the acknowledge bit), frames to the log with receive time | yes, in the `tm_u575_can` image (`can_u575.c`) | decoding: semmc fixture and DBC adapters (`host/telematics/controller_adapter.py`) | no |
| IMU (LSM6DSOX or ISM330DHCX) and TMP117 temperature on I2C1 | yes (`i2c_u575.c`, `tm_imu.c`), polled at 100 Hz and 1 Hz | | no |
| GNSS with PPS capture | no | `host/telematics/node.py`, `host/telematics/clocks.py` | no |
| LTE modem and the live uplink `sem.telemetry.v4` | no | `host/telematics/node.py`, `host/telematics/mqtt_link.py`; real Mosquitto broker | no |
| Battery-side monitor (total battery energy) | no | `host/telematics/sim_vehicle.py`, STLG `BATT` | no |
| Pit: validation, SQLite with idempotent re-import, speed and distance, energy at two boundaries, data quality, shadow monitors | runs on the pit computer | yes (`host/pit/`, `tools/telematics_import.py`, `tools/run_pit_replay.py`) | no vehicle data |
| CAN flood: the log queue keeps a 32-record reserve for the unit's own records; frames beyond it counted (`can_not_logged`, COUNTERS2 id 27) | yes (`tm_app.c`; C test `test_can_flood`) | the same rule in the node model | no |
| Evidence platform: canonical schema, evidence states, stream timing with wait bounds, lineage, vehicle context, cross-domain witnesses, advisory verdicts with receipts, common cause, pit evidence queries, advisory energy, CSIA shadow boundary | runs on the pit computer | yes (`telematics/schema/`, `host/telematics/`, `host/assurance/`, `host/pit/`); labels in [`CLAIMS.md`](CLAIMS.md) | no |
| Vehicle-validation protocols EXP-01 to EXP-04 | | simulated pre-check passes (`tools/run_vehicle_experiment.py`, SIMULATED) | not run ([`../research/vehicle_validation/`](../research/vehicle_validation/README.md)) |

**Bench-tested: nothing.** No connection in the connection table ([`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md) section 4) has been checked on a board. The bench package (`tools/telematics_bench.py package`: images with SHA-256, the procedure, the connection and parts lists, a blank results form) is built in CI; its steps B0 to B12 are not run. The register-level code is checked against ST's HAL and CMSIS sources, not yet against the reference manual RM0456, the data sheet or the errata (T-U5-DOCS).

**Evidence on a computer.** Portable firmware code: unit tests under AddressSanitizer and UndefinedBehaviorSanitizer, its records byte-for-byte equal to the Python reference (`tests/telematics/test_firmware_host.py`); target images link with arm-none-eabi-gcc 13.2, and their vector table, memory map and sections are checked (`tests/telematics/test_firmware_target.py`). The independent demonstration passes 9 checks through a real broker ([`generated/telematics_demo/summary.md`](generated/telematics_demo/summary.md)). Commands and results: [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) sections 9 to 11. Claim labels (SIMULATED, HOST-TESTED, BENCH-TESTED, HIL-TESTED, VEHICLE-TESTED) and their evidence: [`CLAIMS.md`](CLAIMS.md); nothing is above HOST-TESTED.

**Waiting on others.** The controller team's answer to [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md); the battery's maximum voltage, without which the vehicle supply (DC-DC, TVS, fuse) cannot be chosen and the vehicle power connection stays blocked (USB-powered bench work does not need it); part choices and quotes ([`TELEMATICS_BOM.md`](TELEMATICS_BOM.md)). Order of work: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## 2. Deferred controller development: the v0.6 milestones (kept as recorded)

| Milestone | Status | Evidence | What closes it |
|---|---|---|---|
| 1. Engineering design ready for review | **reviewable, with open items**: schematic reviewed topic by topic against the documents available; interface specification, acceptance procedures and pre-layout requirements written | [`../hardware/review/DESIGN_REVIEW.md`](../hardware/review/DESIGN_REVIEW.md), [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md), [`BLOCKERS.md`](BLOCKERS.md) | the datasheets of the register and the vehicle inputs of [`INPUT_SHEET.md`](INPUT_SHEET.md); a signed design review |
| 2. Fabrication-ready hardware and buildable target firmware | **firmware: builds and links** (image in every CI run); **hardware: not fabrication-ready** | `semmc_stm32g474.elf` (CI artifact `semmc-stm32g474-image`); release gate [`generated/release_gate.md`](generated/release_gate.md): FAIL | the release gate conditions ([`../hardware/layout/PRE_LAYOUT.md`](../hardware/layout/PRE_LAYOUT.md) 5) |
| 3. Bench-validated integrated hardware | **not started**: no board exists | procedures and result checker ready ([`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md), `tools/acceptance.py`) | stages S0 to S10 passed with signed records |

**Target firmware: compiled, simulated, bench-tested, untested.**

| Level | What |
|---|---|
| Compiled and linked for the STM32G474 | startup and vector table, linker script, clock tree, pin configuration, TIM1 PWM and break inputs, ADC injected currents and DMA scan, hall capture, FDCAN with bus-off recovery, IWDG and external watchdog, calibration store, event log, precharge sequencing, pedal plausibility, enable-path check, bench PWM image |
| Checked without hardware | vector table against ST's interrupt list; memory map; no double precision on the current-interrupt path; fault handlers reach the safe state; pin and alternate-function map against ST's database (45 functions, 0 errors); timer, dead-time and CAN bit-timing encodings; the core's fast step in an instruction-level emulator (instruction counts, not timing on silicon) |
| Simulated (host) | the controller core, protection and state machine against the synthetic plant; the telemetry chain through a real MQTT broker |
| Bench-tested | nothing |
| Written, inhibited | the start-up sequence and the DRV8353 and INA228 driver logic, host-tested against invented register maps; no verified device description is passed (datasheets not read) and the bus transports are not written, so the power stage stays inhibited, precharge never closes, and no synthetic configuration can enable it on hardware |

Item by item: [`../firmware/platform/stm32g4/README.md`](../firmware/platform/stm32g4/README.md) "Status".

## 3. What works, and where it was shown (v0.4, kept as recorded)

| Item | Shown in | Evidence |
|---|---|---|
| Controller core (C11): four-layer torque contract, state machine, freshness and session rules, FOC, protection, energy at the controller input | x86-64 host build with ASan/UBSan; GitHub-hosted CI | `ctest` (8 entries: 7 test programs, the randomised property test also at 24 × 12 s); soaks of 100 × 30 s and 300 × 30 s simulated driving with 0 failures (`docs/generated/property_soak.md`) |
| Same core, portable build | arm-none-eabi-gcc for Cortex-M4F (compile only) | 0 soft-float double calls in the fast step; not run on a target |
| CAN protocol 1.1 (16 messages), C and Python codecs, DBC | host | golden vectors, hand-computed frames, bus load 12.6 % at 500 kbit/s |
| Telematics node, local log (STLG), LTE/MQTT uplink, pit ingestion into SQLite, offline import, pit-side CSIA replay | host simulation | `python3 tools/run_host_demo.py`: 11 checks, all pass (`docs/generated/host_demo/summary.md`) |
| Energy optimisation (spatial DP), strategies, policy comparison | synthetic models and host plant | `docs/generated/optimization_synthetic.md`, `docs/generated/policy_comparison_host.md` |
| CSIA monitor evaluation (protocol v2, frozen before data) | synthetic, untouched set, run once | `docs/csia/EVALUATION_RESULTS_v2.md`: the simpler majority-vote monitor (R3v) is retained |
| Draft schematic (12 sheets) | KiCad 7 netlist + KiCad 8.0.9 ERC in CI | connectivity 0 problems; ERC 0 errors, 9 library warnings at v0.4 (0 warnings from v0.6, section 2); protection topology and cross-artefact checks 14 PASS, 0 FAIL, 4 OPEN (`hardware/review/CONSISTENCY_CHECK.md`) |

A passing host simulation is not a working vehicle controller. (At v0.4 the STM32G4 platform layer was not written; v0.6 adds it, section 2. The telematics firmware followed in v0.7, section 1.)

## 4. Added in v0.5 (host software)

| Item | Shown in | Evidence |
|---|---|---|
| Telemetry uplink through a real MQTT broker: paho-mqtt client (QoS 1) in the telematics node model, Mosquitto 2.0.18 on loopback, a separate pit ingestion process (validation, `rx` receipt log, idempotent storage), broker crash and pit restart | x86-64 host; GitHub-hosted CI installs Ubuntu's Mosquitto | `python3 tools/run_mqtt_demo.py`: 12 checks (`docs/generated/mqtt_demo/summary.md`); `tests/integration/test_mqtt_pipeline.py` |
| Wheel-magnet detection check, sampled vs continuous Hall switch | analysis of datasheet timing on a labelled geometry grid | `docs/generated/wheel_sensor_check.md` |
| Project procurement table generated from one YAML file: motor controller (ranges from the priced draft BOM), telemetry, shared wiring, development equipment, recurring connectivity; per-category subtotals, no total while lines are unpriced | host | `tools/gen_procurement.py --check`; `tests/hardware/test_procurement.py` |
| Live summary `sem.telemetry.v3` with wheel speed per channel (v2) and temperatures (v3: controller FET and motor, telematics probes); STLG temperature record with per-sample status; the pit accepts v1, v2 and v3 and migrates old databases | host, real broker | `tests/integration/test_mqtt_pipeline.py`, `tests/integration/test_host_demo.py`; MQTT demonstration check `live_wheel_and_temperature_match_log_and_v1_still_accepted` |
| Pit shadow replay of B1, R3v and CSIA2 over an imported log, with data class, signal coverage and insufficient-evidence notes | host (synthetic runs) | `tools/run_pit_replay.py`; `tests/integration/test_shadow_replay.py`; [`TELEMETRY_INTEGRATION.md`](TELEMETRY_INTEGRATION.md) 5 |
| Energy per distance at the pit (controller-input energy, wheel distance, Wh/km, cross-check between wheels) | host (synthetic runs) | `host/pit/energy.py`; `tests/integration/test_pit_energy.py` (includes the README worked example) |
| Documentation for a student team: README front page, integration guide, implementation plan, design decisions, development guide, folder guides, file index | repository | `tests/integration/test_docs.py` (links, file-index coverage, wording) |

## 5. Controller hardware status (deferred)

Draft only: footprints on 82 of 122 BOM lines (68 verified; [`../hardware/footprints/FOOTPRINT_CHECK.md`](../hardware/footprints/FOOTPRINT_CHECK.md)), no layout, no fabrication outputs, no orders; the release gate fails ([`generated/release_gate.md`](generated/release_gate.md)). Power-stage parts, connectors and ratings depend on the motor, battery, harness and rules and stay UNRESOLVED (41 BOM lines). The budget is not shown to be feasible until live quotes and those ratings close the price spread (`tools/price_bom.py`). No hardware freeze is claimed.

## 6. Document index

| Topic | Document |
|---|---|
| Scope: telematics, reference, deferred controller | [`docs/scope.yaml`](scope.yaml), [`docs/generated/scope.md`](generated/scope.md), [`docs/decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md) |
| Interfaces (authoritative) | [`docs/ICD.md`](ICD.md) v2.0 (Part A telematics, Part B deferred controller and the semmc fixture) |
| What we ask the controller team | [`docs/CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md) |
| Signals, energy, shadow mode | [`docs/TELEMETRY_INTEGRATION.md`](TELEMETRY_INTEGRATION.md), [`docs/ENERGY_METHODS.md`](ENERGY_METHODS.md) |
| Firmware status by function | [`docs/TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md), [`telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md) |
| Telematics BOM | [`docs/TELEMATICS_BOM.md`](TELEMATICS_BOM.md) |
| Plan and open items | [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), [`docs/BLOCKERS.md`](BLOCKERS.md), [`docs/INPUT_SHEET.md`](INPUT_SHEET.md) |
| Verification report | [`docs/VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) |
| CSIA v2 protocol and results | [`docs/csia/EVALUATION_PROTOCOL_v2.md`](csia/EVALUATION_PROTOCOL_v2.md), [`docs/csia/EVALUATION_RESULTS_v2.md`](csia/EVALUATION_RESULTS_v2.md) |
| Decisions | [`docs/DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) (D1 to D11); [`docs/decisions/`](decisions/) (ADR-0001 to ADR-0013) |
| Deferred controller: mathematics, control contract, hardware, budget, validation, bench bring-up | [`docs/MATH_SPEC.md`](MATH_SPEC.md), [`docs/CONTROL_CONTRACT.md`](CONTROL_CONTRACT.md), [`docs/HARDWARE_ARCHITECTURE.md`](HARDWARE_ARCHITECTURE.md), [`hardware/bom/README.md`](../hardware/bom/README.md), [`docs/BUDGET.md`](BUDGET.md), [`docs/VALIDATION_PLAN.md`](VALIDATION_PLAN.md), [`docs/BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md), [`docs/INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md) |
| Method selection and sources read | [`docs/METHOD_SELECTION.md`](METHOD_SELECTION.md) |
| Every document with its status | [`docs/README.md`](README.md); every file: [`docs/FILE_INDEX.md`](FILE_INDEX.md) |
| Earlier releases (records) | [`docs/archive/REVIEW_v0.3.md`](archive/REVIEW_v0.3.md), [`docs/archive/CHECKPOINT_v0.2.md`](archive/CHECKPOINT_v0.2.md), [`docs/archive/HANDOFF_v0.1.md`](archive/HANDOFF_v0.1.md) (v0.1) |

## 7. Repository layout
```
telematics/  telematics unit firmware for the NUCLEO-U575ZI-Q (portable code, host simulator, target platform, tests)
config/      parameter registry, schema, unconfigured hardware config, SYNTHETIC vehicle config
firmware/    deferred controller: portable C11 core, public headers, host platform + simulated plant, STM32G474 target platform, C tests
protocol/    semmc CAN schema (a simulation fixture: protocol.yaml), generated codecs, golden vectors, DBC
host/        telematics node model and adapters, pit ingestion, energy, replay, CSIA adapters; legacy supervisor
models/      vehicle and powertrain models, inverter losses, DP optimiser, strategies
hardware/    telematics BOM; deferred controller: KiCad draft, BOM and pricing, calculations, timing, protection, selection, acceptance, layout, review
tests/       integration, fault injection, simulation, hardware (pytest)
tools/       generators, validators, studies, verification
docs/        ICD, specifications, decisions, evaluations, generated reports
```
