# Review package v0.3: vehicle interface and schematic foundation (2026-10-15)

> **Historical record of v0.3, superseded.** Current state: [`STATUS.md`](../STATUS.md) and the [README](../../README.md); index of documents: [`README.md`](../README.md). Statements below describe v0.3 and are not updated. In particular the KiCad ERC, listed here as not run, has run in CI since v0.4 with KiCad 8.0.9 (0 errors, 9 warnings; [`VERIFICATION_REPORT.md`](../VERIFICATION_REPORT.md) 5).

**NOT hardware-frozen · NOT fabrication-ready · NOT vehicle-validated · vehicle bus UNKNOWN · crystal UNSELECTED · KiCad ERC NOT RUN.**
* Continues from `1c17145`. The v0.2 checkpoint is preserved with an errata banner; its unfavourable results stand.
* The optimiser was not expanded. CSIA was not retuned or re-run.
* Nothing was purchased, fabricated, energized or published.

## 1. Assumption corrections
The Cornell repositories are reference projects; v0.1–v0.2 had treated them as our vehicle.
* Full list, with labels (confirmed / reference / proposed / unknown) and every affected file: [`PROVENANCE_AUDIT.md`](PROVENANCE_AUDIT.md).
* **Code change:** the controller core is now **transport-neutral** (`mc_core_on_msg_rx` / `mc_core_msg_tx_poll` / `mc_core_on_link_state`).
* **CAN binding:** CAN is one binding. Its 64-identifier block base is the calibration parameter `supervision.can_id_base`:
  * null until the vehicle team allocates the block;
  * a multiple of 0x40, enforced by validator rule 40.

  See [ADR-0012](../decisions/ADR-0012-transport-neutral-interface.md).
* CHUDS stays an optional adapter.
* Withdrawn: "the controller must run CAN FD", "CAN FD requires a 40 MHz crystal", "the three phase currents are sampled simultaneously" (now *proposed*), and "current limited to ≤ 2 A by the supply" as a phase-current statement.

## 2. Our vehicle vs the reference project
[`VEHICLE_INTERFACE_MATRIX.md`](VEHICLE_INTERFACE_MATRIX.md).
* **No interface fact about our vehicle is confirmed yet.** The telematics proposal (CAN 2.0B, STM32U575, LTE/MQTT) is a design input.
* Six team inputs select the interface:
  * the existing telemetry hardware;
  * the wiring diagram;
  * the message definitions and ID map;
  * the voltage levels;
  * the sample rates;
  * the supervision computer.

## 3. Combined architecture with the telematics proposal
[`COMBINED_ARCHITECTURE.md`](../COMBINED_ARCHITECTURE.md), with an interface-difference table (§6).
* **Supervisor:** on the STM32U575 telematics unit as a protected task (proposed).
* **CSIA:** offline on the pit computer now. A shadow task on the telematics unit only after the next frozen evaluation. Never in the controller's control path, never in the cloud.
* **Driver authorization:** wired to the controller. A driver-input node may mirror it on CAN for logging only.
* **Torque requests:** MANUAL from the wired throttle; ECO from the supervisor over CAN, bounded by L2/L3, with a timeout to zero.
* **Pit/cloud:** one-way, outside the control dependency chain.
* **Logging** (`generated/telematics_budget.md`): the controller's frames alone (7.3 kB/s) fill the proposed 8 MB QSPI flash in **17 min**, against a 40-min attempt. The microSD should hold the raw log.
* **Auxiliary power** (recalled values, unverified): telematics unit 0.45–2.1 W, controller logic 0.15–0.9 W. Over a synthetic 1000 s attempt that is 1–5 % and 0.4–2 % of the synthetic energy, if it is metered.

## 4. Clock-tree alternatives (crystal not selected)
[`../hardware/timing/clock_tree_alternatives.md`](../../hardware/timing/clock_tree_alternatives.md); 28 complete trees × 4 bus cases.
* Evidence: ST register widths and HAL ranges from GitHub. DS12288-only limits are tagged and use the narrower of conflicting values.

| Bus case | Result |
|---|---|
| CAN 2.0B at 250k, 500k or 1M (telematics proposal; rate not stated) | every candidate crystal (8–40 MHz) at every listed CPU frequency gives an exact, feasible timing with the kernel ≤ 48 MHz; tolerance margin ≈ 49× a 100 ppm crystal budget at 500k. **The crystal is not constrained by a classic bus.** |
| CAN FD 500k/2M at exactly 80 %/80 %, kernel ≤ 48 MHz (reference project) | 20 or 40 MHz crystals at any listed CPU frequency; 8, 12, 16, 24 or 25 MHz with a **160 MHz** CPU (PLLQ → 40 MHz) |
| CAN FD at 170 MHz with an 8 MHz crystal | exact 500k/2M, but only 5 time quanta per data bit and a 170 MHz kernel (above an unverified 48 MHz note) |

