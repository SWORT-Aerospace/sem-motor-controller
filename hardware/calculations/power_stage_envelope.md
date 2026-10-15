# Power-stage loss and thermal envelope (generated)

> `tools/hardware_calcs.py` with `models/inverter/losses.py`. MOSFET parameters are **web-search snippet values of candidate parts, UNVERIFIED** against the primary datasheets. The phase current and bus voltage are swept because the motor and battery are unknown. Synchronous conduction R·I_pk²/4 per device; switching from gate-charge transition times (synthetic gate-drive settings). **Not a measurement.**

Assumptions: T_amb 40 °C [A]; design junction limit 110 °C [D] (a derating policy, far below the 175 °C **absolute maximum** quoted for these parts [S]; operating near an absolute-maximum rating is never a design point); case-to-sink 0.5 K/W (TIM) [A]; f_sw 20 kHz [C]; dead time 200 ns [C]; m 0.8; cos φ 0.9.

## V_bus = 36 V (battery maximum UNKNOWN)

| candidate (snippet values) | I_ph,pk A | inverter loss W | hottest device W | max R_th(sink-amb) per device for Tj ≤ 110 °C, K/W |
|---|---|---|---|---|
| CSD19536KTT (D2PAK) [snippet] | 10 | 1.5 | 0.23 | 310.0 |
| CSD19536KTT (D2PAK) [snippet] | 20 | 3.2 | 0.51 | 135.6 |
| CSD19536KTT (D2PAK) [snippet] | 40 | 9.3 | 1.52 | 45.2 |
| CSD19536KTT (D2PAK) [snippet] | 80 | 34.6 | 5.74 | 11.3 |
| CSD19535KTT (D2PAK) [snippet] | 10 | 1.3 | 0.20 | 340.7 |
| CSD19535KTT (D2PAK) [snippet] | 20 | 3.4 | 0.55 | 125.4 |
| CSD19535KTT (D2PAK) [snippet] | 40 | 11.4 | 1.88 | 36.2 |
| CSD19535KTT (D2PAK) [snippet] | 80 | 48.5 | 8.07 | 7.7 |
| CSD19532Q5B (SON5x6) [snippet] | 10 | 1.4 | 0.22 | 321.7 |
| CSD19532Q5B (SON5x6) [snippet] | 20 | 4.1 | 0.68 | 101.5 |
| CSD19532Q5B (SON5x6) [snippet] | 40 | 15.5 | 2.57 | 26.0 |
| CSD19532Q5B (SON5x6) [snippet] | 80 | 76.7 | 12.78 | 4.2 |
| BSC040N10NS5 (SuperSO8) [snippet] | 10 | 1.2 | 0.19 | 360.2 |
| BSC040N10NS5 (SuperSO8) [snippet] | 20 | 3.6 | 0.59 | 116.5 |
| BSC040N10NS5 (SuperSO8) [snippet] | 40 | 13.0 | 2.15 | 31.1 |
| BSC040N10NS5 (SuperSO8) [snippet] | 80 | 59.8 | 9.96 | 5.6 |

## V_bus = 48 V (battery maximum UNKNOWN)

| candidate (snippet values) | I_ph,pk A | inverter loss W | hottest device W | max R_th(sink-amb) per device for Tj ≤ 110 °C, K/W |
|---|---|---|---|---|
| CSD19536KTT (D2PAK) [snippet] | 10 | 1.8 | 0.27 | 253.7 |
| CSD19536KTT (D2PAK) [snippet] | 20 | 3.7 | 0.59 | 118.0 |
| CSD19536KTT (D2PAK) [snippet] | 40 | 10.1 | 1.65 | 41.5 |
| CSD19536KTT (D2PAK) [snippet] | 80 | 36.2 | 6.00 | 10.8 |
| CSD19535KTT (D2PAK) [snippet] | 10 | 1.5 | 0.24 | 292.2 |
| CSD19535KTT (D2PAK) [snippet] | 20 | 3.7 | 0.61 | 114.5 |
| CSD19535KTT (D2PAK) [snippet] | 40 | 11.9 | 1.97 | 34.5 |
| CSD19535KTT (D2PAK) [snippet] | 80 | 49.7 | 8.27 | 7.5 |
| CSD19532Q5B (SON5x6) [snippet] | 10 | 1.5 | 0.24 | 289.3 |
| CSD19532Q5B (SON5x6) [snippet] | 20 | 4.4 | 0.72 | 95.9 |
| CSD19532Q5B (SON5x6) [snippet] | 40 | 15.9 | 2.64 | 25.2 |
| CSD19532Q5B (SON5x6) [snippet] | 80 | 77.8 | 12.96 | 4.1 |
| BSC040N10NS5 (SuperSO8) [snippet] | 10 | 1.4 | 0.22 | 319.4 |
| BSC040N10NS5 (SuperSO8) [snippet] | 20 | 3.9 | 0.64 | 108.5 |
| BSC040N10NS5 (SuperSO8) [snippet] | 40 | 13.5 | 2.24 | 29.9 |
| BSC040N10NS5 (SuperSO8) [snippet] | 80 | 61.0 | 10.16 | 5.5 |

