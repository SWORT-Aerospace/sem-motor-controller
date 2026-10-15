# sem-motor-controller

Purpose-built, telemetry-informed motor controller for a Shell Eco-marathon battery-electric vehicle: power-stage planning, controller firmware core, CAN contract, supervisory energy strategy, and a CSIA vehicle consistency monitor in shadow mode.

## Status (truthful labels, v0.2: [CHECKPOINT_v0.2](docs/CHECKPOINT_v0.2.md))

| | |
|---|---|
| **CONTROL CONTRACT CORRECTED** | four layers (hardware shutdown, inhibits, hard ceilings, supervisory envelopes, comfort slew), host-verified ([CONTROL_CONTRACT](docs/CONTROL_CONTRACT.md), ADR-0011) |
| **HOST IMPLEMENTATION VERIFIED** | C11 core + codecs + host co-simulation, tested on a host with a **synthetic** plant |
| **FUNCTIONAL HARDWARE ARCHITECTURE v0.2 DRAFT** | block diagram, 12-sheet KiCad schematic (connectivity-checked, no ERC), timing, protection truth table, priced BOM ([HARDWARE_ARCHITECTURE](docs/HARDWARE_ARCHITECTURE.md)) |
| **NOT HARDWARE-FROZEN** | component selection blocked by: unknown motor (type, currents, pole pairs, R, L, λ, halls), battery and BMS (voltage range, limits), drivetrain, driver controls, rules edition; no primary datasheet read ([input sheet](docs/VEHICLE_TEAM_INPUT_SHEET.md)) |
| **NOT FABRICATION-READY** | no footprints, no layout, no fabrication outputs, by design; nothing has been energized |
| **NOT VEHICLE-VALIDATED** | every result comes from synthetic models or host tests |
| **BUDGET NOT SHOWN FEASIBLE** | every scenario straddles its limit ([BUDGET](docs/BUDGET.md)) |

Passing host tests does **not** mean the controller is complete or safe to install.

## Layout
```
config/      parameter registry, schema, real (unconfigured) and SYNTHETIC vehicle configs
firmware/    portable C11 core (src/), public headers (include/semmc/), host platform + sim plant, STM32G4 notes, C tests
protocol/    CAN schema (protocol.yaml), generated C/Python codecs, golden vectors
host/        logger, companion supervisor + co-simulation, replay, CSIA vehicle adapter
models/      vehicle longitudinal model, power maps, inverter calculations, DP optimiser, strategies
hardware/    KiCad draft, BOM + pricing, calculations, timing, protection, selection register, bring-up, pin maps, review checklist
tests/       integration, fault injection, simulation (pytest)
tools/       generators, validators, studies, pin allocation, CSIA fetch
docs/        source audit, requirements, open parameters, rules map, freeze, ADRs, ICD, validation, efficiency research, generated reports
```

## Reproduce (Linux; gcc, cmake, ninja, Python 3.11+)
```sh
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 tools/fetch_csia.py                       # pinned CSIA core into .deps/ (not vendored)
cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build
python3 -m pytest                                 # builds ./build automatically if missing
python3 host/replay/replay.py tests/simulation/replay_sample.semmc.log   # requested vs accepted + reasons
python3 tools/run_optimization.py                 # SYNTHETIC DP study (~1.5 min)
python3 tools/run_electrical_calcs.py             # SYNTHETIC electrical sensitivity
python3 tools/run_csia_study.py                   # SYNTHETIC CSIA vs baselines
python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw   # fails by design
python3 tools/control_contract_report.py        # four-layer contract: before/after on 10 scenarios
python3 tools/run_csia_evaluation.py             # CSIA on the HELD-OUT synthetic set (frozen harness)
python3 tools/gen_kicad_schematic.py --check     # KiCad draft + connectivity check (kicad-cli 7; not an ERC)
python3 tools/timing_budget.py && python3 tools/hardware_calcs.py && python3 tools/price_bom.py
```
A hardware-enabled build (`-DSEMMC_HARDWARE_BUILD=ON`) refuses to configure until the hardware config validates, and there is no STM32 platform layer yet.

## Start here
[docs/CHECKPOINT_v0.2.md](docs/CHECKPOINT_v0.2.md) · [docs/VEHICLE_TEAM_INPUT_SHEET.md](docs/VEHICLE_TEAM_INPUT_SHEET.md) · [HANDOFF.md](HANDOFF.md) (v0.1) · [docs/ARCHITECTURE_FREEZE.md](docs/ARCHITECTURE_FREEZE.md) · [docs/OPEN_PARAMETERS.md](docs/OPEN_PARAMETERS.md)
