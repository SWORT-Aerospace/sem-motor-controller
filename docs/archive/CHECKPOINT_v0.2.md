# Checkpoint v0.2: corrected control model and reviewable hardware draft (2026-10-15)

> **Historical record of v0.2, superseded.** Current state: [`STATUS.md`](../STATUS.md) and the [README](../../README.md); index of documents: [`README.md`](../README.md). Statements below describe v0.2 and are not updated; the KiCad ERC, listed here as not executed, has run in CI since v0.4 ([`VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md) 5).

**CONTROL CONTRACT CORRECTED (host-verified) · FUNCTIONAL HARDWARE ARCHITECTURE v0.2 DRAFT (reviewable) · COMPONENT SELECTION NOT FROZEN · NOT HARDWARE-FROZEN · NOT FABRICATION-READY · NOT VEHICLE-VALIDATED · BUDGET NOT SHOWN FEASIBLE**

> **Errata (v0.3, 2026-10-15). The body below is preserved unchanged, including its unfavourable results.** Corrections:
> * **Cornell CHUDS is a reference project, not our vehicle.** Every statement here that our bus is CHUDS / CAN FD 500k/2M, that the controller must run in FD mode, or that IDs must avoid CHUDS classes is an unsupported assumption (`PROVENANCE_AUDIT.md`).
> * **"8 MHz cannot reach the data-phase sample point, so the schematic uses 40 MHz" is withdrawn.** An 8 MHz crystal with a 160 MHz CPU gives exact 500k/2M at 80 %/80 % through PLLQ. The crystal is now unselected (`../hardware/timing/clock_tree_alternatives.md`).
> * **"The three phase currents are now on three ADCs with the same trigger"** describes a proposal. It is not substantiated until trigger configuration, synchronisation, acquisition windows and a measurement confirm it.
> * **"Current limited to ≤ 2 A by the supply and by the configuration"** (§7) conflated two quantities. A supply limit bounds only the battery-input current; the phase-current limit is set and probed separately (`../hardware/bringup/BENCH_BRINGUP_CHECKLIST.md`).
> * **"0 contract violations"** (§2) means command-ceiling compliance plus envelope-ramp compliance against a ramp of ≥ 100 N·m/s with a 20 ms deadline (synthetic). It says nothing about phase current.
> * **KiCad "connectivity, 0 problems" was never an ERC.** The v0.3 pin-type check and the real-ERC blocker are in `REVIEW_v0.3.md`.

Nothing was purchased, fabricated, published or energized. Every result below comes from host software, synthetic models, or search-snippet evidence; none of it is a hardware measurement.

## 1. Where the work is
| Item | State |
|---|---|
| Branch | `andrefp-co/swort` `claude/nice-bell-98hxr2` (no PR; not merged into the site's `main`) |
| Commits | `064ac47` control contract · `46ef5d8` actuator model + CSIA freeze · `43bf666` optimisation + CSIA evaluation · `2c8e444` hardware package + budget · `a54112f` CAN/rules/input sheet · the checkpoint commit (`git log -1`) |
| Changed files | 119 under `sem-motor-controller/` (71 added, 48 modified), including this checkpoint: [`generated/changed_files_v0.2.txt`](changed_files_v0.2.txt). Nothing outside `sem-motor-controller/` changed. |
| Dedicated repository `SWORT-Aerospace/sem-motor-controller` | **NOT created.** The GitHub integration answered `403 Resource not accessible by integration` to repository creation in the organisation, and `add_repo` reports no such repository. A history-preserving export has been prepared (§9). |

## 2. Tests executed (v0.2, x86-64 host) and results
| Command | Result |
|---|---|
| `cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build` | **6/6 suites, 3,962 checks, 0 failures**, 0 warnings (`-Werror` set, ASan+UBSan) |
| `python -m pytest tests` | **185 passed** |
| ARM Cortex-M4F portability build (MinSizeRel, core only, no firmware image) | 0 warnings; 30,565 B text (v0.1: 29,806 B); `mc_core_fast_step` has no soft-double calls |
| `tools/gen_config.py --check`, `tools/gen_protocol.py --check` | generated files current |
| `tools/control_contract_report.py` | **0 contract violations** in 10 scenarios (every update checked) |
| `tools/gen_kicad_schematic.py --check` (kicad-cli 7.0.11) | KiCad connectivity equals the intended connectivity on all 135 nets: **0 problems**. This is not an ERC. |
| `tools/run_optimization.py`, `tools/run_csia_evaluation.py` (held-out set, frozen harness), `tools/run_csia_posthoc.py`, `tools/timing_budget.py`, `tools/hardware_calcs.py`, `tools/price_bom.py`, `tools/can_bit_timing.py` | outputs in `docs/generated/`, `hardware/` |
| **Not executed** | anything on hardware; KiCad ERC (KiCad 7 has no CLI ERC); the VCU bridge on a real socket (no AF_CAN in this container) |

## 3. Corrected control and simulation findings
**Control contract** ([`CONTROL_CONTRACT.md`](../CONTROL_CONTRACT.md), [before/after](../generated/control_contract_before_after.md)):
* Hard ceilings now clamp on the next update. A thermal step went from 9 violating updates (+0.9 N·m) to 0; with slow slew settings, from 500 to 0.
* Supervisory envelopes ramp at no less than the fast rate, bounded by validator rule 38 (≤ supervision timeout). Settling went from 150 ms to 15 ms.
* The envelope applied is min(newest, referenced). A tighter set used to be ignored for 190 ms; a delayed request referencing an older set ramped torque to 1.6 N·m against a newest bound of 0.5. Both now settle in 13 ms with 0 violations.
* One v0.1 test that encoded the defect was corrected, which made it stricter.

**Optimiser v0.2** ([`EFFICIENCY_RESEARCH.md` §4](../EFFICIENCY_RESEARCH.md), [study](../generated/optimization_synthetic.md), [accounting](../ENERGY_ACCOUNTING.md)):
* The actuators are now explicit: coast, propulsion, and driver braking issued as guidance. Nothing brakes implicitly. The motor friction power, previously missing, is now charged.
* The acceleration limit now reduces the applied torque. The v0.1 clip left a 2.76 kJ residual whenever it bound.
* Corner limits are now enforced on whole segments; v0.1 enforced them at nodes only.
* Grid convergence: 0.13 %.
* Track A (synthetic): DP + driver guidance 42.7 kJ, pulse-and-coast 52.5 kJ, constant speed 54.5 kJ, all at matched executed time.
* **A torque-only policy is physically infeasible on track A.** Coasting from rest down the descent reaches 5.99 m/s against a 5.48 m/s corner limit, so braking is structurally required.
* On a flat track, torque-only DP is 33.9 kJ.
* Without pace correction, the fixed plan exceeds the 1000 s limit under +20 % Crr, +5 % mass or a 2 m/s headwind.
* **All v0.1 savings figures are withdrawn.**

**CSIA** ([results](../csia/EVALUATION_RESULTS.md); the harness was frozen before the run):
* On 94 unseen synthetic scenarios (5.8 h), the frozen adapter raised 19.7 false-alarm episodes per hour and made 9 misattributions.
* Gated, calibrated residuals with a majority vote: 0 false alarms per hour (95 % upper bound 0.52) and 0 misattributions, but fewer attributions (35 vs 48).
* Post-hoc and exploratory: the false-alarm difference is entirely the 3-tick debounce.
* TrustCore thresholding performed worst.
* Rotor scale errors and dropped rotor samples are invisible to the relationships; dropped samples are caught only by the freshness checks.
* CSIA stays in shadow mode. **No vehicle claim.**

**Hardware timing and integration** ([timing](../../hardware/timing/timing_budget.md), [CAN](CAN_INTEGRATION.md)):
* The three phase currents are now on three ADCs with the same trigger. v0.1 sampled phase C 0.35 µs after phase A.
* At full linear modulation only one phase is sampleable at 60°. The voltage limit is now a calibrated parameter, bounded by validator rule 39, which takes the measured settling time as an input.
* The CHUDS bus is CAN FD (500k/2M at 80 %/80 %), so the controller must run in FD mode. An 8 MHz crystal cannot reach the data-phase sample point, so the schematic now uses **40 MHz**.
* CHUDS drops classic frames and reserves 0x300+, so the ID allocation and a VCU-side consumer are needed.
* The LQFP-64 MCU package no longer fits; LQFP-100 remains the baseline.

## 4. Schematic and BOM maturity
* **Done (draft):**
  * Functional architecture with block diagram ([`HARDWARE_ARCHITECTURE.md`](../HARDWARE_ARCHITECTURE.md)).
  * A 12-sheet hierarchical KiCad schematic: 206 parts, 135 nets, connectivity-checked, with a review PDF.
  * Protection/shutdown truth table, timing allocation, current-sense error budget, loss/thermal envelope, bring-up checklist.
  * A BOM derived from the schematic and priced with an evidence class on every line.
* **Unresolved selections:**
  * MOSFETs, phase and bus shunts, DC-link capacitors, fuse, TVS, reverse-polarity block, precharge resistor and bypass FET;
  * connectors; buck UVLO, R_ON and inductor; crystal load capacitors; motor-temperature bias; safety-loop LED resistor.
  * All depend on motor, battery or harness inputs.
* **Unverified:**
  * DRV8353S and INA228 pin numbers (project-library placeholders);
  * every "TYPICAL – verify" value;
  * every [R] constant in the timing budget.
  * No primary datasheet could be opened ([`DATASHEET_REGISTER.md`](../../hardware/selection/DATASHEET_REGISTER.md)).
* **Missing for selection freeze:** the motor and battery inputs, the datasheet register filled in, a design review, and a layout. **No footprints, layout or fabrication outputs exist, by design.**

## 5. Cost range (evidence-classed, [`BUDGET.md`](../BUDGET.md))
| Scenario | Controller only | + vehicle integration | + bring-up equipment if not owned |
|---|---|---|---|
| one prototype | $246 – $650 | $311 – $825 | $415 – $1,189 |
| two boards + one revision | $443 – $1,201 | $518 – $1,406 | $622 – $1,770 |

* Per-board parts: $89–231. The price evidence is weak:
  * 5 lines are search-snippet prices for the exact part;
  * 11 lines are representative prices for rating-dependent parts;
  * 84 lines are allowances.
* **Verdict (computed): every scenario straddles its budget.** Feasibility is not shown.
* The spread is driven by board parts, the PCB quote, tax/shipping, harness and spares. Closing it needs a live PCB quote, live part quotes, the motor and battery ratings, and the team's inventory.

## 6. Vehicle-team input sheet
[`VEHICLE_TEAM_INPUT_SHEET.md`](VEHICLE_TEAM_INPUT_SHEET.md): one page, 25 items. **Most urgent: motor peak and continuous current and type (M1, M2), battery voltage range and BMS limits (B1, B2), available test equipment (T1).**

## 7. Shortest path to a current-limited bench demo
Goal: the vehicle motor (or a spare BLDC) turning on a stand in MANUAL, current limited to ≤ 2 A by the supply and by the configuration, on a team-built board, with the hall table and current loop verified.

| Step | Owner | Depends on | Estimate (calendar, unverified) |
|---|---|---|---|
| 1. Inputs M1, M2, B1, B2, T1, T3 | vehicle team | n/a | days |
| 2. Fix the power stage: pick parts in the representative class (ratings from step 1); fill the datasheet-register rows; finish the UNRESOLVED values; replace placeholder pinouts | this project | 1, and readable datasheets (the user can supply the PDFs) | 2–4 days |
| 3. STM32G4 platform layer (clock 40 MHz, TIM1 + break, ADC1/2/3, SPI DRV8353, FDCAN FD mode, inputs, watchdog, DWT), register-level with CMSIS | this project | CMSIS device headers (BSD-3) and the rules answer R2 | 1–2 weeks, **in parallel with 2–5** |
| 4. PCB layout (4-layer, "SEM" etch), review against `REVIEW_CHECKLIST.md`, live quotes, `price_bom.py` re-run, team approves the purchase | this project + team | 2 | 1–2 weeks |
| 5. Fabrication and shipping; hand assembly with the stencil | team | 4 | 1–3 weeks |
| 6. Bring-up stages 1–4 with a dummy load (checklist) | team (qualified) | 3, 5, test equipment | ~1 week |
| 7. Stage 5: hall table, R/L/λ, current-loop step, low-current spin with the supply limit ≤ 2 A | team (qualified) | 6, measured calibration blob in hardware mode | days |

Critical path after the inputs arrive: about 5–8 weeks (estimate). A faster option is a bench-only rig on an MCU development board plus a gate-driver evaluation module. It would test the firmware weeks earlier, but it depends on the organisers' answer about bench use of evaluation boards (R2/Q4), and it costs money outside the current budget. It must never enter the vehicle.

## 8. Blocking questions (grouped; details and units in the input sheet)
* **Motor:** model and type; peak and continuous current and duration; pole pairs, R, L, back-EMF constant; max speed; temperature sensor; hall supply and output type.
* **Battery/BMS:** chemistry and series count; min, nominal and max-charged voltage; BMS continuous and peak limits; short-circuit current; joulemeter and e-stop position.
* **Drivetrain:** gear ratio, wheel circumference, freewheel; vehicle mass and category; tolerance of a step torque reduction.
* **Driver controls:** throttle type and range; brake contact type; dead-man contacts and safety-loop voltage; which switches exist.
* **Event rules:** event and year; the 2027 Chapter I and Chapter II PDFs; attempt format; answers to `RULES_RECONCILIATION.md` §3; CAN ID reservation and the Emergency STOP decision (vehicle team).
* **Test equipment:** bench supply, oscilloscope, **differential probe**, current probe, electronic load, programmer, USB-CAN, reflow; who signs measurements; lab safety procedure; a spare motor.

## 9. Repository extraction (prepared, not pushed)
* `git subtree split --prefix sem-motor-controller` produces the project's history as a standalone branch: `semmc-export` in the local clone.
* The split is deterministic: anyone with this branch can regenerate the same history with `git subtree split --prefix sem-motor-controller -b semmc-export`. A git bundle made during v0.2 lived only in temporary storage, so the branch on GitHub is the durable source.
* Once `SWORT-Aerospace/sem-motor-controller` exists (created by an organisation owner, or once the integration is granted repository-creation rights), push the branch with:
```
git push https://github.com/SWORT-Aerospace/sem-motor-controller.git semmc-export:main
```
* The site repository's `main` is never involved.

## 10. Limits of this checkpoint
* No primary datasheet, rule PDF or distributor page could be opened (network policy). The register, the rules map and the prices are built on search snippets and say so line by line.
* The attachments `bk4000tg_kicad.zip` and `telemetry.pdf` were not available: not in the uploads, the attachments, the filesystem or Drive.
* KiCad 7 has no CLI ERC, so only connectivity was checked. The STM32 platform layer is not written, so no firmware image exists.
