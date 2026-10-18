# STM32U575 register-level firmware: audit against ST's HAL/LL v1.6.3

Scope: `telematics/firmware/platform/u575/` as it stood before the corrections (branch `eng/v0.7-telematics`, 2026-10-18). **"Ours f.c:N" line numbers refer to that state, not to the current files.** The corrections made from this audit, and what stays open, are in [`../U575_REGISTER_CHECK.md`](../U575_REGISTER_CHECK.md).
Reference: `STMicroelectronics/stm32u5xx-hal-driver` v1.6.3, commit `2552682ee5a0d6f826a6435750fc9267be65868b`.
The `.c` files given were used, plus these headers/sources fetched from the same commit (GitHub raw only) into
a local working directory (not committed; every file is at the commit above): `stm32u5xx_hal_rcc.h`, `_hal_rcc_ex.h`, `_hal_pwr_ex.h`, `_hal_pwr.c`, `_hal_flash.h`,
`_hal_flash_ex.h`, `_hal_fdcan.h`, `_hal_tim.h`, `_hal_tim_ex.c`, `_ll_tim.c`, `_hal_i2c.h`, `_hal_i2c_ex.c`,
`_ll_i2c.h`, `_hal_spi.h`, `_ll_spi.h`, `_hal_uart.c/.h`, `_hal_iwdg.h`, `_ll_iwdg.h`, `_ll_pwr.h`, `_ll_utils.c`,
`_hal_gpio.c`, `_hal_gpio_ex.h`, `_hal_conf_template.h`.
"HAL x.c:N" means a line in that ST file. "Ours f.c:N" means a line in our file as it is now.

Verdicts: **DEFECT** = differs from ST in a way likely to break behaviour; **RISK** = differs, effect uncertain;
**MATCH** = same as ST, or a different but equivalent sequence. Where the HAL does not cover something, that is said.

Build context, checked: the toolchain file (`cmake/arm-none-eabi-cortex-m33.cmake:8`) does not pass `-mcmse`, so
`stm32u575xx.h:2394` selects the non-secure aliases (TZEN = 0 assumed). The disassembly of `build-u575/*.elf` confirms
it: RCC at 0x46020C00, PWR at 0x46020800, TIM2 at 0x40000000, IWDG at 0x40003000. The flash HAL also uses NSCR/NSSR
when `__ARM_FEATURE_CMSE != 3` (`IS_FLASH_SECURE_OPERATION() == 0`, HAL hal_flash.h:1100). So the alias choice
matches ST.

---

## 1. Summary of findings

| ID | Class | Where (ours) | What |
|---|---|---|---|
| D1 | DEFECT (probable; RM0456 has the final word) | board_u575.c:86-91 | LSE is started with LSEON only. In the HAL that setting is `RCC_LSE_ON_RTC_ONLY`. HAL's `RCC_LSE_ON` (LSE for RCC and peripherals) also sets LSESYSEN and waits for LSESYSRDY. MSI PLL mode may never lock, while `lse_ok` claims it did. |
| R1 | RISK | board_u575.c:137-138 | TIM2: UG is issued with URS = 0 and SR is then cleared. HAL sets URS around UG, then a `__DSB()`, and v1.6.1 and v1.6.3 both fix UIF left set after this step. A pending UIF would offset every timestamp by 2^32 us. |
| R2 | RISK | board_u575.c:164-165 | Voltage scaling: our code waits only for VOSRDY. HAL also waits for SVMSR.ACTVOSRDY. PLL1 can be enabled before range 3 is in force. |
| R3 | RISK | i2c_u575.c:20-30 | I2C error path: no manual STOP if STOPF never comes, and TXDR is not flushed after NACK/BERR/ARLO (HAL does both). The bus can stay BUSY, or a stale byte goes out first in the next write. |
| R4 | RISK (low) | board_u575.c:85 | DBP is set but not read back before LSEON is written (HAL polls DBP). |
| R5 | RISK | board_u575.c:25-30 | GPIO AF config writes MODER before AFR (HAL writes AFR first). The pin briefly runs AF0, including PD1 = FDCAN1_TX on the vehicle bus. |
| R6 | RISK (low) | uart_u575.c:23 | USART1 enabled without waiting for TEACK/REACK (HAL `UART_CheckIdleState`). |
| R7 | RISK | flash_u575.c:50-51 (and :95) | Bank 2 is assumed at 0x08100000 with BKER = 1. With SWAP_BANK = 1, the "bank 2" at 0x08100000 is not the bank that BKER = 1 erases, so the erase could hit the code bank. Nothing checks FLASH_OPTR.SWAP_BANK. |
| R8 | RISK (low) | spi_u575.c:85 | `CFG1` is overwritten, which clears CRCSIZE. HAL deliberately keeps the reset CRCSIZE when CRC is unused. |
| R9 | RISK | board_u575.c:10-13, stm32u575zi_flash.ld:17-18 | The fault record is in SRAM1 `.noinit`. HAL documents option `SRAM_RST = 0` as "all SRAMs (except SRAM2 and BKPSRAM) erased when a system reset occurs". The record (and the ECC pause) only survives if the option bit is 1. |

All other register accesses are MATCH (tables in section 2). Non-register remarks are in section 6.

---

## 2. File-by-file comparison

