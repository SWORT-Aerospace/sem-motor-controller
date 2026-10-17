# Status in detail

The README keeps a short status; this page holds the detail. "Works" always names the environment in which it was shown. A passing host simulation is not a working vehicle controller, and nothing here has been built, energised or tested on the vehicle.

## 0. The three milestones (v0.6)

| Milestone | Status | Evidence | What closes it |
|---|---|---|---|
| 1. Engineering design ready for review | **reviewable, with open items**: schematic reviewed topic by topic against the documents available; interface specification, acceptance procedures and pre-layout requirements written | [`../hardware/review/DESIGN_REVIEW.md`](../hardware/review/DESIGN_REVIEW.md), [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md), [`BLOCKERS.md`](BLOCKERS.md) | the datasheets of the register and the vehicle inputs of [`INPUT_SHEET.md`](INPUT_SHEET.md); a signed design review |
| 2. Fabrication-ready hardware and buildable target firmware | **firmware: builds and links** (image in every CI run); **hardware: not fabrication-ready** | `semmc_stm32g474.elf` (CI artifact `semmc-stm32g474-image`); release gate [`generated/release_gate.md`](generated/release_gate.md): FAIL | the release gate conditions ([`../hardware/layout/PRE_LAYOUT.md`](../hardware/layout/PRE_LAYOUT.md) 5) |
| 3. Bench-validated integrated hardware | **not started**: no board exists | procedures and result checker ready ([`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md), `tools/acceptance.py`) | stages S0 to S9 passed with signed records |

**Target firmware: compiled, simulated, bench-tested, untested.**

| Level | What |
|---|---|
| Compiled and linked for the STM32G474 | startup and vector table, linker script, clock tree, pin configuration, TIM1 PWM and break inputs, ADC injected currents and DMA scan, hall capture, FDCAN with bus-off recovery, IWDG and external watchdog, calibration store, event log, precharge sequencing, pedal plausibility, enable-path check, bench PWM image |
| Checked without hardware | vector table against ST's interrupt list; memory map; no double precision on the current-interrupt path; fault handlers reach the safe state; pin and alternate-function map against ST's database (45 functions, 0 errors); timer, dead-time and CAN bit-timing encodings; the core's fast step in an instruction-level emulator (instruction counts, not timing on silicon) |
| Simulated (host) | the controller core, protection and state machine against the synthetic plant; the telemetry chain through a real MQTT broker |
| Bench-tested | nothing |
| Not implemented | the DRV8353 configuration and the INA228 battery meter (datasheets not read): the power stage stays inhibited, precharge never closes, and no synthetic configuration can enable it on hardware |

Item by item: [`../firmware/platform/stm32g4/README.md`](../firmware/platform/stm32g4/README.md) "Status".

## 1. What works, and where it was shown (v0.4, kept as recorded)

| Item | Shown in | Evidence |
|---|---|---|
| Controller core (C11): four-layer torque contract, state machine, freshness and session rules, FOC, protection, energy at the controller input | x86-64 host build with ASan/UBSan; GitHub-hosted CI | `ctest` (8 entries: 7 test programs, the randomised property test also at 24 × 12 s); soaks of 100 × 30 s and 300 × 30 s simulated driving with 0 failures (`docs/generated/property_soak.md`) |
| Same core, portable build | arm-none-eabi-gcc for Cortex-M4F (compile only) | 0 soft-float double calls in the fast step; not run on a target |
| CAN protocol 1.1 (16 messages), C and Python codecs, DBC | host | golden vectors, hand-computed frames, bus load 12.6 % at 500 kbit/s |
| Telematics node, local log (STLG), LTE/MQTT uplink, pit ingestion into SQLite, offline import, pit-side CSIA replay | host simulation | `python3 tools/run_host_demo.py`: 11 checks, all pass (`docs/generated/host_demo/summary.md`) |
| Energy optimisation (spatial DP), strategies, policy comparison | synthetic models and host plant | `docs/generated/optimization_synthetic.md`, `docs/generated/policy_comparison_host.md` |
| CSIA monitor evaluation (protocol v2, frozen before data) | synthetic, untouched set, run once | `docs/csia/EVALUATION_RESULTS_v2.md`: the simpler majority-vote monitor (R3v) is retained |
| Draft schematic (12 sheets) | KiCad 7 netlist + KiCad 8.0.9 ERC in CI | connectivity 0 problems; ERC 0 errors, 9 library warnings at v0.4 (0 warnings from v0.6, section 0); protection topology and cross-artefact checks 14 PASS, 0 FAIL, 4 OPEN (`hardware/review/CONSISTENCY_CHECK.md`) |

A passing host simulation is not a working vehicle controller. (At v0.4 the STM32G4 platform layer was not written; v0.6 adds it, section 0. The telematics firmware is still not implemented.)

## 2. Added in v0.5 (host software)

| Item | Shown in | Evidence |
|---|---|---|
| Telemetry uplink through a real MQTT broker: paho-mqtt client (QoS 1) in the telematics node model, Mosquitto 2.0.18 on loopback, a separate pit ingestion process (validation, `rx` receipt log, idempotent storage), broker crash and pit restart | x86-64 host; GitHub-hosted CI installs Ubuntu's Mosquitto | `python3 tools/run_mqtt_demo.py`: 12 checks (`docs/generated/mqtt_demo/summary.md`); `tests/integration/test_mqtt_pipeline.py` |
| Wheel-magnet detection check, sampled vs continuous Hall switch | analysis of datasheet timing on a labelled geometry grid | `docs/generated/wheel_sensor_check.md` |
| Project procurement table generated from one YAML file: motor controller (ranges from the priced draft BOM), telemetry, shared wiring, development equipment, recurring connectivity; per-category subtotals, no total while lines are unpriced | host | `tools/gen_procurement.py --check`; `tests/hardware/test_procurement.py` |
| Live summary `sem.telemetry.v3` with wheel speed per channel (v2) and temperatures (v3: controller FET and motor, telematics probes); STLG temperature record with per-sample status; the pit accepts v1, v2 and v3 and migrates old databases | host, real broker | `tests/integration/test_mqtt_pipeline.py`, `tests/integration/test_host_demo.py`; MQTT demonstration check `live_wheel_and_temperature_match_log_and_v1_still_accepted` |
| Pit shadow replay of B1, R3v and CSIA2 over an imported log, with data class, signal coverage and insufficient-evidence notes | host (synthetic runs) | `tools/run_pit_replay.py`; `tests/integration/test_shadow_replay.py`; [`TELEMETRY_INTEGRATION.md`](TELEMETRY_INTEGRATION.md) 5 |
| Energy per distance at the pit (controller-input energy, wheel distance, Wh/km, cross-check between wheels) | host (synthetic runs) | `host/pit/energy.py`; `tests/integration/test_pit_energy.py` (includes the README worked example) |
| Documentation for a student team: README front page, integration guide, implementation plan, design decisions, development guide, folder guides, file index | repository | `tests/integration/test_docs.py` (links, file-index coverage, wording) |

## 3. Hardware status

Draft only: no footprints, no layout, no fabrication outputs, no orders; the release gate fails ([`generated/release_gate.md`](generated/release_gate.md)). Power-stage parts, connectors and ratings depend on the motor, battery, harness and rules and stay UNRESOLVED (41 BOM lines). The budget is not shown to be feasible until live quotes and those ratings close the price spread (`tools/price_bom.py`). No hardware freeze is claimed.

## 4. Document index

| Topic | Document |
|---|---|
| Interfaces (authoritative) | [`docs/ICD.md`](ICD.md) v1.0 |
| Mathematics, tied to code and tests | [`docs/MATH_SPEC.md`](MATH_SPEC.md) |
| Method selection and sources read | [`docs/METHOD_SELECTION.md`](METHOD_SELECTION.md) |
| Verification report | [`docs/VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) |
| Control contract | [`docs/CONTROL_CONTRACT.md`](CONTROL_CONTRACT.md) |
| CSIA v2 protocol and results | [`docs/csia/EVALUATION_PROTOCOL_v2.md`](csia/EVALUATION_PROTOCOL_v2.md), [`docs/csia/EVALUATION_RESULTS_v2.md`](csia/EVALUATION_RESULTS_v2.md) |
| Hardware status, BOM and budget | [`docs/HARDWARE_ARCHITECTURE.md`](HARDWARE_ARCHITECTURE.md), [`hardware/bom/README.md`](../hardware/bom/README.md), [`docs/BUDGET.md`](BUDGET.md) |
| Inputs needed from the team (prioritised) | [`docs/INPUT_SHEET.md`](INPUT_SHEET.md) |
| Validation plan and bench bring-up | [`docs/VALIDATION_PLAN.md`](VALIDATION_PLAN.md), [`docs/BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md) |
| Decisions | [`docs/DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) (D1 to D10, v0.5); [`docs/decisions/`](decisions/) (ADR-0001 to ADR-0012) |
| Integration and the staged plan | [`docs/INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md), [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) |
| Every document with its status | [`docs/README.md`](README.md); every file: [`docs/FILE_INDEX.md`](FILE_INDEX.md) |
| Earlier releases (records) | [`docs/archive/REVIEW_v0.3.md`](archive/REVIEW_v0.3.md), [`docs/archive/CHECKPOINT_v0.2.md`](archive/CHECKPOINT_v0.2.md), [`docs/archive/HANDOFF_v0.1.md`](archive/HANDOFF_v0.1.md) (v0.1) |

## 5. Repository layout
```
config/      parameter registry, schema, unconfigured hardware config, SYNTHETIC vehicle config
firmware/    portable C11 core, public headers, host platform + simulated plant, STM32G474 target platform, C tests
protocol/    CAN schema (protocol.yaml), generated codecs, golden vectors, DBC
host/        supervisor + co-simulation, telematics node model, pit ingestion, replay, CSIA adapters
models/      vehicle and powertrain models, inverter losses, DP optimiser, strategies
hardware/    KiCad draft, BOM and pricing, calculations, timing, protection, selection, acceptance, layout, review
tests/       integration, fault injection, simulation, hardware (pytest)
tools/       generators, validators, studies, verification
docs/        ICD, specifications, decisions, evaluations, generated reports
```
