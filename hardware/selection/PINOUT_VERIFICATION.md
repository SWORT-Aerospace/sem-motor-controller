# Pinout verification records and schematic checks (v0.3)

**No primary datasheet could be opened from this environment.** st.com, ti.com, the distributors and the datasheet mirrors are all refused by the network policy (recorded in `DATASHEET_REGISTER.md`). What was reachable:
* ST's machine-readable pin database (`STM32_open_pin_data`, ST-published);
* ST's register headers and HAL/LL sources on GitHub;
* the KiCad official symbol library on GitLab.

Each record says which of these it rests on. Evidence levels:
* **[ST-DB]** ST's own pin database `STMicroelectronics/STM32_open_pin_data@7d1f151`. ST-published and machine-readable; the strongest source available here.
* **[KiCad]** KiCad official library (`kicad-symbols@cf07d539`, or the KiCad 7.0.11 library installed here). Independent and librarian-reviewed against datasheets, but **secondary**.
* **[none]** placeholder; not verified.

**A secondary match is not primary verification.** Every row below is re-checked against the vendor PDF, with its revision and page, before footprints or layout (`DATASHEET_REGISTER.md`).

## 1. ICs
| Ref | Part (orderable) | Package | Pin numbers / names | Evidence | Checked in this draft | Still to check against the primary datasheet |
|---|---|---|---|---|---|---|
| U801 | STM32G474VET6 | LQFP-100 (no exposed pad) | KiCad symbol generated from ST's database; function pins allocated by `tools/pin_allocation.py` | **[ST-DB]** + [KiCad] | power and special pins cross-checked against ST-DB: VBAT 6; NRST (PG10) 14; VSS/VDD 23/24, 48/49, 63/64, 74/75, 99/100; VSSA 35; VREF+ 36; VDDA 37; BOOT0 (PB8) 95. No VCAP pins on this family. Draft: every VDD on +3V3 (5 × 100 nF + 4.7 µF); VDDA and VREF+ on +3V3A through a ferrite (1 µF + 10 nF + 1 µF); VBAT on +3V3; VSSA on GND; NRST 100 nF + button + SWD pin 10; BOOT0 10 k pull-down; HSE on PF0/PF1 | DS12288 decoupling values per pin group; VREF+ when VREFBUF is unused; NRST internal pull-up and filter; BOOT0 vs nSWBOOT0/nBOOT0 option-byte defaults; reset state of every pin used (analog/high-Z [R]; debug pins pulled [R]) |
| U401 | DRV8353SRTAR (candidate) | WQFN-40 "RTA" with exposed pad (assumed from the order code) | **placeholder, numbered in drawing order** | **[none]** | net intent only: VM and VDRAIN to VDC; charge pump CPH/CPL/VCP; VGLS; DVDD; VREF to +3V3A; ENABLE = MCU_DRV_EN AND HW_PERMIT with pull-downs; nFAULT open-drain to TIM1_BKIN with a pull-up | **everything**: pin numbers and names for the RTA package; exposed-pad net; VM vs VDRAIN roles; charge-pump and VGLS/DVDD capacitor values and voltage ratings; VCP reference node; VREF range and CSA bias; SPI logic levels; ENABLE wake time and internal pull-down; INHx/INLx internal pull-downs; CSA gain options; VDS-OCP levels |
| U601 | INA228AIDGSR | VSSOP-10 (DGS) | 1 A1, 2 A0, 3 ALERT, 4 SDA, 5 SCL, 6 VS, 7 GND, 8 VBUS, 9 IN−, 10 IN+ (**v0.3: placeholder order replaced**) | **[KiCad]** (INA228 extends the INA226 DGS symbol) | A0 = A1 = GND (address [R] 0x40); ALERT open-drain with 10 k pull-up; 4.7 k I²C pull-ups to 3.3 V; VS at 3.3 V; input filter 10 Ω + 100 nF | pin table; VS range; IN± and VBUS common-mode range; input-filter guidance (series resistance vs gain error); address table |
| U1101 | TJA1051T/3/1J | SO-8 | 1 TXD, 2 GND, 3 VCC, 4 RXD, 5 VIO, 6 CANL, 7 CANH, 8 S | **[KiCad]** | VCC +5 V, VIO +3.3 V; S held low by 10 k (normal mode); split termination behind jumpers | VIO range; S polarity; TXD dominant timeout; loop delay (used in the clock-tree tolerance analysis) |
| U1201 | LM5164DDAR | SO-8 PowerPAD (exposed pad, pin 9) | 1 GND, 2 VIN, 3 EN/UVLO, 4 RON, 5 FB, 6 PGOOD, 7 BST, 8 SW, 9 EP | **[KiCad]** | **EP connected to GND** | EP net and thermal-via guidance; R_ON, UVLO divider, inductor, BST capacitor (all UNRESOLVED or "TYPICAL – verify") |
| U1202 | TLV75533PDBVR | SOT-23-5 | 1 IN, 2 GND, 3 EN, 4 NC, 5 OUT | **[KiCad]** | EN tied to IN; NC unconnected | input/output capacitor requirements |
| U402 | SN74LVC1G08DBVR | SOT-23-5 | 1 A, 2 B, 3 GND, 4 Y, 5 VCC | **[KiCad]** | A = MCU_DRV_EN, B = HW_PERMIT, Y = DRV_EN_GATED with 100 k pull-down | input behaviour unpowered (I_off) |
| U802 | MAX6369KA+T | SOT-23-8 | 1 WDI, 2 GND, 3 NC, 4 SET0, 5 SET1, 6 SET2, 7 WDO#, 8 VCC | **[KiCad]** | SET pins strapped per the draft timeout | SET-strap timeout table; WDO# output type |
| U201, U202 | TLV7041DBVR, TL431BIDBZR | SOT-23-5, SOT-23-3 | KiCad symbols | **[KiCad]** | OV comparator into TIM1_BKIN2 | thresholds and hysteresis |
| U1001 | PC817 | DIP-4 / SMD-4 | KiCad symbol | **[KiCad]** | safety-loop sense into HW_PERMIT | LED current at the loop voltage (UNKNOWN) |