### 2.1 system_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :5 | `SystemCoreClock = 4000000` | HAL rcc_ex.c:3426 "RCC_MSIRANGE_4 Range 4 around 4 MHz (reset value)"; hal_conf_template.h:115 `MSI_VALUE 4000000` | MATCH |
| :10 | SCB->CPACR CP10/CP11 | CMSIS core, not a HAL driver (ST's `system_stm32u5xx.c` is in cmsis-device-u5, outside the allowed source) | not compared |
| :11 | VTOR = FLASH_BASE_NS | same; consistent with the linker script | not compared |

### 2.2 board_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :25-30 | GPIO: MODER, then OTYPER, PUPDR, OSPEEDR, AFR | HAL gpio.c:253-271 (AF branch): AFR written at :264 **before** MODER at :270; OSPEEDR :295, OTYPER :301, PUPDR :314 after MODER | **R5** |
| :47-48 | BSRR, then MODER = output | HAL_GPIO_Init does not touch ODR; setting the level first avoids a glitch | MATCH |
| :61-67 | IWDG: KR=CCCC, KR=5555, PR=4, RLR=1000, wait SR==0, KR=AAAA | HAL iwdg.c:218 start, :222 write access, :225-226 PR/RLR, :233 EWCR=EWIC (EWI off), :247 wait `SR & (EWU|WVU|RVU|PVU)`, :263-271 WINR only if different, else reload | MATCH (EWCR not written; reset value already has EWIE = 0) |
| :74-75 | read RCC_CSR, then `CSR |= RMVF` | HAL hal_rcc.h:4687 `__HAL_RCC_CLEAR_RESET_FLAGS() (RCC->CSR |= RCC_CSR_RMVF)`; rcc.c:1998-2001 | MATCH |
| :78 | AHB2ENR1 GPIOA..D (read back through the AHB3ENR read at :80) | hal_rcc.h:1376-1382 pattern: SET_BIT, then a read-back "Delay after an RCC peripheral clock enabling" | MATCH (the RCC read after the write gives the same ordering) |
| :79-80 | AHB3ENR.PWREN + read back | hal_rcc.h:1376-1382 | MATCH |
| :85 | `PWR->DBPR |= DBP` | HAL rcc.c:892-906: SET_BIT, then `while (HAL_IS_BIT_CLR(PWR->DBPR, PWR_DBPR_DBP))` with `RCC_DBP_TIMEOUT_VALUE` (hal_rcc.h:201) | **R4** |
| :86 | `BDCR |= LSEON` | HAL rcc.c:921 | MATCH (LSEBYP not cleared; HAL rcc.c:514-516 says bypass transitions need LSE off first; only matters if earlier firmware set LSEBYP) |
| :87 | wait for LSERDY, 3,000,000 polls | HAL rcc.c:936-941, `RCC_LSE_TIMEOUT_VALUE = LSE_STARTUP_TIMEOUT` = 5000 ms (hal_conf_template.h:160). The compiled loop is 5 instructions including an RCC read, so about 6 s at 4 MHz | MATCH |
| (missing) | LSESYSEN + LSESYSRDY | HAL rcc.c:944-956 sets LSESYSEN and waits for LSESYSRDY when `RCC_LSE_ON` is requested; :958-969 clears it for `RCC_LSE_ON_RTC_ONLY` | **D1** |
| :89 | `CR |= MSIPLLSEL` (with MSIPLLEN still 0) | HAL rcc_ex.c:3333-3338: written only while `MSIPLLEN == 0` | MATCH |
| :90 | `CR |= MSIPLLEN` after LSERDY | LL ll_rcc.h:2080-2083 "MSIPLLEN must be enabled after LSE is enabled (LSEON enabled) and ready (LSERDY set by hardware)"; HAL rcc_ex.c:3680-3687 | MATCH (but see D1) |
| :97-98 | LED BSRR | LL semantics | MATCH |
| :105-106 | read CNT, then SR.UIF, IRQs masked | not covered by the HAL; logic is right with `tm_time_extend` | n/a |
| :125 | PA0/2/3 AF1, pull-up | hal_gpio_ex.h:78 `GPIO_AF1_TIM2 0x01` | MATCH (order: R5) |
| :126-127 | APB1ENR1.TIM2EN + read back | hal_rcc.h:1460-1466 | MATCH |
| :128 | CR1 = 0 (up-counting, CKD = 0, ARPE = 0) | HAL tim.c:7260-7283 | MATCH |
| :129 | PSC = 3 | HAL tim.c:7287 | MATCH (1 MHz at 4 MHz with APB1 /1) |
| :130 | ARR = 0xFFFFFFFF | TIM2 is 32-bit: stm32u575xx.h:23752 `IS_TIM_32B_COUNTER_INSTANCE` includes TIM2 | MATCH |
| :132-134 | CCMR1/CCMR2: CCxS = 01, ICxF = 0011 | HAL tim.c:7874-7915 / 8083-8113 / 8140-8172; LL ll_tim.h:858 `LL_TIM_IC_FILTER_FDIV1_N8 = IC1F_1|IC1F_0` ("fSAMPLING=fCK_INT, N=8"), ll_tim.h:834 DIRECTTI = CC1S_0 | MATCH. HAL clears CCxE before writing CCMR (tim.c:7884); ours relies on CCER = 0 after reset, which holds because this runs once |
| :136 | CCER: CCxE + CCxP, CCxNP = 0 | ll_tim.h:879 `LL_TIM_IC_POLARITY_FALLING = TIM_CCER_CC1P`; hal_tim.h:671 | MATCH |
| :137-138 | `EGR = UG; SR = 0` (URS = 0) | HAL tim.c:7297 `SET_BIT(TIMx->CR1, TIM_CR1_URS)`, :7301 `EGR = UG`, :7304 `__DSB()`, :7306 restore CR1; Release_Notes.html:159 (v1.6.3) "Fix UIF flag set after TIM_Base_SetConfig()", :365 (v1.6.1) "Fix update flag (UIF) clearing in TIM_Base_SetConfig" | **R1** |
| :140 | DIER = CC1IE, CC3IE, CC4IE, UIE | HAL_TIM_IC_Start_IT / Base_Start_IT enable the same bits | MATCH |
| :141-143 | NVIC priority/enable, then CEN | - | MATCH |
| :149-154 | UID words at UID_BASE, +4, +8 | HAL hal.c:487-507 `HAL_GetUIDw0/1/2` | MATCH |
| :164 | `VOSR.VOS = 01` | hal_pwr_ex.h:265 `PWR_REGULATOR_VOLTAGE_SCALE3 = PWR_VOSR_VOS_0` | MATCH (value) |
| :165 | wait for VOSRDY only | HAL pwr_ex.c:378-384 waits VOSRDY, **then** :388-394 `while (HAL_IS_BIT_CLR(PWR->SVMSR, PWR_SVMSR_ACTVOSRDY) ...)` | **R2** |
| :166-167 | PLL1CFGR = SRC MSIS, RGE 00, M = 1, MBOOST /1, QEN | hal_rcc.h:4456-4468 `__HAL_RCC_PLL_CONFIG` (M-1, SRC field at Pos 0, MBOOST); hal_rcc.h:357 `RCC_PLLVCIRANGE_0 = 0`; ll_rcc.h:1072 "4 to 8 MHz"; hal_rcc.h:341 `RCC_PLLMBOOST_DIV1 = 0`. HAL first disables the PLL and waits (rcc.c:1161-1172) and clears BOOSTEN (rcc.c:1181-1186); after reset the PLL is off and BOOSTEN = 0, so this is equivalent. FRACN: HAL rcc.c:1199-1206; ours FRACEN = 0, integer mode | MATCH |
| :168-169 | PLL1DIVR: N-1 = 39, P = 2, Q = 8, R = 2 | hal_rcc.h:4460-4467 (field = value - 1) | MATCH: VCO 160 MHz, inside ll_utils.c:52-53 (64-344 MHz); PLL1Q = 20 MHz |
| :170-171 | PLL1ON, wait PLL1RDY | HAL rcc.c:1226, 1231-1237 | MATCH |
| - | QEN set before PLL1ON | HAL rcc_ex.c:1113-1116 `__HAL_RCC_PLLCLKOUT_ENABLE(RCC_PLL1_DIVQ)` (hal_rcc.h:331, 4394), no ordering constraint | MATCH |
| :172 | CCIPR1.FDCANSEL = 01 (PLL1Q) | ll_rcc.h:627-629 (00 HSE, 01 PLL1Q, 10 PLL2P); hal_rcc_ex.h:791, 1470-1471; rcc_ex.c:1129-1130 | MATCH |

### 2.3 main_u575.c (TIM2_IRQHandler)

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :45 | read SR | HAL tim.c:3846-3849 (reads SR and DIER) | MATCH |
| :47-49 | read CCR4/3/1 (reading clears CCxIF) | HAL clears CCxIF explicitly, before the callback: tim.c:3857 `__HAL_TIM_CLEAR_FLAG(htim, TIM_FLAG_CC1)` | MATCH (an equivalent method; it depends on the RM rule "CCxIF cleared by reading CCRx", question Q7) |
| :50 | re-read SR.UIF after the CCR reads | not in the HAL; the ordering is right for `tm_time_extend` | n/a |
| :65 | `SR = ~clear` (rc_w0) | hal_tim.h:1440 `#define __HAL_TIM_CLEAR_FLAG(...) ((__HANDLE__)->Instance->SR = ~(__FLAG__))` | MATCH |

### 2.4 flash_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :14-15 | keys | hal_flash.h:620-621 `FLASH_KEY1 0x45670123U`, `FLASH_KEY2 0xCDEF89ABU` | MATCH |
| :23-26 | unlock if NSCR.LOCK | HAL flash.c:453-457; HAL also re-reads LOCK (:460) | MATCH (no re-check; a failed unlock shows up as a PGSERR/WRPERR error on the next `busy()`) |
| :32-33 | busy = NSSR.BSY or WDW | HAL flash.c:730 `while (((*reg_sr) & (FLASH_FLAG_BSY | FLASH_FLAG_WDW)) != 0U)` | MATCH |
| :34 | clear PG and PER when not busy | HAL flash.c:206 (PG after programming), flash_ex.c:240 (PER after erasing) | MATCH |
| :35-38 | write 1 to clear the error bits | hal_flash.h:177-179 `FLASH_FLAG_SR_ERRORS` (non-secure set: OPERR, PROGERR, WRPERR, PGAERR, SIZERR, PGSERR, OPTWERR); flash.c:745-753 `(*reg_sr) = error` | MATCH (OPTWERR omitted; no option-byte work here) |
| :39 | clear EOP | HAL flash.c:765-768 | MATCH |
| :46, :49 | page = (addr - 0x08100000) / 8192, 0..127 | hal_flash.h:1000 `IS_FLASH_PAGE(PAGE) ((PAGE) < FLASH_PAGE_NB)`; stm32u575xx.h:8142-8150 FLASH_SIZE (2 MB on this part), `FLASH_BANK_SIZE = FLASH_SIZE >> 1`, `FLASH_PAGE_SIZE 0x2000`, `FLASH_PAGE_NB = BANK_SIZE / PAGE_SIZE` = 128 | MATCH |
| :50-52 | NSCR: BKER, PNB, PER; then STRT | HAL flash_ex.c:938-947: `SET_BIT(BKER)`, then `MODIFY_REG(PNB|PER|STRT, Page<<PNB_Pos | PER | STRT)` | MATCH (STRT written separately, after PER/PNB; both orders are valid) |
| - | assumes SWAP_BANK = 0 | hal_flash.h:444-447 "OB_SWAP_BANK_DISABLE: Bank 1 at offset 0x0, Bank 2 at 0x100000; OB_SWAP_BANK_ENABLE: Bank 1 at 0x100000, Bank 2 at 0x0" | **R7** |
| :59 | 16-byte alignment, n = 16 | HAL flash.c:157-158 "Address ... shall be aligned to the Flash word (128 bits)"; "DataAddress ... shall be 32-bit aligned" (our local `w[]` is) | MATCH |
| :64 | NSCR.PG = 1 (PER cleared) | HAL flash.c:796 `SET_BIT((*reg_cr), FLASH_NSCR_PG)` | MATCH |
| :65-69 | IRQs off, four 32-bit stores | HAL flash.c:799-813 | MATCH (disassembly: four separate `str`, no wider access) |
| :92-96 | read ECCR; `ECCR = e | ECCD` | hal_flash.h:864-867 `SET_BIT(FLASH->ECCR, ...ECCR_ERRORS)` | MATCH for clearing. The HAL has no ECC-address decode, so the ADDR_ECC/BK_ECC interpretation at :95 is unverified (Q10c) |

### 2.5 uart_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :17-18 | PA9/PA10 AF7 | hal_gpio_ex.h:172 `GPIO_AF7_USART1 0x07` | MATCH (order: R5) |
| :19-20 | APB2ENR.USART1EN + read back | clock-enable macro pattern | MATCH |
| :21 | CR1 = 0 (UE = 0) | HAL uart.c:351 `__HAL_UART_DISABLE` | MATCH |
| :22 | BRR = 35 | HAL uart.c:3286-3289 `UART_DIV_SAMPLING16` (hal_uart.h:1260-1261: `((pclk/presc) + baud/2) / baud`) = (4,000,000 + 57,600) / 115,200 = 35. That gives 114,286 baud, -0.79 %. `UART_BRR_MIN 0x10` (uart.c:189) is respected. Kernel clock: ll_rcc.h:462 `LL_RCC_USART1_CLKSOURCE_PCLK2` = USART1SEL 00 | MATCH |
| :23 | CR1 = TE, RE, UE | HAL uart.c:372 enable, then :375 `UART_CheckIdleState`, which waits for TEACK (:3403-3404) and REACK (:3421-3422) | **R6** |
| :28-29, :49-51 | TXE_TXFNF, then TDR | FIFO disabled, so TXE semantics apply | MATCH |
| :58 | ORE cleared through ICR.ORECF | HAL clears ORE through ICR | MATCH |
| :59-60 | RXNE_RXFNE, then RDR | - | MATCH |

### 2.6 can_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :24-26 | RF0 at 0x0B0, 72-byte elements, RAM size 0x350 | HAL fdcan.c:211-235: FLS 28 x 4 B, FLE 8 x 8 B, giving RF0SA = 112 + 64 = 0xB0; RF0 3 x 72 B; RF1SA 0x188; TEFSA 0x260; TFQSA 0x278; SRAMCAN_SIZE 0x350. Base: fdcan.c:3421 `SramCanInstanceBase = SRAMCAN_BASE` (= APB1 + 0xAC00, stm32u575xx.h:1683) | MATCH |
| :46-47 | APB1ENR2.FDCAN1EN + read back, **after** FDCANSEL | HAL MspInit order (kernel clock config, then bus clock) | MATCH |
| :48-49 | PD0/PD1 AF9 | hal_gpio_ex.h:204 `GPIO_AF9_FDCAN1 0x09` | MATCH (order: R5) |
| :50-51 | clear CSR, wait for CSA = 0 | HAL fdcan.c:365, 371-383 | MATCH |
| :52-53 | INIT = 1, wait for INIT | HAL fdcan.c:386, 392-404 | MATCH |
| :54 | CCE = 1 (no acknowledge wait) | HAL fdcan.c:408 (no wait either) | MATCH |
| :55 | FDCAN_CONFIG->CKDIV = 0 (with INIT and CCE set) | HAL fdcan.c:411; hal_fdcan.h:560 `FDCAN_CLOCK_DIV1 0` | MATCH |
| :56-57 | CCCR: clear FDOE, BRSE, TEST, ASM; set MON, DAR | HAL fdcan.c:414-421 DAR, :433-441 PXHD, :444 frame format, :447 clears TEST/MON/ASM, :479-482 `SET_BIT(CCCR, MON)` for bus monitoring | MATCH (PXHD left 0, which is HAL `ProtocolException = ENABLE`) |
| :58-59 | NBTP = (SJW-1)<<25, (BRP-1)<<16, (TSEG1-1)<<8, (TSEG2-1) | HAL fdcan.c:490-493; ranges at hal_fdcan.h:1325-1328. 500 kbit/s: 40 tq, TSEG1 34, TSEG2 5, SJW 5, NBTP = 0x08002104, sample point 87.5 % | MATCH |
| :60 | clear the message RAM in 32-bit words | HAL fdcan.c:3448-3451 | MATCH |
| :62 | RXGFC = ANFS 0, ANFE 0, RRFS, RRFE; LSS = LSE = 0; F0OM = 0 | HAL fdcan.c:1388-1395; hal_fdcan.h:768 `FDCAN_ACCEPT_IN_RX_FIFO0 0`, :779 `FDCAN_REJECT_REMOTE 1`; LSS/LSE from the element counts (fdcan.c:3427, 3433) | MATCH (blocking FIFO) |
| :63-65 | IE = RF0NE, RF0LE, PEAE; ILS = 0; ILE = EINT0 | HAL fdcan.c:2709-2780 (ILE line 0 for groups with ILS bit 0, :2744; IE :2780); hal_fdcan.h:920-943 | MATCH |
| :68 | INIT = 0 | HAL fdcan.c:1995 `HAL_FDCAN_Start` (no wait) | MATCH |
| :81-82 | read IR, write it back (rc_w1) | hal_fdcan.h:1111-1112 `IR = flag` | MATCH |
| :85-87 | F0FL; F0GI; element = RF0SA + idx x 72 | HAL fdcan.c:2228-2252 (the overwrite-mode GetIndex adjustment at :2241-2249 applies only with F0OM = 1) | MATCH |
| :88-97 | decode XTD/ID/DLC/FDF/BRS, payload | HAL fdcan.c:2286-2334, masks at fdcan.c:196-209, `DLCtoBytes` at :246 | MATCH |
| :98 | `RXF0A = idx` | HAL fdcan.c:2339 | MATCH |

### 2.7 spi_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :79-81 | PA5/6/7 AF5 | hal_gpio_ex.h:148 `GPIO_AF5_SPI1 0x05` | MATCH |
| :82-83 | APB2ENR.SPI1EN + read back | - | MATCH. Kernel clock ll_rcc.h:571 `SPI1_CLKSOURCE_PCLK2` = 00, so 4 MHz / 2 = 2 MHz |
| :84 | CR1 = SSI (SPE = 0) | HAL spi.c:381 disable, :396-399 SSI for master + soft NSS | MATCH |
| :85 | CFG1 = MBR 000, DSIZE 7 (FTHLV 0, CRCSIZE 0) | HAL spi.c:385 "Keep the default value of CRCSIZE in case of CRC is not used: `crc_length = CFG1 & CRCSIZE`", :412-413 `WRITE_REG(CFG1, ... | crc_length | FifoThreshold | DataSize)`; hal_spi.h:373 `SPI_BAUDRATEPRESCALER_2 0`, :452 `SPI_FIFO_THRESHOLD_01DATA 0` | **R8** (CRCSIZE); the rest MATCH |
| :86 | CFG2 = MASTER, SSM, AFCNTR (mode 0, full duplex, MSB first) | HAL spi.c:416-422, :479-484 (AFCNTR for master) | MATCH |
| :28 | CR2 = TSIZE (SPE = 0; cleared at :46 after each chunk) | HAL spi.c:1455 `MODIFY_REG(CR2, SPI_CR2_TSIZE, Size)` before :1457 enable | MATCH (TSIZE <= 0xFFFF; SPI1 is a "full" instance, stm32u575xx.h:23699) |
| :29-30 | SPE, then CSTART | HAL spi.c:1457, :1460-1463 | MATCH |
| :32-36 | wait TXP, byte store to TXDR | HAL spi.c:1619-1622 `*((__IO uint8_t *)&hspi->Instance->TXDR)` | MATCH |
| :37-41 | wait RXP, byte load from RXDR | HAL 8-bit branch, spi.c:1633-1636 | MATCH (one byte in flight, so no overrun and RXWNE/RXPLVL are not needed) |
| :44 | wait EOT | HAL spi.c:1685 | MATCH |
| :45-46 | IFCR = EOTC, TXTFC; SPE = 0 | HAL spi.c:3936-3940 `SPI_CloseTransfer` | MATCH |
| - | SUSP / MASRX | CR1.MASRX = 0, so SUSP never sets. The v1.6.2 fix "Clear auto suspend flag in HAL_SPI_Receive()" (Release_Notes.html:253) does not apply | MATCH |

### 2.8 i2c_u575.c

| Ours | Access | ST reference | Verdict |
|---|---|---|---|
| :67-68 | PB8/PB9 AF4, open drain | hal_gpio_ex.h:129 `GPIO_AF4_I2C1 0x04` | MATCH (order: R5) |
| :69-70 | APB1ENR1.I2C1EN + read back | - | MATCH. Kernel clock ll_rcc.h:518 `I2C1_CLKSOURCE_PCLK1` = 00, 4 MHz |
| :71-73 | PE = 0; TIMINGR; PE = 1 | HAL i2c.c:593 disable, :597 `TIMINGR = Timing & TIMING_CLEAR_MASK (0xF0FFFFFF)`, :640 enable; ll_i2c.h:1087 "can only be programmed when the I2C is disabled (PE = 0)" | MATCH (bits 27:24 of 0x00420F13 are 0; analog filter on, DNF = 0, as in the HAL defaults) |
| :41 | BUSY: return at once | HAL i2c.c:1138 waits up to `I2C_TIMEOUT_BUSY` 25 ms (:344) | MATCH (design choice) |
| :44, :52 | CR2 written whole: SADD, NBYTES, AUTOEND/SOFTEND, RD_WRN, START | HAL i2c.c:7637-7655 `I2C_TransferConfig` (MODIFY_REG of the same fields) | MATCH |
| :45-48 | wait TXIS, write TXDR | HAL i2c.c:1170-1175 | MATCH |
| :49 | wait TC (repeated start) or STOPF | HAL Mem_Read / Master_Transmit (i2c.c:1208) | MATCH |
| :53-56 | wait RXNE, read RXDR | HAL `I2C_WaitOnRXNEFlagUntilTimeout` i2c.c:7419-7494 | MATCH. Release_Notes.html:541 "check I2C_FLAG_AF independently from I2C_FLAG_RXNE" is satisfied: `wait_flag` checks NACKF first |
| :57-59 | STOPF, then ICR.STOPCF | HAL i2c.c:1208-1217 (and I2C_RESET_CR2; not needed because CR2 is rewritten whole) | MATCH |
| :20-26 | NACK: clear NACKF, wait STOPF (bounded), clear STOPF | HAL i2c.c:7508 clear AF, :7512 wait STOPF; **on timeout :7524-7529 "In case of I2C still busy, try to regenerate a STOP manually" (`CR2 |= I2C_CR2_STOP`)**; :7554 clear STOPF; **:7602 `I2C_Flush_TXDR`** (i2c.c:7014-7027: dummy TXDR write if TXIS, `ISR |= TXE` if TXE = 0); :7605 `I2C_RESET_CR2` | **R3** |
| :27-30 | BERR/ARLO: clear and return | HAL i2c.c:7563-7590, then the same flush and CR2 reset at :7600-7605 | part of **R3** |

### 2.9 startup_stm32u575.c / stm32u575zi_flash.ld

| Ours | Item | ST reference | Verdict |
|---|---|---|---|
| startup:32 | NMI weak alias, overridden by flash_u575.c:90 | - | MATCH |
| ld:17-18, board:10-13 | fault record in the last 32 B of SRAM1 (`.noinit`) | hal_flash.h:397-400 `OB_SRAM_RST_ERASE 0x0` "All SRAMs (except SRAM2 and BKPSRAM) erased when a system reset occurs", `OB_SRAM_RST_NOT_ERASE FLASH_OPTR_SRAM_RST`; option bit at stm32u575xx.h:8399 | **R9** |
| ld:15-16 | bank 1 code, bank 2 log | see (f) in section 4 | MATCH (with SWAP_BANK = 0) |

---

## 3. DEFECT / RISK details and minimal fixes

### D1: LSE started "for RTC only"; MSI PLL mode may never lock (board_u575.c:86-91)

- **ST:** hal_rcc.h:242 `#define RCC_LSE_ON_RTC_ONLY RCC_BDCR_LSEON /*!< LSE clock activation for RTC only */`;
  hal_rcc.h:243 `#define RCC_LSE_ON (RCC_BDCR_LSESYSEN | RCC_BDCR_LSEON) /*!< LSE clock activation for RCC and peripherals */`.
  HAL rcc.c:944-956: after LSERDY, "Enable LSESYS additionally if requested": `SET_BIT(RCC->BDCR, RCC_BDCR_LSESYSEN)`,
  then waits for LSESYSRDY. For RTC-only it actively clears LSESYSEN (rcc.c:958-969). LL ll_rcc.h:1813: LSESYSEN
  is "Enable LSE oscillator propagation for system clock".
- **Ours:** sets LSEON only, which is ST's RTC-only state, and then turns on MSI PLL mode (an RCC function) at :89-90.
- **Consequence:** if MSI PLL mode needs LSESYS, MSIS stays untrimmed. `g_board.lse_ok` is still true, the boot banner
  says "PLL mode on the LSE (LSE accuracy)", and `board_pll1q_20mhz()` lets CAN run from an untrimmed clock. That
  defeats the gate it exists for. The HAL source supports this reading; whether LSESYS is requested automatically by
  MSI PLL mode with LSESYSEN = 0 is a register-description question for RM0456 (Q3). The fix is harmless either way.
- **Fix:**

```c
    RCC->BDCR |= RCC_BDCR_LSEON;
    g_board.lse_ok = wait_set(&RCC->BDCR, RCC_BDCR_LSERDY, 3000000u);
    if (g_board.lse_ok) {                                  /* HAL RCC_LSE_ON: rcc.c:944-956 */
        RCC->BDCR |= RCC_BDCR_LSESYSEN;
        g_board.lse_ok = wait_set(&RCC->BDCR, RCC_BDCR_LSESYSRDY, 3000000u);
    }
    if (g_board.lse_ok) {
        RCC->CR |= RCC_CR_MSIPLLSEL;
        RCC->CR |= RCC_CR_MSIPLLEN;
    }
```

### R1: TIM2 update event with URS = 0, then a plain SR clear (board_u575.c:137-138)

- **ST:** HAL tim.c:7295-7306:
  `/* Disable Update Event (UEV) with Update Generation (UG) by changing Update Request Source (URS) to avoid Update flag (UIF) */ SET_BIT(TIMx->CR1, TIM_CR1_URS); ... TIMx->EGR = TIM_EGR_UG; /* Ensure that the update event is generated before writing back CR1 register with URS = 0 */ __DSB(); TIMx->CR1 = tmpcr1;`.
  ST changed this step twice: Release_Notes.html:365 (v1.6.1) "Fix update flag (UIF) clearing in TIM_Base_SetConfig"
  and :159 (v1.6.3) "Fix UIF flag set after TIM_Base_SetConfig()". (LL ll_tim.c:376 issues UG without URS and leaves
  UIF to the caller.)
- **Ours:** `EGR = UG;` immediately followed by `SR = 0;` (back-to-back `str` in the disassembly, 0x8001e52/0x8001e54).
  If UIF is set after the SR write lands, it is still pending when UIE and the NVIC are enabled.
- **Consequence:** the first TIM2 interrupt sees `ovf` with a small CNT, so `g_tim2_hi` becomes 1. Every timestamp is
  then 2^32 us (71.6 min) late. Intervals are unaffected.
- **Fix (keep URS = 1: only counter overflow raises UIF, which is all this timer needs):**

```c
    TIM2->CR1 = TIM_CR1_URS;                 /* line 128; HAL tim.c:7297 */
    ...
    TIM2->EGR = TIM_EGR_UG;                  /* line 137 */
    __DSB();                                 /* HAL tim.c:7304 */
    TIM2->SR = 0u;                           /* line 138 */
    ...
    TIM2->CR1 = TIM_CR1_URS | TIM_CR1_CEN;   /* line 143 */
```

### R2: voltage range raised without waiting for ACTVOSRDY (board_u575.c:164-165)

- **ST:** HAL pwr_ex.c:375 `MODIFY_REG(PWR->VOSR, (PWR_VOSR_VOS | PWR_VOSR_BOOSTEN), VoltageScaling);`, :378-384
  "Wait until VOSRDY is raised", then :388-394 "Wait until ACTVOSRDY is raised"
  `while ((HAL_IS_BIT_CLR(PWR->SVMSR, PWR_SVMSR_ACTVOSRDY)) && (timeout != 0U))`. The HAL reads the applied range from
  `SVMSR.ACTVOS` (pwr_ex.c:349, 411).
- **Ours:** polls VOSRDY right after the write and then enables PLL1. If VOSRDY still reads its pre-write 1, or if the
  applied range (ACTVOS) lags behind, PLL1 is started while the core still runs in range 4.
- **Consequence:** PLL1 started in range 4. Whether that is allowed at 160 MHz VCO is not in the HAL (Q1). The effect
  is uncertain.
- **Fix:**

```c
    PWR->VOSR = (PWR->VOSR & ~PWR_VOSR_VOS) | PWR_VOSR_VOS_0;                 /* range 3 */
    if (!wait_set(&PWR->VOSR, PWR_VOSR_VOSRDY, 100000u)) return false;
    if (!wait_set(&PWR->SVMSR, PWR_SVMSR_ACTVOSRDY, 100000u)) return false;  /* pwr_ex.c:388-394 */
    if ((PWR->SVMSR & PWR_SVMSR_ACTVOS) != PWR_VOSR_VOS_0) return false;     /* applied = range 3 */
```

### R3: I2C error path has no STOP fallback and no TXDR flush (i2c_u575.c:20-30)

- **ST:** see table 2.8. HAL i2c.c:7524-7529 generates STOP manually if STOPF does not arrive and the bus is still
  BUSY. :7602 flushes TXDR: i2c.c:7018-7027 `if TXIS: TXDR = 0x00; if TXE == RESET: __HAL_I2C_CLEAR_FLAG(TXE)`, where
  hal_i2c.h:568-570 shows that clearing TXE is `ISR |= TXE`.
- **Ours:** waits up to LOOPS for STOPF, clears STOPCF anyway, and leaves TXDR as it is.
- **Consequence:**
  - If no STOP follows a NACK in software-end mode (the write phase of every write_read with nr > 0, which is how the
    probes at 0x48-0x4B and 0x6A/0x6B run), BUSY stays set. Every later transfer then returns TM_BUS_TIMEOUT at :41.
  - After a NACK on a data byte, the next byte, already written to TXDR (TXIS is raised as soon as TXDR moves to the
    shift register), stays there. It becomes the first data byte of the next write, so a sensor register is written
    with a wrong address or value.
- **Fix (in both error branches):**

```c
static void i2c_recover(void)
{
    uint32_t k = 0;
    while (k < LOOPS && !(I2C1->ISR & I2C_ISR_STOPF)) k++;
    if (k == LOOPS && (I2C1->ISR & I2C_ISR_BUSY) && !(I2C1->CR2 & I2C_CR2_STOP)) {   /* i2c.c:7524-7529 */
        I2C1->CR2 |= I2C_CR2_STOP;
        for (k = 0; k < LOOPS && !(I2C1->ISR & I2C_ISR_STOPF); k++) {}
    }
    I2C1->ICR = I2C_ICR_STOPCF;
    if (I2C1->ISR & I2C_ISR_TXIS) I2C1->TXDR = 0u;                                   /* i2c.c:7018-7021 */
    if (!(I2C1->ISR & I2C_ISR_TXE)) I2C1->ISR |= I2C_ISR_TXE;                        /* i2c.c:7024-7027 */
}
/* NACK branch: I2C1->ICR = I2C_ICR_NACKCF; i2c_recover(); return TM_BUS_NACK;
   BERR/ARLO branch: I2C1->ICR = I2C_ICR_BERRCF | I2C_ICR_ARLOCF; i2c_recover(); return TM_BUS_ERROR; */
```

### R4: no read-back of DBP (board_u575.c:85)

- **ST:** HAL rcc.c:892-906 (LSE block) and rcc_ex.c:825-836 (RTC block): `SET_BIT(PWR->DBPR, PWR_DBPR_DBP);` then
  `while (HAL_IS_BIT_CLR(PWR->DBPR, PWR_DBPR_DBP))` with a timeout. (`HAL_PWR_EnableBkUpAccess`, pwr.c:215-218, does
  not wait.)
- **Consequence:** if write protection is not yet lifted when LSEON is written (one instruction later), the write is
  lost. The LSE then never starts: `lse_ok = false`, MSI stays untrimmed, and CAN stays off.
- **Fix:** `PWR->DBPR |= PWR_DBPR_DBP; (void)wait_set(&PWR->DBPR, PWR_DBPR_DBP, 10000u);`

### R5: MODER written before AFR (board_u575.c:25-30)

- **ST:** HAL gpio.c:260-264 sets `AFR` **then** :266-270 `MODER` (AF branch). OSPEEDR/OTYPER/PUPDR follow at
  :295/:301/:314.
- **Ours:** the pin enters AF mode with the old AFR value (AF0 after reset) and gets its AF only five accesses later.
  For PD1 (FDCAN1_TX) the pin goes from analog to "AF0", whose level the HAL does not show (DS13737, Q15), and then to
  AF9 (recessive). A low level for about 1 us would be a dominant pulse on the vehicle bus, unless the transceiver's
  silent pin is used (BENCH.md, row can_slnt). The same applies to PA9 (USART1 TX) and PB8/PB9 (I2C).
- **Fix (AFR first, as the HAL does; MODER last also makes the OTYPER/pull settings apply before the pin drives):**

```c
static void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode, uint32_t af, uint32_t pull, bool open_drain)
{
    volatile uint32_t *afr = &g->AFR[pin / 8u];
    *afr = (*afr & ~(0xFuL << (4u * (pin % 8u)))) | (af << (4u * (pin % 8u)));     /* gpio.c:260-264 */
    g->OTYPER = (g->OTYPER & ~(1uL << pin)) | ((open_drain ? 1uL : 0uL) << pin);
    g->PUPDR = (g->PUPDR & ~(3uL << (2u * pin))) | (pull << (2u * pin));
    g->OSPEEDR = (g->OSPEEDR & ~(3uL << (2u * pin))) | (1uL << (2u * pin));
    g->MODER = (g->MODER & ~(3uL << (2u * pin))) | (mode << (2u * pin));            /* last */
}
```

### R6: USART1 used before TEACK/REACK (uart_u575.c:23)

- **ST:** HAL uart.c:372-375, then :3403-3404 / :3421-3422 wait for `USART_ISR_TEACK` and `USART_ISR_REACK`.
- **Consequence:** probably nothing (TDR is buffered). The first character may be sent before the idle frame, or the
  receiver may not yet be enabled. Low risk.
- **Fix:**

```c
    USART1->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
    for (uint32_t k = 0; k < 100000u &&
         (USART1->ISR & (USART_ISR_TEACK | USART_ISR_REACK)) != (USART_ISR_TEACK | USART_ISR_REACK); k++) {
    }
```

### R7: bank layout assumed without checking SWAP_BANK (flash_u575.c:50-51, :95)

- **ST:** hal_flash.h:444-447 (quoted in 2.4). The HAL's `FLASH_PageErase(Page, Banks)` (flash_ex.c:925-947) takes a
  bank; the caller chooses it from the address and the swap state.
- **Ours:** always BKER = 1 for 0x08100000..0x081FFFFF. With SWAP_BANK = 1 (an option byte a programmer can change),
  0x08100000 is bank 1 and bank 2 holds the running code at 0x08000000. Whether BKER then selects the physical or the
  mapped bank is Q10a. In the worst case `ERASE YES` or log writes erase pages of the firmware. The NMI address at :95
  would also map to the wrong bank.
- **Fix (refuse to touch flash when swapped):** add `if (FLASH->OPTR & FLASH_OPTR_SWAP_BANK) return -1;` at the top
  of `f_erase` and `f_program` (or once at start, falling back to "no storage").

### R8: CFG1 write clears CRCSIZE (spi_u575.c:85)

- **ST:** HAL spi.c:384-385 `/* Keep the default value of CRCSIZE in case of CRC is not used */ crc_length = hspi->Instance->CFG1 & SPI_CFG1_CRCSIZE;`
  then :412.
- **Consequence:** unknown with CRCEN = 0 (Q12). The HAL takes care to preserve the field, so match it.
- **Fix:** `SPI1->CFG1 = (SPI1->CFG1 & SPI_CFG1_CRCSIZE) | (0u << SPI_CFG1_MBR_Pos) | (7u << SPI_CFG1_DSIZE_Pos);`

### R9: fault record depends on the SRAM_RST option byte (board_u575.c:10-13, stm32u575zi_flash.ld:17-18)

- **ST:** hal_flash.h:397-400 (quoted in 2.9). SRAM2 has its own option, `OB_SRAM2_RST_ERASE 0x0` at
  hal_flash.h:491-492.
- **Consequence:** with SRAM_RST = 0 the IWDG reset after a fault clears SRAM1. `last_fault` is then lost, and in
  particular FAULT_NMI_ECC never pauses the log. The factory value is not in the HAL (Q10e).
- **Fix (minimal: detect and report):** at the start of `board_init()`:
  `bool fault_record_kept = (FLASH->OPTR & FLASH_OPTR_SRAM_RST) != 0u;`, and put it in the boot banner. A sturdier
  option is to keep the two words in TAMP backup registers (`TAMP->BKP0R/BKP1R`, stm32u575xx.h:1073; backup domain,
  DBP is already set; `RCC_APB3ENR_RTCAPBEN` must be on). The HAL RTC/TAMP sequence for that was not among the
  reviewed files.

---

## 4. Specific items

**(a) PLL1 vs voltage range.** HAL pwr_ex.c:290: "After reset, the regulator is the LDO, in Range 4". The ranges are
given only as system-clock maxima: 24 MHz (range 4), 50 (3), 100 (2), 160 (1) (pwr_ex.c:300-309). HAL_RCC_OscConfig
does **not** read or raise VOS before enabling PLL1 (rcc.c:1138-1240). It only clears and restores BOOSTEN around the
PLL1MBOOST write (:1181-1217). The application is expected to call `HAL_PWREx_ControlVoltageScaling` first. That
function writes VOS (adding BOOSTEN only for ranges 1/2: pwr_ex.c:366-376, "EPOD must be enabled before switching to
voltage scale 1 / 2"), waits for VOSRDY and then ACTVOSRDY (:378-394). The HAL defers per-clock limits to RM0456:
rcc.c:319-320 "The clock source frequency should be adapted depending on the device voltage range as listed in the
Reference Manual 'Clock source frequency versus voltage scaling' chapter". The LL check `IS_LL_UTILS_PLL_FREQUENCY`
(ll_utils.c:124-130) maps SCALE4 to 160 MHz, which looks inconsistent and cannot be relied on. Our code raises to
range 3 before PLL1 (the right pattern) but lacks the ACTVOSRDY wait (R2). pwr_ex.c:334-335 says "Before moving to
voltage scaling 3, it is mandatory to ensure that the system frequency is between 24 MHz and 50 MHz"; we run at
4 MHz. This is probably upper-bound wording, but only RM0456 can confirm it (Q2). Whether PLL1 may run at all in
range 4, and whether a 160 MHz VCO is allowed in range 3, is not in the HAL (Q1).

**(b) LSE / MSI PLL mode.** PWR clock: yes (:79-80). DBP: yes, without read-back (R4). LSEON: yes. LSERDY timeout:
about 6 s versus HAL 5 s, MATCH. LSESYSEN: missing (D1). MSIPLLSEL before MSIPLLEN, and MSIPLLEN after LSERDY:
MATCH (rcc_ex.c:3333-3338; ll_rcc.h:2080-2083). LSEDRV is left at its backup-domain value; the HAL OscConfig does
not set it either (macro at hal_rcc.h:4555-4556, with the note at :4544-4546 that drive cannot be increased while
LSEON = 1). It is a board question (Q4). On rev X parts, ST notes that MSIPLLUNLCK and LSECSS EXTI are not available
(rcc_ex.c:48-56), so nothing reports a later loss of lock.

**(c) FDCAN.** RAM base `SRAMCAN_BASE` (APB1 + 0xAC00). The fixed layout (28 std x 4 B, 8 ext x 8 B, RF0 / RF1 /
TEF / TFQ x 3) gives RF0 = 0x0B0, 72-byte elements, 0x350 bytes in total: all MATCH (fdcan.c:211-235, 3421). Get
index from RXF0S.F0GI[9:8]; ack by writing the index to RXF0A: MATCH (fdcan.c:2238, 2339). The overwrite-mode
correction (fdcan.c:2241-2249; v1.6.3 "Fix GetIndex computation overflow in overwrite mode",
Release_Notes.html:98) does not apply in blocking mode (F0OM = 0). Kernel clock: RCC_CCIPR1.FDCANSEL[25:24]
(00 HSE, 01 PLL1Q, 10 PLL2P), with PLL1QEN set: MATCH (ll_rcc.h:627-629; rcc_ex.c:1113-1130; stm32u575xx.h:16625).
Configuration happens only with INIT = 1 and CCE = 1: MATCH. The HAL says nothing about the APB-versus-kernel clock
ratio (PCLK1 4 MHz vs fdcan_ker 20 MHz): Q11.

**(d) TIM2.** 32-bit: MATCH. PSC is preloaded and needs UG: MATCH (tim.c:7287, 7301). UG with URS = 0 sets UIF; ST
avoids that with URS = 1 plus `__DSB()` and fixed this step in v1.6.1 and v1.6.3. Our SR clear may lose the race:
R1. Filter: `ICxF = 0011` = fCK_INT, N = 8, which is 2 us at 4 MHz (ll_tim.h:858). Falling edge: CCxP = 1, CCxNP = 0.

**(e) IWDG.** CCCC, 5555, PR, RLR, wait for PVU/RVU (and WVU/EWU) = 0, reload: MATCH (iwdg.c:218-270). Timeout:
64 x 1000 / 32 kHz = 2.0 s (`LSI_VALUE 32000`, hal_conf_template.h:143). The SR poll budget (100,000 iterations,
about 0.15 s) covers the HAL's worst case (iwdg.c:131-141: 5 LSI periods plus one prescaled period plus LSI
start-up).

**(f) Flash bank 2.** Per the HAL and the vendored header: FLASH_SIZE is read from FLASHSIZE_BASE (2 MB on the
U575ZI), `FLASH_BANK_SIZE = FLASH_SIZE >> 1` = 1 MB, `FLASH_PAGE_SIZE` = 8 KB, `FLASH_PAGE_NB` = 128 per bank
(stm32u575xx.h:8142-8150). The DUALBANK option exists only for 1 MB/512 KB parts (hal_flash.h:333, 455-456), so a
2 MB part is always dual-bank. With SWAP_BANK = 0, bank 2 starts at offset 0x100000 (hal_flash.h:444-445). So
0x08100000 is bank 2 page 0, PNB is relative to the bank, and BKER = 1 selects bank 2 (flash_ex.c:938-947):
MATCH. 1 MiB / 8 KiB = 128 pages, which PNB[9:3] (7 bits) can address. Quad-word programming: PG, then four 32-bit
writes to a 16-byte-aligned address with IRQs off, then wait for BSY/WDW and clear PG: MATCH (flash.c:781-813,
203-206). Caveats: R7 (SWAP_BANK); the ECC address decode is unverified (Q10c).

**(g) USART1.** USART1SEL = 00 means PCLK2 (ll_rcc.h:462). After reset that is 4 MHz, assuming RCC_CCIPR1 resets to
0 (Q6). BRR = 35 per `UART_DIV_SAMPLING16`, giving 114,286 baud (-0.79 %) before MSI error: MATCH.

**(h) I2C TIMINGR 0x00420F13 at 4 MHz.** Decoded: PRESC 0 (tPRESC = 250 ns), SCLDEL 4, SDADEL 2, SCLH 0x0F, SCLL 0x13.
With the LL formulas (ll_i2c.h:458-468): tSCLDEL = (4+1) x 250 = 1.25 us; tSDADEL = 2 x 250 = 0.50 us;
tSCLH = 16 x 250 = 4.0 us; tSCLL = 20 x 250 = 5.0 us. The HAL and LL give **no** timing constraints: the HAL says
"calculated by referring to I2C initialization section in Reference manual" (hal_i2c.h:49-51); the LL says "set by
referring to the STM32CubeMX Tool" (ll_i2c.h:75-77). Against the I2C-bus standard-mode limits (UM10204, not an ST
source): tLOW >= 4.7 us (5.0 + sync, OK); tHIGH >= 4.0 us (4.0 + sync, OK, at the limit); tSU;DAT >= 250 ns with
tr <= 1000 ns, so SCLDEL must give at least 1.25 us (exactly met); tHD;DAT <= 3.45 us (0.5 us + delays, OK).
fSCL = 1 / (9.0 us + tSYNC1 + tSYNC2 + tr + tf), roughly 85-95 kHz, below 100 kHz. The exact RM conditions
(SDADEL min/max with tAF and (DNF+3/4) x tI2CCLK, SCLDEL min, the tI2CCLK limits) need RM0456/DS13737 (Q13).

