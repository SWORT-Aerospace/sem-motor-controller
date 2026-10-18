# STM32G474 clock-tree alternatives and CAN bit timing (generated)

> `tools/clock_tree.py`. **No crystal is selected by this report.** The vehicle bus is UNKNOWN: the telematics proposal (v0.1, 14/10/2026) shows CAN 2.0B without a bit rate; CAN FD 500k/2M is only observed in a reference project. Select the crystal after the bus and the full timing requirements are confirmed.

> **The v0.2 statement "CAN FD requires a 40 MHz crystal" is withdrawn.** It considered only HSE used directly and the PLL outputs of a 170 MHz VCO. An 8 MHz crystal reaches 500k/2M at exactly 80 %/80 % with a 160 MHz CPU (PLLQ = 40 MHz); at 170 MHz it still gives exact 500k/2M timings, with fewer time quanta per data bit and a kernel above the unverified 48 MHz note (section 3).

## 1. Constraints used and their evidence

| Constraint | Value used | Evidence | Source |
|---|---|---|---|
| PLLM | 1, 16 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3285 IS_RCC_PLLM_VALUE |
| PLLN | 8, 127 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3287 IS_RCC_PLLN_VALUE |
| PLLP | 2, 31 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3289 IS_RCC_PLLP_VALUE |
| PLLQ/PLLR | 2, 4, 6, 8 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3291-3295 |
| VCO input (Hz) | 2.66 MHz, 8 MHz | [Sc] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:2972-2973 says 2.66-8 MHz; DS12288 recalled as 2.66-16 MHz [R]. Narrower range used. |
| VCO output (Hz) | 96 MHz, 344 MHz | [Sc] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3000-3001 says 64-344 MHz; DS12288 recalled as 96-344 MHz [R]. Narrower range used. |
| SYSCLK max (Hz) | 150 MHz, 170 MHz | [Sc] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_pwr_ex.h:640-645: range 1 up to 150 MHz, range 1 BOOST up to 170 MHz |
| HSE crystal (Hz) | 4 MHz, 48 MHz | [Sc] | stm32g4xx_hal_driver@a6001282 Src/stm32g4xx_hal_rcc.c:134 '4 to 48 MHz crystal' |
| FDCAN kernel sources | HSE, PLL Q, PCLK1 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_ll_rcc.h:420-422; cmsis_device_g4@626ee412 RCC_CCIPR_FDCANSEL (bits 25:24) |
| FDCAN kernel divider | 1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_fdcan.h:560-575 FDCAN_CLOCK_DIVx (FDCAN_CKDIV, common to all instances) |
| FDCAN kernel max (Hz) | 48 MHz | [Sc] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_rcc.h:3045-3046 '48M1CLK ... FDCAN (<=48 MHz)'. Possibly inherited from another family; not confirmed by any register limit. Treated as UNVERIFIED: options above 48 MHz are flagged, not excluded. |
| Nominal BRP/TSEG1/TSEG2/SJW | 1..512; 1..256; 1..128; 1..128 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_fdcan.h:1325-1328; cmsis_device_g4@626ee412 FDCAN_NBTP field widths 9/8/7/7 bits |
| Data BRP/TSEG1/TSEG2/SJW | 1..32; 1..32; 1..16; 1..16 | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_hal_fdcan.h:1329-1332; cmsis_device_g4@626ee412 FDCAN_DBTP field widths 5/5/4/4 bits |
| ADC kernel sources | PLL P, SYSCLK, HCLK/1,/2,/4 synchronous | [S] | stm32g4xx_hal_driver@a6001282 Inc/stm32g4xx_ll_rcc.h:449-451 (ADC12SEL); CKMODE synchronous modes [R] |
| ADC clock max (Hz) | 60 MHz | [R] | DS12288 ADC characteristics, recalled; NOT verified |
| TIM1 clock | = PCLK2 x1 when APB2 prescaler is 1 | [R] | RM0440 RCC timer clock rule, recalled |

Assumptions: propagation for the nominal phase = 2 x (transceiver loop 255 ns [R] + 10 m x 5 ns/m [A]) = 610 ns; crystal budget 100 ppm per node [A]. PWM 20 kHz centre-aligned and dead time 200 ns from `config/vehicle.synthetic.yaml` (SYNTHETIC).

## 2. Complete clock trees