Timing implications are tabulated per tree:
* **TIM1 resolution:** 4000–4250 counts per half-period at 20 kHz.
* **Dead-time code:** 200 ns = DTG 0x20 at 160 MHz, 0x22 at 170 MHz.
* **ADC kernel:** 53–60 MHz.
* **CPU cycles per PWM period:** 7200–8500.

The tolerance analysis computes ISO 11898-1 conditions I–III. The CAN FD switch conditions IV–V are not computed.

## 5. Pinout verification and electrical checks
[`../hardware/selection/PINOUT_VERIFICATION.md`](../../hardware/selection/PINOUT_VERIFICATION.md).

**Pinouts**
* **No primary datasheet was readable** (vendor hosts refused).
* MCU power, VREF+, NRST, BOOT0 and HSE pins cross-checked against ST's pin database.
* **INA228: the placeholder numbering was wrong and is replaced** by the VSSOP-10 numbering, cross-checked against the KiCad library. This is secondary evidence.
* **DRV8353S remains an explicit placeholder:** no datasheet, no library symbol. It was not renumbered from memory.

**Electrical checks**
* Reset states and shutdown paths reviewed: no gate signal sits on a pin pulled at reset.
* **Connectivity check:** 0 problems.
* **New pin-type check** (not ERC): it found 6 genuine power-flag errors that a KiCad ERC would also raise. They were fixed with PWR_FLAG markers; 0 findings now.
* **A real KiCad ERC was not run:** KiCad 7 has no CLI ERC, and installing KiCad 9 here was refused by the environment's permission policy. `tools/run_kicad_erc.sh` runs it on any machine with KiCad 8+.

## 6. Remaining schematic blockers
1. Primary datasheets (add the PDFs under `docs/reference/datasheets/`).
2. The DRV8353S symbol for the orderable package.
3. A real KiCad ERC.
4. The crystal (after the bus).
5. The CAN identifier block, connector and termination.
6. All power-stage ratings (motor and battery unknown; explicit UNRESOLVED placeholders, none invented).
7. Bias values that depend on the motor, the driver controls and the safety loop.

## 7. Validation language
[`VALIDATION_PLAN.md`](../VALIDATION_PLAN.md) §2 and the bring-up checklist now separate four quantities:
* command-ceiling compliance;
* supervisory envelope-ramp compliance (always quoted with its ramp, ≥ 100 N·m/s, and its deadline, 20 ms ≤ 100 ms timeout; synthetic);
* physical phase current;
* battery-input current.

A bench-supply limit bounds only the battery-input current. The checklist adds DC-link stored energy (½CV², discharge before handling) and body-diode regeneration (rectification above ω = V_DC/(√3·p·λ); a source-only supply cannot absorb it).

## 8. CSIA
[`csia/EVALUATION_RESULTS.md`](../csia/EVALUATION_RESULTS.md) §5–6.
* The frozen held-out results are unchanged. The debounce finding is labelled post-hoc.
* New table of which output comes from which component: residual design, validity gates, debounce, corroboration logic, TrustCore.
* **No result is attributed to TrustCore**: no ablation shows a contribution, and its only detector was the worst.
* The next evaluation is planned but not run.

## 9. Tests run (v0.3, x86-64 host and arm-none-eabi; nothing on hardware)
| Command | Result |
|---|---|
| fresh `cmake` + build (`-Werror`, ASan+UBSan) + `ctest` | 0 warnings; **6/6 suites, 4,006 checks, 0 failures**. New: CAN block relocation with a full ECO engagement at base 0x500; transport-neutral message API; rule 40 mutations |
| `python -m pytest tests` | **199 passed**. New: DBC vs golden vectors with cantools at two bases; bridge relocation; rule-40 C/Python parity; clock-tree and telematics-budget regressions |
| ARM Cortex-M4F portability build (MinSizeRel, core only) | 0 warnings; 30,823 B text; no soft-double calls in `mc_core_fast_step` |
| `gen_config` / `gen_protocol` / `gen_dbc` `--check` | current |
| `gen_kicad_schematic.py --check`; `pin_type_check.py` | 0 connectivity problems; 0 pin-type findings |
| `control_contract_report.py` | 0 command-ceiling and 0 envelope-ramp violations, against ramp ≥ 100 N·m/s and deadline 20 ms (synthetic) |
| **Not run** | KiCad ERC; anything on hardware; a real CAN socket |

## 10. Inputs still missing
* `bk4000tg_kicad.zip` and `telemetry.pdf` were referenced by the vehicle team but not received. (v0.4: requested in `docs/INPUT_SHEET.md`.) Until then no Cornell or other hardware is substituted for them.
* The two telematics PDFs that did arrive are used as design inputs.

Questions for the physical team (short, prioritised): [`PHYSICAL_TEAM_QUESTIONNAIRE.md`](PHYSICAL_TEAM_QUESTIONNAIRE.md). Repository move: [`MIGRATION.md`](MIGRATION.md).
