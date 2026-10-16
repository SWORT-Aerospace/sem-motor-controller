# Requirements v0.1

Tags: **[V]** from a verified source · **[R?]** from an **unverified** rule extract (must be checked against the 2027 Chapter I) · **[P]** proposed engineering decision · **[A]** simulation assumption.
Verification: **T** automated test (named) · **An** analysis · **I** inspection · **HW** hardware test (VALIDATION_PLAN stage). *Host-test* verification is software behaviour on a host only.

## 1. Objective
Minimize battery energy over a valid completed run, subject to finish time, driver authority, and electrical, thermal and vehicle constraints. [P]

## 2. Safety and authority

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| SAF-1 | No torque in BOOT, SELF_TEST, DISARMED, FAULT_LATCHED | P | T `test_state_machine.c` (no_torque_after_reset…), `test_fault_injection.py::test_invalid_startup_never_outputs` | host-verified |
| SAF-2 | Arming requires a local arm-switch OFF→ON edge after boot or disarm, throttle released, e-stop chain closed | P | T `test_no_torque_after_reset_with_switch_held`, `test_arm_refused_with_pedal_pressed_or_estop` | host-verified |
| SAF-3 | Fault recovery only to DISARMED; never resumes a prior command or mode | P | T `test_hw_trip_immediate_and_reset_does_not_resume`, `test_fault_recovery_does_not_resume` | host-verified |
| SAF-4 | Supervisor loss in ECO → READY, zero torque, throttle latch | P | T `test_eco_supervisor_loss_never_jumps_to_manual`, `test_supervisor_disconnect`, `test_end_to_end.py::test_supervisor_loss_returns_to_ready_within_timeout` | host-verified |
| SAF-5 | Brake, eco-cancel and dead-man release remove torque without slew | P / R? (dead-man 37i) | T `test_brake_and_cancel_are_immediate`, `test_driver_absent_immediate`, `test_driver_cancel_and_brake_override` | host-verified |
| SAF-6 | Hardware trips (overcurrent, overvoltage, gate-driver fault, watchdog) act independently of software; software mirrors them, latches, and disables PWM in the same fast step | P | HW stages 3–6; T `test_gate_driver_fault`, `test_hw_overcurrent_trip_overrides_everything` (software mirror only) | **hardware unverified** |
| SAF-7 | The e-stop physically isolates the battery with NO contacts not driven by controller logic; the controller only senses it | R? 37e | I (schematic review), HW stage 7 | open |
| SAF-8 | The supervisor cannot arm, reset faults, select a mode, or command PWM | P | I `protocol.yaml` (no such messages); T `test_supervisor_cannot_arm_or_exceed_limits` | host-verified |
| SAF-9 | The supervisor can only tighten limits; the controller clamps to its own validated limits | P | T `test_supervisor_cannot_arm_or_exceed_limits`, `test_limits_update_between_requests` | host-verified |
| SAF-10 | Cellular is monitoring-only | P | I (companion software design), INTERFACE_CONTROL §6 | open (companion not built) |
| SAF-11 | Configurations that would allow uncontrolled rectification (line-line back-EMF ≥ min battery voltage at overspeed trip) are rejected | P | T `test_config.c` (`BACKEMF_EXCEEDS_MIN_BUS`), parity test | host-verified |
| SAF-12 | Stuck or illegal hall code, two-phase current loss, Vbus sensor loss and invalid dt latch faults | P | T `test_missing_speed_hall_disconnected`, `test_stuck_speed_detected_as_stall`, `test_two_phase_currents_missing_is_a_fault`, `test_bus_voltage_sensor_nan_faults`, `test_pi_rejects_bad_dt` | host-verified |

## 3. Electrical

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| EL-1 | Maximum voltage at any point ≤ 60 V **by design**, including transients and capacitors | R? 57a | An (`max_bus_voltage`), HW double-pulse overshoot measurement | open; needs pack data |
| EL-2 | Inverter bus rating ≥ V_max_charged × (1 + measured margin) | P | T validator rule `BUS_RATING_MARGIN`; HW stage 4 | open |
| EL-3 | Phase-current hardware trip below the current-sense full scale; software trip below the hardware trip; operating limit below the software trip | P | T rules `CURRENT_TRIP_ORDER`, `CURRENT_SENSE_RANGE` | host-verified (rules) |
| EL-4 | Phase RMS, phase peak and battery average currents tracked and reported separately | P | I `models/inverter/losses.py`; protocol fields `iq_A`, `ibatt_A` | done (models) |
| EL-5 | DC-link precharge and post-isolation discharge provided and sized | P / R? 37e | An `precharge()`; HW stage 2/4 | open |
| EL-6 | Main fuse on the positive conductor within 300 mm of the battery terminal (vehicle harness) | R? 57e | I | out of controller scope; noted |
| EL-7 | A purpose-built controller, documented, with "SEM" etched on the PCB | R? 66a / tips page | I | open |