**(i) SPI v2.** TSIZE is written with SPE = 0, then SPE, then CSTART. Per byte: TXP, then a byte store to TXDR; RXP,
then a byte load from RXDR. Then wait for EOT, clear EOTC and TXTFC, SPE = 0. FTHLV = 0 (1 data). MASRX = 0, so SUSP
never sets. CFG1/CFG2 are written with SPE = 0. All MATCH (spi.c:1455-1462, 1619-1636, 1685, 3936-3940). Only
CRCSIZE differs (R8).

---

## 5. Errata and workarounds in the HAL and release notes (peripherals we use)

The sources were searched for "errata", "workaround", "ES0499", "limitation", "rev.", "Cut1", "HW bug", `__DSB`/`__ISB`
and "Delay after".

| Source | Text | Peripheral | Needed by us? |
|---|---|---|---|
| rcc_ex.c:48, :55, :3484, :3500, :3550, :3563, :3592 | "Not available in STM32U575/585 rev. X ..." (the LSECSS EXTI line and the MSI PLL unlock interrupt, EXTI line 23) | RCC / MSI PLL mode | Not used. It does mean a rev X part cannot report an MSI PLL unlock, so `lse_ok` is a start-up check only. The silicon revision can be read with `HAL_GetREVID()` (hal.c:469-471, DBGMCU->IDCODE.REV_ID); worth logging at boot |
| hal_rcc.h:1376-1382 (and every `__HAL_RCC_xxx_CLK_ENABLE`) | "Delay after an RCC peripheral clock enabling" (read-back) | RCC | Yes; done at board:80, :127; uart:20; spi:83; i2c:70; can:47 |
| tim.c:7295-7306; Release_Notes.html:159 (v1.6.3) and :365 (v1.6.1) | URS + `__DSB()` around UG; "Fix UIF flag set after TIM_Base_SetConfig()" | TIM | Yes: R1 |
| tim_ex.c:3495; ll_tim.h:5145 | "The Cut1.x contains a limitation when using HSE/32 as input capture for TIM16" | TIM16 | No |
| Release_Notes.html:85 (v1.6.3) | "Implement a software workaround for the LPTIM interrupt limitation" | LPTIM | No |
| Release_Notes.html:431 (v1.6.1) | SMARTCARD "Implement workaround to resolve HW bug" | USART smartcard mode | No (asynchronous mode only) |
| Release_Notes.html:98 (v1.6.3) | FDCAN "Fix GetIndex computation overflow in overwrite mode" | FDCAN | No (blocking FIFO) |
| Release_Notes.html:253 (v1.6.2) | SPI "Clear auto suspend flag in HAL_SPI_Receive()" | SPI | No (MASRX = 0) |
| Release_Notes.html:541 (v1.5.0) | I2C "check I2C_FLAG_AF independently from I2C_FLAG_RXNE" | I2C | Already true in `wait_flag` |
| Release_Notes.html:89 (v1.6.3) | FLASH "Separate secure and non-secure flash locking" | FLASH | No (TZEN = 0, non-secure only) |
| rcc.c:1297 | "Wait at least 2 CK_REF ..." when changing PLL1FRACN on the fly | RCC PLL1 | No (FRACN unused) |

