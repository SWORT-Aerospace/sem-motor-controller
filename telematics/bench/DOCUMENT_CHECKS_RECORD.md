# Document checks: record

The answers to the document checks of `bench.yaml` (DC01 to DC17). A check is complete only when its conclusion
comes from the named document, with its revision and page or section. A header file, ST's HAL, a board description or
a simulated test does not complete a check; such sources are noted as secondary. A discrepancy is fixed in the code,
the relevant tests are rerun, and the fix is named here. A document answers what the board and silicon should be. It
does not show that the board on the bench matches: that is checked at M0 and M1 on the results form.

## Documents read

| Document | Revision | File received | SHA-256 |
|---|---|---|---|
| UM2861, STM32U5 Nucleo-144 board (MB1549) user manual | Rev 10, March 2025 | `dm00789949.pdf`, 52 pages | `2ad8e32398e92f2a2d803c7c436bbe85bd15d4c187df5d3fc57840159da977e2` |
| ES0499, STM32U575xx and STM32U585xx device errata | Rev 12, June 2026 | `es0499-stm32u575xx-and-stm32u585xx-device-errata-stmicroelectronics.pdf`, 51 pages | `52dac38c801ae72c42ebffd39296ddf7c80ae378cd555f1a1d1baf49daf86a56` |

Both were provided by the team on 2026-10-19 and read locally; they are not committed to the repository. **RM0456 and
DS13737 were not provided**, and www.st.com is refused by this environment's network policy. The page numbers below
are the printed page numbers.

## Applicability: which board and silicon

A NUCLEO-U575ZI-Q is one of four products (UM2861 Rev 10, Table 21, page 42; ES0499 Rev 12, Table 2, cover page):

| Product identification (sticker) | Main board | Silicon revision | REV_ID (banner `chip: rev`) |
|---|---|---|---|
| NUU575ZIQ$AT1 | MB1549-U575ZIQ-C02 | X | 0x2001 |
| NUU575ZIQ$AT2 | MB1549-U575ZIQ-C03 | X | 0x2001 |
| NUU575ZIQ$AT3 | MB1549-U575ZIQ-C05 | W | 0x3001 |
| NUU575ZIQ$AT4 | MB1549-U575ZIQ-C05 | U | 0x3007 |

The board on the bench is not known here. M0 records the sticker; M1 records the banner's REV_ID; they must agree.
Every errata conclusion below states the revisions it applies to. Firmware line numbers are at the bench candidate
that carries the two fixes of this record (the commit after `0fadcef`).

## 1. Before flashing: the minimal internal-flash procedure (M0, M1)

