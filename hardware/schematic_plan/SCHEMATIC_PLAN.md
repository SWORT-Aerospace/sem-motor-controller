# Schematic sheet plan v0.1 — NOT A DESIGN, NOT FABRICATION READY

Draft blocks are given only where the inputs support them. Power-stage values are deliberately absent (ADR-0004). Nothing here may be sent for fabrication.

| Sheet | Content | Draftable now? | Blocked by |
|---|---|---|---|
| 01 Power entry | battery connector (after the vehicle fuse and e-stop), reverse-polarity strategy, TVS/clamp, precharge path, DC-bus shunt for INA228, bleeder/active discharge | topology only | pack V, BMS limits, isolation topology (rules), measured transients |
| 02 DC link | bulk + film/ceramic capacitors close to each half-bridge | topology only | drive-cycle ripple, layout inductance |
| 03 Power stage | 3 half-bridges (one MOSFET per position initially), Kelvin gate routing, 3 low-side shunts, phase connectors, NTC on the heatsink/copper | topology only | MOSFET selection, shunt value, thermal path |
| 04 Gate driver | DRV8353S/RS-class: VM, VDRAIN sense, SPI, ENABLE, nFAULT → MCU GPIO **and** TIM1_BKIN via the protection OR; CSA outputs → ADC; bootstrap/charge-pump components per datasheet | **yes, logic-side connections** | exact order code; datasheet review (ti.com unreachable) |
| 05 Independent protection | overcurrent comparator (from CSA or a separate sense) → latch → driver ENABLE + TIM1_BKIN; overvoltage comparator; external windowed watchdog → ENABLE; ENABLE requires (WDT OK ∧ no latch ∧ dead-man chain) in **hardware AND logic**, with no MCU in the path | **yes, block level** | thresholds (unfrozen) |
| 06 MCU | STM32G474V·T6 (LQFP100), 3.3 V, decoupling, HSE, SWD, BOOT0, reset, analog reference filtering | **yes** (pins per `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`) | AF/timing review in CubeMX; errata ES0430 |
| 07 Sensing I/O | hall inputs (pull-ups, RC, clamp, Schmitt), motor temperature input, Vbus divider, throttle 2-track inputs with open/short detection | partially | hall type/supply, motor sensor type, pedal type |
| 08 Driver controls | arm, mode, cancel, brake (NC), reset, e-stop chain sense, dead-man sense; ESD/EMI protection; debounce RC | **yes** | connector choice |
| 09 CAN + DC meter | TCAN1042-class transceiver (VIO 3.3 V), split termination option, CMC footprint, INA228 on I2C1 with ALERT | **yes** | — |
| 10 Logic supply | wide-input buck (or the DRV8353RS internal buck) → 12 V / 5 V / 3.3 V; **quiescent current budget** | topology only | pack voltage; measured load (H6) |
| 11 Mechanical | mounting, heatsink/thermal pad, "SEM" etched on copper, test points for every rail and switch node | partially | enclosure |

## Draft block: independent enable chain (sheet 05)
```
DEADMAN_SW ──┐
ESTOP_SENSE ─┼─[AND, discrete logic]──┐
WDT_OK ──────┘                        ├─[AND]── DRV_ENABLE ── gate driver
OC_LATCH_n (comparator, manual reset) ┘
                     └──────────────── TIM1_BKIN (MCU PWM break, hardware path)
MCU GPIO DRV_ENABLE_REQ ── can only *disable* (series AND input), never override
```
The MCU can request disable but cannot assert enable against the chain. Latch reset is a local action (fault-reset button through hardware) and is also reported to the MCU.

## Draft block: phase-current sampling (sheet 03/04)
Low-side shunt → driver CSA (gain per calibration) → RC anti-alias → ADC1/ADC2 injected, simultaneous, triggered from TIM1 at the PWM valley (all low-sides on). The minimum low-side on-time ≥ dead time + CSA settling + ADC sampling (`models/inverter/losses.amplifier_settling_ok`). This sets `inverter.duty_max`.
