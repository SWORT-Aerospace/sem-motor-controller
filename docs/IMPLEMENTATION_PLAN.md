# Implementation plan (v0.7, telematics)

The single plan for this repository. The deliverable is the telematics unit and the pit software; the motor controller is built by another team ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)). Open items with their owners are in [`BLOCKERS.md`](BLOCKERS.md); this page orders them.

**Critical path.** Interface agreement and telemetry hardware selection, then embedded acquisition and the local log, then bench integration, then the remote uplink, then vehicle data and analysis. T1 and T2 can run at the same time: T2 needs only a development board and a signal generator. Controller items (power-stage parts, precharge, footprints, the current loop) block none of these stages; they are listed at the end as deferred controller development.

**Safety.** The unit only listens: it sends nothing to the controller, and no stage below adds a transmit path. Connecting to the vehicle is done only with the controller team's agreement, after the electrical checks of stage T3, by team members under their own laboratory and event safety procedures. Nothing in this repository authorises energising the vehicle, and no step is to be carried out autonomously.

| Stage | Goal | Status | Blockers |
|---|---|---|---|
| T0 | Host software and simulation | done on a computer: receive-only node, adapters, pit, independent demonstration (9 checks through a real broker) | none |
| T1 | Interface agreement and telemetry hardware selection | request written, not sent; BOM lines priced as dated search snapshots, parts not chosen | [T-CTRL-IF](BLOCKERS.md#t-ctrl-if), [T-PARTS](BLOCKERS.md#t-parts), [B-BAT-V](BLOCKERS.md#b-bat-v) |
| T2 | Embedded acquisition and local log | firmware written and built for the NUCLEO-U575ZI-Q; **never flashed** | [T-BENCH1](BLOCKERS.md#t-bench1), [T-U5-DOCS](BLOCKERS.md#t-u5-docs), [T-STORAGE](BLOCKERS.md#t-storage), [T-GNSS](BLOCKERS.md#t-gnss) |
| T3 | Bench integration | CAN receive image built; not run | [T-CTRL-IF](BLOCKERS.md#t-ctrl-if) for the controller's frames and connector |
| T4 | Remote uplink | host model only | [T-MODEM](BLOCKERS.md#t-modem), [B-RULES](BLOCKERS.md#b-rules) |
| T5 | Vehicle data and analysis | pit analysis ready on simulated data; no vehicle data | T1 to T3; [B-DRIVETRAIN](BLOCKERS.md#b-drivetrain) |

## T0. Host software and simulation (done on a computer)

* **Files:** `host/telematics/` (node, measurement model, signal registry, controller adapters, wheel estimator, simulated external controller), `host/pit/` (validation, SQLite, energy, shadow replay), `tools/run_telematics_demo.py`, `tools/telematics_import.py`.
* **Evidence:** [`generated/telematics_demo/summary.md`](generated/telematics_demo/summary.md) (9 checks through Mosquitto 2.0.18: no command frames, missing data null and never zero, every dropped record accounted for, acquisition through an uplink outage, no duplicates on re-ingestion, speed and distance from edge timing, energy at two boundaries, a restart as a new session); `python3 -m pytest -m "telematics or reference"`; [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) section 9.
* **Limits:** every input is simulated, including the external controller (`host/telematics/sim_vehicle.py`); host simulation is not embedded firmware.

## T1. Interface agreement and telemetry hardware selection

* **Prerequisites:** none.
* **Files:** [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md), [`TELEMATICS_BOM.md`](TELEMATICS_BOM.md) (from `hardware/telematics/bom.yaml`, `tools/telematics_bom.py`), `host/telematics/controller_adapter.py` (`DbcAdapter`), `host/telematics/signals.py`.
* **Steps:**
  1. Send the request to the controller team. Receive their answers, DBC (or protocol document) and a recording.
  2. Write the mapping from their DBC to the signal registry (units checked against the DBC) and replay the recording through `DbcAdapter`; send them the decoded values for confirmation.
  3. If an essential signal (DC voltage and current at the controller input) is missing, send the exact broadcast request of section 4 of the request sheet. Polling stays a separate decision.
  4. Take live quotes for the bench and configuration A lines. The vehicle supply (DC-DC, TVS, fuse) waits for the battery's maximum voltage (T-VEH-PWR); until then the unit runs from USB on the bench only.
* **Completion evidence:** the controller team's written answers in the repository; a mapping file and a decoded-recording report they have confirmed; a quoted configuration A list.
* **Blockers:** the controller team's answer; the battery maximum voltage (input protection; the 48 V nominal, 10 Ah figures are team-reported).

## T2. Embedded acquisition and local log

* **Prerequisites:** the bench parts (the `bench` lines of [`TELEMATICS_BOM.md`](TELEMATICS_BOM.md)); T1 is not needed.
* **Files:** the bench package (`python3 tools/telematics_bench.py package --images build-u575 --out build/telematics_bench --rebuild`, also a CI artifact): images with SHA-256, [`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md) (rendered from `telematics/bench/bench.yaml`), connection and parts lists, `tools/uart_capture.py`, a blank results form; `tools/telematics_import.py`; [`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md).
* **Equipment:** a function generator with a stated frequency accuracy, a multimeter, a scope or logic analyzer, two USB-CAN adapters (B11), STM32CubeProgrammer or OpenOCD, a soldering iron (the NOR onto its adapter).
* **Steps:**
  1. **First milestone:** bench steps B0 to B7: preflight, wheel pulse, timestamped measurement, bounded queue, log on the NOR, read-back, import, plotted speed and distance; the timebase error against the generator; stuck and disconnected sensors (B6); the 32-bit timer overflow at 71.6 min with the console capture and a ranged dump (B7).
  2. B8 to B10: power loss during a write, internal flash filling into sparse logging, erase.
  3. B12: IMU and TMP117 on I2C1.
  4. GNSS with PPS capture on the target (not written; the host model fixes the behaviour).
  5. The log storage for an attempt's length (T-STORAGE: the NOR holds 26.7 min of the fixture vehicle's mix at full rate; docs/generated/telematics_storage.md).
* **Completion evidence:** the bench record of each step with the import report and plots committed; the wheel channels against a reference tachometer once the vehicle's wheel is available.
* **Blockers:** the board on the bench; the STM32U575 reference documents (the register-level code is checked against ST's HAL and CMSIS sources, [`U575_REGISTER_CHECK.md`](U575_REGISTER_CHECK.md); RM0456, DS13737, ES0499 and UM2861 were not readable here); the wheel circumference and magnet count for real speed (B-DRIVETRAIN).

## T3. Bench integration

* **Prerequisites:** T2 steps 1 to 3; the CAN Pal (bench line `can_xcvr`) with its silent pin high; two USB-CAN adapters; for step 2, the controller team's DBC and recording.
* **Files:** `telematics/firmware/platform/u575/can_u575.c` (FDCAN1 in bus-monitoring mode), [`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md) B11 and section 7, `host/telematics/controller_adapter.py`.
* **Steps:**
  1. B11: `tm_u575_can.bin` against a USB-CAN adapter: the board acknowledges nothing and sends nothing; every frame counted.
  2. Replay the controller team's recording onto a bench bus at its real rate and bit rate; import the board's log through the DBC adapter; compare with the recording frame by frame.
  3. Electrical checks E1 to E6 with the controller team's connector pinout and ground point: transmitter disabled in hardware, unpowered behaviour, no added termination, stub length, one ground, no back-feeding.
* **Completion evidence:** frame counts on every node with error counters; the comparison report; the E1 to E6 records with scope captures, reviewed by the controller team.
* **Blockers:** the interface agreement (T1). "Receive-only" in firmware does not prove electrical noninterference: E1 to E6 are required before any vehicle bus.

## T4. Remote uplink

* **Prerequisites:** T2; the configuration B modem board, SIM and antenna; a broker reachable from the mobile network ([`MQTT_SETUP.md`](MQTT_SETUP.md)).
* **Files:** `host/telematics/node.py` and `host/telematics/mqtt_link.py` (the reference behaviour, `sem.telemetry.v4`), `host/pit/mqtt_ingest.py`, [`ICD.md`](ICD.md) A.8, [`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md) section 4 (U1 to U5).
* **Steps:** the modem driver as a non-blocking state machine below acquisition and logging; then U1 to U5: network outage and reconnect, pit restart, modem supply droop, the unit's consumption, a supply cut.
* **Completion evidence:** a pit database in which every sequence number is stored, counted as dropped on the car, or reported as a gap; acquisition and the log unaffected during the outage (the same properties the host demonstration checks).
* **Blockers:** the event country (band set), broker hosting.

## T5. Vehicle data and analysis

* **Prerequisites:** T1 to T3 passed; the controller team's agreement to connect at a time they choose; the team's and the organiser's safety process; manual driving.
* **Files:** [`ENERGY_METHODS.md`](ENERGY_METHODS.md) section 0, `host/pit/energy.py`, `tools/run_pit_replay.py`, `models/vehicle/longitudinal.py` (`fit_coastdown`), [`generated/coastdown_sensitivity.md`](generated/coastdown_sensitivity.md).
* **Steps:**
  1. Logged runs: energy at the controller input and, with the battery-side monitor, at the battery; the missing intervals and their causes reported with each figure.
  2. Coast-downs in both directions on a surveyed section, with the wind recorded; constant-speed runs; the unit's own consumption.
  3. The shadow-mode monitors (R3v, CSIA2) on measured data; relationships whose inputs are missing are disabled and say so.
  4. Strategy comparison, offline: counterbalanced run order, the same route and finish-time target, a kinetic-energy correction, the energy boundary stated, a minimum useful effect written down before testing ([`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 5). Results go to the driver as advice; there is no automatic speed control.
* **Completion evidence:** per-run reports with data quality; road-load coefficients with uncertainty; the comparison's mean difference with a 95 % confidence interval, every run kept.
* **Blockers:** track access, the rule edition, the number of attempts.

CSIA stays in shadow mode at every stage, with no propulsion authority. The frozen evaluation (`csia/V2_FREEZE.json`, [`csia/EVALUATION_RESULTS_v2.md`](csia/EVALUATION_RESULTS_v2.md)) and its result favouring R3v are kept unchanged.

## Deferred controller development (not on the critical path)

Our earlier controller work is kept, with its own suite (`python3 -m pytest -m controller`) and CI job, in case the team needs it later. It blocks no telematics stage. Its stages, as recorded in v0.6:

* **D1. Reviewed controller hardware and staged bring-up.** Needs the battery and BMS datasheets, motor data, the primary datasheets ([`../hardware/selection/DATASHEET_REGISTER.md`](../hardware/selection/DATASHEET_REGISTER.md)), footprints and a layout, a signed design review ([`../hardware/review/REVIEW_CHECKLIST.md`](../hardware/review/REVIEW_CHECKLIST.md)), and the DRV8353 and INA228 bus transports on the STM32G474 (not written: `../firmware/platform/stm32g4/README.md`). Procedure: [`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md) S0 to S8; records checked with `tools/acceptance.py check`. The board does not exist; the release gate fails ([`generated/release_gate.md`](generated/release_gate.md)).
* **D2. Controller and supervisor integration.** The ECO supervisor (`host/telemetry_adapter/`) is a legacy mode, run only with `--legacy-supervised`; it is not part of the telematics unit. Its timing is provisional and needs a hazard and latency analysis before it could be offered in any vehicle ([`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md), [`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 3 and 4).
