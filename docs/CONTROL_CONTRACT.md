# Control contract v0.2: shutdown, ceilings, envelopes, requests

This document defines how a torque request becomes a current reference, and how quickly each kind of bound must take effect. Implementation: `firmware/src/state_machine/mc_arbiter.c` (layers) and `firmware/src/core/mc_core.c` (supervisor envelope selection). Tests: `firmware/tests/test_state_machine.c` (`test_contract_*`) and `firmware/tests/test_core.c` (`test_contract_*`). Before/after evidence (synthetic, host only): [`generated/control_contract_before_after.md`](generated/control_contract_before_after.md).

v0.1 had three defects (§6), found by review of `mc_arbiter.c` and `mc_core.c` and then confirmed by the harness. v0.2 corrects them. **Nothing here has run on hardware.** The latencies below are those of the host model; the numbers marked *to be measured* need the bench stages in `VALIDATION_PLAN.md`.

## 1. Layers (highest precedence first)

| Layer | What | Who sets it | On a reduction | Deadline | Reason bits |
|---|---|---|---|---|---|
| **L0 Independent hardware shutdown** | hardware overcurrent comparator → timer break (BKIN) and gate-driver disable; gate-driver fault (nFAULT); e-stop / dead-man hardware chain that removes gate-driver or bus power | hardware, never firmware or CAN | gates off in hardware; firmware sets torque 0, `iq_ref` 0, PWM disabled on its next update and latches the fault | hardware path: **to be measured** at stage 3/4 (break-input latency, comparator delay); firmware confirmation ≤ 1 slow update (1 ms) | `HW_TRIP`, `FAULT_INHIBIT` |
| **L1 Immediate inhibits** | latched fault; state not in {MANUAL, ECO_ASSIST, DERATED}; driver absent (dead-man sense); brake switch; eco cancel | wired driver controls and the controller's own fault logic | torque 0 and `iq_ref` 0 on this update; **no slew** | ≤ 1 slow update after the input is sampled (input filtering: hardware design item) | `NOT_ARMED`, `FAULT_INHIBIT`, `DRIVER_ABSENT`, `BRAKE_OVERRIDE`, `CANCEL_OVERRIDE` |
| **L2 Local hard ceilings** | `min(max_motor_torque, kt·max_phase_current)`; battery-current feed-forward `η_min·V_bus·I_batt,max/ω`; closed-loop battery trim; thermal / undervoltage / unknown-temperature derate; speed taper | controller configuration + controller's own measurements | `accepted` and `|iq_ref|·kt` clamped to the ceiling **on the same update in which the lower ceiling is computed**, regardless of the previous output, slew settings, owner or the supervisor's `limits_ref` | 1 slow update (1 ms); no ramp | `CLAMP_TORQUE`, `CLAMP_BATTERY`, `CLAMP_DERATE`, `CLAMP_SPEED` (set when the request **or the previous output** exceeds that ceiling) |
| **L3 Supervisory operating envelope** (ECO only) | companion's `max_torque_Nm`, `max_batt_power_W` (as torque `P·η_min/ω`) | companion via CAN `sup_limits`; selection rule §3 | output above the envelope falls at **at least** `slew_down_fast` per second until at or below it | worst case `max_motor_torque / slew_down_fast ≤ supervision.timeout_s` (validator rule 38). Synthetic: 2.0 / 100 = 20 ms ≤ 100 ms | `SUPERVISOR_BOUND` (+ `SLEW` while ramping) |
| **L4 Owner request with comfort slew** | MANUAL/DERATED: throttle × `manual_max_torque`; ECO: companion `torque_req`; ECO coast request → 0 | driver (wired) or companion | normal ramps `slew_up` / `slew_down` | none (comfort only; it is a request, not a bound) | `SLEW`, `COAST`, `REGEN_DISABLED`, `THROTTLE_LATCH`, `SUPERVISOR_INVALID` |

The order of computation inside one update is: request → L0/L1 (return zero) → L2 ceiling → L3 envelope → target = clamp(request, 0, min(L2, L3)) → L4 comfort slew from `min(previous, L2)` → L3 ramp floor → **final clamp to L2**. The final clamp is the last statement that writes `accepted`, so nothing above it can leave the output over the hard ceiling.

Invariants (stated in `mc_state_machine.h`, tested):
* **I8** `accepted ≤ hard ceiling` and `|iq_ref|·kt ≤ hard ceiling` on every update.
* **I9** While above a reduced envelope, the output falls at least at `slew_down_fast`. The envelope is never looser than the newest committed limits set, whatever `limits_ref` the request carries.

## 2. Which bounds may ramp, and why

| Bound | Ramp allowed? | Justification |
|---|---|---|
| L0, L1 | **No** (immediate zero) | Driver and hardware safety functions. Removing propulsion torque is always in the safe direction for this controller: regeneration is disabled (ADR-0007), so the motor only drives. |
| L2 static/current, derate, speed taper, battery feed-forward | **No** (clamp on the next update) | These protect hardware: phase current, battery current, temperature, speed. A ceiling that has fallen is already the controller's best estimate of what is safe *now*; ramping toward it would knowingly exceed it. A torque step **down** is safe for a propulsion-only drive. Its drivability and driveline-shock consequences (chain/belt backlash) are a vehicle-team input (§7). |
| L2 closed-loop battery trim | The **trim itself** is a regulator: the scale falls at 0.5 per (A·s) of measured excess. Each value of the trim is applied immediately. | It corrects model error in the feed-forward bound using the measured DC current, and it cannot react faster than the measurement. The allowable duration of battery overcurrent comes from the BMS/fuse datasheet, which is an **open input**. The trim gain must be checked against it before hardware use. |
| L3 supervisory envelope | **Yes**, at ≥ `slew_down_fast`, worst case ≤ `supervision.timeout_s` (rule 38) | The envelope is an energy-strategy bound, not a protection. Hardware protection is L2. The companion can already force zero torque within `timeout_s` by going silent: the controller then leaves ECO with immediate zero (I4). A ramp no longer than that is therefore never a weaker guarantee than silence. It avoids torque steps from routine strategy updates. |
| L4 request | Comfort slew only | Drivability. |

