# STM32U575 register-level code: what was checked, what was corrected, what stays open

**Status (2026-10-18).** The register-level code of the telematics firmware (`telematics/firmware/platform/u575/`) has been compared line by line with ST's own drivers, `STMicroelectronics/stm32u5xx-hal-driver` v1.6.3 (commit `2552682ee5a0d6f826a6435750fc9267be65868b`: HAL, LL and release notes), and with the vendored CMSIS device header (`vendor/PROVENANCE.md`). It has **not** been checked against the reference manual RM0456, the data sheet DS13737 or the errata sheet ES0499: st.com is refused by this environment's network policy and the PDFs are not in the repository (T-U5-DOCS in [`BLOCKERS.md`](BLOCKERS.md)). Register names that compile and sequences that match ST's HAL are not proof that the peripherals behave as intended on the part; the bench is the check ([`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md)). Full comparison, with every HAL file and line cited: [`reference/u575_hal_audit.md`](reference/u575_hal_audit.md).

## 1. Corrected

Each difference from ST's sequence was changed to ST's sequence. `tests/telematics/test_firmware_target.py::test_register_sequences_follow_st_hal` keeps the orderings from regressing (a source check; it does not run the code).

| ID | Where | Was | ST's sequence (HAL v1.6.3) | Now | Bench step that shows it |
|---|---|---|---|---|---|
| D1 | `board_u575.c` `board_init` | LSE started with LSEON only, then MSI PLL mode | LSEON alone is `RCC_LSE_ON_RTC_ONLY`; `RCC_LSE_ON` ("for RCC and peripherals") also sets LSESYSEN and waits for LSESYSRDY (`hal_rcc.h`, `HAL_RCC_OscConfig`) | LSESYSEN set and LSESYSRDY awaited before MSIPLLSEL and MSIPLLEN; without them `lse_ok` is false, so CAN stays off rather than run untrimmed | B1 (clock line), B4 (timebase error), B11 (CAN on) |
| R1 | `board_capture_start` | TIM2 `EGR = UG` with URS = 0, then `SR = 0` | URS = 1 around UG, then `__DSB()` (`TIM_Base_SetConfig`; release notes v1.6.1 and v1.6.3 fix UIF after this step) | URS = 1 kept (only a counter overflow sets UIF), `__DSB()` after UG: a pending UIF would have put every time 2^32 us late | B1 (`tov=0` on the first status lines), B7 |
| R2 | `board_pll1q_20mhz` | waited for VOSRDY only before PLL1ON | then waits for `SVMSR.ACTVOSRDY` (`HAL_PWREx_ControlVoltageScaling`) | waits for ACTVOSRDY and checks that ACTVOS reads range 3 | B11 |
| R3 | `i2c_u575.c` error path | after a NACK or bus error: no STOP if STOPF never came, TXDR left as it was | generates STOP when the bus stays busy, flushes TXDR (`I2C_IsErrorOccurred`, `I2C_Flush_TXDR`) | `recover()` does both. The start-up probe NACKs at the absent TMP117 and IMU addresses on every boot, so this path runs each time | B1 (IMU and TMP117 found after the NACKs), B12 |
| R4 | `board_init` | DBP set, not read back, before LSEON | polls DBP (`HAL_RCC_OscConfig`) | bounded poll | B1 |
| R5 | `gpio_mode` | MODER before AFR: each pin briefly in AF0 | AFR before MODER (`HAL_GPIO_Init`) | AFR, OTYPER, PUPDR, OSPEEDR, then MODER: PD1 never drives FDCAN1_TX with another function on its way to AF9 | B11, E1 (scope on TX through a reset) |
| R6 | `uart_init` | USART1 used at once after UE | waits for TEACK and REACK (`UART_CheckIdleState`) | bounded wait | B1 |
| R7 | `flash_u575.c` | bank 2 assumed at 0x08100000 | the bank map depends on option SWAP_BANK (`hal_flash.h`) | erase and program refused with SWAP_BANK set; the banner says the internal log is refused | B9 (banner) |
| R8 | `spi1_init` | CFG1 written whole, clearing CRCSIZE | keeps CRCSIZE when the CRC is unused (`HAL_SPI_Init`) | kept | B1 (NOR JEDEC id) |
| R9 | fault record in SRAM1 | assumed to survive a reset | option SRAM_RST = 0 erases SRAM1 on a system reset (`hal_flash.h`) | read at start and printed: `chip: ... fault record kept across reset` or `lost on reset (SRAM_RST = 0)` | B1 |
| - | `can_monitor_init` | divided by the bit rate before checking it is not zero | (not a HAL item) | checked first | none (500 kbit/s fixed) |
| - | `main_u575.c` banner | silicon revision unknown | `HAL_GetREVID` (DBGMCU_IDCODE.REV_ID) | printed (`chip: rev 0x....`): it selects the ES0499 errata that apply. On revision X parts ST notes that the MSI PLL unlock and LSE CSS lines do not exist, so a later loss of lock is not reported | B1 |

