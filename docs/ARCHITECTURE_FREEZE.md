# Architecture Freeze v0.1 — SEM telemetry-informed motor controller

**Status: ARCHITECTURE FREEZE COMPLETE (v0.1, conditional) · HOST IMPLEMENTATION VERIFIED · HARDWARE DESIGN BLOCKED · NOT FABRICATION READY**

Date: 2026-10-14 · Applies to: `sem-motor-controller/` at the commit that contains this file.

An architecture freeze fixes **boundaries and interfaces**. It is not manufacturing approval, not a component selection, and not evidence that anything is safe to energize. Each frozen item lists the conditions under which it must be reopened, and that reopening must be recorded in `docs/decisions/`.

---

## 1. Conditional assumptions (all must hold for this freeze to stand)

| # | Assumption | Status | If false |
|---|---|---|---|
| C1 | The traction motor is a **three-phase permanent-magnet machine** (PMSM or BLDC) with **hall sensors** | UNKNOWN (no motor identified in any source) | Brushed DC → ADR-0003 path B (H-bridge; no FOC). Sensorless or encoder → reopen rotor-sensing interfaces. The config validator rejects non-PMSM types today (`ARCH_MOTOR_TYPE`). |
| C2 | Battery-electric vehicle with a single **lithium** pack, **≤ 60 V by design at any point** | Rule UNVERIFIED (search extract of SEM 2026 Ch. I Art. 57a); pack unknown | A higher-voltage pack is outside every frozen voltage class here; reopen the power stage and gate-driver family. |
| C3 | The SEM rules require a **purpose-built controller** and forbid evaluation kits and their software | UNVERIFIED (Art. 66a + official tips page, search extracts) | If vendor motor-control kit software is permitted, ADR-0009 (no MCSDK-generated control code) may be relaxed. |
| C4 | The e-stop **physically isolates the battery** using normally-open contacts **not driven by the controller** | UNVERIFIED (Art. 37e) | Precharge and isolation sequencing in the power stage change. |
| C5 | The organizers' joulemeter measures **everything downstream of the battery**, with no accessory battery for BEV | UNVERIFIED (Art. 56c, 57b) | If the electronics may use a separate battery, the auxiliary-energy hypothesis H6 loses weight. |
| C6 | A companion computer (Linux-class) exists on the vehicle and is reachable over wired CAN | Proposed (telemetry proposal unavailable; Cornell uses a Pi) | The supervisor role moves or is dropped. The controller is designed to run without it. |

## 2. Frozen system boundaries (A–H)

| ID | Boundary (frozen) | How it is enforced in this repository |
|---|---|---|
| **A** | The **local MCU** owns PWM, commutation, current regulation, protection handling, command arbitration, and operating state. | `firmware/src/*`: the FOC fast loop, protection, state machine and arbiter all run in the controller core. No message on the bus carries duty, PWM, transistor state, arming, mode selection or fault reset (`protocol/protocol.yaml`, header comment; checked by `test_protocol.c::test_ids_outside_chuds_range` and by review). |
| **B** | The **companion computer** initially owns logging, track matching and the supervisory energy strategy. | `host/telemetry_adapter/supervisor.py`, `models/optimization/*`. The companion sends **bounded requests** only (`sup_torque_req`, `sup_limits`). |
| **C** | **Wired CAN** connects supervision and controller. | 11-bit IDs `0x300–0x33F`, classic 8-byte frames, 500 kbit/s nominal, CAN-FD-tolerant (ADR-0005). |
| **D** | **CSIA observes and logs**; it does not command torque. | `firmware/src/csia_adapter/mc_csia_shadow.c::mc_csia_may_restrict()` returns `false` unconditionally. Shadow-mode proof: `tests/fault_injection/test_csia_adapter.py::test_shadow_mode_never_changes_controller_commands`. |
| **E** | **Independent hardware protection** acts without waiting for CSIA, Linux, CAN or cellular. | Hardware: gate-driver VDS monitor + overcurrent comparator into `TIM1_BKIN` + external windowed watchdog on driver ENABLE (`hardware/schematic_plan`). Software only *mirrors* hardware trips (`mc_prot_*`, `MC_R_HW_TRIP`). The fast loop also disables outputs immediately on a hardware-trip input (`mc_fast_inputs_t.hw_trip`). |
| **F** | **Physical emergency isolation and driver presence** stay independent of optimization software. | The e-stop chain and dead-man act on power hardware. The controller only *senses* them (`estop_chain_ok`, `driver_present`) and drops to DISARMED/READY. No software path closes an isolation contact. |
| **G** | **Cellular is monitoring-only.** | No protocol message originates from the cellular path. The companion must never bridge cellular input onto CAN writes (INTERFACE_CONTROL §6). |
| **H** | **Mechanical steering and braking** remain under driver control. | The controller has no steering or brake actuator interface. The brake *switch* only removes torque (`MC_R_BRAKE_OVERRIDE`, immediate). |

