# Telematics logging capacity, LTE volume and auxiliary power (generated)

> `tools/telematics_budget.py`. Tags: [P] this project's protocol (exact); [T] telematics proposal v0.1 (design input, not built); [A] assumption; [R] recalled typical value, NOT verified. Nothing here is a measurement. Other nodes' message sets do not exist yet, so their rates are assumed ranges.

## 1. Frame rates

| Source | Frames/s | Basis |
|---|---|---|
| semmc controller -> bus (12 messages) | 394 | [P] periods in protocol.yaml |
| supervisor -> controller (hello, limits, torque request, CSIA advisory) | 72 | [P]; sent by whichever computer runs the supervisor |
| BMS (cell V, SOC, temps) [T] rates [A] | 10-50 | assumed |
| wheel speed node [T] rates [A] | 10-100 | assumed |
| driver input node (optional) [T] rates [A] | 10-50 | assumed |
| GNSS (NEO-M9N class) [T], not on CAN, 32 B records | 1-10 | [A] |
| IMU 6-axis [T], not on CAN, 16 B records | 50-200 | [A] |

Raw CAN log record: 16 B [A] (u32 microsecond timestamp, u16 id + flags, u8 DLC, u8 bus, 8 data bytes; a periodic 64-bit time marker handles the 71-minute wrap). QSPI flash 8 MiB [T], 90 % usable [A] = 7.55 MB.

## 2. Local logging capacity

| Logging profile | Bytes/s | QSPI flash lasts | fits synthetic track model (1000 s limit)? | fits 40 min attempt [A]? | microSD 32 GB [A] lasts |
|---|---|---|---|---|---|
| semmc frames only (controller + supervisor), full rate | 7,456 | 16.9 min | yes | **no** (42 %) | 1,192 h |
| all CAN at full rate + direct sensors, LOW node rates | 8,768 | 14.4 min | **no** (86 %) | **no** (36 %) | 1,014 h |
| all CAN at full rate + direct sensors, HIGH node rates | 14,176 | 8.9 min | **no** (53 %) | **no** (22 %) | 627 h |
| semmc decimated to <= 10 Hz + others LOW + direct LOW | 3,328 | 37.8 min | yes | **no** (95 %) | 2,671 h |

* **The proposed 8 MB QSPI flash cannot hold one 40-minute attempt of the controller's frames at full rate**, before any other node is added. Options, in order of simplicity: make the microSD (shown optional in the proposal) the raw log and keep the QSPI flash for a decimated summary; log the 50-100 Hz controller messages at a reduced rate (row 4); or a larger flash. The controller's own rates can also be reduced, but that changes supervisor freshness margins (`INTERFACE_CONTROL.md`) and needs the hazard analysis.
* Flash write bandwidth and endurance are not limiting at a few kB/s (NOR page program and sector erase rates are orders of magnitude higher [R]); the binding constraint is capacity.

## 3. LTE / MQTT volume (live, downsampled) [T][A]

| Payload | Rate | Bytes per publish incl. overhead | kB per hour | MB per 40 min attempt |
|---|---|---|---|---|
| JSON, ~25 signals | 1 Hz | 640 | 2,304 | 1.54 |
| JSON, ~25 signals | 5 Hz | 640 | 11,520 | 7.68 |
| packed binary, ~25 signals | 1 Hz | 210 | 756 | 0.50 |
| packed binary, ~25 signals | 5 Hz | 210 | 3,780 | 2.52 |

Volume is small for any Cat-1 plan. The cost is energy (section 4): a modem kept connected to publish every 0.2-1 s rarely reaches its low-power states. Batching (for example one publish every 10 s carrying 10-50 samples) keeps the same data with far less radio-on time.

## 4. Auxiliary power and energy per attempt

### Telematics unit (as proposed)

| Item | Rail | Current (mA) | Power (mW) | Basis |
|---|---|---|---|---|
| STM32U575 running (SMPS/LDO dependent) | 3.3 V | 5-25 | 16-82 | [R] |
| GNSS receiver, continuous tracking | 3.3 V | 25-40 | 82-132 | [R] |
| active GNSS antenna | 3.3 V | 5-20 | 16-66 | [R] |
| IMU 6-axis | 3.3 V | 0.5-1.5 | 2-5 | [R] |
| CAN transceiver (bus-load dependent) | 5 V | 10-50 | 50-250 | [R] |
| QSPI flash, writing a few kB/s (average) | 3.3 V | 1-8 | 3-26 | [A] |
| microSD, if fitted (average) | 3.3 V | 0-40 | 0-132 | [A] |
| LTE Cat-1 modem, connected and publishing at 1-5 Hz (average) | 3.8 V | 60-250 | 228-950 | [R] |
| status LED + LED bar (burn/coast display) | 3.3 V | 2-40 | 7-132 | [A] |
| **total at the rails** | | | **405-1776** | |
| **at the input, DC-DC 85-90 % [A]** | | | **450-2089** | |

### Motor-controller logic (excludes gate-drive power and battery-voltage loads: MOSFETs and battery unknown)

| Item | Rail | Current (mA) | Power (mW) | Basis |
|---|---|---|---|---|
| STM32G474 at 150-170 MHz | 3.3 V | 25-60 | 82-198 | [R] |
| CAN transceiver TJA1051-class | 5 V | 10-70 | 50-350 | [R] |
| INA228 + watchdog + logic + opto | 3.3 V | 2-8 | 7-26 | [R] |
| hall sensors (motor unknown) | 5 V | 0-40 | 0-200 | [A] |
| **total at the rails** | | | **139-774** | |
| **at the input, DC-DC 85-90 % [A]** | | | **155-911** | |

| Load | Power (W) | Energy, 1000 s | Energy, 2400 s | Share of 42.7 kJ (SYNTHETIC track A, not our vehicle) |
|---|---|---|---|---|
| telematics unit | 0.45-2.09 | 0.45-2.09 kJ | 1.08-5.01 kJ | 1.1-4.9 % (1000 s) |
| motor-controller logic | 0.15-0.91 | 0.15-0.91 kJ | 0.37-2.19 kJ | 0.4-2.1 % (1000 s) |
| both | 0.60-3.00 | 0.60-3.00 kJ | 1.45-7.20 kJ | 1.4-7.0 % (1000 s) |

* Excluded and still unknown: gate-drive power (Q_g x V_GS x f_PWM x 6, MOSFETs not selected), the gate driver's supply current at battery voltage, and the BMS's own consumption.
* **Whether this energy counts against the vehicle depends on where the joulemeter sits** and what the 2027 rules require for auxiliary systems. Both are open questions (input sheet B3, R1). If it counts, the telematics unit is a first-order term: about 1-5 % of a synthetic 1000 s attempt's energy, dominated by the LTE modem's duty cycle.
* Measure, do not trust this table: bench-measure each board's input power with the modem in its real publishing pattern before deciding.
