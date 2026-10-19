# Document checks: record

The answers to the document checks of `bench.yaml` (DC01 to DC17), against the firmware of the bench candidate
`b734667`. Line numbers are at that commit. A check is complete only when its conclusion comes from the named document,
with that document's revision and page or section. A header file, ST's HAL, a board description or a simulated test
does not complete a check; such sources are noted as secondary. A discrepancy is fixed in the code, the relevant tests
are rerun, and the fix commit is written here. That commit also makes a new bench candidate.

**Status (2026-10-19): every check is open.** RM0456, DS13737, ES0499 and UM2861 are not in the repository, and
www.st.com is refused by this environment's network policy (last attempt 2026-10-19 01:01 UTC, proxy 403). Commit the
PDFs to `docs/reference/datasheets/` as `st-rm0456-stm32u5.pdf`, `st-ds13737-stm32u575.pdf`,
`st-es0499-stm32u575-errata.pdf` and `st-um2861-nucleo-u575zi-q.pdf`.

## 1. Before flashing: the minimal internal-flash procedure (M0, M1)

| Check | Document | Revision | Page or section | Affected code at `b734667` | Conclusion | Status |
|---|---|---|---|---|---|---|
| DC01 | UM2861 | | | `uart_u575.c:17` (`uart_init`, USART1 on PA9/PA10, AF7); connection rows `usb`, `wheel_0` (Arduino A0), `gen_gnd` | | open. Secondary: ST's board support package `stm32u5xx-nucleo-bsp` v1.2.3 (board MB1549C) puts COM1 on USART1 PA9/PA10 AF7 and LD1/LD2 on PC7/PB7; A0 = PA3 comes from Zephyr's board description only |
| DC02 | DS13737 | | | `board_u575.c:150` (`board_capture_start`: PA3, PA2, PA0 in AF1 with pull-up) | | open |
| DC03 | DS13737 | | | `board_u575.c:138` (`WHEEL_PIN`), `:150`; `uart_u575.c:17` | | open |
| DC04 | RM0456 | | | `board_u575.c:85` to `118` (`board_init`: LSESYSEN at `:110`, MSI PLL mode); `board_u575.c:154` (TIM2 prescaler from the 4 MHz clock) | | open |
| DC05 | RM0456 | | | `board_u575.c:148` to `170` (`board_capture_start`: URS, PSC, input filter, edge polarity, UG); `main_u575.c:40` (`TIM2_IRQHandler`) | | open |
| DC06 | RM0456 | | | `flash_u575.c:14` (keys), `:47` `f_erase`, `:61` `f_program`, `:78` `f_read`, `:29` `f_busy` | | open |
| DC07 | RM0456 | | | `flash_u575.c:95` (`NMI_Handler`, FLASH_ECCR) | | open |
| DC08 | RM0456 | | | `flash_u575.c:45` (`swapped`); `board_u575.c:93`, `:94` (SRAM_RST, SWAP_BANK) | | open |
| DC09 | DS13737 | | | `board_u575.c:71` (`watchdog_start`: prescaler /64, reload 1000) | | open |
| DC10 | ES0499 | | | `board_u575.c:95` (silicon revision read); every driver | | open |

## 2. Before external NOR use (Winbond W25Q128JV; full bench B0 and B7)

Not part of the minimal procedure: nothing is wired to SPI1, and the firmware then logs to internal flash bank 2 (the
M1 banner says so). These checks need the Winbond data sheet (`winbond-w25q128jv.pdf`); www.winbond.com is refused
here too.

| Check | Revision | Page or section | Affected code at `b734667` | Conclusion | Status |
|---|---|---|---|---|---|
| DC11 | | | `spi_u575.c:2`, `:86` (mode 0, 2 MHz) | | open |
| DC12 | | | `tm_w25q.c:92` (JEDEC id check) | | open |
| DC13 | | | `tm_w25q.c:3` to `11` (commands, status bits), `wren` | | open |
| DC14 | | | `tm_w25q.c:8` (chip erase); the host model's erase and program times | | open |
| DC15 | | | `tm_w25q.c:9` (Read Data); connection row `nor_wp_hold` | | open |

## 3. Before CAN and I2C (full bench B11 and B12)

| Check | Document | Revision | Page or section | Affected code at `b734667` | Conclusion | Status |
|---|---|---|---|---|---|---|
| DC16 | RM0456 | | | `board_u575.c:184` (`board_pll1q_20mhz`) | | open |
| DC17 | RM0456 | | | `i2c_u575.c:82`, `:87` (TIMINGR) | | open |
