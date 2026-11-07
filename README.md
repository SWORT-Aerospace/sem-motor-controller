# SEM motor controller

A purpose-built, telemetry-informed motor controller for a battery-electric Shell Eco-marathon vehicle. Its proposed design objective is to minimize battery energy over a valid completed run, subject to finish time, driver authority, and electrical, thermal and vehicle constraints ([requirements](docs/REQUIREMENTS.md)).

> **Status in brief (v0.3):** not hardware-frozen, not fabrication-ready and not vehicle-validated. Nothing has been energized, and every result comes from synthetic models or host tests. See [Status](#status) for detail.

## What's in it

- **Controller firmware core.** A portable C11 core with public headers, a host platform with a simulated plant, and STM32G4 notes. The core is transport-neutral; CAN is one binding.
- **CAN contract.** A CAN schema with generated C and Python codecs and golden vectors.
- **Control contract.** The four-layer contract that defines how a torque request becomes a current reference: hardware shutdown, inhibits, hard ceilings, supervisory envelopes and comfort slew.
- **Supervisory energy strategy.** A vehicle longitudinal model, power maps, an offline dynamic-programming (DP) optimiser and strategies, plus a companion supervisor with host co-simulation.
- **Power-stage planning.** A draft functional hardware architecture (block diagram, KiCad schematic, timing, protection truth table), inverter calculations, a priced BOM and a bench bring-up checklist.
- **CSIA vehicle consistency monitor, in shadow mode.** It observes and logs; it does not command torque ([ADR-0008](docs/decisions/ADR-0008-csia-shadow-mode.md)).

## Status

Current as of v0.3 ([review package](docs/REVIEW_v0.3.md)). The previous checkpoint is [v0.2](docs/CHECKPOINT_v0.2.md).

| Area | State | Reference |
|---|---|---|
| Control contract | Corrected and host-verified. Four layers: hardware shutdown, inhibits, hard ceilings, supervisory envelopes and comfort slew. | [Control contract](docs/CONTROL_CONTRACT.md), [ADR-0011](docs/decisions/ADR-0011-control-contract-layers.md) |
| Host implementation | Verified on a host, tested against a synthetic plant: the C11 core (transport-neutral; CAN is one binding), the codecs and the host co-simulation. | [firmware/](firmware/), [host/](host/) |
| Vehicle interface | Unknown. No interface fact about our vehicle is confirmed. The Cornell repositories are reference projects only, and the telematics proposal (CAN 2.0B, STM32U575, LTE/MQTT) is a design input. | [Provenance audit](docs/PROVENANCE_AUDIT.md), [combined architecture](docs/COMBINED_ARCHITECTURE.md) |
| Hardware architecture | Functional architecture v0.2, draft: block diagram, 12-sheet KiCad schematic (connectivity-checked, no ERC), timing, protection truth table and priced BOM. | [Hardware architecture](docs/HARDWARE_ARCHITECTURE.md) |
| Hardware freeze | Not hardware-frozen. Component selection is blocked by inputs that are not yet known: the motor (type, currents, pole pairs, R, L, λ, halls), the battery and BMS (voltage range, limits), the drivetrain, the driver controls and the rules edition. No primary datasheet has been read. | [Vehicle-team input sheet](docs/VEHICLE_TEAM_INPUT_SHEET.md) |
| Fabrication | Not fabrication-ready. By design there are no footprints, no layout and no fabrication outputs. The DRV8353S pinout is a placeholder, the crystal is unselected and KiCad ERC has not been run. Nothing has been energized. | [Review package v0.3](docs/REVIEW_v0.3.md) |
| Vehicle validation | Not vehicle-validated. Every result comes from synthetic models or host tests. | [Validation plan](docs/VALIDATION_PLAN.md) |
| Budget | Not shown feasible. Every scenario straddles its limit. | [Budget](docs/BUDGET.md) |

**Passing host tests does not mean the controller is complete or safe to install.**

## Repository layout

```
config/      parameter registry, schema, real (unconfigured) and synthetic vehicle configs
firmware/    portable C11 core (src/), public headers (include/semmc/), host platform + sim plant, STM32G4 notes, C tests
protocol/    CAN schema (protocol.yaml), generated C/Python codecs, golden vectors
host/        logger, companion supervisor + co-simulation, replay, CSIA vehicle adapter
models/      vehicle longitudinal model, power maps, inverter calculations, DP optimiser, strategies
hardware/    KiCad draft, BOM + pricing, calculations, timing, protection, selection register, bring-up, pin maps, review checklist
tests/       integration, fault injection, simulation (pytest)
tools/       generators, validators, studies, pin allocation, CSIA fetch
docs/        source audit, requirements, open parameters, rules map, freeze, ADRs, ICD, validation, efficiency research, generated reports
```

## How to reproduce

Requirements: Linux with gcc, cmake, ninja and Python 3.11 or newer.

Set up, build and test:

```sh
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 tools/fetch_csia.py                       # pinned CSIA core into .deps/ (not vendored)
cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build
python3 -m pytest                                 # builds ./build automatically if missing
```

Replay and synthetic studies:

```sh
python3 host/replay/replay.py tests/simulation/replay_sample.semmc.log   # requested vs accepted + reasons
python3 tools/run_optimization.py                 # synthetic DP study (~1.5 min)
python3 tools/run_electrical_calcs.py             # synthetic electrical sensitivity
python3 tools/run_csia_study.py                   # synthetic CSIA vs baselines
python3 tools/control_contract_report.py          # four-layer contract: before/after on 10 scenarios
python3 tools/run_csia_evaluation.py              # CSIA on the held-out synthetic set (frozen harness)
```

Configuration check:

```sh
python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw   # fails by design
```

A hardware-enabled build (`-DSEMMC_HARDWARE_BUILD=ON`) refuses to configure until the hardware config validates, and there is no STM32 platform layer yet.

Hardware, timing and interface reports:

```sh
python3 tools/gen_kicad_schematic.py --check      # KiCad draft + connectivity check (kicad-cli 7; not an ERC)
python3 tools/timing_budget.py && python3 tools/hardware_calcs.py && python3 tools/price_bom.py
python3 tools/clock_tree.py                       # clock-tree alternatives and CAN bit timing per bus case (no crystal chosen)
python3 tools/telematics_budget.py                # logging capacity, LTE volume, auxiliary power (assumption-tagged)
python3 tools/gen_dbc.py --base 0x300             # DBC for other teams' CAN tools (block base = calibration)
python3 tools/pin_type_check.py                   # pin-type rules on the KiCad netlist (not an ERC)
tools/run_kicad_erc.sh                            # real KiCad ERC; needs KiCad 8 or newer
```

## Documentation

Start here:

- [Review package v0.3](docs/REVIEW_v0.3.md): current status, vehicle interface and schematic foundation
- [Physical-team questionnaire](docs/PHYSICAL_TEAM_QUESTIONNAIRE.md): short, prioritised questions for the vehicle team
- [Migration](docs/MIGRATION.md): moving the project to `SWORT-Aerospace/sem-motor-controller`
- [Checkpoint v0.2](docs/CHECKPOINT_v0.2.md): corrected control model and hardware draft, with v0.3 errata
- [Vehicle-team input sheet](docs/VEHICLE_TEAM_INPUT_SHEET.md): one-page list of required inputs and what each one unblocks
- [Handoff v0.1](HANDOFF.md): first milestone, kept as a historical record
- [Architecture freeze](docs/ARCHITECTURE_FREEZE.md): v0.1, conditional
- [Open parameters](docs/OPEN_PARAMETERS.md): unknowns that block hardware

Design references:

- [Requirements](docs/REQUIREMENTS.md)
- [Control contract](docs/CONTROL_CONTRACT.md)
- [Hardware architecture](docs/HARDWARE_ARCHITECTURE.md)
- [Interface control document](docs/INTERFACE_CONTROL.md)
- [Validation plan](docs/VALIDATION_PLAN.md)
- [Architecture decision records](docs/decisions/README.md)
