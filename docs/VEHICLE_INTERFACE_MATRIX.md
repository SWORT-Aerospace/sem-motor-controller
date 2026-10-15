# Vehicle interface matrix: our vehicle vs proposals vs the reference project (v0.3)

Labels:
* **Confirmed for our vehicle**: stated by our physical team or measured on our vehicle.
* **Proposed design input**: the telematics proposal v0.1 (14/10/2026) or a decision request.
* **Observed in a reference project**: Cornell repositories `urban-concept@c422c0f`, `uc26_sensor_reader@3471a97`.
* **Proposed design choice**: this project.
* **Unknown**.

**Nothing in the "Confirmed for our vehicle" column is filled at v0.3.** No interface fact about our vehicle has been stated by the physical team or measured.

| Interface | Confirmed for our vehicle | Proposed design input (telematics v0.1) | Observed in a reference project (Cornell) | Proposed design choice (semmc v0.3) | Unknown / needed |
|---|---|---|---|---|---|
| Bus type | — | CAN 2.0B | CAN FD (CHUDS), MCP251863 nodes | classic 11-bit frames; FDCAN mode follows the bus | which bus is fitted |
| Bit rate, sample point | — | not stated | 500 kbit/s / 2 Mbit/s, 80 % / 80 % | crystal and timing chosen after confirmation (`clock_tree_alternatives.md`) | bit rate, sample point, transceivers, cable length |
| Identifier map | — | not stated | 3-bit class + subaddress; 0x300–0x7FF reserved | one 64-id block at `supervision.can_id_base` (null until allocated) | full ID map; 11 or 29-bit; our block |
| Message definitions | — | MC "rpm, current, temps"; BMS "cell V, SOC, temps"; wheel speed | CHUDS catalog | protocol v1 (frozen); DBC generated | BMS, wheel-speed and driver-node message definitions |
| Termination, topology, connector | — | 120 Ω at both ends; CANH, CANL, GND | not documented | split-termination jumpers; connector unselected | topology, connector, stub lengths, harness supply and ground |
| Supervision computer | — | telematics unit STM32U575 (no supervisor shown) | Linux VCU (Raspberry Pi) | supervisor task on the telematics unit (proposed) | team decision |
| Driver inputs | — | optional driver-input node on CAN | aux nodes on CAN | wired to the controller; CAN copies for logging only (ADR-0010) | which switches exist; signal levels; throttle type |
| Emergency stop | — | not on CAN | CHUDS Emergency STOP 0x000 | hardware safety loop → HW_PERMIT; no CAN dependency | safety-loop voltage, contacts, e-stop topology |
| Wheel speed | — | wheel-speed node (halls); 3 pulse inputs on the unit | edge counts per 100 ms window, misleadingly named "rpm" | supervisor input, not a controller input | pulses per revolution, circumference |
| Telemetry uplink | — | LTE Cat-1 → MQTT, 1–5 Hz, one-way intended | Linux telemetry stack | one-way only, outside the control chain | confirm one-way; broker owner |
| Logging | — | QSPI 8 MB every run; microSD optional; USB download | shared-memory telemetry | raw on microSD, summary on QSPI (capacity, `telematics_budget.md`) | logging profile; card fitted |
| Time base | — | GNSS PPS + RTC | — | receive timestamps on the telematics unit | timestamp resolution |
| Signal voltage levels | — | 3.3 V GPIO inputs; fused 5 V sensor supply | — | 3.3 V MCU I/O; 5 V/3.3 V hall supply jumper | hall supply and output type; throttle range; safety-loop voltage |
| Power for electronics | — | wide-range DC input | — | controller logic from its battery input | which battery; joulemeter position (rules) |
| Motor | — | — | no traction controller code | three-phase PMSM/BLDC with halls (conditional, ADR-0003) | **identity and ratings** |
| Battery / BMS | — | BMS on CAN | joulemeter frame in CHUDS | ≤ 60 V class assumed by rule, UNVERIFIED | **voltage range, limits** |

## Smallest set of actual-team inputs that selects the interface
1. **Existing telemetry hardware:** is the telematics unit built or only drawn? Which CAN transceiver and controller (STM32U575 FDCAN in classic mode?).
2. **Wiring diagram:** bus topology, where the two 120 Ω terminations sit, connector and pinout, stub lengths, whether supply and ground run in the harness.
3. **Protocol and message definitions:** bit rate and sample point; 11 or 29-bit identifiers; the ID map (or a DBC) for BMS, wheel-speed and driver nodes; any stop message.
4. **Voltage levels:** CAN transceiver supply; hall and throttle supply and output ranges; safety-loop voltage.
5. **Sample rates:** what the team needs logged at what rate; the LTE downsampling plan.
6. **The computer responsible for supervision**: the telematics unit, another computer, or none (MANUAL only).

With these six answered, the CAN mode, crystal, termination, identifier block, DBC base and supervisor placement can all be fixed.