## 3. Platform decision (frozen, conditional on the pin/resource check)

* **Baseline MCU: STM32G474, LQFP100 (STM32G474V·T6 class).** Rationale: TIM1 6-PWM with break input, five ADCs for simultaneous phase-current sampling, three FDCAN, CORDIC, single-precision FPU. The **pin/resource check passed** against ST's own pin database (`STMicroelectronics/STM32_open_pin_data` @ `7d1f151`, BSD-3-Clause): all 27 peripheral-bound and 16 GPIO functions allocate with **34 spare I/O** (`docs/generated/pin_allocation.md`). LQFP64 also fits, but with **0 spare**. LQFP48/UFQFPN48 do **not** fit. Not checked: alternate-function numbers, ADC speed classes, internal OPAMP/COMP routing, errata ES0430 and the clock tree, because st.com was unreachable.
* **STSPIN32G4 evaluated once and not selected** (ADR-0002): single FDCAN, fewer ADC channels and I/O, 1 A gate drive (snippet data), and coupling of MCU and gate-driver failure modes in one package. It is retained as the fallback for a compact single-board revision. Not to be revisited without new requirements.
* **Gate-driver family: SPI-configurable three-phase smart gate driver** (DRV8353S/RS class) with VDS monitoring and three CSAs. The exact order code is **unfrozen**.

## 4. Control architecture (frozen conditional on C1)

* **Sensored FOC with hall sensors** (sector decode, period-based speed, intra-sector angle interpolation, sector-centre angle at standstill), `id_ref = 0`. MTPA is deferred because its value depends on saliency, which is unknown.
* **Current sampling:** three low-side shunts. A phase is "measured" only if its low-side window was valid this cycle. With exactly two measured phases, the third is **reconstructed and flagged**, and the KCL residual is **unavailable** (`mc_currents_resolve`).
* **Loops:** fast loop at PWM rate (single precision only — verified: `mc_core_fast_step` calls no soft-double routines on Cortex-M4F); slow loop at 1 kHz (protection, state machine, arbitration, freshness); CAN TX/RX tasks outside the current ISR.
* **Torque path:** owner request → (hardware trip / fault / not armed → 0 now) → (driver absent / brake / eco-cancel → 0 now) → static, battery-current, derate and speed limits → supervisor-declared bounds (ECO only) → slew → `iq_ref = T / Kt`. The supervisor can only ever *tighten* this path.

## 5. State machine (frozen)

States: `BOOT, SELF_TEST, DISARMED, READY, MANUAL, ECO_ASSIST, DERATED, FAULT_LATCHED`. Owner: `NONE` (BOOT, SELF_TEST, DISARMED, READY, FAULT_LATCHED), `DRIVER` (MANUAL, DERATED), `SUPERVISOR` (ECO_ASSIST).

Evaluation order on each slow tick: BOOT first, then latched faults (from any state), then armed-state exits (e-stop, arm switch), then state-specific transitions. "Released" means the throttle is valid and at or below `throttle_release_threshold`. "Engage" means the throttle is valid, the throttle latch is clear, and the throttle is at or above `throttle_engage_threshold`.

