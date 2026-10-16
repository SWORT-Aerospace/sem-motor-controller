# Handoff: first milestone (2026-10-14)

> **Current status is in [`docs/REVIEW_v0.3.md`](docs/REVIEW_v0.3.md) (v0.3) and [`docs/CHECKPOINT_v0.2.md`](docs/CHECKPOINT_v0.2.md) (v0.2, with errata) (2026-10-15).** This file is the v0.1 handoff and is kept as a historical record. Superseded by v0.2:
> * the optimiser energies in §2 (39.7 / 46.2 / 55.1 kJ) and every v0.1 savings figure, which are **withdrawn**. The v0.1 model let gate-off coast brake implicitly, left an acceleration-clip residual, and checked corner limits at nodes only (`docs/EFFICIENCY_RESEARCH.md` §4);
> * the CSIA nuisance and attribution figures in §1, which came from the development scenarios. Held-out results are in `docs/csia/EVALUATION_RESULTS.md`;
> * the arbiter behaviour, now governed by the four-layer contract (`docs/CONTROL_CONTRACT.md`, ADR-0011), and the test counts.
> v0.2 status: **NOT hardware-frozen · NOT fabrication-ready · NOT vehicle-validated · budget NOT shown feasible.**

**ARCHITECTURE FREEZE COMPLETE (v0.1, conditional) · HOST IMPLEMENTATION VERIFIED · HARDWARE DESIGN BLOCKED BY missing motor, battery, vehicle and rules inputs (§4) · NOT FABRICATION READY**

The controller is not complete and not safe to install. Every test below ran on an x86-64 host against a synthetic plant. Nothing has been energized.

## 1. Implemented and verified on a host (actual commands, actual results)

| Deliverable | Where | Verification run at v0.1 |
|---|---|---|
| Architecture freeze v0.1 + 10 ADRs | `docs/ARCHITECTURE_FREEZE.md`, `docs/decisions/` | review |
| Source audit, requirements, open parameters, rules map | `docs/SOURCE_AUDIT.md`, `REQUIREMENTS.md`, `OPEN_PARAMETERS.md`, `RULES_COMPLIANCE.md` | review |
| C11 controller core: config blob + validator, state machine (8 states, 18 transitions), arbiter, freshness/session, protection/derating, PI/Clarke/Park/SVPWM/FOC, hall decoder, stall check, CSIA shadow interface | `firmware/` | `cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build` → **6/6 suites, 1,293 checks, 0 failures, 0 compiler warnings** (`-Wall -Wextra -Wpedantic -Werror -Wdouble-promotion -Wfloat-conversion -Wsign-conversion`, ASan + UBSan) |
| Cortex-M4F portability (core only, not a firmware image) | `firmware/cmake/arm-none-eabi-cortex-m4f.cmake` | arm-none-eabi-gcc 13.2.1, 0 warnings, 29,806 B text; `mc_core_fast_step` makes no soft-double calls (objdump) |
| Versioned CAN contract v1.0 + generated C/Python codecs + 18 golden vectors | `protocol/` | C golden check 0 failures (incl. every single-bit flip caught); Python roundtrip + independent hand-calculated bytes + bitwise reference CRC |
| Config validation parity C ↔ Python | `tools/config_tool.py`, `mc_config.c` | 33 mutations × 2 modes, identical rule codes |
| Hardware build fails closed | `firmware/CMakeLists.txt` | `-DSEMMC_HARDWARE_BUILD=ON` refuses to configure on the unconfigured config (`MISSING_REQUIRED`) and on the synthetic config (`PROVENANCE`); tested |
| Host replay (requested vs accepted + reason codes) | `host/replay/replay.py`, `tests/simulation/replay_sample.semmc.log` | duplicates and a late reordered frame ignored; stale gap → READY; new driver edge required; NaN request → READY; voltage sag → `CLAMP_DERATE`; brake → 0 |
| End-to-end lockstep co-simulation: supervisor → Python encode → C decode → freshness → state machine → arbiter → FOC → plant → C encode → Python decode | `host/telemetry_adapter/{e2e,cosim,supervisor}.py` | 25 s run: ECO engages only after the driver edge, speed held at 6 m/s ± 0.5, ECO → READY 100 ms after the last new request, controller-vs-plant energy within 2 % |
| Fault injection (21 scenarios) | `tests/fault_injection/` | all pass: gate-driver fault, HW OC, hall disconnect, stuck hall (stall check), two-phase sense loss, biased current visible in KCL, thermal derate → trip, temperature-sensor loss → bounded derate, Vbus NaN, hill/acceleration not a fault, brake override, invalid startup, synthetic config on a hardware build, fault recovery without resume, cached-sample replay, supervisor reboot, controller reboot, bus-off, reordered frames, malformed frames, NaN request |
| Vehicle + powertrain + inverter models | `models/` | numerical checks: synchronous-MOSFET conduction rule; DC-link ripple formula vs a switching simulation (within 3 %); coast-down identifiability on wide vs narrow speed ranges |
| Offline spatial DP + strategies + bounded pace correction | `models/optimization/`, `tools/run_optimization.py` | grid convergence 0.29 %; schedule exported (`docs/generated/dp_schedule_synthetic.csv`) |
| Electrical calculations + sensitivity | `models/inverter/losses.py`, `tools/run_electrical_calcs.py` | `docs/generated/electrical_calcs_synthetic.md` |
| Conditional BOM | `hardware/bom/BOM_candidates.csv` | 20 rows; no prices or stock (unknown); nothing order-ready |
| STM32G474 pin/resource check | `tools/pin_allocation.py` | against ST pin DB @7d1f151: LQFP100 fits with 34 spare I/O; LQFP64 fits with 0 spare; 48-pin packages fail |
| CSIA vehicle adapter (shadow) with pinned CSIA core | `host/csia_adapter/`, `third_party/csia-trust-layer.lock` | synthetic: 0 nuisance flags on normal events (fixed-threshold baseline: 935 ticks of 1199); 6 fault classes attributed correctly with 0 misattributions; hostile advisory frames leave controller commands bit-identical |
| Python test suite | `tests/` | `python -m pytest` → **160 passed** (36 s) |