## 4. Measurement and energy

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| ME-1 | Energy accounting uses an independent DC-bus meter (INA228 class), never the phase shunts | P | T `test_energy_accounting_consistent` (sim); HW stage 6 calibration vs reference and vs SEM joulemeter | open (hardware) |
| ME-2 | Phase-current offsets calibrated per board and stored in the calibration blob | P | config `inverter.current_offset_counts` (null until measured) | open |
| ME-3 | KCL residual reported only with three measured phases; a reconstructed phase is never independent evidence | P | T `test_currents_measured_vs_reconstructed`, `test_reconstructed_phase_is_flagged`, `test_reconstructed_phase_is_not_kcl_evidence` | host-verified |
| ME-4 | All measurements carry validity: missing, stale, invalid, saturated, nonfinite, out of range | P | T `test_freshness.c`, `ctrl_validity` frames | host-verified |

## 5. Communications and timing

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| CO-1 | Validity renewed only by new samples; duplicates, reordered frames and re-sent cached samples never renew | P | T `test_freshness.c`, `test_eco_handshake_timeout_and_cached_sample`, `test_repeated_cached_sample_does_not_keep_eco_alive` | host-verified |
| CO-2 | Counter and timestamp wrap handled; source reboot = new session | P | T `test_counter_and_timestamp_wrap`, `test_supervisor_reboot_ends_eco_and_needs_new_edge` | host-verified |
| CO-3 | Controller reboot during an active request: no torque until locally re-armed; old-session frames rejected | P | T `test_controller_reboot_during_active_request` (C and co-sim) | host-verified |
| CO-4 | Bus-off ends ECO immediately; manual driving unaffected | P | T `test_bus_off_exits_eco_immediately`, `test_bus_off_and_reordered_frames` | host-verified |
| CO-5 | Supervisory rate and timeout set by a hazard and latency analysis (50 Hz / 100 ms provisional, sim only) | P | An (pending) + `tools/bus_load.py`; hardware validation refuses provisional timing | open |
| CO-6 | Bus load ≤ 30 % at nominal rate with the vehicle bus's other traffic (UNKNOWN; CHUDS used only as a reference-project load case) | P | T `test_bus_load_budget` (estimate 13.7 %) | analysed |

## 6. Configuration

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| CF-1 | SI units, explicit sign conventions, calibration identity, version, provenance | P | schema `conventions` const block; T `test_schema_rejects_typo_and_wrong_convention` | host-verified |
| CF-2 | Reject missing, nonfinite, out-of-range, non-integer and inconsistent parameters, identically in C and Python | P | T `test_config_parity.py` (66 cases) | host-verified |
| CF-3 | Synthetic configuration cannot enable a physical output | P | T `test_synthetic_cannot_claim_physical_output`, `test_hardware_build_rejects_synthetic` | host-verified |
| CF-4 | A hardware build fails if required ratings or calibrations are missing | P | T `test_hardware_cmake_configure_refuses_unconfigured` | host-verified |

## 7. Supervisory energy strategy

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| ST-1 | Offline spatial DP with documented discretization and grid-convergence report | P | An `docs/generated/optimization_synthetic.md`; T `test_models.py` DP tests | done (synthetic) |
| ST-2 | The exported schedule is position-indexed and torque-bounded | P | T `test_schedule_export_is_bounded` | done |
| ST-3 | Only bounded pace correction online; no unrestricted adaptation | P | T `test_pace_correction_bounded_and_effective` | done |
| ST-4 | Finish-time reserve sized from measured model uncertainty | P | An (synthetic robustness study shows open-loop plans fail the time limit under +20 % Crr or a 2 m/s headwind) | open (needs data) |
| ST-5 | Driver override always available (takeover, brake, cancel, eco deselect) | P | T `test_driver_takeover_from_eco` and SAF-5 | host-verified |

## 8. CSIA

| ID | Requirement | Src | Verification | Status |
|---|---|---|---|---|
| CS-1 | Shadow mode: no command effect | P | T `test_shadow_mode_never_changes_controller_commands` | host-verified |
| CS-2 | Freshness, evidence, observability, trust and monitor health reported separately | P | T `test_freshness_separate_from_trust` | host-verified |
| CS-3 | No forced single-sensor blame; derived quantities are not independent witnesses | P | T `test_disagreement_without_corroboration_is_ambiguous`, misattribution checks | host-verified (synthetic) |
| CS-4 | Normal events are not reported as faults | P | T `test_normal_events_are_not_faults` | host-verified (synthetic) |
| CS-5 | Evidence gate before any restriction | P | ADR-0008, VALIDATION_PLAN §6 | open |

## 9. Non-goals for v0.1
Regeneration, field weakening, sensorless control, MTPA, variable switching frequency, online adaptation, autonomy, remote control of any kind.
