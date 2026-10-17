# Pre-layout requirements

What must be fixed before the printed-circuit board is laid out, what is already fixed by the circuit, and which
parts of the board could be laid out first. **No layout exists and none is started in this revision:** every
sheet still has at least one footprint that cannot be chosen (an unselected connector, a rating that waits for the
battery or motor, or a package drawing in an unread datasheet). The release gate (`tools/release_gate.py`)
refuses to produce fabrication outputs until the conditions at the end of this document hold.

## 1. Inputs still needed

| Input | Decides | Blocker |
|---|---|---|
| Space, mounting points and cable directions in the vehicle | board outline, mounting holes, connector edge | B-MECH |
| Heatsink or cold plate (a metal plate of the vehicle, a separate heatsink, or board copper only) | MOSFET package and placement, thermal vias, mounting pressure | B-MECH |
| Connector families and pinouts | footprints of J101, J301, J701, J901, J1001, J1101 and their positions | B-HARNESS |
| V_bat,max with transients | conductor spacing on the power nets (IPC-2221B), part voltage classes | B-BAT-V |
| Battery and phase currents (continuous and peak) | copper width and weight on the power paths (IPC-2152), shunt and MOSFET packages | B-BAT-I, B-MOTOR |
| Assembly process (hand or assembly service) and copper weight | footprint variants, stencil, minimum features | B-ASSY |
| DRV8353 pinout and package drawing | the gate driver footprint and its thermal pad | B-DRV |
| STM32G474 LQFP-100 package drawing | the MCU footprint (pin mapping already verified against ST's pin database) | B-ST-DOCS |

## 2. Constraints fixed by the circuit (independent of the missing ratings)

**Stack-up (proposed).** Four layers, outer copper 2 oz for the power paths (the pricing assumption,
`hardware/bom/pricing.yaml`): layer 1 power and components, layer 2 an unbroken ground plane (PGND under the power
stage, GND under the logic, joined only at NT1201), layer 3 logic signals and +3V3, layer 4 power return and
heatsink side. A decision once the copper weight and fabricator are chosen (B-ASSY).

**Commutation loops.** One ceramic DC-link capacitor per half-bridge (sheet 02, the three MLCC positions) placed
across that leg's high-side drain and low-side source, so the loop high-side FET, low-side FET, shunt and
capacitor encloses the smallest area over the layer-2 plane. Bulk capacitors may sit further away; the
ceramics carry the switching edge.

**Gate drive.** Each gate signal routed together with its return: GHx with SHx (the phase node) for the high
side, GLx with the low-side source for the low side, as close pairs from the driver pins to the MOSFET; the 0 ohm
series positions at the MOSFET end. The charge-pump and regulator capacitors (CP, VCP, VGLS, DVDD) at the driver
pins. The switch nodes (PHASE_x) as short and compact as the current allows, away from every analog trace.

**Kelvin sensing.** Each four-terminal shunt's sense pads (pins 3 and 4 of R_Shunt) routed as a differential
pair to the driver's SPx/SNx inputs, carrying no load current; the differential filter capacitor position (DNP)
at the driver end. The same for the bus shunt to the INA228 (IBUS_SP/IBUS_SN through its 10 ohm filter).

**Analog returns.** The 100 ohm / 470 pF current-sense filters and the 1 k / 100 nF (temperature, pedal) and
1 k (VBUS_SENSE) filters at the MCU pins, with their capacitors returned to GND next to the MCU's VSSA. +3V3A
from the ferrite bead with its 1 uF / 10 nF decoupling at VDDA and VREF+. No PGND current through the GND plane:
the only PGND-GND connection is the net tie at the phase-shunt ground.

**Over-voltage comparator.** Divider, TL431, comparator and the 10 k / 390 k hysteresis network close together on
the GND plane, with BRK2_N routed to PC3 away from the switch nodes (it stops the outputs in hardware).

**Testability.** The 21 test points of this revision plus the existing ones on the top side, each with a ground
point within probe reach (`docs/BENCH_ACCEPTANCE.md` probes them); SWD (J801) and UART (J802) reachable with the
enclosure open; the reset button reachable.

**Temperature sensing.** The power-stage NTC in thermal contact with the low-side MOSFETs' copper (the hottest
devices in the envelope's low-speed points).

## 3. Clearances and current paths (values pending)

* Spacing on VBAT, VDC and PHASE nets: from IPC-2221B for the working voltage V_bat,max plus measured
  transients, uncoated or coated as the enclosure decides. Not set until B-BAT-V closes.
* Copper width and weight: IPC-2152 for the continuous battery and phase currents at the allowed temperature
  rise, checked for the peak current's duration. Not set until B-BAT-I and B-MOTOR close.
* Creepage to the safety-loop side of the PC817: the loop voltage (B-LOOP).

## 4. Layout readiness by sheet

| Sheet | Footprints that can be chosen now | What blocks the rest |
|---|---|---|
| 01 power input | none | connector J101, fuse, TVS, reverse-polarity block, shunt, precharge parts (B-BAT-V, B-BAT-I, B-HARNESS) |
| 02 DC link | comparator, TL431, 0603 resistors and capacitors of the comparator network | bulk and ceramic capacitors, bleeder, divider (B-BAT-V, B-MOTOR) |
| 03 bridge | none | MOSFETs, shunts, J301 (B-MOTOR, B-BAT-V, B-HARNESS) |
| 04 gate drive | AND gate, pull-downs | DRV8353 package and pinout (B-DRV); capacitor voltages (B-BAT-V) |
| 05 current sense | filter resistors and capacitors | none on this sheet once the shunt and driver are placed |
| 06 bus measurement | filter and pull-up passives | INA228 package drawing (B-INA) |
| 07 temperature | filter passives | NTC part, J701 (B-NTC, B-HARNESS) |
| 08 MCU, debug, watchdog | SWD and UART headers, LEDs, passives | LQFP-100 drawing (B-ST-DOCS); crystal (B-CAN); MAX6369 package drawing (B-PART-DOCS) |
| 09 hall inputs | filter passives | J901, hall supply, polyfuse (B-MOTOR, B-HARNESS) |
| 10 driver controls | filter and pull-up passives, ESD diodes | J1001, PC817 LED resistor (B-HARNESS, B-LOOP) |
| 11 CAN | transceiver, termination network | J1101 (B-HARNESS) |
| 12 auxiliary rails | LDO and its capacitors | LM5164 input parts, inductor, UVLO and RON (B-BAT-V, B-PART-DOCS) |

The footprints marked "can be chosen now" are standard packages whose pin mapping follows from the symbol, but they
are not assigned: a partial layout of the logic section would be redone when the power stage and the connectors
fix the outline, so the layout starts once B-MECH, B-HARNESS and the power ratings are known.

## 5. Release gate (fabrication readiness)

`python3 tools/release_gate.py` checks, and only when all hold writes the release package (editable sources,
schematic and assembly PDFs, Gerbers and drill files, BOM and placement files, notes, firmware revision and
configuration, review checklist, known limitations, checksums and a manifest):

1. no UNRESOLVED line in `hardware/bom/BOM_draft.csv`;
2. every symbol has a footprint, and every IC's pin numbers are checked against a primary document (`Pin_check`
   naming the document), so no project placeholder symbol remains;
3. every row of `hardware/selection/DATASHEET_REGISTER.md` filled;
4. a PCB file with a passing KiCad DRC;
5. a KiCad ERC with no error and every warning reviewed;
6. a signed design review (`hardware/review/REVIEW_CHECKLIST.md`) and a signed manual schematic-to-layout review
   (`hardware/review/LAYOUT_REVIEW.md`), because passing automated checks does not close design-review issues;
7. the firmware revision and the vehicle configuration the board will run, the configuration hardware-valid.

Current result: `docs/generated/release_gate.md`.