The HAL contains no reference to ES0499 and no errata workaround for FLASH, PWR, IWDG, FDCAN, SPI, I2C or USART
beyond the rows above. ES0499 itself must be checked (Q-E).

---

## 6. Other observations (not HAL-sequence differences)

- can_u575.c:42 divides by `bitrate` before the `bitrate == 0` check at :43. This is undefined in C; on the M33 UDIV
  returns 0 unless SCB->CCR.DIV_0_TRP is set. Swap the two lines.
- TIM2 ISR: a second capture landing between the SR read (:45) and the CCRx read (:47-49) is reported as an overrun
  only on the next edge, because CCxOF is not in the `sr` snapshot. Diagnostic only.
- The flash is never re-locked after an operation (the HAL leaves locking to the caller too).
- The IWDG is not frozen under the debugger (DBGMCU APB1FZR1.DBG_IWDG_STOP, stm32u575xx.h:5635). A halted core resets
  after about 2 s on the bench.
- After a NACK on the address (no data byte queued), our NACK path leaves CR2 as it was; that is harmless because
  CR2 is rewritten whole.

---

## 7. Questions only RM0456 / DS13737 / ES0499 can settle

Section titles are given rather than numbers, since numbering changes between revisions.

**RM0456 (STM32U5 reference manual)**
1. *RCC, "Clock source frequency versus voltage scaling" table* (cited by HAL rcc.c:319-320): is PLL1 usable in
   range 4? What are the maximum PLL1 VCO and PLL1Q output in range 3? (We use a 160 MHz VCO and a 20 MHz Q output.)
   Is there a per-range limit on the FDCAN kernel clock?