## 2. Reset states and hardware shutdown paths (draft, not measured)
* **MCU pins at reset** [R]: analog / high-impedance, except the debug pins (PA13, PA14, PA15, PB3, PB4 have pulls).
  * Checked against the allocation: no PWM, ENABLE or precharge signal sits on those pins.
  * PA15 carries I²C SCL, which is pulled up anyway.
  * The USB-PD dead-battery pins (PB4/PB6 with PA9/PA10 [R]) are not used.
* **Gate driver disabled at reset**: MCU_DRV_EN has a 100 k pull-down; the AND gate output has a 100 k pull-down; the 74LVC1G08 output is low when either input is low. The gate driver's own ENABLE and INHx/INLx pull-downs are [R] until the datasheet is read.
* **Shutdown paths**, independent of firmware:
  * DRV nFAULT → TIM1_BKIN;
  * OV comparator → TIM1_BKIN2;
  * watchdog WDO# → HW_PERMIT low → DRV ENABLE low;
  * safety loop open → opto off → HW_PERMIT low.

  Truth table: `hardware/protection/SHUTDOWN_TRUTH_TABLE.md`. Latencies are measured at bring-up stage 3; none is claimed here.

## 3. Current-sense topology and sampling
* **Topology**: low-side shunts per phase → gate-driver CSAs (gain set over SPI) → 100 Ω / 470 pF anti-alias filter → MCU ADC inputs.
* **Bias**: the CSA reference VREF is tied to +3V3A, ratiometric with the ADC reference. Whether the DRV8353 CSA biases at VREF/2 and which VREF range it accepts is [R], pending the datasheet.
* **Three-ADC simultaneous sampling is PROPOSED**, not substantiated:
  * ADC1/ADC2 dual mode plus ADC3, all triggered by TIM1_TRGO2.
  * It needs the trigger configuration, ADC synchronisation, acquisition windows (rule 39 uses a measured settle time) and a bench measurement.

## 4. Electrical rule checks
| Check | Tool | Result | What it does and does not show |
|---|---|---|---|
| Connectivity: KiCad-exported netlist equals the intended netlist | `tools/gen_kicad_schematic.py --check` (kicad-cli 7.0.11) | 135 intended nets, **0 problems** | KiCad connects what the generator meant to connect. It does not show that the circuit is correct. |
| Pin-type rules on the KiCad-exported netlist | `tools/pin_type_check.py` | v0.3 first run: **6 findings**, all R2 (power input with no power source: +3V3A, +5V, GND, PGND, VBAT_PROT, VDC, i.e. rails driven through a ferrite, an inductor, a switch or a connector). **Fixed** by adding PWR_FLAG markers; re-run: **0 findings** | A subset of ERC pin rules on KiCad's own pin types. **Not a KiCad ERC.** |
| **KiCad ERC** | `tools/run_kicad_erc.sh` (KiCad 8+) or Eeschema GUI | **NOT RUN.** KiCad 7.0.11 has no CLI ERC. Installing KiCad 9 (Ubuntu 26.04 packages) in an isolated root was refused by this environment's permission policy. | Remains a blocker. Run it on a machine with KiCad 8 or newer and commit `hardware/kicad/ERC_REPORT.rpt`. |

## 5. Remaining schematic blockers
1. **Primary datasheets**: DS12288 + RM0440 (ST), DRV8353 (TI SLVSDY6), INA228, TJA1051, LM5164, TLV755P, MAX6369. These can be attached to the session as PDFs, as the telematics diagrams were.
2. **The DRV8353S symbol** for the exact orderable package (pins, exposed pad, charge-pump network).
3. **A real KiCad ERC** and review of every finding.
4. **The crystal** (unselected): needs the vehicle bus (`clock_tree_alternatives.md`).
5. **The CAN identifier block, connector, termination location** (vehicle team).
6. **Every power-stage rating** (MOSFETs, shunts, DC-link, fuse, TVS, reverse-polarity, precharge, connectors). These stay explicit **UNRESOLVED** placeholders until the motor and battery are identified. None is invented.
7. **Bias and thresholds that depend on unknown inputs**: hall supply and pull-ups, motor-temperature bias, safety-loop LED resistor, buck UVLO.
8. No footprints, no layout, no fabrication outputs, by design.
