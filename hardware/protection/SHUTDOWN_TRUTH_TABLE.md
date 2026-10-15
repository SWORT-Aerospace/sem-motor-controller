# Protection and shutdown truth table (draft)

How every protective input reaches the outputs, independent of firmware where marked. "Gates off" means all six gate outputs low (no switching; the motor freewheels or the bridge body diodes conduct). Latencies are **design intent**; every number marked *measure* is a bench stage 3/4/7 item (`docs/VALIDATION_PLAN.md`).

Legend: **HW** = acts without firmware; **FW** = firmware action; L0–L4 = control-contract layers (`docs/CONTROL_CONTRACT.md`).

## 1. Inputs → outputs

| # | Condition | Detected by | Path | Gate driver ENABLE | TIM1 MOE (PWM) | Torque reference | Precharge bypass | Latched? | Reset / re-arm | Latency |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Vehicle e-stop pressed | vehicle hardware isolates the battery; safety loop de-energised | HW: loop opto → HW_PERMIT low → AND → ENABLE low | **low (HW)** | FW clears on DISARMED | 0 (L1) | opens when the MCU loses power, or FW opens it | FW: DISARMED | e-stop release + arm-switch OFF→ON | HW path: opto + gate, sub-ms (measure) |
| 2 | Dead-man released | safety loop (HW) + DEADMAN_SENSE (FW) | as #1 + FW READY | **low (HW)** | FW | 0 (L1, same update) | unchanged | no | press again + new throttle/eco edge | as #1 |
| 3 | Phase over-current / shoot-through (VDS monitor) | gate driver | HW: driver turns gates off; nFAULT → TIM1_BKIN | driver shuts down per its OCP mode (verify DS) | **cleared by break (HW)** | 0 (L0) | unchanged | yes (FAULT_LATCHED) | fault-reset edge, then arm edge | driver deglitch + BKIN filter (measure) |
| 4 | Bus over-voltage | comparator TLV7041 | HW: BRK2_N → TIM1_BKIN2 | unchanged | **cleared by break (HW)** | 0 (L0) | unchanged | yes | fault reset when V_bus is back below threshold | comparator + BKF (measure) |
| 5 | Gate-driver fault: UVLO, thermal, charge pump (via SPI status) | gate driver nFAULT | HW: as #3 | per driver | **cleared (HW)** | 0 | unchanged | yes | fault reset | as #3 |
| 6 | Watchdog timeout (firmware hung) | MAX6369 | HW: WDO → NRST (MCU reset) and WDO → HW_PERMIT (diode) | **low (HW)** | outputs idle while reset (pins high-Z, AND low) | 0 | **OFF** (pull-down while the MCU is in reset) | MCU reboots: BOOT → DISARMED | arm-switch OFF→ON after reboot (I2) | watchdog period (configured by SET pins) |
| 7 | MCU reset or brown-out | supervisor in the MCU | HW: pins high-Z → pull-downs | **low (HW)** | — | 0 | **OFF** | reboot | as #6 | immediate |
| 8 | Software over-current (any phase, measured or reconstructed) | fast loop | FW: outputs off in the same ISR, latched in the next slow step | FW: kept enabled (MOE off) | FW clears | 0 | unchanged | yes | fault reset | ≤ 1 PWM period |
| 9 | Brake switch | wired input | FW: L1 | unchanged | PWM continues at zero current, or gate-off coast | **0 on the next update** | unchanged | no | release | ≤ 1 slow update (1 ms) + input filter |
| 10 | Thermal / undervoltage / unknown temperature | ADC | FW: L2 hard ceiling (clamp) → trip above threshold | unchanged (trip: as #8) | trip: FW | clamped on the next update | unchanged | derate: no; trip: yes | automatic recovery with hold (derate); fault reset (trip) | 1 ms |
| 11 | Supervisor stale / lost / bus-off | freshness tracker | FW: ECO → READY | unchanged | FW | 0 | unchanged | no | new driver eco edge | timeout (provisional 100 ms) |
| 12 | Hall invalid / stall / current-sense loss | FW plausibility | FW: fault | unchanged | FW | 0 | unchanged | yes | fault reset | per detector |
| 13 | Throttle implausible | FW (dual track) | FW: fault | unchanged | FW | 0 | unchanged | yes | fault reset + release | 1 ms |

## 2. Independence argument (what still stops the motor if X fails)

| Failure | Remaining path that stops propulsion |
|---|---|
| Firmware hangs | Watchdog → HW_PERMIT low → ENABLE low (#6); vehicle e-stop and dead-man in the safety loop (#1, #2) |
| MCU drives ENABLE high wrongly | The AND gate needs HW_PERMIT, i.e. the loop energised and the watchdog not asserting |
| A PWM output stuck active | Driver VDS monitor (#3); ENABLE low through HW_PERMIT; vehicle e-stop |
| Gate driver fails short (gate on) | Not covered by this board. The vehicle e-stop and fuse isolate the battery. This is a residual risk for the review: no on-board series disconnect in the draft. |
| Safety-loop opto fails ON | HW_PERMIT stays high, so firmware DEADMAN_SENSE and the vehicle loop (which removes battery power) remain. Opto failure detection is an open item for the review. |
| OV comparator fails | Firmware OV trip from VBUS_SENSE (FW only); battery BMS |

## 3. Requirements this table places on the selection
* The gate driver's OCP mode must turn off **all** gates and assert nFAULT (the "latched shutdown" mode).
  * Mode names and deglitch values: unverified; read SLVSDY6x.
* ENABLE low must turn every gate output off within a bounded time (verify the datasheet value; measure at stage 3).
* TIM1 configuration:
  * BKIN and BKIN2 active low;
  * BKF set (draft: 4 samples);
  * OSSI = 1, OISx = OISxN = 0;
  * AOE = 0.
* Watchdog timeout: shorter than the time to a hazardous speed change at worst-case torque, and longer than the slow loop's worst case. Derived in the vehicle hazard and latency analysis (open).