2. *PWR, "Dynamic voltage scaling management"* and the PWR_VOSR / PWR_SVMSR register descriptions: does VOSRDY drop
   synchronously with the VOS write? Is the ACTVOSRDY wait mandatory? Does pwr_ex.c:334-335's "between 24 MHz and
   50 MHz before moving to scale 3" mean a lower bound? Is BOOSTEN needed for PLL1 in range 3?
3. *RCC_BDCR register description, LSESYSEN/LSESYSRDY*: with LSESYSEN = 0, does MSI PLL mode request LSESYS
   automatically? (This settles D1.)
4. *RCC_BDCR.LSEDRV*: backup-domain reset value, and the drive level required for the NUCLEO crystal (with UM2861 for
   the crystal type).
5. *RCC, MSI PLL mode*: allowed MSIS ranges in PLL mode; the exact MSIS frequency in range 4 with a 32.768 kHz LSE
   (the PLL1 input minimum is 4 MHz, ll_utils.c:50); how a loss of lock shows on rev X.
6. *RCC register map*: reset values of RCC_CCIPR1 (USART1SEL, I2C1SEL, SPI1SEL, FDCANSEL = 00?) and RCC_CFGR2
   (PPRE1/PPRE2 = /1, which TIM2's 1 MHz depends on).
7. *General-purpose timers TIM2-5, TIMx_SR*: is "CCxIF cleared by reading TIMx_CCRx" true on the U5? How many timer
   clocks after `EGR.UG` is UIF set when URS = 0?
8. *TIMx_CR1.URS*: confirm that URS = 1 still raises UIF on counter overflow.
9. *IWDG*: SR update latency; FLASH_OPTR.IWDG_SW factory value. If the factory value selects the hardware watchdog,
   the about 6 s LSE wait before `watchdog_start()` outlasts the default timeout.
10. *FLASH*: (a) with SWAP_BANK = 1, does NSCR.BKER select the physical or the mapped bank? (b) Page size and pages
    per bank for the 2 MB U575, confirming the header's 8 KB / 128. (c) FLASH_ECCR.ADDR_ECC units (byte offset in the
    bank or quad-word index) and BK_ECC meaning with swap; does a double ECC error on a CPU data read always raise
    the NMI? (d) Are program and erase allowed in voltage ranges 4 and 3? What happens to a read of bank 2 while
    bank 2 is BSY (AHB stall and interrupt latency vs bus error)? (e) Factory value of FLASH_OPTR.SRAM_RST (R9) and
    SRAM2_RST. (f) Is NSSR.EOP set only when EOPIE = 1?
