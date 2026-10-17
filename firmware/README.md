# Motor-controller firmware (`firmware/`)

Portable C11 core of the motor controller, its public headers, a host platform with a simulated plant, notes for the future STM32G4 platform layer, and the C unit and property tests. The core contains the operating state machine, torque arbitration, field-oriented control (FOC), protection, energy accounting and the binding to CAN (Controller Area Network).

**Status:** only host builds and host simulations exist. Nothing in this directory has been built for, flashed to or tested on hardware. The STM32G4 platform layer is not implemented, so no embedded firmware image can be produced from this tree.

## 1. What the directory contains and what the core does

```
firmware/
  CMakeLists.txt            build: portable core library, host tools, calibration blobs, tests
  cmake/                    toolchain file for the Cortex-M4F portability compile
  include/semmc/            public headers of the core (one generated)
  src/                      portable core: no I/O (input/output), no dynamic allocation
    core/                   mc_core.c: wiring of every subsystem, slow and fast steps
    state_machine/          operating state machine and torque arbiter
    telemetry/              freshness, sequencing and time handling for received data
    control/                FOC current loop, PI controller, transforms, Hall decoding
    protection/             software fault detection, latching and derating
    calibration/            calibration blob parser and validator, CRC helpers
    transport/              CAN binding of the transport-neutral message interface
    csia_adapter/           tracking of CSIA advisories (experimental sensor-consistency
                            diagnostic, see the root README), shadow mode only
  platform/host/            host-only executables and the simulated plant
  platform/stm32g4/         integration notes only (README.md); no code
  tests/                    C unit tests and the randomised property test
```

The core runs one motor. It is plain C11 with single-precision floating point in the control paths (the build uses `-Wdouble-promotion` and `-Werror`), and it never allocates memory, blocks, formats text or performs I/O. The platform calls five entry points (`include/semmc/mc_core.h`):

| Call | Where the platform calls it | Purpose |
|---|---|---|
| `mc_core_init()` | once at boot, with the calibration blob | parse and validate the calibration; returns false if it was rejected |
| `mc_core_slow_step()` | at the supervisory rate (1 kHz in every host tool) | measurements, energy, protection, supervisor input, state machine, arbitration |
| `mc_core_fast_step()` | in the current-control interrupt, at the PWM (pulse-width modulation) rate | Hall angle, phase currents, software overcurrent, FOC current loop, duties |
| `mc_core_on_can_rx()` / `mc_core_on_msg_rx()` | from the link receive task, not from the current interrupt | received protocol messages |
| `mc_core_can_tx_poll()` / `mc_core_msg_tx_poll()` | from the link transmit task | at most one due controller message per call |

The slow step hands its result to the fast step through one struct, `mc_fast_cmd_t` (PWM enable, `id_ref_A`, `iq_ref_A`). The host build is single-threaded; on the target this copy needs a sequence lock or a masked interrupt (`mc_core.h`, [platform/stm32g4/README.md](platform/stm32g4/README.md)).

### 1.1 Operating state machine

`src/state_machine/mc_state_machine.c` implements eight states (`BOOT`, `SELF_TEST`, `DISARMED`, `READY`, `MANUAL`, `ECO_ASSIST`, `DERATED`, `FAULT_LATCHED`) and 18 numbered transitions (`MC_T_*`). It decides who owns the torque request: nobody, the driver (`MANUAL`, `DERATED`) or the supervisor (`ECO_ASSIST`, the supervised eco-assist mode). Arming, mode selection and fault reset come only from wired driver inputs, never from CAN. Section 4 lists every state and transition.

### 1.2 Torque arbitration: layers and ceilings

`src/state_machine/mc_arbiter.c` (`mc_arb_step`) turns the owner's request into an accepted torque and a current reference. The layers, highest precedence first, are named in the code as follows (the project documents, including architecture decision record ADR-0011, call this the four-layer control contract; the code numbers the layers L0 to L4). `Vbus` is the measured direct-current bus voltage.

| Layer | What the code does | Reason bits set |
|---|---|---|
| L0 independent hardware shutdown | if the hardware-trip input is set, accepted torque, `iq_ref` and PWM enable are zero on this update | `MC_R_HW_TRIP` |
| L1 immediate inhibits | latched fault or `FAULT_LATCHED`; state not `MANUAL`, `ECO_ASSIST` or `DERATED`; driver absent; brake; ECO cancel. Output zero on this update, no slew | `MC_R_FAULT_INHIBIT`, `MC_R_NOT_ARMED`, `MC_R_DRIVER_ABSENT`, `MC_R_BRAKE_OVERRIDE`, `MC_R_CANCEL_OVERRIDE` |
| L2 local hard ceiling | minimum of: static limit `min(max_motor_torque_Nm, Kt x max_phase_current_A)`; battery feed-forward `min_efficiency_for_limit x Vbus x battery_current_limit_A / w` (only with a usable speed above 1 rad/s); static limit x closed-loop battery scale (the scale falls by 0.5 per ampere of measured excess per second and recovers at 0.5 per second); static limit x protection derate factor; static limit x speed taper (linear from `speed_taper_start_rad_s` to zero at `overspeed_trip_rad_s`). Applied on the same update, no ramp, and applied again as the last statement | `MC_R_CLAMP_TORQUE`, `MC_R_CLAMP_BATTERY`, `MC_R_CLAMP_DERATE`, `MC_R_CLAMP_SPEED` |
| L3 supervisory envelope (`ECO_ASSIST` only) | `max_torque_Nm` from the supervisor, tightened by `max_batt_power_W x min_efficiency_for_limit / w`. Output above the envelope falls at least at `torque_slew_down_fast_Nm_s`. A coast request sets the target to zero | `MC_R_SUPERVISOR_BOUND`, `MC_R_COAST` |
| L4 owner request with comfort slew | `MANUAL`/`DERATED`: throttle x `manual_max_torque_Nm`; `ECO_ASSIST`: supervisor torque request. Slewed at `torque_slew_up_Nm_s` / `torque_slew_down_Nm_s` | `MC_R_SLEW`, `MC_R_THROTTLE_LATCH`, `MC_R_SUPERVISOR_INVALID`, `MC_R_REGEN_DISABLED` |

