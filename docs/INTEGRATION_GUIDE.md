# Vehicle interface specification (integration guide)

This is the single authoritative specification of the connections between the motor controller, the vehicle, the telemetry unit and the pit: motor and motor feedback (2.2), battery and BMS (2.8), throttle, brake, enable and emergency shutdown (2.1, 2.3, 5), wheel-speed measurement (2.9), controller-to-telematics communication (2.4 to 2.6), sensors and display (3, 4), power distribution and grounding (2.7). [`ICD.md`](ICD.md) holds the protocol, timing and logging details it refers to; [`INPUT_SHEET.md`](INPUT_SHEET.md) asks for what is unknown; [`BLOCKERS.md`](BLOCKERS.md) tracks it. It is kept with three classes apart:

* **Confirmed in the design** (section 2): defined in a repository file that a tool checks: the draft schematic (its netlist is compared with the intended nets by `tools/gen_kicad_schematic.py --check` and `tools/hw_consistency.py`), the CAN protocol (`protocol/protocol.yaml`, codecs and golden vectors), or host code with tests. "Confirmed" means the files agree. **It does not mean measured, reviewed or agreed with the vehicle team**: no board exists.
* **Proposed** (section 3): from the team's telematics proposal or the candidate research ([`TELEMETRY_CANDIDATES.md`](TELEMETRY_CANDIDATES.md)), not yet in a checked file.
* **Unknown** (section 4): no source yet. Each row names the input that resolves it ([`INPUT_SHEET.md`](INPUT_SHEET.md)).

No row may be read as construction-ready wiring. Connector families and pinouts are unresolved for every external connector; the "draft pin" columns give the pin of the generic connector symbol in the draft schematic, which will change when the harness is agreed. MCU pins are candidates from ST's pin database (`hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`, alternate functions and timing not verified). Numbers in the README's connection table (README section B.4) are given in brackets.