| Check | Document | Revision | Page or section | Affected code | Conclusion | Status |
|---|---|---|---|---|---|---|
| DC01 | UM2861 | Rev 10 | Table 17, p. 35; Table 18, p. 35; Table 20, pp. 39 to 40; Table 10, p. 29; section 3.1, p. 4; Table 6, p. 14; Table 4, p. 7; section 7.4.1, pp. 17 to 18; section 7.5, p. 25; section 7.6, p. 26; section 7.7.1, p. 27; Table 22, p. 43 | `uart_u575.c:17` (USART1 PA9/PA10, AF7); `board_u575.c:161` (`WHEEL_PIN`); `board_u575.c` `board_led` (PC7, PB7); connection rows `usb`, `wheel_0`, `wheel_1`, `wheel_2`, `gen_gnd` | A0 = PA3 at CN9 pin 1, A1 = PA2 at CN9 pin 3, GND at CN9 pins 12 and 23 (Table 17). PA2 also reaches CN10 pin 13 (SB56 and SB57 both ON by default, Table 20). PA0 is at CN10 pin 29 (Table 18); the user button is on PC13 by default (SB58 ON, SB59 OFF, section 7.6). USART1 PA9/PA10 reaches the ST-LINK virtual COM port with SB32 and SB34 ON, the default (Table 10). LD1 is PC7, LD2 PB7 (section 7.5). The X2 32.768 kHz crystal is fitted by default (R32, R33 ON; SB51, SB52 OFF; section 7.7.1). Power by default: JP6 [1-2] takes 5V_STLK from the ST-LINK connector CN1; the board is powered only after USB enumeration, and LD5 shows it (section 7.4.1, Table 4). **CN1 is USB Micro-B** (section 3.1, Table 6). The firmware agrees. Three documentation discrepancies were fixed: the BOM's USB-C cable is now Type-A or Type-C to Micro-B; the flash commands set SWD to 8 MHz, as Table 22 recommends for every MB1549 revision; and the positions marked "locate" now come from Tables 15, 17 and 18 | complete (documentary). The physical board is checked at M0 |
| DC02 | DS13737 | | | `board_u575.c:173` (`board_capture_start`: PA3, PA2, PA0 in AF1 with pull-up) | Not answerable from these documents. UM2861 Table 4 (p. 7) gives VDD = 3.3 V by default (JP4 [1-2]), so a 0 to 3.3 V generator stays within VDD. The pin's absolute maximum, its I/O structure, VIL and VIH, and the pull-up range are in DS13737 | open |
| DC03 | DS13737 | | | `board_u575.c:161`, `:173`; `uart_u575.c:17` | Not answerable. UM2861 lists TIM2_CH1 as PA0's MCU function on CN10 (Table 18) and USART1 on PA9/PA10 (Table 10), but the alternate-function numbers (AF1, AF7) are in DS13737. Secondary: ST's board support package uses `GPIO_AF7_USART1` for PA9/PA10 | open |
| DC04 | RM0456 | | | `board_u575.c:94` to `141` (`board_init`: LSE drive, LSE start, LSESYSEN, MSI PLL mode); `board_u575.c:177` (TIM2 prescaler) | **Discrepancy found and fixed.** The firmware never set the LSE drive. ES0499 Rev 12 sections 2.2.3 and 2.2.16 (pp. 8 and 13) forbid the low and medium-low drives on revision X. Medium-high is now set before LSEON, with the LSE switched off first if a previous program left it on at a lower drive or in bypass. Also open from ES0499 2.2.27 (p. 16), status P on X, W and U: a spurious MSI PLL unlock degrades the timebase to untrimmed MSI. ST's workaround needs the unlock interrupt, and the vendored device header has no flag for it, so it is not implemented; M4's speed check is the bench's detection. Reset values, PLL-mode rules and the drive level needed by the X2 crystal need RM0456 (and DS13737 for the oscillator's transconductance) | open (one fix made) |
| DC05 | RM0456 | | | `board_u575.c:171` (`board_capture_start`); `main_u575.c:40` (`TIM2_IRQHandler`) | ES0499 Rev 12 lists no erratum on TIM input capture, flag clearing or update events. The two TIM limitations (2.16.1 break, 2.16.2 ocref_clr, p. 28) concern functions the firmware does not use. The register behaviour itself needs RM0456 | open (errata part: none apply) |
| DC06 | RM0456 | | | `flash_u575.c:14` (keys), `:29` `f_busy`, `:47` `f_erase`, `:61` `f_program`, `:78` `f_read` | ES0499 2.2.25 (p. 15; A on X, W, U): programming stays stuck if STRT is set while WDW is set. `f_busy` treats BSY or WDW as busy (`flash_u575.c:33`), `f_erase` and `f_program` refuse to start while busy, and each quad-word is written with interrupts off, so the driver never produces that condition. No change. Keys, page erase, quad-word programming and read while busy need RM0456 | open (errata part: complies) |
| DC07 | RM0456 | | | `flash_u575.c:95` (`NMI_Handler`, FLASH_ECCR) | ES0499 lists no flash-ECC erratum. Documentation erratum 2.2.23 (p. 15) concerns SRAM ECC, which the firmware does not use. ECCR semantics need RM0456 | open (errata part: none apply) |
| DC08 | RM0456 | | | `flash_u575.c:45` (`swapped`); `board_u575.c:102`, `:103` | ES0499's option-byte items (2.2.17, 2.2.18: bootloader and RSS with TZEN or RDP) concern functions not used. UM2861 Table 21 notes for $AT1 that the bootloader interfaces are unavailable with TZEN = 1, which is not used. Factory option values need RM0456 | open |
| DC09 | DS13737 | | | `board_u575.c:80` (`watchdog_start`: prescaler /64, reload 1000) | ES0499 2.18.1 (IWDG in Stop mode, p. 30) does not apply: no Stop mode. 2.18.2 (p. 30; P on X, W, U: the IWDG stops while BDRST is set) does not apply: the firmware never sets BDRST. Flash erase and program times and the LSI range need DS13737 | open (errata part: none apply) |
| DC10 | ES0499 | Rev 12 | Table 2, cover page; Table 3, pp. 2 to 5; sections as listed in section 4 below | every driver; `board_u575.c:104` (REV_ID in the banner) | Every limitation for the functions the minimal image uses is reviewed in section 4, per silicon revision. Two firmware discrepancies were fixed: the LSE drive (2.2.3, 2.2.16) and the I2C bus-error handling (2.20.2). Two procedure rules were added: do not press the blue user button B1 (2.2.1), and keep the board unpowered at least 10 s in M3 (2.2.9). One item stays open: the 2.2.27 MSI PLL unlock workaround | complete for the minimal image; 2.2.27 open |

