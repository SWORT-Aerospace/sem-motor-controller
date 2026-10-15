# FDCAN bit timing for the CHUDS CAN-FD bus (generated)

> `tools/can_bit_timing.py`. Bus parameters from Cornell `urban-concept@c422c0f` `cev-lib/chuds/frame.hpp:16-19` and `tools/can_link_args.cpp`: 500 kbit/s nominal and 2 Mbit/s data, both at an 80 % sample point, `fd on`. STM32G4 FDCAN field limits are recalled [R], not read from RM0440.

| FDCAN kernel clock | nominal: BRP / tq / TSEG1 / TSEG2 / SP | data: BRP / tq / TSEG1 / TSEG2 / SP | both at exactly 80 %? |
|---|---|---|---|
| HSE 8 MHz (v0.2 draft crystal) | 1 / 16 / 12 / 3 / 81.25 % | 1 / 4 / 2 / 1 / 75.00 % | no |
| PLLQ 42.5 MHz (from 170 MHz VCO/8) | 1 / 85 / 67 / 17 / 80.00 % | impossible | no |
| PLLQ 85 MHz | 1 / 170 / 135 / 34 / 80.00 % | impossible | no |
| HSE 20 MHz | 1 / 40 / 31 / 8 / 80.00 % | 1 / 10 / 7 / 2 / 80.00 % | **yes** |
| HSE 40 MHz | 1 / 80 / 63 / 16 / 80.00 % | 1 / 20 / 15 / 4 / 80.00 % | **yes** |
| HSE 24 MHz | 1 / 48 / 37 / 10 / 79.17 % | 1 / 12 / 9 / 2 / 83.33 % | no |

Consequences:
* The v0.2 draft's 8 MHz crystal cannot place the 2 Mbit/s data-phase sample point at 80 %: it allows only 4 tq per bit, so 75 %. The 42.5/85 MHz PLL outputs available with a 170 MHz system clock give non-integer tq counts at 2 Mbit/s.
* **Change: HSE crystal 40 MHz** (also 20 MHz would work), used directly as the FDCAN kernel clock. The system clock is still 170 MHz (40 MHz / 10 × 85 / 2) [R].
* The controller transmits classic frames only (semmc v1). Transmitter delay compensation is therefore not needed, but data-phase reception timing is.
* Every number must be cross-checked with the bus at stage 2 (CAN error counters zero with CHUDS traffic present).