Provisional numbers: `slew_up` 5 N·m/s, `slew_down` 10 N·m/s, `slew_down_fast` 100 N·m/s, timeout 100 ms. All are **synthetic** and must be replaced from the vehicle hazard/latency analysis (`OPEN_PARAMETERS.md`).

## 3. Supervisor envelope selection (CAN)

* `sup_limits` frames carry `limits_seq`. A frame with a **new** `limits_seq` becomes the newest set `lim[0]`; the previous newest moves to `lim[1]`. A frame with the **same** `limits_seq` as `lim[0]` is a refresh and updates `lim[0]` in place. It no longer evicts `lim[1]`; in v0.1, a periodic re-send could make a still-in-flight request referencing the previous set fail spuriously.
* A torque request must reference (`limits_ref`, 4 bits) a set the controller holds. Otherwise the supervisor input is INVALID and ECO exits with immediate zero (unchanged).
* The envelope applied is **`min(newest set, referenced set)`** field by field. A tighter set therefore takes effect on the slow update after it is committed, before any request references it. An older reference can only tighten the envelope; it never restores permission the newest set withdrew. A looser new set takes effect only once a request references it.
* Supervisor obligation (ICD §1.2): change `limits_seq` whenever the content changes. If the content changes under the same `limits_seq`, the latest frame is taken as the newest set.
* Counter `env_newest_tighter_steps` (core) counts slow updates in which the newest set bounded an older reference. It is a diagnostic only; it is not on CAN v1.0.

## 4. Timing on the host model

* Slow (supervisory) update: 1 kHz. The new `iq_ref` is handed to the fast loop in the same slow step (`fast_cmd`). The current loop then tracks it within its bandwidth (synthetic ≈ 1 kHz). "Next control update" in this document means the next slow step.
* On the target, the handoff needs a sequence lock or a masked copy (`firmware/platform/stm32g4/README.md`). The interrupt timing budget is in `hardware/timing/MCU_TIMING_ALLOCATION.md`.

## 5. Evidence

* `ctest`: `test_contract_hard_ceiling_clamps_next_update`, `…_independent_of_slew_settings`, `…_battery_ceiling_at_rising_speed`, `…_envelope_ramp_bounded`, `…_power_envelope_speed_step`, `…_envelope_cannot_raise_hard_ceiling`, `…_reengage_after_brake_starts_from_zero` (arbiter). `…_lower_limits_before_matching_request`, `…_delayed_request_with_older_ref`, `…_limits_refresh_keeps_previous_set`, `…_reordered_request_ignored`, `…_reengage_bounded_by_newest_envelope` (core through CAN + plant).
* Validator rule 38 `ENVELOPE_RAMP_DEADLINE` (C and Python, parity-tested).
* Before/after harness: [`generated/control_contract_before_after.md`](generated/control_contract_before_after.md), with every update checked against an independent oracle.

## 6. Defects corrected in v0.2

| # | v0.1 behaviour | Consequence (synthetic harness) | v0.2 |
|---|---|---|---|
| D1 | A lower L2 ceiling was approached at `slew_down_fast` from the previous output. | Thermal derate to 1.0 N·m: output above the ceiling for 9 updates (max +0.9 N·m). With slow slew settings: still 0.5 N·m over after 500 ms. | Clamp on the same update. 0 command-ceiling violations (host, synthetic; a command bound, not a phase-current measurement). |
| D2 | The supervisor envelope only clamped the target, so a reduction was followed at the comfort rate `slew_down`. | Envelope 2.0 → 0.5 N·m took 150 ms. Power envelope with a speed step: 88 ms. | Ramp at ≥ `slew_down_fast`: 15 ms and 9 ms, within the 20 ms rule-38 bound. |
| D3 | The envelope was taken from the set the request referenced, even when a newer, tighter set was committed. | A tighter set was ignored for 190 ms until a matching request arrived. A delayed request referencing the older set ramped the output to 1.6 N·m against a newest bound of 0.5 N·m. | `min(newest, referenced)`: 0.5 N·m within 13 ms. A delayed older reference changes nothing. |
| D3b | A same-`limits_seq` refresh shifted the buffer and evicted the previous set. | A request still referencing the previous set failed after any refresh (spurious ECO exit). | In-place refresh. |

The v0.1 test `test_limits_update_between_requests` asserted the D3 behaviour: the old bound 2.0 after a tighter set arrived. Its expectation was corrected to 0.5, which makes the test **stricter**. No other test expectation was relaxed.

## 7. Open items

* L0 hardware path latency, and brake / dead-man input filtering: hardware design items (`hardware/protection/SHUTDOWN_TRUTH_TABLE.md`), *to be measured*.
* Driveline response to step torque reductions (backlash, chain): vehicle team.
* BMS overcurrent time tolerance, to check the closed-loop trim gain.
* CAN v1.1 could carry `hard_ceiling_Nm` / `envelope_Nm` in a trace message. This is not implemented, and v1.0 is unchanged.
