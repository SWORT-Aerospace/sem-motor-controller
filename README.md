# sem-motor-controller

Motor controller, supervisory energy strategy and vehicle data chain for a Shell Eco-marathon battery-electric vehicle. Goal: lower energy per attempt within the event's constraints, on a budget of roughly $500 to $1,000, with the vehicle team doing assembly and testing.

**State at v0.4: a host-verified software stack and a draft schematic. Nothing has been built, energised or tested on the vehicle.** "Works" below always names the environment in which it was shown.

## What works, and where it was shown

| Item | Shown in | Evidence |
|---|---|---|
| Controller core (C11): four-layer torque contract, state machine, freshness and session rules, FOC, protection, energy at the controller input | x86-64 host build with ASan/UBSan; GitHub-hosted CI | `ctest` (8 entries: 7 test programs, the randomised property test also at 24 × 12 s); soaks of 100 × 30 s and 300 × 30 s simulated driving with 0 failures (`docs/generated/property_soak.md`) |
| Same core, portable build | arm-none-eabi-gcc for Cortex-M4F (compile only) | 0 soft-float double calls in the fast step; not run on a target |
| CAN protocol 1.1 (16 messages), C and Python codecs, DBC | host | golden vectors, hand-computed frames, bus load 12.6 % at 500 kbit/s |
| Telematics node, local log (STLG), LTE/MQTT uplink, pit ingestion into SQLite, offline import, pit-side CSIA replay | host simulation | `python3 tools/run_host_demo.py`: 9 checks, all pass (`docs/generated/host_demo/summary.md`) |
| Energy optimisation (spatial DP), strategies, policy comparison | synthetic models and host plant | `docs/generated/optimization_synthetic.md`, `docs/generated/policy_comparison_host.md` |
| CSIA monitor evaluation (protocol v2, frozen before data) | synthetic, untouched set, run once | `docs/csia/EVALUATION_RESULTS_v2.md`: the simpler majority-vote monitor (R3v) is retained |
| Draft schematic (12 sheets) | KiCad 7 netlist + KiCad 8.0.9 ERC in CI | connectivity 0 problems; ERC 0 errors, 9 library-version warnings; protection topology and cross-artefact checks 14 PASS, 0 FAIL, 4 OPEN (`hardware/review/CONSISTENCY_CHECK.md`) |

A passing host simulation is not a working vehicle controller. The STM32G4 platform layer (timers, ADC, CAN driver, precharge logic) and the telematics firmware are not implemented.

## Reproduce

Linux with gcc, cmake, ninja, Python 3.11+ (3.13 used), arm-none-eabi-gcc for the portable build, KiCad 7+ for the schematic check (8+ for ERC):

```sh
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 tools/verify_all.py --out build/verify          # every check below; record in build/verify/verification.md
python3 tools/verify_all.py --out build/verify --full   # + full studies, frozen CSIA v1 re-run, 100 x 30 s soak, policy comparison
```

Single steps:
```sh
python3 tools/fetch_csia.py                                   # pinned CSIA core into .deps/
cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build
python3 -m pytest
python3 tools/run_host_demo.py --out build/host_demo          # end-to-end host demonstration
python3 tools/hw_consistency.py                               # protection topology, pins, BOM, rails
bash tools/run_kicad_erc.sh                                   # real ERC; needs KiCad 8+
```

The last full verification record, with the exact commit and every command, is `docs/generated/verification/verification.md`.

## What passes, fails, is simulated or needs measurement

`docs/VERIFICATION_REPORT.md` is the authoritative list: the baseline reproduction of the starting commit, the discrepancy list (reproduced; failing; simulated only; proposed but not implemented; blocked by physical inputs), every defect fixed in v0.4 with the test that first reproduced it, and CI results.

## Documents

| Topic | Document |
|---|---|
| Interfaces (authoritative) | [`docs/ICD.md`](docs/ICD.md) v1.0 |
| Mathematics, tied to code and tests | [`docs/MATH_SPEC.md`](docs/MATH_SPEC.md) |
| Method selection and sources read | [`docs/METHOD_SELECTION.md`](docs/METHOD_SELECTION.md) |
| Verification report | [`docs/VERIFICATION_REPORT.md`](docs/VERIFICATION_REPORT.md) |
| Control contract | [`docs/CONTROL_CONTRACT.md`](docs/CONTROL_CONTRACT.md) |
| CSIA v2 protocol and results | [`docs/csia/EVALUATION_PROTOCOL_v2.md`](docs/csia/EVALUATION_PROTOCOL_v2.md), [`docs/csia/EVALUATION_RESULTS_v2.md`](docs/csia/EVALUATION_RESULTS_v2.md) |
| Hardware status, BOM and budget | [`docs/HARDWARE_ARCHITECTURE.md`](docs/HARDWARE_ARCHITECTURE.md), [`hardware/bom/README.md`](hardware/bom/README.md), [`docs/BUDGET.md`](docs/BUDGET.md) |
| Inputs needed from the team (prioritised) | [`docs/INPUT_SHEET.md`](docs/INPUT_SHEET.md) |
| Validation plan and bench bring-up | [`docs/VALIDATION_PLAN.md`](docs/VALIDATION_PLAN.md), [`hardware/bringup/BENCH_BRINGUP_CHECKLIST.md`](hardware/bringup/BENCH_BRINGUP_CHECKLIST.md) |
| Decisions | [`docs/decisions/`](docs/decisions/) (ADR-0001 to ADR-0012) |
| Earlier releases (records) | [`docs/REVIEW_v0.3.md`](docs/REVIEW_v0.3.md), [`docs/CHECKPOINT_v0.2.md`](docs/CHECKPOINT_v0.2.md), [`HANDOFF.md`](HANDOFF.md) (v0.1) |

## Hardware status

Draft only: no footprints, no layout, no fabrication outputs, no orders. Power-stage parts, connectors and ratings depend on the motor, battery, harness and rules and stay UNRESOLVED (42 BOM lines). The budget is not shown to be feasible until live quotes and those ratings close the price spread (`tools/price_bom.py`). No hardware freeze is claimed.

## Inputs needed from the team

The fifteen items of [`docs/INPUT_SHEET.md`](docs/INPUT_SHEET.md). The first three decide the most: the motor's type and parameters, the battery and BMS limits, and a measured battery-power map near cruise with a coast-down (they decide between constant speed and pulse-and-coast). `telemetry.pdf` and `bk4000tg_kicad.zip` were referenced but not received.

## Layout
```
config/      parameter registry, schema, unconfigured hardware config, SYNTHETIC vehicle config
firmware/    portable C11 core, public headers, host platform + simulated plant, STM32G4 notes, C tests
protocol/    CAN schema (protocol.yaml), generated codecs, golden vectors, DBC
host/        supervisor + co-simulation, telematics node model, pit ingestion, replay, CSIA adapters
models/      vehicle and powertrain models, inverter losses, DP optimiser, strategies
hardware/    KiCad draft, BOM and pricing, calculations, timing, protection, selection, bring-up, review
tests/       integration, fault injection, simulation, hardware (pytest)
tools/       generators, validators, studies, verification
docs/        ICD, specifications, decisions, evaluations, generated reports
```