## 2. Simulated only (labelled SYNTHETIC everywhere)
Plant, motor, battery, vehicle and track parameters · DP / pulse-and-coast / constant-speed energies (39.7 / 46.2 / 55.1 kJ, track-specific) · robustness results (the open-loop plan misses the time limit under +20 % Crr or a 2 m/s headwind; bounded pace correction recovers it) · inverter-loss rankings and PWM optimum · auxiliary-energy share (~16 %) · CSIA detection latencies.

## 3. Unverified (read nothing primary, or not yet tested on hardware)
* **All SEM rules** (60 V cap, e-stop isolation, purpose-built controller and kit-software ban, joulemeter placement, dead-man): search extracts only.
* **All datasheet values** (DRV8353, INA228, TCAN1042HGV, STM32G474, STSPIN32G4, candidate MOSFETs) and the TIDA-010056 guide: snippets only.
* **All three MDPI papers:** inaccessible; no content used.
* The **attached KiCad board and telemetry proposal**: not present in the container; prior findings not rechecked.
* Every hardware behaviour: hardware protection independence, timing, thermal, efficiency, CAN physical layer.
* CSIA on the target: host benchmark only (0.23 ms/tick in CPython); the native kernel is double precision and not used.

## 4. Exact hardware inputs still required
1. **Motor**: make/model and datasheet; type (PMSM/BLDC/brushed); pole pairs; line-to-line R and L (d/q) with test conditions; line-line back-EMF constant; rated/max speed; continuous/peak current and duration; winding temperature limit and sensor; hall sensor type, supply and output stage; hall-to-rotor alignment.
2. **Battery/BMS**: chemistry, series count, min/nominal/max-charged voltage, capacity, BMS continuous/peak discharge and charge limits, short-circuit current.
3. **Vehicle**: category (Prototype vs Urban Concept), mass with driver, gear ratio, loaded wheel circumference, freewheel/clutch, track width, existing controller and baseline data, cooling/enclosure/harness/connector constraints.
4. **Competition**: event and year; the rule edition in force (2027 Ch I) and the event's Ch II; attempt format (laps, time limit).
5. **Measurements** (VALIDATION_PLAN stages 2–6): rail quiescent currents, switching overshoot, CSA offsets, hardware trip latency, R/L/λ, hall table, loss map, thermal curves, coast-down.
6. **Hazard and latency analysis** for supervisory timing (replaces the provisional 50 Hz / 100 ms).
7. **Budget and deadline**, and who performs and signs bench measurements.

## 5. Placement and publication
* The project lives at `sem-motor-controller/` inside `andrefp-co/swort` on branch `claude/nice-bell-98hxr2` (pushed; no PR). It is self-contained, and no other file in the site repository was modified.
* **Do not merge this branch into the site's `main`**: it is a static-site deploy repository and the files would be served publicly. The intended home is a dedicated private repository (ADR-0001): `git subtree split --prefix sem-motor-controller -b semmc` and push it to the new repository.
* No remote repository was created; nothing was purchased, ordered, published or energized.

## 6. Reproduce
See `README.md` (venv + `pip install -r requirements.txt`, `tools/fetch_csia.py`, CMake/CTest, `pytest`).