## V_bus = 60 V (battery maximum UNKNOWN)

| candidate (snippet values) | I_ph,pk A | inverter loss W | hottest device W | max R_th(sink-amb) per device for Tj ≤ 110 °C, K/W |
|---|---|---|---|---|
| CSD19536KTT (D2PAK) [snippet] | 10 | 2.1 | 0.32 | 214.6 |
| CSD19536KTT (D2PAK) [snippet] | 20 | 4.1 | 0.67 | 104.4 |
| CSD19536KTT (D2PAK) [snippet] | 40 | 10.8 | 1.78 | 38.4 |
| CSD19536KTT (D2PAK) [snippet] | 80 | 37.8 | 6.27 | 10.3 |
| CSD19535KTT (D2PAK) [snippet] | 10 | 1.7 | 0.27 | 255.7 |
| CSD19535KTT (D2PAK) [snippet] | 20 | 4.0 | 0.66 | 105.3 |
| CSD19535KTT (D2PAK) [snippet] | 40 | 12.5 | 2.07 | 32.9 |
| CSD19535KTT (D2PAK) [snippet] | 80 | 50.9 | 8.47 | 7.3 |
| CSD19532Q5B (SON5x6) [snippet] | 10 | 1.6 | 0.26 | 262.9 |
| CSD19532Q5B (SON5x6) [snippet] | 20 | 4.6 | 0.76 | 91.0 |
| CSD19532Q5B (SON5x6) [snippet] | 40 | 16.3 | 2.71 | 24.5 |
| CSD19532Q5B (SON5x6) [snippet] | 80 | 78.8 | 13.13 | 4.0 |
| BSC040N10NS5 (SuperSO8) [snippet] | 10 | 1.5 | 0.24 | 286.8 |
| BSC040N10NS5 (SuperSO8) [snippet] | 20 | 4.2 | 0.68 | 101.5 |
| BSC040N10NS5 (SuperSO8) [snippet] | 40 | 14.0 | 2.32 | 28.7 |
| BSC040N10NS5 (SuperSO8) [snippet] | 80 | 62.2 | 10.36 | 5.4 |

## DC-link ripple current (sizing input for the bulk capacitors)

| I_ph,rms A | m 0.5 | m 0.8 | m 1.0 |
|---|---|---|---|
| 7 | 4.2 A | 4.2 A | 3.6 A |
| 14 | 8.4 A | 8.3 A | 7.1 A |
| 28 | 16.7 A | 16.6 A | 14.2 A |
| 57 | 34.0 A | 33.8 A | 28.9 A |

Kolar–Round approximation, cos φ 0.9 (verified against a switching simulation in `tests/simulation`).

## What this decides and what it does not

* With the motor's continuous and peak currents unknown, **no MOSFET, heatsink or capacitor can be frozen**. The table shows the decision space: a single 2.4–5 mΩ device per switch keeps per-device dissipation at a few watts up to ~40 A peak, which a modest heatsink handles. At ~80 A the required sink resistance becomes demanding for the higher-R_DS(on) parts.
* Selection requires the motor's peak current and duration, continuous current, and the battery's maximum charged voltage (V_DS rating ≥ 1.5 × V_bat,max for ringing margin [D], verified with overshoot measurements at stage 4).
