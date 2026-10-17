# Primary datasheet register and verification table

**State of evidence.** No manufacturer datasheet for these parts has been read into this register yet. The document identifiers and revisions below come from **web-search result titles and snippets** of the manufacturers' own document viewers (2026-10-15). Pages are therefore **not cited**: they were not read. Each "needed value" is a blocking item for selection freeze and must be filled in from the PDF, with document, revision and page.

When filling the table, every value must be marked **AMR** (absolute maximum rating: never a design point) or **ROC** (recommended operating condition: the design range), or **EC** (electrical characteristic: typ/min/max at stated conditions).

| Part | Document (from search) | Revision seen | Values needed (class) | Where used | Status |
|---|---|---|---|---|---|
| DRV8350/53 family | TI SLVSDY6 | A (Aug 2018 – Jun 2019); a later revision may exist | VM, VDRAIN, SHx (AMR, ROC); 40-pin DRV8353 pin table; CSA gain settings, input offset, gain error, settling time, output swing (EC); VDS OCP thresholds, modes, deglitch (EC); nFAULT type; INHx/INLx and ENABLE pull-downs; ENABLE-low to gates-off time; IDRIVE steps; CP/VCP/VGLS/DVDD capacitor values | gate_drive sheet; rule 39; error budget; truth table #3/#5 | **open** |
| INA228 | TI INA228 datasheet (document ID uncertain from snippets) | A (May 2022) | IN± and VBUS AMR/ROC; shunt full-scale ranges; offset/gain error (EC); input filter guidance; I²C address table; VSSOP-10 pin table | bus_measurement sheet | **open** |
| STM32G474xB/xC/xE | ST DS12288 | Rev 6 (Nov 2021, earlier search snippet); Rev 5 (Oct 2020) on a mirror; current revision unknown | VDD/VDDA ROC; FT-pin tolerance of PE2–PE4 (hall) and other 5 V inputs; ADC sampling-time vs source-impedance table; ADC fast-channel list; ADC clock max; reset state of the pins | mcu_debug sheet; timing budget [R] items | **open** |
| STM32G4 reference manual | ST RM0440 | ≥ Rev 4 | TIM1 BDTR (DTG encoding, BKF, OSSI/OISx, AOE); BKIN/BKIN2 polarity; ADC dual simultaneous injected mode and ADC3 trigger mapping to TIM1_TRGO2; COMPx-to-break routing | timing budget [R] items | **open** |
| STM32G474 errata | ST ES0430 | Rev 9 (earlier search snippet) | any ADC/TIM1/FDCAN errata | firmware platform | **open** |
| TJA1051 | NXP TJA1051 product data sheet | Rev 7 (2015) / Rev 8 (2016) seen; later possible | VIO range (EC); TXD pull-up and dominant time-out; CANH/CANL AMR; S-pin behaviour | can_phy sheet | **open** |
| LM5164 / LM5164-Q1 | TI SNVSAU4 / SNVSB51 | C (Apr 2024) / C (Dec 2025) | VIN AMR/ROC; RON equation; VFB; BST capacitor; minimum on/off time vs V_IN range | aux_rails sheet | **open** |
| TLV755P | TI datasheet | unknown | VIN ROC; dropout; stability capacitors | aux_rails | **open** |
| MAX6369 | Analog Devices (Maxim) MAX6369–MAX6374 | unknown | SET0–2 timeout table; WDO behaviour; startup delay | mcu_debug | **open** |
| TLV7041, TL431 | TI datasheets | unknown | input range, open-drain output; TL431 stable capacitance region | dc_link | **open** |
| Candidate MOSFETs (CSD19536/35KTT, CSD19532Q5B, BSC040N10NS5) | TI / Infineon datasheets | unknown | V_DS, V_GS (AMR); R_DS(on) at V_GS = drive voltage, Q_g, Q_gd, Q_oss, Q_rr, R_thJC (EC); SOA | power_stage_envelope (currently snippet values) | **open** |
| Shunts (WSK2512, CSS2H-2512) | Vishay / Bourns | Bourns CSS2H-2512 PDF found by search | power rating vs PCB temperature; TCR; pulse rating; Kelvin pad layout | bridge sheet; error budget | **open** |

**Rule for using this table.** A schematic value tagged "TYPICAL – verify" or "[R]", or a project-library pin number marked UNVERIFIED, may not be carried into a layout until its row is filled with document, revision, page and value class.

## v0.3 sources (2026-10-15)
* **Not accessible for that work:** st.com, ti.com, ti.com.cn, mouser.com, digikey.com, alldatasheet, the ST China CDN and other mirrors.
* **Reachable and used**, as secondary evidence only, never in place of a datasheet row above:
  * `STMicroelectronics/stm32g4xx_hal_driver@a6001282` and `STMicroelectronics/cmsis_device_g4@626ee412` (raw GitHub). Register field widths, HAL range macros and HAL comments, used in `hardware/timing/clock_tree_alternatives.md`.
  * `STMicroelectronics/STM32_open_pin_data@7d1f151` (pin database).
  * `kicad-symbols@cf07d539` on GitLab (INA228 pin numbers).
* **Conflicts found** between ST HAL comments and recalled DS12288 values: the PLL VCO input range (2.66–8 vs 2.66–16 MHz), the VCO output range (64–344 vs 96–344 MHz), and an unexplained "FDCAN (≤ 48 MHz)" note. The narrower values are used until DS12288 resolves them.
* Fastest path: add the PDFs under `docs/reference/datasheets/` (DS12288, RM0440, DRV8353 SLVSDY6, INA228, TJA1051, LM5164, TLV755P, MAX6369). Each row above then gets its revision and page numbers.