`Kt` is the torque constant, derived as `1.5 x pole_pairs x flux_linkage_Wb`, and `w` is the absolute mechanical speed. The target is clamped to `[0, hard ceiling]`, so the arbiter never produces negative (regenerative) torque. The current reference is `iq_ref = accepted / Kt`, clamped to `max_phase_current_A`, and `id_ref = 0` (surface permanent-magnet assumption; MTPA, maximum torque per ampere, is deferred). With `coast_mode = gate_off`, PWM is disabled whenever both the accepted torque and the target are zero. Nothing the supervisor sends can raise the L2 ceiling. The full contract is in [../docs/CONTROL_CONTRACT.md](../docs/CONTROL_CONTRACT.md).

### 1.3 Supervisor requests: session and freshness rules

Supervisor messages are handled in `mc_core_on_msg_rx()` (`src/core/mc_core.c`) with the trackers of `src/telemetry/mc_freshness.c`:

* **Session.** A valid `sup_hello` (its CRC, the cyclic redundancy check, passes; its protocol major version matches; its role is 1) from a new companion session, or while no tag is held, resets the supervisor session and issues a new non-zero 8-bit session tag, `1 + (offset(boot_id) + tags issued) mod 255`. The count of issued tags survives session resets, so 255 consecutive sessions of one boot get distinct tags. The tag is announced in `ctrl_session`.
* **Tag check.** `sup_limits` and `sup_torque_req` must carry the current tag; any other tag is dropped and counted (`rx_tag_mismatch`). The session is established once both a limits frame and a request frame with the tag have been accepted.
* **New sample only.** The request tracker renews validity only for a frame that is not an exact re-delivery of the last frame seen, whose u8 (unsigned 8-bit) sequence number is newer than every frame seen within the freshness window, whose u16 (unsigned 16-bit, milliseconds) source time (`src_time_ms`) advanced, and whose timing lag against the controller's own clock stays within 100 ms (`MC_REQ_TIME_SKEW_MS`, with a 2 % drift allowance). Duplicates, reordered frames, re-sent cached samples and time jumps never renew validity. The limits tracker uses the sequence number only.
* **Windows.** A request is fresh for `supervision.timeout_s` after its last new sample, a limits set for `supervision.limits_timeout_s` (calibration values; synthetic: 0.10 s and 0.5 s).
* **Content.** A request carrying the invalid sentinel (NaN, not a number) or an out-of-range torque marks the supervisor input INVALID; it is never read as zero torque. Limits frames with out-of-range fields are dropped.
* **Limits sets.** The controller holds two sets, `lim[0]` (newest) and `lim[1]` (previous). A new `limits_seq` shifts the newest set to `lim[1]`; a re-send of the same `limits_seq` refreshes it in place. A request must reference a held set (`limits_ref`, low 4 bits of `limits_seq`), and the envelope applied is `min(newest, referenced)`.
* **Supervisor OK** (`mc_supervisor_ok`): session established and link up, request and limits validity both exactly zero (not missing, stale, invalid or session-new), the request references a held set, and all values finite. `ECO_ASSIST` is entered and kept only while this holds.
* **Link loss.** A bus-off report (`mc_core_on_can_bus_off`) resets the session at once; `ECO_ASSIST` exits on the next slow step and re-entry needs a new hello, a re-established session and a new driver mode-switch edge.

### 1.4 Field-oriented control (FOC)

The fast step (`mc_core_fast_step`) does, in order:

1. Hall decoding (`src/control/mc_hall.c`): sector from a calibrated code-to-sector table, signed speed from the last full sector period (decaying toward zero while the current sector lasts longer, zero after 0.25 s without an edge), angle interpolated inside the sector and clamped to it; at standstill the sector centre is used, which the code comment gives as an error of up to 30 electrical degrees either way. Three consecutive illegal codes or three consecutive non-adjacent sector jumps set the Hall invalid flag.
2. Phase-current resolution (`mc_currents_resolve`, `src/control/mc_transforms.c`): a phase counts as measured only if the platform marked it valid this cycle and its value is finite. With three measured phases the KCL (Kirchhoff's current law) residual is available; with exactly two the third is reconstructed and flagged; with fewer the sample is invalid.
3. Software overcurrent: any phase (measured or reconstructed) above `software_overcurrent_A` disables the outputs in this interrupt; the fault latches in the next slow step.
4. Current loop (`src/control/mc_foc.c`): amplitude-invariant Clarke and Park transforms into the rotor d (direct, flux) and q (quadrature, torque) axes, two PI (proportional-integral) controllers with conditional-integration anti-windup (`src/control/mc_pi.c`), cross-coupling and back-EMF (electromotive force) feed-forward, a voltage limit of `voltage_limit_fraction x Vbus / sqrt(3)` with d-axis priority, inverse Park, and space-vector PWM (SVPWM) by min-max zero-sequence injection with duties clamped to `[duty_min, duty_max]`.

The loop is inhibited (PWM off, duties 0.5) when the calibration was rejected, the handoff disables PWM, the measured time step `dt` since the previous fast step is not finite or not in `(0, 5 / pwm_frequency_Hz]`, the hardware-trip line is set, the software overcurrent flag is set, fewer than two phases are valid, or any FOC input is non-finite. The PI integrators are reset whenever the output is off and when it is re-enabled.

### 1.5 Protection

`src/protection/mc_protection.c` is the software layer. The header states that it is not the primary protection: independent hardware (overcurrent comparator or gate-driver monitor, overvoltage comparator, external watchdog, emergency-stop (e-stop) isolation) must act without it, and the platform reports those trips so software state follows hardware state. Every slow step (with a valid calibration) evaluates 16 conditions; `MC_F_CONFIG_INVALID` and `MC_F_SELFTEST` are latched by the state machine instead:

| Fault (`mc_fault_t`) | Condition in the code |
|---|---|
| `HW_OVERCURRENT`, `HW_OVERVOLTAGE`, `GATE_DRIVER`, `WATCHDOG` | platform flags in `mc_slow_inputs_t` |
| `SW_OVERCURRENT`, `CONTROL_DT_INVALID` | set by the fast step, consumed by the next slow step |
| `BUS_OVERVOLTAGE` | Vbus above `overvoltage_trip_V` |
| `BUS_UNDERVOLTAGE` | Vbus below `undervoltage_trip_V` for 0.1 s (`MC_UV_TRIP_DEBOUNCE_S`) |
| `VBUS_SENSE_INVALID` | Vbus measurement not usable or not finite |
| `FET_OVERTEMP`, `MOTOR_OVERTEMP` | temperature at or above its trip value |
| `OVERSPEED` | absolute mechanical speed above `overspeed_trip_rad_s` |
| `HALL_INVALID` | Hall invalid flag (section 1.4) |
| `CURRENT_SENSE_INVALID` | 3 consecutive fast steps with PWM commanded but fewer than two valid phases |
| `THROTTLE_IMPLAUSIBLE` | `throttle_valid` false |
| `ROTOR_STALL` | PWM enabled, measured `|iq|` above 0.3 x `max_phase_current_A`, and no Hall edge for 1.0 s |

All faults latch until a local fault reset. `mc_prot_try_reset()` clears only latched faults whose condition is no longer active and never clears `CONFIG_INVALID`. Derating is not a fault: the factor is the minimum of the FET (field-effect transistor, the power-stage switches) and motor temperature ramps (derate start to trip), the undervoltage ramp (`undervoltage_trip_V` to `undervoltage_derate_V`), and `unknown_temperature_derate_factor` when a temperature is not usable. It drops at once, recovers at 0.2 per second, and derating counts as active until the factor has been back at 1 for 1 s.

### 1.6 Energy integration with gap accounting

Each slow step computes the battery power at the controller's bus-current measurement, `p_batt_W = vbus_V x ibatt_A`, when both values are usable, and NaN otherwise. The interval since the previous slow step is added to `energy_J` and `energy_integrated_s` only if the power is usable and the interval is at most 20 ms (`MC_ENERGY_MAX_DT_S`); every other interval is added to `energy_gap_s`. Energy is never interpolated across a gap. `energy_J` is sent in `ctrl_energy`, the two time totals in `ctrl_energy_quality`; the energy value is complete only while the gap total is zero.

### 1.7 Transport binding to CAN

The core itself is transport-neutral: it exchanges 8-byte messages identified by the protocol's canonical message numbers `0x300` to `0x33F` (`MC_PROTO_MSG_FIRST`, `MC_PROTO_MSG_SPAN`). Each payload carries its own CRC over a per-message data ID and a sequence counter, so integrity does not depend on transport addressing. `src/transport/mc_can_binding.c` is the only binding implemented:

* 11-bit identifier = `supervision.can_id_base + (message number - 0x300)`; the base must be a multiple of 0x40 (validator rule 40), so the whole block fits one acceptance filter (`mc_can_id_base()`, mask 0x7C0 per the STM32G4 notes). With a rejected calibration the protocol default 0x300 is used.
* Frames outside the block are counted as `rx_unknown`; the platform must filter extended and remote frames before calling the binding.
* `mc_core_on_can_bus_off()` reports the link state; while the link is down nothing is transmitted and the supervisor session is reset.
* Transmission is polled: `mc_core_msg_tx_poll()` walks the controller messages in ascending number (priority) order and returns the first one that is due or forced.

### 1.8 Calibration and CSIA

* `src/calibration/mc_config.c` parses the calibration blob produced by `tools/config_tool.py`, validates it with the same rule codes as the Python validator, and derives the typed parameters (`mc_params_t`). Missing values are never defaulted. `mc_config_permits_physical_output()` is the only gate for a physical output: a hardware build, a clean hardware-mode validation, `bench_measured` provenance and `physical_output_permitted` all required. A host build always gets a virtual output only.
* `src/csia_adapter/mc_csia_shadow.c` tracks `csia_advisory` frames from CSIA (the project's experimental sensor-consistency diagnostic, see the root README) for freshness and stores their content. `mc_csia_may_restrict()` returns false unconditionally (shadow mode, ADR-0008); no torque command depends on CSIA.

## 2. Who works here

Motor-control firmware developers: anyone changing the control core, protection, state machine, arbitration, supervisor handling or CAN binding, writing the STM32G4 platform layer, or extending the C tests. The interface control document ([../docs/ICD.md](../docs/ICD.md)) names the controls lead as owner of controller behaviour and of the protocol. Protocol changes are made in `protocol/protocol.yaml` and calibration parameters in `config/parameters.yaml`, then regenerated (section 8); neither is edited in this directory.

## 3. Important files

| File | What it does in the system | Inputs | Outputs |
|---|---|---|---|
| [`src/core/mc_core.c`](src/core/mc_core.c) | Central module. At boot it parses and validates the calibration and decides whether output is permitted. Each slow step it checks measurement finiteness, integrates energy with gap accounting, detects rotor stall, runs protection, builds the supervisor input from the session and freshness state (including the `min(newest, referenced)` envelope), runs the state machine and the arbiter, and writes the slow-to-fast handoff. Each fast step it runs Hall decoding, current resolution, the software overcurrent check and the FOC loop. On receive it decodes supervisor frames with the generated codec and rejects bad CRCs, wrong tags and frames that are not new samples. On transmit it schedules and encodes the 12 controller messages. | calibration blob, build kind, boot id; `mc_slow_inputs_t`; `mc_fast_inputs_t`; received messages; link state | PWM enable and duties (`mc_fast_outputs_t`); encoded controller messages; state, counters and energy totals in `mc_core_t` |
| [`src/state_machine/mc_state_machine.c`](src/state_machine/mc_state_machine.c) | Decides the operating state and the torque owner from the wired controls, the supervisor status and the fault state. Detects arm-switch, mode-switch and fault-reset edges and keeps the throttle latch, so a switch or pedal held through a reset or a mode change never produces torque. | driver inputs, `mc_supervisor_input_t`, protection state, `mc_sm_aux_t` (config OK, self-test result, output permitted, hardware trip) | state, owner and transition id; latches `CONFIG_INVALID` and `SELFTEST` |
| [`src/state_machine/mc_arbiter.c`](src/state_machine/mc_arbiter.c) | Applies layers L0 to L4 to the owner's request and produces the accepted torque and current reference, with a reason bit for every limit that acted. | state and throttle latch, driver inputs, supervisor request and envelope, Vbus, battery current and speed with validity, derate factor and latched faults, hardware trip, `dt` | `accepted_Nm`, `iq_ref_A`, `id_ref_A`, PWM enable, 16 reason bits, `hard_ceiling_Nm`, `envelope_Nm` |
| [`src/telemetry/mc_freshness.c`](src/telemetry/mc_freshness.c) | Decides whether a received frame is a new sample. Rejects duplicates, reordered frames, cached samples whose source time did not advance, clock-domain mismatches and delayed or jumped source times (telescoping lag with candidate re-anchoring); handles u8/u16 wraparound and source reboots. Also extends a 32-bit hardware timer to 64 bits (`mc_time_extend`). | per frame: session id, clock domain, sequence, source time, local receive time | result code (`MC_RX_*`), validity bits `MISSING`/`STALE`/`SESSION_NEW`, saturating counters |
| [`src/control/mc_foc.c`](src/control/mc_foc.c) | One FOC current-loop update: measured currents to dq, PI with feed-forward, voltage limit, SVPWM duties. Inhibits on invalid inputs or a rejected time step. | dq current reference, sin and cos of the Hall angle, electrical speed, Vbus, `dt`, resolved phase currents | measured `id`/`iq`, limited dq voltage, three duties, inhibit flag |
| [`src/control/mc_hall.c`](src/control/mc_hall.c) | Rotor position from three Hall sensors: sector, direction, period-based speed and intra-sector angle. Treats standstill, low speed and reversal as normal; only persistent illegal codes or sector skips are faults. | 3-bit Hall code (bit 0 = A), `dt`, code-to-sector table, angle offset | electrical angle in `[0, 2 pi)`, signed electrical speed, time since edge, invalid flag |
| [`src/protection/mc_protection.c`](src/protection/mc_protection.c) | Software fault detection and latching, derating with fast drop and slow recovery, fault reset, speed-taper factor for the arbiter. | `mc_prot_inputs_t` (hardware flags, fast-loop trips, Vbus, temperatures with validity, speed, Hall and current-sense status, throttle validity, stall) | active and latched fault bits, first fault, fault count, derate factor and reasons |
| [`src/calibration/mc_config.c`](src/calibration/mc_config.c) | Accepts or rejects the whole calibration blob (magic, format version, length, CRC-32, known ids, kinds, duplicates), runs per-parameter and cross-parameter rules with codes shared with `tools/config_tool.py`, derives typed parameters, and gates physical output. Runs at boot only, in double precision for parity with Python. | blob bytes, validation mode (`sim` or `hw`) | `mc_config_t`, `mc_cfg_report_t` (rule code and parameter id per issue), `mc_params_t`, output-permit decision |
| [`src/transport/mc_can_binding.c`](src/transport/mc_can_binding.c) | Places the 64 protocol numbers at the calibrated 11-bit CAN identifier block and forwards bus-off reports. | CAN identifier and payload, bus-off flag | calls into the core's message interface; CAN identifier of each transmitted message |
| [`src/csia_adapter/mc_csia_shadow.c`](src/csia_adapter/mc_csia_shadow.c) | Tracks CSIA advisories in shadow mode: freshness separate from content, counts senders that claim a restricting mode. | decoded `csia_advisory` fields, sequence, source time | stored advisory, validity, counters; `mc_csia_may_restrict()` always false |
| [`include/semmc/mc_params_generated.h`](include/semmc/mc_params_generated.h) | Generated parameter registry: blob element ids (`MC_P_*`), enumerations, and the table of kinds, required flags and ranges that the C validator checks. Do not edit (section 8). | `config/parameters.yaml` via `tools/gen_config.py` | compiled into `mc_config.c` |
| [`platform/host/host_main.c`](platform/host/host_main.c) | `semmc_host`: runs the core against the simulated plant (or replayed measurements with `--no-plant`), from an event log or interactively in lockstep with a Python supervisor. Used by the Python co-simulation, replay and host demonstration. | calibration blob, `semmc-log v1` events (driver IO, CAN frames, hardware flags, faults, bus-off, reset) | CSV (comma-separated values) trace per slow step, transmitted CAN frames, per-step state lines |
| [`platform/host/sim_plant.c`](platform/host/sim_plant.c) | Host-only synthetic plant: PMSM (permanent-magnet synchronous motor) in dq with averaged inverter, vehicle road load, battery, thermal models, noisy sensors with low-side shunt windows, fault injection. Not a validated model. | duties and PWM enable, `mc_params_t`, fault settings | phase currents with valid mask, Hall code, Vbus, battery current, temperatures, vehicle speed and energy |
| [`platform/host/contract_report_main.c`](platform/host/contract_report_main.c) | `semmc_contract_report`: drives the arbiter and the full core through the control-contract scenarios A1 to A6 and B1 to B4 and checks every update against an independent oracle. | synthetic calibration blob | CSV rows and per-scenario summaries (violations, settle time) on stdout |
| [`platform/host/cfgcheck_main.c`](platform/host/cfgcheck_main.c) | `semmc_cfgcheck`: runs the C validator on a blob so the Python parity test can compare rule codes. | blob path, `sim` or `hw` | `CODES <code>:<param_id> ...` line, hardware-permit line, exit 0/1/2 |
| [`CMakeLists.txt`](CMakeLists.txt) | Builds `semmc_core`, the host tools and tests, encodes the calibration blobs, registers the tests, and refuses a hardware build. | options `SEMMC_HARDWARE_BUILD`, `SEMMC_SANITIZE`, `SEMMC_PORTABLE_ONLY`, `SEMMC_VEHICLE_CONFIG` | library, executables, `cal/*.bin`, ctest entries |

Other files:

* `include/semmc/`: one public header per module. `mc_core.h` (entry points, input and output structs, CAN binding API), `mc_types.h` (validity flags and sign conventions), `mc_state_machine.h` (states, transitions, reason bits, invariants I1 to I9), `mc_control.h` (transform conventions, PI, FOC, Hall), `mc_freshness.h` (freshness rules in full), `mc_protection.h` (fault list, derate constants), `mc_config.h` (blob format v1, rule codes, `mc_params_t`), `mc_crc.h`, `mc_csia_shadow.h`.
* `src/control/mc_pi.c` (PI controller, `mc_slew`, `mc_wrap_2pi`), `src/control/mc_transforms.c` (Clarke, Park, current resolution, voltage and current limits, SVPWM), `src/calibration/mc_crc.c` (CRC-8/SAE-J1850 and CRC-32), `platform/host/sim_plant.h`.
* `cmake/arm-none-eabi-cortex-m4f.cmake`: toolchain file for the portability compile (section 7.3).
* `tests/`: `test_control.c` (transforms, PI, limits, SVPWM, Hall), `test_freshness.c`, `test_config.c` (blob parsing, CRC check values, rule violations), `test_state_machine.c` (state machine invariants and arbiter contract), `test_protocol.c` (golden vectors, malformed frames), `test_core.c` (core with codec and simulated plant), `test_core_properties.c` (randomised property test), `mc_test.h` (minimal check harness), `test_support.h` (blob loading).

## 4. State machine

Source: `src/state_machine/mc_state_machine.c`, `include/semmc/mc_state_machine.h`; frozen description in [../docs/ARCHITECTURE_FREEZE.md](../docs/ARCHITECTURE_FREEZE.md) section 5.

**States and owners**

| State | Owner | Torque |
|---|---|---|
| `BOOT` | none | zero |
| `SELF_TEST` | none | zero |
| `DISARMED` | none | zero |
| `READY` | none | zero (armed, waiting for a mode) |
| `MANUAL` | driver | throttle x `manual_max_torque_Nm`, bounded |
| `ECO_ASSIST` | supervisor | supervisor request, bounded by L2 and L3 |
| `DERATED` | driver | throttle request, bounded by the derated ceiling |
| `FAULT_LATCHED` | none | zero, PWM off |

**Definitions used below**

* *released*: throttle valid and at or below `throttle_release_threshold`; this also clears the throttle latch.
* *engage*: throttle valid, throttle latch clear, throttle at or above `throttle_engage_threshold`.
* *arm edge*: arm switch ON now, OFF in the previous step, and seen OFF since boot or since the last entry to `DISARMED`/`FAULT_LATCHED`. At init the previous arm, mode and reset inputs are taken as ON, so a switch held ON through a reset gives no edge.
* *eco edge pending*: set on a mode-switch OFF to ON edge; cleared when the switch is OFF, on arming, on entry to `DISARMED` or `FAULT_LATCHED`, and when consumed by an ECO entry.
* *eco_ok*: mode switch ECO, eco edge pending, supervisor OK (section 1.3), released, no brake, no cancel, driver present.
* *derating*: `mc_prot_derating()` true (section 1.5).

**Evaluation order in each slow step:** `BOOT` first; then any latched fault moves every other state except `FAULT_LATCHED` to `FAULT_LATCHED`; then, in the armed states (`READY`, `MANUAL`, `ECO_ASSIST`, `DERATED`), e-stop chain open and arm switch OFF; then the state-specific rows below, in the order listed. At most one transition is taken per step.

| Id | From → to | Condition as implemented | Side effect |
|---|---|---|---|
| T1 `BOOT_CONFIG_OK` | `BOOT` → `SELF_TEST` | calibration accepted (on a hardware build also permitted for physical output) | |
| T2 `BOOT_CONFIG_BAD` | `BOOT` → `FAULT_LATCHED` | otherwise | latch `CONFIG_INVALID` (never resettable) |
| T16 `FAULT` | any except `BOOT`, `FAULT_LATCHED` → `FAULT_LATCHED` | any latched fault | |
| T15 `ESTOP` | armed → `DISARMED` | `estop_chain_ok` false | |
| T14 `DISARM` | armed → `DISARMED` | arm switch OFF | |
| T3 `SELFTEST_PASS` | `SELF_TEST` → `DISARMED` | at least 50 ms in `SELF_TEST` (`MC_SELFTEST_MIN_S`) and: gate driver ready, no gate-driver or watchdog fault, current offsets OK, Vbus usable and within `[undervoltage_trip_V, overvoltage_trip_V]`, Hall sector known and Hall not invalid, both temperatures usable | |
| T4 `SELFTEST_FAIL` | `SELF_TEST` → `FAULT_LATCHED` | at least 50 ms and any of the above false | latch `SELFTEST` |
| T5 `ARM` | `DISARMED` → `READY` | arm edge, e-stop chain OK, released, no latched and no active fault, output permitted, no hardware trip | clear pending eco edge |
| T12 `DERATE` | `READY` → `DERATED` | derating | |
| T7 `ECO_ENGAGE` | `READY` → `ECO_ASSIST` | eco_ok | consume eco edge |
| T6 `MANUAL_ENGAGE` | `READY` → `MANUAL` | mode switch manual, driver present, engage | |
| T18 `DRIVER_ABSENT` | `MANUAL` → `READY` | `driver_present` false | set throttle latch |
| T12 `DERATE` | `MANUAL` → `DERATED` | derating | |
| T7 `ECO_ENGAGE` | `MANUAL` → `ECO_ASSIST` | eco_ok | consume eco edge |
| T18 `DRIVER_ABSENT` | `ECO_ASSIST` → `READY` | `driver_present` false | set throttle latch |
| T8 `ECO_DRIVER_CANCEL` | `ECO_ASSIST` → `READY` | brake or cancel | set throttle latch |
| T9 `ECO_DESELECT` | `ECO_ASSIST` → `READY` | mode switch manual | set throttle latch |
| T10 `ECO_SUPERVISOR_LOST` | `ECO_ASSIST` → `READY` | supervisor not OK (stale, missing, repeated cached sample, invalid or NaN request, unmatched limits reference, session reset, bus-off) | set throttle latch |
| T12 `DERATE` | `ECO_ASSIST` → `DERATED` | derating | set throttle latch |
| T11 `DRIVER_TAKEOVER` | `ECO_ASSIST` → `MANUAL` | engage | |
| T18 `DRIVER_ABSENT` | `DERATED` → `READY` | `driver_present` false | set throttle latch |
| T13 `DERATE_CLEAR` | `DERATED` → `MANUAL` | not derating (factor back at 1 and held 1 s) | |
| T17 `FAULT_RESET` | `FAULT_LATCHED` → `DISARMED` | fault-reset rising edge, released, and `mc_prot_try_reset()` leaves nothing latched | |

Entering `DISARMED` or `FAULT_LATCHED` always clears the arm-seen-OFF flag and the pending eco edge and sets the throttle latch, so re-arming needs a new arm edge and ECO needs a new mode-switch edge. The transition id is reported in `ctrl_status.last_transition`. The arbiter adds the immediate inhibits of L1 on top of the state, so a brake, cancel or driver-absent input gives zero torque in the same slow step in which it is sampled.

**Provisional:** the supervision windows that drive T7 and T10 are calibration values; the synthetic configuration sets `supervision.timing_status: provisional_simulation_only` with a 20 ms update period and a 100 ms timeout marked "PROVISIONAL ... simulation only", and the hardware validator rejects that status (rule 29). The 100 ms lag tolerance and the request and limits windows are marked PROV (provisional) in the ICD. The 50 ms self-test minimum, 0.1 s undervoltage debounce, 1 s derate-clear hold, 0.2 per second derate recovery, 1 s stall time and 0.25 s Hall timeout are compile-time constants that have not been checked on hardware.

## 5. Inputs and outputs of the core

Message layouts, scaling and periods: [../protocol/README.md](../protocol/README.md), [../docs/generated/can_messages.md](../docs/generated/can_messages.md) (generated from [../protocol/protocol.yaml](../protocol/protocol.yaml)). Interfaces between nodes, timestamps, session handshake and protection boundaries: [../docs/ICD.md](../docs/ICD.md).

Sign conventions (`mc_types.h`): battery current positive for discharge, phase current positive into the motor terminal, torque positive for forward motoring, angles in electrical radians of the rotor d-axis from the phase-a axis.

### 5.1 Wired driver inputs (`mc_driver_inputs_t`, sampled by the platform for each slow step)

| Field | Meaning in the core |
|---|---|
| `throttle`, `throttle_valid` | demand 0 to 1; `throttle_valid` false latches `THROTTLE_IMPLAUSIBLE` |
| `brake`, `cancel` | immediate zero torque; brake in any torque state, cancel in `ECO_ASSIST`; both exit ECO |
| `mode_eco` | mode switch; its OFF to ON edge is needed for every ECO entry |
| `arm_switch` | OFF to ON edge arms; OFF disarms |
| `fault_reset` | rising edge requests a fault reset |
| `estop_chain_ok` | sense of the independent e-stop chain; open disarms |
| `driver_present` | dead-man sense; false gives immediate zero torque and leaves `MANUAL`, `ECO_ASSIST` and `DERATED` |

None of these can be set over CAN; the last sampled values are echoed in `driver_controls` (0x312).

### 5.2 Measurements and platform status

| Struct | Fields |
|---|---|
| `mc_slow_inputs_t` (each slow step) | hardware flags `hw_overcurrent`, `hw_overvoltage`, `gate_driver_fault`, `gate_driver_ready`, `watchdog_fault`; `vbus_V`, `ibatt_A` (independent bus-current meter, positive for discharge), `t_fet_degC`, `t_motor_degC`, each with a validity word (`mc_validity_t`, 0 = valid); `current_offsets_ok` (zero-current ADC (analog-to-digital converter) offsets within tolerance, for the self-test); `reset_reason` |
| `mc_fast_inputs_t` (each fast step) | `phase` (calibrated phase currents in amperes and the mask of phases sampled in a valid low-side window), `hall_code`, `vbus_V`, measured `dt`, `hw_trip` (independent hardware trip line) |

The core expects engineering units: ADC counts are converted by the platform layer. A hardware trip from any of `hw_overcurrent`, `hw_overvoltage` or `gate_driver_fault` zeroes the output in the slow step; `hw_trip` does so in the fast step.

### 5.3 Outputs to the power stage

`mc_fast_outputs_t`: `pwm_enable` and three duties in `[duty_min, duty_max]`. When the output is disabled the duties are 0.5 and `pwm_enable` is false. On a host build no physical output exists; the host tools feed the duties to the simulated plant.

### 5.4 CAN messages consumed (supervisor and companion to controller)

| Message | Number | Nominal sender period | Use in the core |
|---|---|---|---|
| `sup_torque_req` | 0x308 | 20 ms (marked PROVISIONAL in the protocol) | torque request, coast request, `limits_ref`, source time; freshness with source-time checks |
| `sup_limits` | 0x309 | 100 ms | supervisory envelope (`max_torque_Nm`, `max_batt_power_W`), `limits_seq`; sequence-only freshness |
| `sup_hello` | 0x30A | 500 ms | companion session announcement; starts a new session and tag |
| `csia_advisory` | 0x328 | 100 ms | shadow tracking only |

Any other number in the block, including the controller's own transmit numbers, is counted as `rx_unknown`.

### 5.5 CAN messages produced (controller to bus)

| Message | Number | Period | Sent early when | Content |
|---|---|---|---|---|
| `ctrl_fault` | 0x300 | 1 s | a transition enters or leaves `FAULT_LATCHED` | latched fault bits, first fault, reset reason, fault count |
| `ctrl_status` | 0x310 | 20 ms | any state transition | state, owner, supervisor link (none, hello, established, lost), session tag, boot id, build kind, calibration provenance, output permitted, PWM enabled, derating, hardware trip, last transition |
| `ctrl_cmd_trace` | 0x311 | 20 ms | | requested and accepted torque, reason bits |
| `driver_controls` | 0x312 | 20 ms | | echo of the wired driver inputs (throttle NaN when invalid) |
| `ctrl_session` | 0x313 | 500 ms | a new tag is issued | session tag, echoed companion session, protocol version |
| `ctrl_motion` | 0x318 | 10 ms | | speed, measured `iq`, Vbus (NaN unless usable) |
| `ctrl_currents` | 0x319 | 10 ms | | measured `id`, battery current, measured and reconstructed phase masks, KCL availability and residual |
| `ctrl_energy` | 0x320 | 100 ms | | `energy_J`, battery power |
| `ctrl_thermal` | 0x321 | 100 ms | | FET and motor temperature (NaN unless usable), derate factor and reasons |
| `ctrl_validity` | 0x322 | 100 ms | | 4-bit validity per measurement: 1 missing, 2 stale, 4 invalid, 8 saturated (a reconstructed phase reads 0 here; the masks are in `ctrl_currents`) |
| `ctrl_energy_quality` | 0x323 | 100 ms | | seconds integrated, seconds of gap |
| `ctrl_identity` | 0x330 | 1 s | | protocol, firmware (0.1) and calibration versions, provenance, build kind, hardware revision (always 0 in this code) |

Every message is also sent once in the first polls after `mc_core_init()`. Measurements that do not exist yet or are not usable are sent as NaN, never as zero. The numbers above are protocol numbers; on the bus each is offset by `can_id_base - 0x300`.

## 6. Dependencies on other directories

| Directory or file | What the firmware takes from it |
|---|---|
| [`../protocol/generated/`](../protocol/generated/) | `semmc_protocol.c` / `.h` (generated C codec, compiled into `semmc_core` directly from that directory) and `semmc_golden_vectors.c` (linked into `test_protocol`). Source of truth: [`../protocol/protocol.yaml`](../protocol/protocol.yaml) |
| [`../tools/config_tool.py`](../tools/config_tool.py) | encodes the calibration blobs at build time (`blob ... --mode sim`) and validates `SEMMC_VEHICLE_CONFIG` in hardware mode when `SEMMC_HARDWARE_BUILD=ON`. Its rule codes must match `mc_config.c`; `tests/integration/test_config_parity.py` compares the two through `semmc_cfgcheck` |
| [`../config/`](../config/) | `parameters.yaml` (registry behind `mc_params_generated.h` and both validators), `vehicle.synthetic.yaml` (test blob), `vehicle.unconfigured.yaml` (blob that must be rejected; default hardware config) |
| [`../tools/gen_config.py`](../tools/gen_config.py), [`../tools/gen_protocol.py`](../tools/gen_protocol.py) | generators of `mc_params_generated.h` and of the protocol codec (section 8) |
| [`platform/stm32g4/README.md`](platform/stm32g4/README.md) | integration plan for the target platform layer (timers, ADC trigger, CAN, watchdog, calibration flash page); no code |
| Python 3 with the packages in [`../requirements.txt`](../requirements.txt) | needed by CMake for the blob step (`config_tool.py` imports PyYAML and jsonschema); not needed for the portable-only build |

Users of the firmware build outside this directory: `conftest.py` builds `build/` (or `$SEMMC_BUILD_DIR`) on demand for pytest and uses `semmc_host`, `semmc_cfgcheck` and `cal/synthetic.bin`; `host/telemetry_adapter/cosim.py` drives `semmc_host --interactive`; `host/replay/replay.py`, `tools/run_host_demo.py` and `tools/make_replay_sample.py` run `semmc_host`; `tools/control_contract_report.py` runs `semmc_contract_report`. Continuous integration (CI) runs the commands of section 7 ([`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)).

## 7. How to build and test

Requirements: CMake 3.20 or newer, Ninja, a C11 compiler (gcc), Python 3 with `pip install -r requirements.txt`; for the portability compile, `arm-none-eabi-gcc` with newlib. Run from the repository root.

### 7.1 Host build and unit tests

```sh
cmake -S firmware -B build -G Ninja
cmake --build build
ctest --test-dir build --output-on-failure
```

Host tests are built with AddressSanitizer and UndefinedBehaviorSanitizer by default (`-DSEMMC_SANITIZE=OFF` disables them). The build writes the calibration blobs to `build/cal/synthetic.bin` and `build/cal/unconfigured.bin`.

ctest has 8 entries: the 7 test programs, plus `test_core_properties_24x12`, the property test run again with arguments `24 12`. Result observed on 2026-10-17 on this tree (gcc 13.3.0, CMake 3.28.3, Ninja 1.11.1, separate build directory): **8/8 passed, 0 failed, about 13 s in total**. Check counts printed by each program in that run:

| ctest entry | Test functions | Checks | Failures |
|---|---|---|---|
| `test_control` | 12 | 736 | 0 |
| `test_freshness` | 15 | 99 | 0 |
| `test_config` | 7 | 290 | 0 |
| `test_state_machine` | 24 | 1966 | 0 |
| `test_protocol` | 5 | 46 | 0 |
| `test_core` | 21 | 1043 | 0 |
| `test_core_properties` (6 seeds x 12 s) | | 326 246 (72 000 slow steps) | 0 |
| `test_core_properties_24x12` | | 1 237 899 (288 000 slow steps) | 0 |

### 7.2 Property test

`test_core_properties` drives the core through the real CAN binding with an adversarial supervisor (silence, duplicates, older frames, corrupted CRCs, wrong tags, NaN torque, cached samples, stalls, companion restarts, bus-off), a random driver and controller reboots, and checks properties P1 to P8 (listed in the file header) after every slow step.

```sh
./build/test_core_properties                    # default: 6 seeds x 12 s, base seed 0x1234567
./build/test_core_properties 24 12              # as run by ctest
./build/test_core_properties 300 30 0x5EED2026  # longer soak with another base seed
```

Arguments: `[n_seeds [seconds_per_seed [base_seed]]]`; at least 6 seeds of 8 s, otherwise it prints `need at least 6 seeds of 8 s` and exits 2. It prints the slow-step, ECO and recovery-check counts and the number of each injected behaviour, and exits 1 on any failed check, including the checks that the run was not vacuous (at least 10 ECO entries and 2000 ECO steps, every injected behaviour seen, more than 10 000 recovery checks, at least 6 reboots). Recorded soaks of 100 x 30 s and 300 x 30 s: [../docs/generated/property_soak.md](../docs/generated/property_soak.md) (not re-run here).

### 7.3 Cortex-M4F portability compile

```sh
cmake -S firmware -B build-arm -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi-cortex-m4f.cmake \
  -DSEMMC_PORTABLE_ONLY=ON -DSEMMC_SANITIZE=OFF -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build build-arm
arm-none-eabi-size -t build-arm/libsemmc_core.a
```

This compiles only `semmc_core` (core plus generated codec) for `-mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard`. It proves the core has no host dependencies; it is not a firmware image (no startup code, linker script, drivers or integration). Observed on 2026-10-17 with arm-none-eabi-gcc 13.2.1: build succeeded, **31 955 bytes of unlinked text**, 0 data, 0 bss. Disassembly showed no software double-precision calls (`__aeabi_d*`) in `mc_core_fast_step` or in the control objects (`mc_foc`, `mc_pi`, `mc_transforms`, `mc_hall`); in `mc_core.c` they occur only in `mc_core_slow_step` and message building (double-precision energy totals), and also in `mc_config.c` (boot-time validation) and the generated codec.

### 7.4 Host tools

```sh
./build/semmc_cfgcheck build/cal/synthetic.bin sim      # exit 0, "CODES" with no issues
./build/semmc_contract_report build/cal/synthetic.bin  # contract scenarios, CSV on stdout
./build/semmc_host --cal build/cal/synthetic.bin --log <scenario.log> --out <result.csv> [--frames tx.log]
./build/semmc_host --cal build/cal/synthetic.bin --interactive --out <result.csv>
```

`semmc_host` options and the `semmc-log v1` event format are documented at the top of `platform/host/host_main.c`. Its PWM period must divide 1 ms.

### 7.5 Hardware build option

`-DSEMMC_HARDWARE_BUILD=ON` validates `SEMMC_VEHICLE_CONFIG` (default `config/vehicle.unconfigured.yaml`) with `tools/config_tool.py validate ... --mode hw` at configure time and fails if it is invalid. If it is valid, configuration still stops with an error because the STM32G4 platform layer is not implemented. With the default configuration it fails at the validation step.

## 8. Generated files

Do not edit these by hand; change the source and regenerate from the repository root.

| File | Generated from | Regenerate | Check (as in CI) |
|---|---|---|---|
| `firmware/include/semmc/mc_params_generated.h` (also writes `config/vehicle.schema.json`) | `config/parameters.yaml` | `python3 tools/gen_config.py` | `python3 tools/gen_config.py --check` |
| `protocol/generated/semmc_protocol.h`, `semmc_protocol.c`, `semmc_golden_vectors.c` (also `semmc_protocol.py`, `protocol/golden_vectors/vectors.json`, `docs/generated/can_messages.md`) | `protocol/protocol.yaml` | `python3 tools/gen_protocol.py` | `python3 tools/gen_protocol.py --check` |
| `<build>/cal/synthetic.bin`, `<build>/cal/unconfigured.bin` | `config/vehicle.synthetic.yaml`, `config/vehicle.unconfigured.yaml` | produced by the CMake build (`tools/config_tool.py blob`) | not committed |

The protocol codec is not copied into `firmware/`; CMake compiles it from `protocol/generated/`. Both `--check` commands reported the committed files as current on 2026-10-17.

## 9. Current limitations

* **No target platform layer.** The STM32G4 layer is not implemented: no timer and PWM driver, ADC sampling and conversion to engineering units, CAN driver (STM32 FDCAN peripheral) and acceptance filter, precharge bypass closing logic (the ICD gives its rule; the closing logic belongs to this layer), watchdog servicing, reset-reason readout, calibration flash storage, startup code or linker script. The calibration's ADC and shunt parameters (`shunt_ohm`, `amp_gain_V_per_V`, `adc_vref_V`, offsets, divider ratio) are validated and derived but not used by the core. The plan is in [platform/stm32g4/README.md](platform/stm32g4/README.md).
* **Host platform and simulated plant are for testing only.** `sim_plant.c` uses synthetic constants and is "NOT a validated model of any real motor, inverter, battery or vehicle" (averaged inverter without dead time, rigid drivetrain, first-order thermal models). The synthetic calibration is not a real motor or battery and can never permit physical output. The host build is single-threaded, so the slow-to-fast handoff is not protected there.
* **Provisional timing.** Supervision period and timeout are provisional and simulation-only (section 4); the CAN identifier base 0x300 is "PROPOSED, NOT allocated on any real bus" (synthetic configuration); bus bit rate and classic CAN or CAN FD (flexible data rate) mode are unknown. The fast-step execution time on the target is not measured (the STM32G4 notes give a budget of 50 µs at 20 kHz minus ADC conversion time and claim no figure).
* **Control scope.** Hall-sensored sinusoidal PMSM only (validator rules 30 and 31); `id_ref = 0`, MTPA deferred; regeneration deferred (rule 18 rejects `regen_enabled`, ADR-0007, and the arbiter never outputs negative torque). The closed-loop battery-trim gain still has to be checked against the BMS (battery management system) and fuse data ([../docs/CONTROL_CONTRACT.md](../docs/CONTROL_CONTRACT.md) section 2).
* **CSIA is shadow only.** Advisory content is tracked but used by nothing; the controller does not re-transmit it on CAN (only `semmc_host` writes it to its CSV).
* **Behaviour visible in the code that a reviewer should know:**
  * The Hall invalid flag is cleared only by `mc_hall_init()`, so a `HALL_INVALID` fault stays active and cannot be reset with the fault-reset input; it needs a core re-initialisation.
  * `MC_F_SELFTEST` is never an active condition, so a fault reset clears it; the self-test is not repeated before the next arming.
  * `sup_hello` frames are tracked with a 3 s window (`MC_HELLO_MAX_AGE_US`) and `last_hello_us` is recorded, but nothing reads either: there is no hello timeout. Sessions end on a companion restart, bus-off or controller reboot.
  * The counter `rx_len_fail` is never incremented; length errors are counted in `rx_crc_fail`.
  * `ctrl_fault` is sent early only on a transition into or out of `FAULT_LATCHED`; a further fault latched while already in `FAULT_LATCHED` waits for the 1 s period.
  * `mc_crc8_j1850()` and `mc_crc8_with_data_id()` in `mc_crc.c` are exercised only by `test_config`; CAN payload CRCs are computed by the generated codec's own function.