## 2. Same as ST's sequence

Clock enables with read-back; reset flags and their clearing; IWDG start (key sequence, prescaler /64, reload 1000, about 2 s on a 32 kHz LSI); MSIPLLSEL before MSIPLLEN, after LSERDY; PLL1 from MSIS 4 MHz, M 1, N 40, Q 8 (160 MHz VCO, 20 MHz PLL1Q), PLL1QEN, FDCANSEL = PLL1Q; TIM2 as a 32-bit counter, PSC 3, input capture on CH1/CH3/CH4 with an 8-sample filter (2 us) on falling edges, flags cleared with rc_w0 writes; flash keys, page erase in bank 2 (8 KiB pages, 128 per bank on the 2 MB part, BKER, PNB, PER, STRT), quad-word programming with interrupts off, error flags cleared, ECC flag cleared; USART1 BRR 35 from 4 MHz (114,286 baud, 0.8 % low); FDCAN1 message RAM layout (RX FIFO 0 at 0xB0, 72-byte elements), init and configuration-change sequence, bus monitoring (MON), DAR, bit timing 40 tq at 87.5 %, RX FIFO 0 get index and acknowledge; SPI1 TSIZE, SPE, CSTART, TXP/RXP, EOT and close; I2C1 TIMINGR written with PE = 0, transfer configuration in CR2, NACK checked before RXNE; unique id; non-secure register aliases (no `-mcmse`; the disassembly shows the non-secure addresses). Details and HAL lines: [`reference/u575_hal_audit.md`](reference/u575_hal_audit.md) section 2.

## 3. Open until RM0456, DS13737 and ES0499 are read

Each is a question about the silicon that ST's drivers do not answer. The bench step named checks the consequence, not the cause.

| Question | Code it affects | Bench |
|---|---|---|
| Does MSI PLL mode need LSESYSEN (D1), and which MSIS ranges and LSE drive level does PLL mode allow? | `board_init` | B1, B4 |
| Is PLL1 allowed in range 4, and a 160 MHz VCO and a 20 MHz PLL1Q in range 3? Is the ACTVOSRDY wait mandatory? | `board_pll1q_20mhz` | B11 |
| Reset values of RCC_CCIPR1 (USART1SEL, I2C1SEL, SPI1SEL, FDCANSEL) and of the APB prescalers, on which the 4 MHz kernel clocks and TIM2's 1 MHz depend | all drivers | B1, B4 |
| Is CCxIF cleared by reading CCRx on the U5? Does URS = 1 still set UIF on overflow? | `TIM2_IRQHandler`, `board_capture_start` | B3, B7 |
| Factory values of the options IWDG_SW, SRAM_RST and SWAP_BANK; with SWAP_BANK = 1, does BKER name the physical or the mapped bank? | `board_init`, `flash_u575.c` | B1 banner |
| FLASH_ECCR.ADDR_ECC units and BK_ECC meaning; page-erase and quad-word program times; behaviour of a read of bank 2 while bank 2 is busy | `NMI_Handler`, `flash_u575.c` | B8, B9 |
| FDCAN: any ratio required between the APB clock (4 MHz) and the kernel clock (20 MHz); behaviour in bus monitoring when an FD frame arrives | `can_u575.c` | B11 |
| SPI CFG1.CRCSIZE reset value and its effect with the CRC off | `spi1_init` | B1 |
| I2C timing formula (SCLDEL, SDADEL limits with the analog filter) at 4 MHz; whether a STOP follows a NACK with AUTOEND = 0 | `i2c_u575.c` | B12 |
| What a pin in AF mode with an AF number that has no function drives; 5 V tolerance per pin | `gpio_mode`, the connection table | B0, E1 |
| MSI accuracy untrimmed and in PLL mode; LSE start-up time; LSI range (the real watchdog timeout) | clock, CAN, IWDG | B4, B11 |
| ES0499: the silicon revision on the board and the errata for MSI PLL mode, LSE, voltage scaling, flash (ECC, read while write, bank swap), TIM input capture and UIF, IWDG, FDCAN, SPI, I2C, USART, GPIO | all | B1 (`chip: rev`) |

## 4. Noted, not changed

* The link pulls newlib's start file `crt0.o`, whose `exit` path brings in the stdio stubs (`_close`, `_lseek`, `_read`, `_write` "not implemented" warnings). `main` never returns, so they are never called; the reset handler is the image's entry.
* The IWDG is not frozen when a debugger halts the core: with a debugger attached, a halt resets the board after about 2 s.
* A second capture between the TIM2 status read and the capture-register reads is reported as an overrun only on the next edge (diagnostic counters only).
* The flash is not locked again after an operation (ST's HAL also leaves it to the caller).
