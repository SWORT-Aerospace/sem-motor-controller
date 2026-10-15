# Component selection status (separate from the functional architecture)

**Selection freeze: NONE.** Every part below is a candidate or UNRESOLVED. The functional architecture (`docs/HARDWARE_ARCHITECTURE.md`) does not depend on any of these choices; a candidate can be swapped without changing it.

Status meanings:
* **CANDIDATE:** chosen for the draft. The datasheet still has to be read (see `DATASHEET_REGISTER.md`), and availability confirmed on live pages.
* **UNRESOLVED:** the rating depends on missing motor, battery, harness or rule inputs. A representative part is used only for pricing.
* **DESIGN VALUE:** a passive value that follows from the circuit and does not depend on unknown inputs.

| Function | Candidate (MPN) | Status | Why this candidate | Depends on / blocks freeze | Alternates | Pinout source in the schematic |
|---|---|---|---|---|---|---|
| MCU | STM32G474VET6 (LQFP-100) | CANDIDATE | Cortex-M4F with FPU; TIM1 complementary PWM with two break inputs; three or more ADCs for simultaneous phase sampling; FDCAN; 32 spare I/O in the generated allocation (LQFP-64 no longer fits after the sampling fix) | errata review (ES0430), clock tree in CubeMX | STM32G474VCT6 (same pinout, 256 kB) | KiCad library + ST open pin data @7d1f151 |
| Gate driver + CSA | DRV8353SRTAR (WQFN-40) | CANDIDATE | 100 V-class three-phase smart driver: VDS monitors that shut down in hardware, three integrated CSAs, SPI status (snippet: TI SLVSDY6A) | MOSFET gate charge (IDRIVE); CSA offset/settling values (error budget, rule 39) | DRV8353RS (integrated buck, 48-pin); discrete half-bridge drivers + INA240 | **UNVERIFIED** placeholder pin numbers (project symbol) |
| Phase MOSFETs ×6 | UNRESOLVED (representative CSD19536KTT, 100 V D2PAK) | UNRESOLVED | the envelope shows a few W per device to ~40 A peak with 2.4–5 mΩ parts | motor peak and continuous current, V_bat,max (V_DS ≥ 1.5·V_bat,max) | CSD19535KTT, BSC040N10NS5 | generic symbol |
| Phase shunts ×3 | UNRESOLVED (representative 2512, 4-terminal) | UNRESOLVED | Kelvin sensing; value from I_fs and CSA gain (`current_sense_error_budget.md`) | motor peak current; 38-week lead time seen for the 1 mΩ Kelvin part | 2-terminal 2512 with Kelvin pads (accuracy trade-off) | generic symbol |
| DC-bus meter | INA228AIDGSR (VSSOP-10) | CANDIDATE | 85 V common mode, 20-bit, energy accumulator; independent of the phase shunts | US stock gap in the snapshot | INA229 (SPI), INA238 | **UNVERIFIED** placeholder pin numbers |
| Bus shunt | UNRESOLVED | UNRESOLVED | INA228 full-scale range vs I_batt,max | I_batt,max | — | generic |
| DC-link bulk | UNRESOLVED (representative 220 µF / 100 V low-ESR) | UNRESOLVED | ripple current from the envelope table | I_ph,rms, V_bat,max, temperature | polymer / OS-CON | generic |
| Fuse, TVS, reverse polarity, precharge R, bypass P-FET | UNRESOLVED | UNRESOLVED | — | BMS short-circuit current, V_bat,max, C_link, harness decision | — | generic |
| CAN transceiver | TJA1051T/3/1J (SO-8) | CANDIDATE | 3.3 V VIO variant; CAN FD-capable (coexists with CHUDS); pinout verified by the KiCad library | bus wiring and termination location | TCAN1042V-class (verify pin compatibility) | KiCad library |
| CAN ESD | NUP2105LT1G | CANDIDATE | standard dual-line CAN TVS | — | PESD2CAN | KiCad library |
| Aux buck | LM5164DDAR (SO-8 PowerPAD) | CANDIDATE | 100 V input class: margin over an unknown ≤ 60 V battery | V_bat,min (UVLO), V_bat,max; LM5164-Q1 was out of stock (16 weeks) in a snapshot | LM5164QDDARQ1 | KiCad library |
| 3.3 V LDO | TLV75533PDBVR | CANDIDATE | low noise for the analog rail | — | TLV757P | KiCad library |
| Watchdog | MAX6369KA+T | CANDIDATE | pin-selectable timeout; open-drain WDO into the hardware permit chain | timeout from the hazard analysis | TPS3431, STWD100 | KiCad library |
| OV comparator + reference | TLV7041DBVR + TL431BIDBZR | CANDIDATE | open-drain output, wired-OR into BKIN2; independent of firmware | OV threshold from V_bat,max | TLV3691, LM4041 | KiCad library |
| Enable AND gate | SN74LVC1G08DBVR | CANDIDATE | ENABLE = MCU_DRV_EN AND HW_PERMIT | — | 74AHC1G08 | KiCad library |
| Safety-loop isolator | PC817-class | CANDIDATE | isolates the vehicle loop voltage | loop voltage (LED resistor) | — | KiCad library |
| Connectors | UNRESOLVED | UNRESOLVED | — | vehicle harness families (agree with the vehicle team) | — | generic |

## Decisions still open
1. Reverse-polarity protection: an active ideal-diode stage, or harness keying only.
2. Integrated CSAs (draft) versus external INA240-class amplifiers. Decide after the CSA offset and settling are read from SLVSDY6x and measured; rule 39 and the error budget take those values as inputs.
3. PWM frequency (20 kHz synthetic). It trades switching loss against the sampling window and ripple copper loss (`EFFICIENCY_RESEARCH.md` H1); rule 39 limits it.
4. Precharge on the board (draft) versus in the vehicle's contactor box.
