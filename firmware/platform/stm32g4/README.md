# STM32G4 platform layer: NOT IMPLEMENTED (v0.1)

No embedded motor-control firmware image exists. The portable core cross-compiles for Cortex-M4F (`firmware/cmake/arm-none-eabi-cortex-m4f.cmake`, `SEMMC_PORTABLE_ONLY=ON`): about 29.5 kB of unlinked text, and **no software double-precision calls inside `mc_core_fast_step`** (checked with `arm-none-eabi-objdump`). That is a portability check, not a firmware build.

## Vendor tooling assessment (ST X-CUBE-MCSDK)
* Seen (search snippets only): MCSDK 6.4.x supports STM32G4; license SLA0048 ("Ultimate Liberty" mix). Not downloaded; st.com unreachable.
* Decision (ADR-0009): use MCSDK as a **reference** for TIM1/ADC injected-trigger configuration and timing, but not generated control code, until the Art. 66a "kit software" question is answered.
* Use STM32CubeG4 HAL/LL (BSD-3) for peripheral bring-up, subject to the same rule confirmation.

## Integration plan (what the platform layer must provide)
| Function | Peripheral | Notes |
|---|---|---|
| Fast step at PWM rate | TIM1 center-aligned, update at the valley → ADC1/ADC2 injected simultaneous conversions → ADC JEOC ISR calls `mc_core_fast_step` | measured `dt` from a free-running timer, never assumed |
| Duty output | TIM1 CCR1–3, complementary outputs, hardware dead time (DTG) ≥ configured `deadtime_s` | break input BKIN from the protection chain; MOE cleared by hardware |
| Slow step 1 kHz | TIM6 ISR at lower priority, or a main-loop tick | `mc_core_slow_step` |
| Slow→fast handoff | `mc_fast_cmd_t` copied under a sequence lock or with the ADC ISR masked for the 3-word copy | the host build is single-threaded |
| CAN | FDCAN1, bit rate and classic/FD mode per the vehicle bus (UNKNOWN); RX FIFO drained in a task (not the ADC ISR) → `mc_core_on_can_rx` (CAN binding; the core itself takes `mc_core_on_msg_rx`); bus-off IRQ → `mc_core_on_can_bus_off`; acceptance filter = `mc_can_id_base()` / mask 0x7C0, standard ids only | bus UNKNOWN |
| 64-bit time | 32-bit TIM2/TIM5 at 1 MHz extended with `mc_time_extend` at ≥ 1 Hz | |
| Calibration blob | dedicated flash page; CRC-checked by `mc_config_parse_blob` | written only by a bench tool while DISARMED |
| Watchdog | external windowed WDT kicked from the slow loop only after the fast loop reports progress; IWDG as backup | |
| Reset reason | RCC CSR → `mc_slow_inputs_t.reset_reason` | reported in `ctrl_fault` |

## Timing budget (to be measured, not estimated)
Fast step on M4F at 170 MHz: TBD by measurement on hardware (GPIO toggle + scope, or the DWT cycle counter). The budget is 50 µs at 20 kHz minus ADC conversion time. No figure is claimed until measured.

## v0.2 platform requirements (from the hardware draft)
* **Clock (v0.3: NOT selected).** v0.2 fixed a 40 MHz HSE for CHUDS CAN FD; that is withdrawn. Candidate clock trees with PLL settings, TIM1/ADC/FDCAN clocks and bit timings: `hardware/timing/clock_tree_alternatives.md`. Choose after the vehicle bus is confirmed.
* **FDCAN1 (only if the vehicle bus is CAN FD; the values below are the reference-project case at a 40 MHz kernel):** FD operation enabled (CCCR.FDOE = 1); transmits classic frames only. On a classic CAN 2.0B bus: classic mode, nominal timing only.
  * Nominal timing: NBRP 1, NTSEG1 63, NTSEG2 16 (80 tq, 80 %).
  * Data timing: DBRP 1, DTSEG1 15, DTSEG2 4 (20 tq, 80 %).
  * Register encodings subtract 1 [R].
  * Needed only to coexist with an FD bus such as CHUDS (`docs/CAN_INTEGRATION.md`, reference project). Acceptance filter: the configured 64-identifier block, standard ids only.
* **TIM1:** centre-aligned complementary PWM.
  * BDTR: DTG per `hardware/timing/timing_budget.md`; BKIN (PE15, nFAULT) and BKIN2 (PC3, OV comparator) active low; BKF 4; OSSI = 1, OISx = OISxN = 0; AOE = 0.
  * PROPOSED: TRGO2 starts ADC1/ADC2 (dual simultaneous injected) and ADC3 (injected) at the PWM valley. Simultaneity is not substantiated until the trigger configuration, ADC synchronization and acquisition windows are written and measured (bring-up stage 4).
* **Per-cycle phase validity:** phase k is valid only if its duty is ≤ the sampleable limit, `1 - 2 (deadtime + current_sample_settle_s) f_pwm`. Pass the mask to `mc_phase_meas_t`; validator rule 39 guarantees at least two valid phases.
* **Fast step:** measure DWT->CYCCNT around `mc_core_fast_step` at bench stage 2 and record it in the timing budget.