## 2. Before external NOR use (Winbond W25Q128JV; full bench B0 and B7)

Not part of the minimal procedure. Nothing is wired to SPI1 there, and the firmware logs to internal flash bank 2 (the
M1 banner says so). These checks need the Winbond data sheet (`winbond-w25q128jv.pdf`); www.winbond.com is refused
here. ES0499 does bear on the SPI side of these steps: 2.23.1 (p. 35) is met, since CRCSIZE is kept at its reset
value with CRC off (`spi_u575.c:86`), and 2.23.7 (p. 37) is met, since SCK is PCLK/2, the lowest ratio.

| Check | Revision | Page or section | Affected code | Conclusion | Status |
|---|---|---|---|---|---|
| DC11 | | | `spi_u575.c:2`, `:86` (mode 0, 2 MHz) | | open |
| DC12 | | | `tm_w25q.c:92` (JEDEC id check) | | open |
| DC13 | | | `tm_w25q.c:3` to `11` (commands, status bits), `wren` | | open |
| DC14 | | | `tm_w25q.c:8` (chip erase); the host model's erase and program times | | open |
| DC15 | | | `tm_w25q.c:9` (Read Data); connection row `nor_wp_hold` | | open |

## 3. Before CAN and I2C (full bench B11 and B12)

| Check | Document | Revision | Page or section | Affected code | Conclusion | Status |
|---|---|---|---|---|---|---|
| DC16 | RM0456 | | | `board_u575.c:207` (`board_pll1q_20mhz`) | ES0499 2.24.1 and 2.24.2 (p. 37; FDCAN edge filtering, Tx FIFO order) are to be checked against the CAN image's configuration with RM0456; the CAN image does not transmit. UM2861 Table 17 puts PD0/PD1 at CN9 pins 25 and 27 | open |
| DC17 | RM0456 | | | `i2c_u575.c:32` (`wait_flag`), `:90` (TIMINGR) | **ES0499 2.20.2 (p. 32; A on X, W, U): a discrepancy, fixed.** In controller mode a bus error can be flagged spuriously and has no effect on the transfer; the driver used to abort the transfer and now clears the flag and continues (`i2c_u575.c:43`). 2.20.1 (p. 32) is met: standard mode with a 4 MHz kernel clock, the minimum it states. The TIMINGR formula needs RM0456 | open (one fix made) |