Contents: [1. Owners](#1-owners) · [2. Confirmed in the design](#2-confirmed-in-the-design) · [3. Proposed](#3-proposed) · [4. Unknown](#4-unknown) · [5. Shutdown](#5-shutdown) · [6. Changing an interface](#6-changing-an-interface)

## 1. Owners

| Interface | Owner (from [`ICD.md`](ICD.md)) | Single source |
|---|---|---|
| Controller behaviour and the CAN protocol | controls lead | `firmware/src`, `protocol/protocol.yaml` |
| Controller schematic and connectors | hardware lead | `tools/gen_kicad_schematic.py` (writes `hardware/kicad/`) |
| Calibration parameters | controls lead | `config/parameters.yaml`, vehicle files in `config/` |
| Telemetry unit, log format, uplink schema | telematics engineer | `host/telematics/` (reference implementation), [`ICD.md`](ICD.md) 8 to 10 |
| Pit database and analysis | pit software | `host/pit/` |
| Vehicle harness, safety loop, battery isolation | vehicle team | none yet |

No person is named for any role yet (README section H).

## 2. Confirmed in the design

### 2.1 Driver inputs to the controller [1, 2]

Connector J1001 (generic 12-pin symbol, sheet 10). Every switch input has a 10 kΩ pull-up to 3.3 V, a 1 kΩ / 10 nF RC filter (τ = 10 µs) and an ESD diode; the MCU samples them at each slow step (1 kHz in the host tools). Contact types, switch polarities and the safety-loop voltage are unknown (section 4); the brake switch is preferably normally closed (sheet note).

| Signal | Draft pin | MCU pin (candidate) | Level and conditioning | Units, meaning | Verification |
|---|---|---|---|---|---|
| Sensor supply `SENS_5V` | 1 | - | +5 V through a polyfuse | supply for the pedal | bench: polyfuse trip with a short (bring-up checklist) |
| Ground | 2 | - | GND | - | continuity |
| Throttle track A | 3 | PE12 (ADC3_IN16) | 0 to 5 V ratiometric pedal assumed; 10 kΩ / 18 kΩ divider (5 V reads 3.21 V), 100 kΩ pull-down (an open wire reads 0, which is implausible), 100 nF | demand 0 to 1 | two-track plausibility in firmware (`throttle_valid`); bench sweep of the real pedal |
| Throttle track B | 4 | PE13 (ADC3_IN3) | as track A | redundant track | as track A |
| Brake | 5 | PD13 | pull-up, RC, ESD | zero torque in the same step; exits ECO | `test_state_machine.c`; bench |
| ECO cancel | 6 | PF2 | as above | exits ECO | as above |
| Mode (manual / ECO) | 7 | PD7 | as above | an OFF to ON edge is needed for every ECO entry | as above |
| Arm | 8 | PD4 | as above | OFF to ON edge arms; OFF disarms | as above |
| Fault reset | 9 | PC8 | as above | rising edge requests a reset | as above |
| Dead-man | 10 | PD6 | as above; also part of the safety loop | driver present | as above |
| Safety loop + / - | 11, 12 | `HW_PERMIT` sensed on PD2 (`ESTOP_CHAIN_SENSE`) | PC817 optocoupler LED with a series resistor (UNRESOLVED: loop voltage unknown, about 5 mA); output 10 kΩ pull-down, 1 nF | loop energised → `HW_PERMIT` high | `hw_consistency.py` PR items; bench: open the loop and confirm the gate-driver ENABLE falls |

None of these signals can be set over CAN; their sampled values are echoed in `driver_controls` (0x312).

### 2.2 Motor feedback to the controller [6, 7]

| Signal | Connector, draft pin | MCU pin (candidate) | Level and conditioning | Rate | Verification |
|---|---|---|---|---|---|
| Hall supply | J901 pin 1 | - | +5 V or +3.3 V by solder jumper, polyfuse (UNRESOLVED) | - | measure at the connector |
| Hall A, B, C | J901 pins 3, 4, 5 (pin 2 GND) | PE2, PE3, PE4 (TIM3_CH1 to CH3) | 4.7 kΩ pull-up to 3.3 V (assumes open-collector outputs: verify), 1 kΩ / 1 nF (τ = 1 µs), ESD diode | edges up to 6 x pole pairs x motor revolutions per second | `test_control.c` (Hall decoding); bench: rotate by hand and log the sector sequence |
| Motor temperature | J701 pins 1, 2 | PE11 (ADC3_IN15) | bias resistor to +3V3A UNRESOLVED (sensor type unknown: NTC, PTC, KTY or PT1000), 1 kΩ / 100 nF, ESD diode | sampled at the slow step | compare with a reference thermometer at two temperatures |
| Power-stage temperature | on board (TH701) | PE10 (ADC3_IN14) | 10 kΩ NTC at the low-side MOSFETs, 10 kΩ bias to +3V3A, 1 kΩ / 100 nF | slow step | as above |
| Phase currents | on board | PA0 (ADC1_IN1), PA1 (ADC2_IN2), PE7 (ADC3_IN4) | gate-driver current-sense amplifier outputs, 100 Ω / 470 pF | one sample per PWM period | sampling window budget `hardware/timing/`; bench stage 4 |
| Bus voltage | on board | PE9 (ADC3_IN2) | divider (sheet 02) | slow and fast step | compare with a meter across the DC link |
| Bus current and energy | INA228 on I2C | PA15 (SCL), PB7 (SDA), ALERT on PD1 | 4.7 kΩ pull-ups, 10 kΩ on ALERT; address pins A0, A1 to GND | INA228 conversion time (datasheet to read) | compare with a calibrated shunt and meter ([`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 4) |

### 2.3 Controller to power stage, and the independent protection [3, 4, 5]

| Signal | MCU pin (candidate) | Destination | Notes | Verification |
|---|---|---|---|---|
| PWM high A, B, C | PC0, PC1, PC2 (TIM1_CH1 to CH3, AF2 verified against ST's pin database) | gate driver INHA to INHC | six-PWM mode; 100 kΩ pull-downs fitted (v0.6) | acceptance S4 with the bench image `semmc_stm32g474_pwmtest`, driver unpowered |
| PWM low A, B, C | PE8 (AF2), PB0, PB1 (AF6) (TIM1_CH1N to CH3N) | INLA to INLC | dead time from `inverter.deadtime_s` (depends on the MOSFETs); the bench image uses 1.0 µs | as above |
| `MCU_DRV_EN` | PD0 | 74LVC1G08 input A | 100 kΩ pull-down; ENABLE = `MCU_DRV_EN` AND `HW_PERMIT`, output pulled down | `hw_consistency.py`; bench: either input low disables the driver |
| gate-driver SPI | PA5, PA6, PA7, NSS on PD5 | DRV8353S candidate | pin numbers of the driver symbol are placeholders | datasheet before any footprint |
| nFAULT | PE15 (TIM1_BKIN) and PE1 | timer break input | open drain, pull-up; PWM off in timer hardware | bench: force nFAULT low, outputs go to the safe state |
| Bus over-voltage `BRK2_N` | PC3 (TIM1_BKIN2) | timer break input 2 | TLV7041 comparator, TL431 2.495 V reference through 10 kΩ, 390 kΩ hysteresis (trip +0.8 %, release -2.5 % around the divider's value); threshold divider UNRESOLVED | acceptance S6.6 |
| Watchdog | PE0 (WDI), PE5 (reset sense) | MAX6369 | WDO resets the MCU and pulls `HW_PERMIT` low through a diode | bench: stop servicing, confirm reset and driver disable |
| Precharge | PC6 (`PRECHG_EN`) | bypass driver FET | 100 kΩ pull-down, bypass open at power-up and in reset; closes when V_DC ≥ `power.precharge_complete_fraction` x V_BAT within `power.precharge_timeout_s` (`firmware/src/io/mc_precharge.c`, host-tested); waits for the INA228 driver (B-INA), so it never closes in this revision | acceptance S6.4 |
| Phases | - | J301 pins 1 to 3 | ratings wait for the motor and battery | - |
| Battery input | - | J101 pins 1 (VBAT_IN), 2 (PGND) | fuse, TVS, reverse-polarity block, all rating-dependent | - |

### 2.4 Controller to telemetry unit: CAN [8, 9]

Physical layer at the controller: TJA1051T/3 candidate (5 V supply, 3.3 V logic), PA11 / PA12 (FDCAN1), NUP2105L ESD protection, split termination 2 x 60.4 Ω with 4.7 nF behind two open solder jumpers (close only if the controller is a bus end), connector J1101 (draft pins 1 CAN_H, 2 CAN_L, 3 GND, 4 shield through 1 nF). Bus bit rate unknown: 500 kbit/s is assumed in the analyses.

Frames: classic CAN, 11-bit identifiers, 8 data bytes; byte 0 CRC-8 over a per-message data ID, byte 1 sequence counter ([`ICD.md`](ICD.md) 3). Identifiers are `can_id_base + (number - 0x300)`, base a multiple of 0x40 (proposed 0x300; the block is the vehicle team's to allocate).

| Message | Number | Direction | Period | Use | Verification |
|---|---|---|---|---|---|
| `ctrl_fault` | 0x300 | controller → bus | 1 s, early on entering or leaving `FAULT_LATCHED` | latched faults | golden vectors (`protocol/golden_vectors/vectors.json`), `test_protocol.c`, `tests/integration/test_protocol_python.py` |
| `ctrl_status` | 0x310 | controller → bus | 20 ms, early on a transition | state, owner, session, flags | as above |
| `ctrl_cmd_trace` | 0x311 | controller → bus | 20 ms | requested and accepted torque, reason bits | as above |
| `driver_controls` | 0x312 | controller → bus | 20 ms | echo of the wired inputs | as above |
| `ctrl_session` | 0x313 | controller → bus | 500 ms, early on change | session tag | as above |
| `ctrl_motion` | 0x318 | controller → bus | 10 ms | speed, iq, bus voltage | as above |
| `ctrl_currents` | 0x319 | controller → bus | 10 ms | phase and battery currents, KCL residual | as above |
| `ctrl_energy` | 0x320 | controller → bus | 100 ms | battery power and energy | as above |
| `ctrl_thermal` | 0x321 | controller → bus | 100 ms | FET and motor temperatures | as above |
| `ctrl_validity` | 0x322 | controller → bus | 100 ms | validity words | as above |
| `ctrl_energy_quality` | 0x323 | controller → bus | 100 ms | integrated and gap time | as above |
| `ctrl_identity` | 0x330 | controller → bus | 1 s | versions, calibration identity | as above |
| `sup_torque_req` | 0x308 | supervisor → controller | 20 ms (provisional) | ECO torque request | freshness tests `test_freshness.c`; host demonstration |
| `sup_limits` | 0x309 | supervisor → controller | 100 ms | ECO envelope | as above |
| `sup_hello` | 0x30A | supervisor → controller | 500 ms | session announcement | as above |
| `csia_advisory` | 0x328 | companion → controller | 100 ms | shadow tracking only; never used for torque | `test_core.c` |

Full layouts: [`generated/can_messages.md`](generated/can_messages.md). Load at 500 kbit/s: 12.6 % for this traffic ([`generated/bus_load.md`](generated/bus_load.md)); other nodes unknown. Bench verification: stage 3 of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (USB-CAN adapter, simulated controller and BMS).

### 2.5 Local logging [15, 20]

| Item | Value | Source | Verification |
|---|---|---|---|
| Format | STLG v1: header with metadata JSON and CRC-32, 4 KiB blocks with sequence and CRC-32, typed records (CAN, PPS, GNSS, IMU, wheel window, counters, event) | `host/telematics/stlg.py`; [`ICD.md`](ICD.md) 8 | reader tests; host demonstration: blocks ok, 0 corrupt |
| Rate | 9.35 KiB/s with every frame and the unit's sensors | host demonstration | write benchmark on the target ([`ICD.md`](ICD.md) 12) |
| Drops | queue full: newest record dropped and counted; storage full: counted | `node.py` | host demonstration check `log_drops_counted_not_hidden` |
| Import | `host/pit/ingest.py` `import_log`, idempotent on (run, block, index) | host code | check `offline_import_complete_and_idempotent` |

### 2.6 MQTT and the pit database [17, 18, 19, 21]

| Item | Value | Source | Verification |
|---|---|---|---|
| Topic, encoding | `sem/car/telemetry`, JSON, schema `sem.telemetry.v3` (v1 and v2 still accepted) | `host/telematics/node.py`; [`ICD.md`](ICD.md) 10 | `tests/integration/test_mqtt_pipeline.py` |
| Rate | 2 Hz (proposal allows 1 to 5 Hz) | `node.py` | demonstration |
| Quality of service | QoS 1; at most 10 unacknowledged; backlog of 30 messages, oldest dropped and counted | `host/telematics/mqtt_link.py` | check `uplink_backlog_bounded_and_drops_counted` |
| Pit subscriber | persistent session, fixed client id, commit before acknowledgement | `host/pit/mqtt_ingest.py` | check `pit_restart_without_loss` |
| Validation | schema, types (booleans rejected as numbers), states, ranges; every receipt in `rx` with its outcome | `host/pit/ingest.py` `validate_live` | check `invalid_messages_rejected_before_storage` |
| Storage | SQLite tables `runs`, `live` (key run, seq), `rx`, `rejected`, `records`, `signals`, `imports`; WAL mode | `ingest.py` | check `duplicates_ignored_and_ingest_idempotent` |
| Broker | Mosquitto 2.0.18 with persistence, loopback only in the tests | `tools/mqtt_broker.py`, `tools/mqtt/mosquitto.conf` | `run_mqtt_demo.py` (12 checks) |
| Analysis | shadow replay (B1, R3v, CSIA2) and energy per distance | `host/pit/shadow_replay.py`, `host/pit/energy.py`, `tools/run_pit_replay.py` | `test_shadow_replay.py`, `test_pit_energy.py` |

### 2.7 Power distribution and grounding

| Path | Design | Source | Verification |
|---|---|---|---|
| Battery input | J101 → fuse → TVS → reverse-polarity block → `VBAT_PROT` → bus shunt (INA228) → `VBAT_SH` → precharge resistor with the P-FET bypass → `VDC` (DC link) | sheet 01 | `hw_consistency.py` PW1; acceptance S1, S6 |
| Logic supply | LM5164 buck from `VBAT_PROT` (before the precharge: the MCU runs while the link charges) → +5 V → TLV75533 → +3V3 → ferrite bead → +3V3A (VDDA, VREF+) | sheet 12 | PW1; acceptance S3.1 to S3.4 |
| Ground | PGND (power stage, shunts) and GND (logic) are separate nets joined only at the net tie NT1201 at the phase-shunt ground | sheet 12 | connectivity check; acceptance S1.5 |
| Telemetry supply | not from the controller: the telemetry unit has its own protected DC-DC from the propulsion battery downstream of the joulemeter (Articles 56d, 57b), sized for the modem's 2 A peaks (A7672X Hardware Design V1.04 p. 26) | procurement line "Protected DC-DC supply"; `hardware/review/DESIGN_REVIEW.md` 11 | supply droop during transmit bursts |

### 2.8 Battery and BMS

| Item | Status | Value | Source |
|---|---|---|---|
| Nominal voltage, capacity | reported, not verified | 48 V, 10 Ah | team message 2026-10-16 ([`BATTERY.md`](BATTERY.md)) |
| Maximum charged and minimum voltage, chemistry, cells, current limits, BMS thresholds | unknown | null in the configuration | request 1 |
| Power connection | confirmed in the design | J101 pins 1 (VBAT_IN), 2 (PGND), ratings UNRESOLVED | sheet 01 |
| Battery-side measurement | confirmed in the design, driver blocked | INA228 on the battery side of the precharge: voltage, current and energy | sheet 06; B-INA |
| BMS data link | unknown | none in the controller design; whether the BMS has one (CAN, UART) is part of request 1 | - |

### 2.9 Wheel speed

The controller measures rotor speed only, from the motor's hall sensors (2.2). Wheel speed is measured by the telemetry unit (proposed, section 3 row 11), logged as wheel windows in the STLG log and sent in the live summary (`wheel.speed_mps` since `sem.telemetry.v2`, null without a fresh window). The pit derives distance and energy per distance from the logged windows (`host/pit/energy.py`).

### 2.10 Proposed decisions in this revision

Not yet decisions: each needs the named input or a review before it is recorded in [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md).

| Proposal | Why | Needs |
|---|---|---|
| 16 MHz crystal, 160 MHz SYSCLK | exact classic CAN bit rates with the FDCAN kernel on the crystal; the internal RC's tolerance exceeds the CAN limit (`hardware/review/DESIGN_REVIEW.md` 13) | request 5 (bus bit rate) |
| Brake switch normally closed | an open wire then reads as braking | request 4 |
| Precharge on the controller board | the controller sequences it with its own measurements | request 1 and the vehicle's contactor arrangement (open decision 4 in `hardware/selection/COMPONENT_SELECTION.md`) |
| Hardware overcurrent through the MCU's internal comparators into the timer break | a faster trip without a schematic change; not independent: it watches the gate driver's own amplifiers and exists only once firmware has configured it (`DESIGN_REVIEW.md` 5) | request 2 (peak current), D1 (RM0440) |
| Zero-current offsets measured with the driver awake and all gates off | the driver's amplifiers may be off while it is disabled | D1 (DRV8353) |

## 3. Proposed

Telemetry unit side. Source: the team's telematics proposal (STM32U575) and the candidate research; the board files have not been received, so no pin is allocated.

| # | Source → destination | Connector, pin | Signal and level | Units, rate | Termination, pull-up | Verification method |
|---|---|---|---|---|---|---|
| 8 | CAN bus → telemetry MCU | board connector (proposal: CANH, CANL, GND) | external transceiver to FDCAN1, 3.3 V logic; the Nucleo has no transceiver | 466 frames/s from the controller and supervisor | 120 Ω at both bus ends (proposal) | FDCAN RX FIFO overrun counter at the full rate ([`ICD.md`](ICD.md) 12) |
| 9 | ECO supervisor → controller | as above | `sup_*` messages | 50 Hz requests (provisional) | - | GPIO timing of the task during flash stalls and LTE transfers |
| 11 | wheel Hall sensor → timer input capture | to be allocated | continuous Hall switch (DRV5023-Q1 class: 2.7 to 38 V supply, output delay 25 µs max); DRV5032 rejected (sampled) | pulses: 149 Hz at 7 m/s with 32 pulses per revolution and C = 1.5 m | depends on the output stage of the selected part | stage 2 bench: magnet wheel at known speeds, compare counts and period |
| 12 | GNSS → telemetry MCU | carrier board | NEO-M9N UART (default 38400 baud), VCC 2.7 to 3.6 V; PPS to a timer capture input | fix at 10 Hz logged (25 Hz possible); PPS 1 Hz | active L1 antenna from VCC_RF, at most 50 mA | PPS capture against the unit's clock for 10 minutes |
| 13 | IMU → telemetry MCU | carrier board | SPI or I2C at 3.3 V (LSM6DSV or ISM330DHCX) | 100 Hz logged | - | offset calibration at rest; self-test at boot |
| 14 | temperature probes → telemetry MCU | to be allocated | DS18B20 1-Wire, 3.0 to 5.5 V | 1 Hz or slower (750 ms per 12-bit conversion) | about 5 kΩ pull-up (datasheet p. 7) | step test for each probe's time constant. **Excluded** until a log record type exists |
| - | steering angle (optional) → telemetry MCU | to be allocated | AS5600 I2C at fixed address 0x36, 3.3 V with VDD5V and VDD3V3 tied | up to 100 Hz | bus pull-ups | bench: angle sweep with the real magnet mount |
| 15 | telemetry MCU → storage | on board | QSPI NOR flash 8 MB (proposal); microSD recommended | 9.35 KiB/s | - | write benchmark with sector erases; power cut during a write |
| 17 | telemetry MCU → LTE modem | on board | A7672 UART at **1.8 V** with RTS/CTS: a level translator is needed to 3.3 V; default 115200 baud | 2 Hz messages | - | AT command loop on the bench; UART ready about 8 s after power-up |
| 17 | modem supply | on board | VBAT 3.4 to 4.2 V (3.8 V recommended); peaks up to 2 A at maximum 2G transmit power | - | bulk capacitance at least 300 µF if the supply delivers 2 A, else 600 µF | supply droop measurement during transmit bursts |

## 4. Unknown

| Connection | What is unknown | Resolved by |
|---|---|---|
| Battery and BMS [10] | chemistry, cell count, maximum and minimum voltage, discharge and regenerative current, BMS thresholds, whether the BMS has a data interface (CAN, UART, none) | battery and BMS model numbers, label photos, datasheets ([`BATTERY.md`](BATTERY.md)) |
| Battery connector, isolation and fuse order | connector type, emergency isolation position relative to the joulemeter, fuse ratings | vehicle wiring plan; the event rules |
| Telemetry power | DC-DC input rating (from the maximum pack voltage with transients), fuse, where the branch leaves the main wiring | battery datasheet; telemetry board files |
| Display [16] | type, interface, power (vehicle-powered through the joulemeter, or an unmodified device with a built-in battery, Article 57i) | display decision |
| Vehicle CAN bus | bit rate, classic or FD, other nodes and their identifiers, termination positions | input sheet item 5 |
| All external connectors | families and pinouts (J101, J301, J701, J901, J1001, J1101; telemetry board) | harness agreement ([`ICD.md`](ICD.md) 11) |
| Driver controls | contact types, switch polarities, pedal type and supply, safety-loop voltage | vehicle team |
| Motor feedback | Hall output stage and supply; motor temperature sensor type | motor datasheet |
| Broker hosting | where the internet-reachable broker runs at the event | event network and hosting decision ([`MQTT_SETUP.md`](MQTT_SETUP.md)) |

## 5. Shutdown

| Event | Path | Effect | Independent of firmware |
|---|---|---|---|
| Emergency stop or dead-man released | safety loop → PC817 → `HW_PERMIT` low | gate-driver ENABLE low; the controller disarms on the next slow step (T15) | yes |
| Gate-driver fault | nFAULT → TIM1_BKIN | PWM outputs off in the timer | yes |
| Bus over-voltage | comparator → TIM1_BKIN2 | PWM outputs off in the timer | yes |
| Watchdog timeout | MAX6369 → MCU reset and `HW_PERMIT` low | driver disabled, MCU restarts in `BOOT` | yes |
| Software fault | protection → `FAULT_LATCHED` | zero torque, PWM off; local reset only | no |
| Brake, cancel | wired inputs | zero torque in the same slow step | no (firmware), but local to the controller |
| Telemetry power removed (emergency stop, Article 37e) | battery isolation | the log loses at most its open block; the pit sees a gap by sequence number | n/a |
| LTE, broker or pit lost | - | only the summary stops; the log continues; drops counted | n/a |

Over-current: there is no independent over-current comparator in the draft; hardware over-current shutdown relies on the gate driver's drain-source monitoring through nFAULT ([`../hardware/protection/SHUTDOWN_TRUTH_TABLE.md`](../hardware/protection/SHUTDOWN_TRUTH_TABLE.md) 2). This is an open design item ([`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md) D8).

## 6. Changing an interface

Follow these steps for any change to a connection above: a CAN message or field, the MQTT schema, the log format, a configuration parameter, a connector, a pin or a signal level.

1. **Write the change down first.** One entry in [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md): which connection (number in README section B.4), what changes, why, and the evidence (datasheet page, measurement, rule).
2. **Classify it.**
   * CAN protocol: adding a message or a field in unused bits is a minor version (1.1 → 1.2); changing a field's position, scale or meaning, or removing one, is a major version, and both nodes must change together (a major mismatch is rejected by the CRC data ID).
   * MQTT summary: a new schema name (`sem.telemetry.v3`) whenever a field changes meaning or a required field is added; the pit keeps accepting the older names it can still read.
   * STLG log: a new record type; readers keep unknown types as raw bytes, so old readers do not break.
   * Calibration: a new parameter id; missing values are never defaulted.
   * Electrical (connector, pin, level, pull-up): a schematic change and a harness change.
3. **Edit the single source and regenerate.**
   * `protocol/protocol.yaml`, then `python3 tools/gen_protocol.py` (C and Python codecs, golden vectors and `docs/generated/can_messages.md`) and `python3 tools/gen_dbc.py` (the DBC file for CAN tools).
   * `config/parameters.yaml`, then `python3 tools/gen_config.py`.
   * `tools/gen_kicad_schematic.py`, then the connectivity and consistency checks ([`../hardware/README.md`](../hardware/README.md) section 6).
   * MQTT: `SCHEMA` in `host/telematics/node.py` and `SCHEMAS_ACCEPTED` with `validate_live` in `host/pit/ingest.py`.
4. **Add the tests.** A golden vector or a compatibility test for the old form (as `test_v2_wheel_speed_validated_and_v1_still_accepted` does for the summary), and a test that fails without the change.
5. **Update the documents in the same commit:** [`ICD.md`](ICD.md), this guide, README section B.4 if a connection appears or disappears, [`INPUT_SHEET.md`](INPUT_SHEET.md) if an input is now needed.
6. **Run the checks:** every generator with `--check`, `python3 -m pytest`, `ctest --test-dir build`, `python3 tools/check_links.py`, then `python3 tools/verify_all.py --out build/verify`.
7. **Review.** The owner of each side (section 1) approves the pull request. Nothing is merged automatically.
8. **Verify on the bench** before vehicle use, at the stage of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) where the connection first exists, and move the row from section 3 or 4 to section 2 with the evidence.