| ID | From → To | Guard | Side effects |
|---|---|---|---|
| T1 `BOOT_CONFIG_OK` | BOOT → SELF_TEST | calibration blob parsed, sim-valid; on a **hardware build** also hardware-valid, bench-measured, `physical_output_permitted` | — |
| T2 `BOOT_CONFIG_BAD` | BOOT → FAULT_LATCHED | otherwise | latch `CONFIG_INVALID` (never resettable) |
| T3 `SELFTEST_PASS` | SELF_TEST → DISARMED | ≥ 50 ms in SELF_TEST; driver ready, no driver fault, no watchdog fault, current offsets OK, Vbus valid and in [UV trip, OV trip], hall sector legal, both temperatures valid | arm needs a fresh OFF→ON edge |
| T4 `SELFTEST_FAIL` | SELF_TEST → FAULT_LATCHED | self-test complete and not passed | latch `SELFTEST` |
| T5 `ARM` | DISARMED → READY | arm-switch **OFF→ON edge observed after boot/disarm**, e-stop chain OK, throttle released, no active or latched faults, output permitted, no hardware trip | clear pending eco edge |
| T6 `MANUAL_ENGAGE` | READY → MANUAL | mode switch = manual, driver present, engage | — |
| T7 `ECO_ENGAGE` | READY/MANUAL → ECO_ASSIST | eco switch ON with an **edge pending**, supervisor OK (session established, request fresh, limits fresh, request references a held limits set), throttle released, no brake/cancel, driver present | consume eco edge |
| T8 `ECO_DRIVER_CANCEL` | ECO_ASSIST → READY | brake or cancel | torque 0 **now**; throttle latch set |
| T9 `ECO_DESELECT` | ECO_ASSIST → READY | eco switch OFF | throttle latch set |
| T10 `ECO_SUPERVISOR_LOST` | ECO_ASSIST → READY | supervisor not OK (stale, missing, repeated cached sample, invalid/NaN request, session change, unmatched limits, bus-off) | torque 0; **throttle latch set** (no jump to a held pedal) |
| T11 `DRIVER_TAKEOVER` | ECO_ASSIST → MANUAL | engage (pedal pressed after it was released at eco entry) | manual demand, slewed |
| T12 `DERATE` | READY/MANUAL/ECO_ASSIST → DERATED | derating active (thermal band, UV band, unknown temperature, or recovery hold) | from ECO: throttle latch set |
| T13 `DERATE_CLEAR` | DERATED → MANUAL | derate factor back to 1 and held 1 s | limit rises at the recovery rate |
| T14 `DISARM` | armed → DISARMED | arm switch OFF | needs a new OFF→ON edge |
| T15 `ESTOP` | armed → DISARMED | e-stop chain sense open | idem |
| T16 `FAULT` | any (except BOOT) → FAULT_LATCHED | any latched fault | torque and PWM off **now** |
| T17 `FAULT_RESET` | FAULT_LATCHED → DISARMED | local reset **edge**, throttle released, every latched condition gone, not `CONFIG_INVALID` | arm needs OFF→ON; eco edge cleared; throttle latch set |
| T18 `DRIVER_ABSENT` | MANUAL/ECO_ASSIST/DERATED → READY | dead-man released | torque 0 now; throttle latch set |

Invariants (each tested; see `firmware/tests/test_state_machine.c` and `test_core.c`):

* **I1** No torque in BOOT, SELF_TEST, DISARMED or FAULT_LATCHED.
* **I2** No arming through a reset with the switch held ON.
* **I3** Fault recovery lands in DISARMED and never resumes a previous command.
* **I4** Supervisor loss never jumps into a nonzero manual demand.
* **I5** Brake, cancel and driver-absent remove torque without a slew.
* **I6** Hardware trips and latched faults remove torque and PWM immediately.
* **I7** The supervisor cannot arm, reset faults or select a mode.

## 6. Interfaces (frozen)

* **CAN contract v1.0**: `protocol/protocol.yaml` with the generated C and Python codecs (`protocol/generated/`) and golden vectors. Changing a field's scale, offset, width or position requires a **major** version bump. The major version is part of every frame's CRC Data ID, so mixed-version nodes reject each other's frames.
* **Calibration blob v1**: `config/parameters.yaml` (registry), `tools/config_tool.py` (encoder and validator), `firmware/src/calibration/mc_config.c` (parser and validator). Rule codes are shared; parity is tested over 33 mutations × 2 modes.
* **Wired driver I/O**: throttle (two tracks), brake, eco cancel, mode switch, arm switch, fault reset, e-stop chain sense, dead-man sense. These are **never** CAN inputs (INTERFACE_CONTROL §3).
* **Host replay/log format**: semmc-log v1 (`host/logger/semmc_log.py`).

## 7. Explicitly UNFROZEN (must be decided from measurements; the hardware build refuses to proceed while they are null)

MOSFET voltage and current ratings and parallel count · gate-driver exact order code · shunt values and amplifier gains · DC-link capacitance · PCB copper and power-path dimensions · thermal solution · PWM frequency and dead time · current, torque and temperature thresholds · connector and fuse ratings · supervisory update rate and timeout (50 Hz / 100 ms is **provisional, simulation-only**) · coast mode (gate-off vs zero-current) · exact MCU order code and temperature grade.

## 8. Reopen triggers

Any assumption C1–C6 proven false · verified rules contradicting §2 · a measured worst-case bus transient above the gate driver's operating VM range · the pin check failing on AF/timing review · supervisory timing failing the hazard and latency analysis · CSIA evidence gate met (that would reopen D only through ADR-0008).

## 9. Decision log

`docs/decisions/ADR-0001` … `ADR-0010` (index in `docs/decisions/README.md`).