## 4. ES0499 Rev 12: every limitation for the functions the minimal image uses

The status letters are the erratum's own for revisions X, W and U (A: workaround available, N: none, P: partial, -:
not applicable).

| Section (page) | Limitation | X / W / U | Firmware or procedure | Conclusion |
|---|---|---|---|---|
| 2.2.1 (p. 7) | LSE disturbed by PC13 transitions on LQFP and UFQFPN | N / N / N | PC13 is never configured; it is the user button B1 (UM2861 section 7.6) | procedure: do not press B1 (M1) |
| 2.2.3 (p. 8) | LSE low drive not functional | N / - / - | LSE drive was never set | **fixed**: medium-high before LSEON (`board_u575.c:119` to `128`) |
| 2.2.16 (p. 13) | LSE medium-low drive not available | N / - / - | as above | **fixed** by the same change |
| 2.2.9 (p. 9) | backup domain reset missed when VBAT and VDD share a source | A / - / - | VBAT through SB50 on the board supply (UM2861 Table 9, p. 24). The firmware rewrites the LSE drive and bypass, and clears LSCOEN (the erratum names LSCO driving PA2, wheel_1's input) | procedure: unpowered at least 10 s in M3 (ST: below 100 mV for over 200 ms). The software erase of the backup domain is not implemented: it needs BDRST, which stops the IWDG (2.18.2) and erases SRAM2 (2.2.24) |
| 2.2.25 (p. 15) | flash programming stuck after a sequence error | A / A / A | the driver never sets STRT while WDW is set | complies; no change |
| 2.2.27 (p. 16) | spurious MSI PLL unlock | P / P / P | the unlock interrupt is not used; no flag for it in the vendored device header | **open**: needs RM0456; M4's speed check detects a timebase error above 0.2 % |
| 2.2.2, 2.2.5, 2.2.11, 2.2.19, 2.2.22, 2.2.26 | Stop, Standby and Shutdown entry and exit | various | the firmware never enters these modes | not applicable |
| 2.2.13, 2.2.24 | PWR_BDCR1 write protection; BDRST erasing SRAM2 | N / N / N; N / - / - | neither register is used | not applicable |
| 2.4.1 (p. 17) | current on I2C pins in Stop 2/3 or with ANFOFF | A / - / - | no Stop mode, ANFOFF not set | not applicable |
| 2.16.1, 2.16.2 (p. 28) | TIM break, ocref_clr | N / N / N | not used | not applicable |
| 2.18.1, 2.18.2 (p. 30) | IWDG in Stop; IWDG stopped by BDRST | N; P | no Stop, no BDRST | not applicable |
| 2.20.1 (p. 32) | I2C data setup shorter than one kernel clock | P / P / P | standard mode, 4 MHz kernel clock | complies (full bench) |
| 2.20.2 (p. 32) | spurious I2C bus error in controller mode | A / A / A | bus errors aborted the transfer | **fixed**: flag cleared, transfer continues (`i2c_u575.c:43`) |
| 2.21.1 (p. 33) | USART data corrupted by a glitch in the stop bit | - / A / A | console RX from the ST-LINK; noise and framing flags ignored | no change: a garbled console command is retyped |
| 2.21.2 to 2.21.7 (pp. 33 to 34) | USART DMA, autonomous mode, smartcard, ABREN, ONEBIT | various | none used | not applicable |
| 2.23.1 (p. 35), 2.23.7 (p. 37) | SPI CRCSIZE; SPI output truncated after EOT | A / A / A | CRCSIZE kept at reset value; SCK = PCLK/2 | complies (the NOR probe at boot; the NOR itself in the full bench) |
| 2.24.x (p. 37) | FDCAN | A / A / A | FDCAN is off in `tm_u575` | not applicable to the minimal image (DC16) |
