# sem-motor-controller

Purpose-built, telemetry-informed motor controller for a Shell Eco-marathon battery-electric vehicle: power-stage planning, controller firmware core, CAN contract, supervisory energy strategy, and a CSIA vehicle consistency monitor in shadow mode.

## Status (truthful labels)

| | |
|---|---|
| **ARCHITECTURE FREEZE COMPLETE** | v0.1, conditional on motor type, battery, and unverified rules ([ARCHITECTURE_FREEZE](docs/ARCHITECTURE_FREEZE.md)) |
| **HOST IMPLEMENTATION VERIFIED** | C11 core + codecs + host co-simulation, tested on a host with a **synthetic** plant |
| **HARDWARE DESIGN BLOCKED BY** | unknown motor (type, pole pairs, R, L, λ, hall type), battery and BMS (V range, limits), vehicle (mass, gearing, freewheel), rules edition (60 V cap, Art. 66a kit-software scope, e-stop topology), supervisory hazard/latency analysis, power-stage measurements |
| **NOT FABRICATION READY** | no schematic, no PCB, no component approval; nothing has been energized |

Passing host tests does **not** mean the controller is complete or safe to install.

## Layout
```
config/      parameter registry, schema, real (unconfigured) and SYNTHETIC vehicle configs
firmware/    portable C11 core (src/), public headers (include/semmc/), host platform + sim plant, STM32G4 notes, C tests
protocol/    CAN schema (protocol.yaml), generated C/Python codecs, golden vectors
host/        logger, companion supervisor + co-simulation, replay, CSIA vehicle adapter
models/      vehicle longitudinal model, power maps, inverter calculations, DP optimiser, strategies
hardware/    conditional BOM, calculations index, interfaces/pin maps, schematic sheet plan, review checklist
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
```
A hardware-enabled build (`-DSEMMC_HARDWARE_BUILD=ON`) refuses to configure until the hardware config validates, and there is no STM32 platform layer yet.

## Start here
[HANDOFF.md](HANDOFF.md) · [docs/ARCHITECTURE_FREEZE.md](docs/ARCHITECTURE_FREEZE.md) · [docs/OPEN_PARAMETERS.md](docs/OPEN_PARAMETERS.md)
