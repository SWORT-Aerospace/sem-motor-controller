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

**v0.3: the v0.2 conclusion drawn from this table ("change the HSE crystal to 40 MHz") is WITHDRAWN.** This table only considers kernel clocks taken directly from HSE or from a 170 MHz VCO. A complete analysis (PLL-derived kernel clocks, the FDCAN clock divider, other CPU frequencies, classic CAN 2.0B buses) is in `hardware/timing/clock_tree_alternatives.md`. The bus analysed here (CHUDS, 500k/2M FD) belongs to a REFERENCE project; our vehicle's bus is not confirmed, and the telematics proposal shows CAN 2.0B.