| HSE | SYSCLK = TIM1 | PLL M / N / R (VCO in, VCO) | boost | ADC kernel (<= 60 MHz [R]) | PWM counts per half-period | dead-time DTG | CPU cycles per PWM period |
|---|---|---|---|---|---|---|---|
| 8 MHz | 170 MHz | 2 / 85 / 2 (4, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 8 MHz | 160 MHz | 1 / 40 / 2 (8, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 8 MHz | 150 MHz | 2 / 75 / 2 (4, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 8 MHz | 144 MHz | 1 / 36 / 2 (8, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |
| 12 MHz | 170 MHz | 3 / 85 / 2 (4, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 12 MHz | 160 MHz | 3 / 80 / 2 (4, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 12 MHz | 150 MHz | 2 / 50 / 2 (6, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 12 MHz | 144 MHz | 2 / 48 / 2 (6, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |
| 16 MHz | 170 MHz | 4 / 85 / 2 (4, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 16 MHz | 160 MHz | 2 / 40 / 2 (8, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 16 MHz | 150 MHz | 4 / 75 / 2 (4, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 16 MHz | 144 MHz | 2 / 36 / 2 (8, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |
| 20 MHz | 170 MHz | 3 / 51 / 2 (6.67, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 20 MHz | 160 MHz | 3 / 48 / 2 (6.67, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 20 MHz | 150 MHz | 3 / 45 / 2 (6.67, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 20 MHz | 144 MHz | 5 / 72 / 2 (4, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |
| 24 MHz | 170 MHz | 6 / 85 / 2 (4, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 24 MHz | 160 MHz | 3 / 40 / 2 (8, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 24 MHz | 150 MHz | 4 / 50 / 2 (6, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 24 MHz | 144 MHz | 3 / 36 / 2 (8, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |
| 25 MHz | 170 MHz | 5 / 68 / 2 (5, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 25 MHz | 160 MHz | 5 / 64 / 2 (5, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 25 MHz | 150 MHz | 4 / 48 / 2 (6.25, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 25 MHz | 144 MHz | no integer PLL setting in range | | | | | |
| 40 MHz | 170 MHz | 6 / 51 / 2 (6.67, 340 MHz) | yes | PLLP (VCO/6) = 56.67 MHz | 4250.0 | 0x22 = 200.0 ns | 8500 |
| 40 MHz | 160 MHz | 5 / 40 / 2 (8, 320 MHz) | yes | PLLP (VCO/6) = 53.33 MHz | 4000.0 | 0x20 = 200.0 ns | 8000 |
| 40 MHz | 150 MHz | 6 / 45 / 2 (6.67, 300 MHz) | no | PLLP (VCO/5) = 60 MHz | 3750.0 | 0x1E = 200.0 ns | 7500 |
| 40 MHz | 144 MHz | 5 / 36 / 2 (8, 288 MHz) | no | PLLP (VCO/5) = 57.6 MHz | 3600.0 | 0x1D = 201.4 ns | 7200 |

## 3. CAN bit timing per bus case (best exact option per clock tree)

Columns: FDCAN kernel clock; nominal BRP/tq/TSEG1/TSEG2/SJW and sample point; data phase likewise (FD only); whether both phases use the same time quantum (CiA 601-3 recommendation [R]); kernel above the unverified 48 MHz note; tolerance limit df_max (and the binding condition); margin = df_max / crystal budget.

### CAN 2.0B 500 kbit/s (telematics proposal: CAN 2.0B, bit rate not stated)
Provenance: Proposed design input (rate assumed). Target sample point 87.5 %.

| HSE | SYSCLK | FDCAN kernel | nominal | data | same tq | > 48 MHz | df_max (cond.) | margin |
|---|---|---|---|---|---|---|---|---|
| 8 | 170 | HSE = 8 MHz | 1/16/13/2/2 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 160 | HSE = 8 MHz | 1/16/13/2/2 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 150 | HSE = 8 MHz | 1/16/13/2/2 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 144 | HSE = 8 MHz | 1/16/13/2/2 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 170 | HSE = 12 MHz | 1/24/20/3/3 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 160 | HSE = 12 MHz | 1/24/20/3/3 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 150 | HSE = 12 MHz | 1/24/20/3/3 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 144 | HSE = 12 MHz | 1/24/20/3/3 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 170 | HSE = 16 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 160 | HSE = 16 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 150 | HSE = 16 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 144 | HSE = 16 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 170 | HSE = 20 MHz | 1/40/34/5/5 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 160 | HSE = 20 MHz | 1/40/34/5/5 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 150 | HSE = 20 MHz | 1/40/34/5/5 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 144 | HSE = 20 MHz | 1/40/34/5/5 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 170 | HSE = 24 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 160 | HSE = 24 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 150 | HSE = 24 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 144 | HSE = 24 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 25 | 170 | PLLQ (VCO/2) / CKDIV 4 = 42.5 MHz | 1/85/73/11/11 @ 87.1 % | - | yes | no | 0.503 % (II) | 50x |
| 25 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 25 | 150 | HSE = 25 MHz | 1/50/43/6/6 @ 88.0 % | - | yes | no | 0.466 % (II) | 47x |
| 40 | 170 | HSE = 40 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 160 | HSE = 40 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 150 | HSE = 40 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 144 | HSE = 40 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |

### CAN 2.0B 250 kbit/s
Provenance: Alternative (rate assumed). Target sample point 87.5 %.

| HSE | SYSCLK | FDCAN kernel | nominal | data | same tq | > 48 MHz | df_max (cond.) | margin |
|---|---|---|---|---|---|---|---|---|
| 8 | 170 | HSE = 8 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 160 | HSE = 8 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 150 | HSE = 8 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 8 | 144 | HSE = 8 MHz | 1/32/27/4/4 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 170 | HSE = 12 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 160 | HSE = 12 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 150 | HSE = 12 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 12 | 144 | HSE = 12 MHz | 1/48/41/6/6 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 170 | HSE = 16 MHz | 1/64/55/8/8 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 160 | HSE = 16 MHz | 1/64/55/8/8 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 150 | HSE = 16 MHz | 1/64/55/8/8 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 16 | 144 | HSE = 16 MHz | 1/64/55/8/8 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 170 | HSE = 20 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 160 | HSE = 20 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 150 | HSE = 20 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 20 | 144 | HSE = 20 MHz | 1/80/69/10/10 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 170 | HSE = 24 MHz | 1/96/83/12/12 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 160 | HSE = 24 MHz | 1/96/83/12/12 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 150 | HSE = 24 MHz | 1/96/83/12/12 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 24 | 144 | HSE = 24 MHz | 1/96/83/12/12 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 25 | 170 | PLLQ (VCO/2) / CKDIV 4 = 42.5 MHz | 1/170/148/21/21 @ 87.6 % | - | yes | no | 0.480 % (II) | 48x |
| 25 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/160/139/20/20 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 25 | 150 | PLLQ (VCO/2) / CKDIV 4 = 37.5 MHz | 1/150/130/19/19 @ 87.3 % | - | yes | no | 0.492 % (II) | 49x |
| 40 | 170 | HSE = 40 MHz | 1/160/139/20/20 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 160 | HSE = 40 MHz | 1/160/139/20/20 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 150 | HSE = 40 MHz | 1/160/139/20/20 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |
| 40 | 144 | HSE = 40 MHz | 1/160/139/20/20 @ 87.5 % | - | yes | no | 0.485 % (II) | 49x |

### CAN 2.0B 1 Mbit/s
Provenance: Alternative (rate assumed). Target sample point 75.0 %.

| HSE | SYSCLK | FDCAN kernel | nominal | data | same tq | > 48 MHz | df_max (cond.) | margin |
|---|---|---|---|---|---|---|---|---|
| 8 | 170 | PLLQ (VCO/2) / CKDIV 10 = 17 MHz | 1/17/12/4/4 @ 76.5 % | - | yes | no | 0.230 % (II) | 23x |
| 8 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 8 | 150 | PLLQ (VCO/2) / CKDIV 6 = 25 MHz | 1/25/18/6/6 @ 76.0 % | - | yes | no | 0.313 % (II) | 31x |
| 8 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |
| 12 | 170 | PLLQ (VCO/2) / CKDIV 10 = 17 MHz | 1/17/12/4/4 @ 76.5 % | - | yes | no | 0.230 % (II) | 23x |
| 12 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 12 | 150 | PLLQ (VCO/2) / CKDIV 6 = 25 MHz | 1/25/18/6/6 @ 76.0 % | - | yes | no | 0.313 % (II) | 31x |
| 12 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |
| 16 | 170 | HSE = 16 MHz | 1/16/11/4/4 @ 75.0 % | - | yes | no | 0.245 % (II) | 25x |
| 16 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 16 | 150 | HSE = 16 MHz | 1/16/11/4/4 @ 75.0 % | - | yes | no | 0.245 % (II) | 25x |
| 16 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |
| 20 | 170 | HSE = 20 MHz | 1/20/14/5/5 @ 75.0 % | - | yes | no | 0.196 % (II) | 20x |
| 20 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 20 | 150 | HSE = 20 MHz | 1/20/14/5/5 @ 75.0 % | - | yes | no | 0.196 % (II) | 20x |
| 20 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |
| 24 | 170 | HSE = 24 MHz | 1/24/17/6/6 @ 75.0 % | - | yes | no | 0.327 % (II) | 33x |
| 24 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 24 | 150 | HSE = 24 MHz | 1/24/17/6/6 @ 75.0 % | - | yes | no | 0.327 % (II) | 33x |
| 24 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |
| 25 | 170 | HSE = 25 MHz | 1/25/18/6/6 @ 76.0 % | - | yes | no | 0.313 % (II) | 31x |
| 25 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 25 | 150 | HSE = 25 MHz | 1/25/18/6/6 @ 76.0 % | - | yes | no | 0.313 % (II) | 31x |
| 40 | 170 | HSE = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 40 | 160 | HSE = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 40 | 150 | HSE = 40 MHz | 1/40/29/10/10 @ 75.0 % | - | yes | no | 0.392 % (II) | 39x |
| 40 | 144 | PLLQ (VCO/2) / CKDIV 4 = 36 MHz | 1/36/26/9/9 @ 75.0 % | - | yes | no | 0.436 % (II) | 44x |

### CAN FD 500 kbit/s / 2 Mbit/s, 80 % / 80 % (REFERENCE project only)
Provenance: Observed in a reference project (Cornell CHUDS). Target sample point 80.0 %, data 80 %.

| HSE | SYSCLK | FDCAN kernel | nominal | data | same tq | > 48 MHz | df_max (cond.) | margin |
|---|---|---|---|---|---|---|---|---|
| 8 | 170 | PLLQ (VCO/2) = 170 MHz | 17/20/15/4/4 @ 80.0 % | 17/5/3/1/1 @ 80.0 % | yes | FLAG | 0.781 % (II) | 78x |
| 8 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 8 | 150 | PLLQ (VCO/6) = 50 MHz | 1/100/79/20/20 @ 80.0 % | 1/25/19/5/5 @ 80.0 % | yes | FLAG | 0.781 % (II) | 78x |
| 8 | 144 | PLLQ (VCO/6) = 48 MHz | 1/96/76/19/19 @ 80.2 % | 1/24/18/5/5 @ 79.2 % | yes | no | 0.773 % (II) | 77x |
| 12 | 170 | HSE = 12 MHz | 1/24/18/5/5 @ 79.2 % | 1/6/4/1/1 @ 83.3 % | yes | no | 0.814 % (II) | 81x |
| 12 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 12 | 150 | HSE = 12 MHz | 1/24/18/5/5 @ 79.2 % | 1/6/4/1/1 @ 83.3 % | yes | no | 0.814 % (II) | 81x |
| 12 | 144 | PLLQ (VCO/6) = 48 MHz | 1/96/76/19/19 @ 80.2 % | 1/24/18/5/5 @ 79.2 % | yes | no | 0.773 % (II) | 77x |
| 16 | 170 | HSE = 16 MHz | 1/32/25/6/6 @ 81.2 % | 1/8/5/2/2 @ 75.0 % | yes | no | 0.732 % (II) | 73x |
| 16 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 16 | 150 | HSE = 16 MHz | 1/32/25/6/6 @ 81.2 % | 1/8/5/2/2 @ 75.0 % | yes | no | 0.732 % (II) | 73x |
| 16 | 144 | PLLQ (VCO/6) = 48 MHz | 1/96/76/19/19 @ 80.2 % | 1/24/18/5/5 @ 79.2 % | yes | no | 0.773 % (II) | 77x |
| 20 | 170 | HSE = 20 MHz | 1/40/31/8/8 @ 80.0 % | 1/10/7/2/2 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 20 | 160 | HSE = 20 MHz | 1/40/31/8/8 @ 80.0 % | 1/10/7/2/2 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 20 | 150 | HSE = 20 MHz | 1/40/31/8/8 @ 80.0 % | 1/10/7/2/2 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 20 | 144 | HSE = 20 MHz | 1/40/31/8/8 @ 80.0 % | 1/10/7/2/2 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 24 | 170 | HSE = 24 MHz | 1/48/37/10/10 @ 79.2 % | 1/12/9/2/2 @ 83.3 % | yes | no | 0.814 % (II) | 81x |
| 24 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 24 | 150 | HSE = 24 MHz | 1/48/37/10/10 @ 79.2 % | 1/12/9/2/2 @ 83.3 % | yes | no | 0.814 % (II) | 81x |
| 24 | 144 | PLLQ (VCO/6) = 48 MHz | 1/96/76/19/19 @ 80.2 % | 1/24/18/5/5 @ 79.2 % | yes | no | 0.773 % (II) | 77x |
| 25 | 170 | PLLQ (VCO/2) = 170 MHz | 17/20/15/4/4 @ 80.0 % | 17/5/3/1/1 @ 80.0 % | yes | FLAG | 0.781 % (II) | 78x |
| 25 | 160 | PLLQ (VCO/2) / CKDIV 4 = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 25 | 150 | PLLQ (VCO/6) = 50 MHz | 1/100/79/20/20 @ 80.0 % | 1/25/19/5/5 @ 80.0 % | yes | FLAG | 0.781 % (II) | 78x |
| 40 | 170 | HSE = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 40 | 160 | HSE = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 40 | 150 | HSE = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |
| 40 | 144 | HSE = 40 MHz | 1/80/63/16/16 @ 80.0 % | 1/20/15/4/4 @ 80.0 % | yes | no | 0.781 % (II) | 78x |

## 4. What this means

* **Receiving CAN correctly requires** the exact bit rate, a timing inside the field ranges, a propagation segment that fits, and an oscillator tolerance inside the ISO 11898-1 limits. Every row above with a timing meets the first three; the tolerance margins are large for any crystal (the limits are 0.1-1 %, a crystal budget is ~0.01 %).
* **Matching a particular sample point is a robustness preference** (CiA 601-3 recommends the same data-phase sample point on all FD nodes [R]). It matters for CAN FD data phases, and only if our bus is FD.
* **Classic CAN 2.0B (the telematics proposal)**: every listed crystal and CPU frequency gives an exact 250k, 500k and 1M timing near the usual sample points. The crystal choice is then free and should follow other criteria (jitter, USB or none, availability, the telematics unit's own clock plan).
* **CAN FD 500k/2M at exactly 80 %/80 % with the kernel <= 48 MHz** is reached by 12 MHz / 160 MHz, 16 MHz / 160 MHz, 20 MHz / 144 MHz, 20 MHz / 150 MHz, 20 MHz / 160 MHz, 20 MHz / 170 MHz, 24 MHz / 160 MHz, 25 MHz / 160 MHz, 40 MHz / 144 MHz, 40 MHz / 150 MHz, 40 MHz / 160 MHz, 40 MHz / 170 MHz, 8 MHz / 160 MHz (HSE / SYSCLK). Other combinations reach 2 Mbit/s with a different data sample point, a kernel above the unverified 48 MHz note, or a data prescaler above 2 (rows above).
* **At SYSCLK 170 MHz**: 8 MHz crystal -> PLLQ (VCO/2), data 80.0 % with 5 tq (kernel above the 48 MHz note); 12 MHz crystal -> HSE, data 83.3 % with 6 tq; 16 MHz crystal -> HSE, data 75.0 % with 8 tq; 20 MHz crystal -> HSE, data 80.0 % with 10 tq; 24 MHz crystal -> HSE, data 83.3 % with 12 tq; 25 MHz crystal -> PLLQ (VCO/2), data 80.0 % with 5 tq (kernel above the 48 MHz note); 40 MHz crystal -> HSE, data 80.0 % with 20 tq.
* **Not yet verified against the datasheet:** DS12288 PLL ranges, the FDCAN kernel maximum, the ADC clock maximum, flash wait states per frequency, and ISO 11898-1:2015 FD conditions IV-V. Each is tagged above.
* **Decision rule**: confirm the vehicle bus (classic or FD; bit rates; sample points; transceivers; cable length), then pick the crystal from these tables, then re-run this tool and `tools/timing_budget.py` with the chosen SYSCLK.