11. *FDCAN, "FDCAN clock" / functional description*: any requirement between fdcan_pclk (APB1, 4 MHz here) and
    fdcan_ker_ck (20 MHz)? What is the behaviour in bus-monitoring mode with FDOE = 0, PXHD = 0 when an FD frame
    arrives? Write conditions of FDCAN_CONFIG->CKDIV.
12. *SPI, SPI_CFG1*: reset value of CRCSIZE, and whether it matters with CRCEN = 0 (R8). TXTF/EOT semantics with
    TSIZE > 0 in polling mode.
13. *I2C, "I2C timings"*: tSYNC1/tSYNC2, the SDADEL/SCLDEL min/max formulas, and the tI2CCLK constraints at 4 MHz.
    *I2C master transmitter*: after a NACK with AUTOEND = 0, is a STOP generated automatically? (This settles R3.)
14. *USART*: TEACK/REACK timing after UE, and BRR with OVER8 = 0 for USARTDIV 35.
15. *GPIO*: what a pin in AF mode with an AF number that has no mapped function drives (R5).

**DS13737 (STM32U575 datasheet)**
- PLL characteristics per range (input 4-16 MHz, VCO min/max per range), and fHCLK/fPCLK limits per range.
- MSI accuracy untrimmed and in PLL mode (UART 0.79 % + MSI error; CAN tolerance at 500 kbit/s), and LSE start-up
  time.
- LSI frequency range (actual IWDG timeout), and flash page-erase and quad-word program times (stall length).
- I2C analog filter tAF min/max (for the RM formulas in Q13).
- Alternate-function table: what AF0 is on PA0, PA2, PA3, PA5-7, PA9, PA10, PB8, PB9, PD0, PD1 (R5).

**ES0499 (STM32U575/585 errata)**
- Q-E1: the silicon revision of the NUCLEO-U575ZI-Q part (rev X or later), and which errata apply (log REV_ID).
- Q-E2: errata touching MSI PLL mode, LSE/LSESYS, PWR voltage scaling (VOSRDY/ACTVOSRDY), FLASH (ECC, programming,
  read-while-write, bank swap), TIM (UIF/URS, input capture), IWDG, FDCAN (bus monitoring, message RAM, RX FIFO),
  SPI (TSIZE/EOT/CSTART, MASRX), I2C (NACK/STOP, analog filter, timing), USART, GPIO.
