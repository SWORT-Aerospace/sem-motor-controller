# Provenance audit: the Cornell reference projects were treated as our vehicle (v0.3)

**Finding.** v0.1–v0.2 used Cornell's repositories, supplied as **reference projects**, as if they described our physical vehicle. The Cornell items involved:
* the CHUDS protocol;
* its CAN FD bit timing;
* its ID classes;
* its Emergency STOP message;
* its Linux VCU;
* its software's handling of classic frames.

Several design decisions followed from that assumption. This audit lists every affected document, configuration and hardware decision, labels each fact, and records the correction. The v0.2 checkpoint is preserved; it now carries an errata banner.

Labels: **[C]** confirmed for our vehicle · **[P-in]** proposed design input (telematics proposal v0.1) · **[REF]** observed in a reference project · **[P]** proposed design choice (this project) · **[U]** unknown.

## 1. Facts and their labels
| Statement in v0.2 | Correct label | Notes |
|---|---|---|
| The vehicle bus is CHUDS CAN FD, 500k/2M at 80 %/80 % | **[REF]** | our bus: **[U]**; the telematics proposal shows CAN 2.0B **[P-in]** |
| CHUDS drops classic frames, so the VCU needs a raw-socket consumer | **[REF]** | relevant only on a CHUDS bus |
| IDs 0x300–0x33F avoid CHUDS classes; CHUDS reserves 0x300–0x7FF | **[REF]** | our ID map: **[U]**; the block base is now a calibration value **[P]** |
| The controller must enable FD operation | **[REF]**-derived | **[U]**: only if our bus is FD |
| A 40 MHz crystal is required for CAN FD | wrong even for the reference bus | withdrawn; PLL-derived clocks work (`clock_tree_alternatives.md`) |
| A Linux companion (Cornell uses a Pi) runs the supervisor | **[REF]** | proposed: the supervisor on the STM32U575 telematics unit **[P]**, **[P-in]** |
| CHUDS Emergency STOP should be an L1 inhibit | **[REF]** | our CAN stop message: **[U]**; the hardware safety loop is the stop path **[P]** |
| Bus load 13.7 % including CHUDS | **[REF]** load case | our other traffic: **[U]** |
| Cornell wheel diameter, pulses per revolution, category (UC) | **[REF]** | already marked "not assumed" in `SOURCE_AUDIT.md` |
| Three phase currents sampled simultaneously on three ADCs | **[P]** | proposed only; to be substantiated by configuration and measurement |

## 2. Affected files and what changed
| File | Change |
|---|---|
| `docs/CAN_INTEGRATION.md` | retitled as a reference-project analysis and optional adapter; status banner; 40 MHz row withdrawn |
| `docs/INTERFACE_CONTROL.md` | amendment note; ID block configurable; CAN mode, bit rate and transceiver per bus (UNKNOWN); DBC row |
| `docs/ARCHITECTURE_FREEZE.md` | C6 (companion) revised; boundary C reworded (block base, bus unknown, transport-neutral core) |
| `docs/REQUIREMENTS.md` | CO-6 no longer assumes CHUDS traffic |
| `docs/OPEN_PARAMETERS.md` | crystal and FDCAN clock not selected; `can_id_base` added; category note |
| `docs/HARDWARE_ARCHITECTURE.md` | bus node relabelled; simultaneous sampling marked proposed |
| `docs/decisions/ADR-0005-can-contract.md` | amended by ADR-0012 (pointer) |
| `docs/decisions/ADR-0012-transport-neutral-interface.md` | new |
| `docs/SOURCE_AUDIT.md` | §2.2 labelled as reference projects |
| `docs/VEHICLE_TEAM_INPUT_SHEET.md` | H2–H4 rewritten without CHUDS |
| `docs/CHECKPOINT_v0.2.md` | errata banner; body unchanged |
| `firmware/platform/stm32g4/README.md` | clock not selected; FD settings conditional on an FD bus; sampling proposed |
| `firmware/include/semmc/mc_core.h`, `firmware/src/core/mc_core.c`, `firmware/src/transport/mc_can_binding.c` | transport-neutral core API; CAN binding with a configurable block |
| `config/parameters.yaml`, `config/vehicle.*.yaml`, generated schema/header, `mc_config.c`, `tools/config_tool.py` | parameter 164 `supervision.can_id_base`, rule 40 |
| `firmware/tests/test_protocol.c` | test renamed: the 64-number block, not "outside CHUDS" |
| `host/vcu_bridge/semmc_socketcan.py` | status text; base parameter; translation to protocol numbers |
| `tools/can_bit_timing.py` (+ generated md) | v0.2 conclusion withdrawn |
| `tools/bus_load.py` (+ generated md) | CHUDS labelled a reference-project load case |
| `tools/gen_kicad_schematic.py` (+ KiCad files, PDF, BOM) | crystal "HSE UNSELECTED"; CAN connector note; sampling note |
| `hardware/bom/pricing.yaml` (+ priced BOM) | crystal line unselected |
| `hardware/selection/COMPONENT_SELECTION.md` | transceiver note without CHUDS |
| `tools/timing_budget.py`, `tools/pin_allocation.py` (+ generated) | three-ADC sampling marked proposed |

**Not changed, on purpose:**
* `protocol/protocol.yaml`: its header comment still gives CHUDS as the v1 rationale. Editing a comment would change the spec hash of a frozen protocol; ADR-0012 records the correction instead.
* The CSIA campaigns and the historical v0.1/v0.2 results.

## 3. What remains true
* The control contract, the protocol's integrity and session rules, the wired driver authority and the fail-closed configuration do not depend on the bus. They are unchanged.
* Every CHUDS-specific item stays available as an **optional adapter** in case the vehicle bus turns out to be CHUDS-like. Nothing requires it.

The smallest set of team inputs that would select the real interface is in `VEHICLE_INTERFACE_MATRIX.md`.
