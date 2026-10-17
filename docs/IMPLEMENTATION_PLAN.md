# Implementation plan

Eight stages from the host software that exists today to a fair comparison of energy strategies on the vehicle. Each stage needs the previous ones passed and recorded, except that stages 2 to 4 (telemetry) and stage 5 (controller hardware) can run in parallel. Only stage 1 is done, and only on the host with synthetic data.

**Safety.** Every energised test (stages 5 to 8) is carried out by qualified team members under their own laboratory and event safety procedures. Nothing in this repository authorises energising a board, and no step is to be carried out autonomously.

The controller stages map onto the hardware validation stages of [`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 2 and the bench procedure [`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md); the telemetry stages use the bench checks E1 to E9 of [`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md) 4.

| Stage | Goal | Status |
|---|---|---|
| 1 | Host simulation and replay | done on the host (synthetic) |
| 2 | Development board with one real sensor | not started: telemetry firmware not written |
| 3 | Bench CAN with a simulated controller and BMS | not started |
| 4 | Logging and a broker outage with the real modem | not started |
| 5 | Reviewed controller hardware and staged bring-up | blocked: battery, motor and datasheet inputs; no layout |
| 6 | Controller and telemetry integration | not started |
| 7 | Controlled vehicle measurements | not started |
| 8 | Fair strategy comparison | not started |

## Stage 1. Host simulation and replay

* **Prerequisites:** none.
* **Files:** `firmware/` (core, host platform, simulated plant), `host/` (telemetry node, supervisor, pit), `tools/run_host_demo.py`, `tools/run_mqtt_demo.py`, `tools/run_pit_replay.py`, `tools/verify_all.py`.
* **Equipment:** a Linux computer; Mosquitto for the MQTT demonstration.
* **Test procedure:** README section F; then `python3 tools/verify_all.py --out build/verify`.
* **Completion evidence:** GitHub-hosted CI green on the commit; [`generated/host_demo/summary.md`](generated/host_demo/summary.md) (10 checks), [`generated/mqtt_demo/summary.md`](generated/mqtt_demo/summary.md) (12 checks), [`generated/host_demo/pit_replay_report.md`](generated/host_demo/pit_replay_report.md); the verification record ([`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md)).
* **Blockers:** none. **Limits:** every vehicle parameter is synthetic; the simulated plant has the motor rigidly coupled; nothing here says how the vehicle behaves.

## Stage 2. Development board with one real sensor

* **Prerequisites:** stage 1; a continuous Hall switch candidate chosen from the wheel geometry ([`generated/wheel_sensor_check.md`](generated/wheel_sensor_check.md)); the telemetry firmware started.
* **Files:** a new directory for the telemetry firmware (to be created; the host model stays the reference); `host/telematics/stlg.py` (log format to reproduce byte for byte), `host/telematics/sensors.py` (wheel-window semantics: counts per 100 ms window), `host/pit/ingest.py` (`import_log`), [`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md).
* **Equipment:** NUCLEO-U575ZI-Q, the Hall sensor on a breakout, one magnet, a disc or wheel driven at known speeds with a reference (optical tachometer), a microSD breakout or the board's flash, a current-limited 5 V supply.
* **Test procedure:**
  1. Log WHEEL records at three or more speeds up to the speed that corresponds to the vehicle's maximum.
  2. Import the log with `import_log` and compare the counts with the reference speed; record the edge periods as well if the firmware measures them (recommended).
  3. Cut the supply 100 times while writing (check E4).
* **Completion evidence:** the imported log in a pit database; a table of counts against reference speed with zero missed pulses up to the maximum speed; the E4 result (every closed block readable).
* **Blockers:** wheel circumference, maximum speed, magnet count and air gap (input sheet); sensor selection.

## Stage 3. Bench CAN with a simulated controller and BMS

* **Prerequisites:** stage 2; a CAN transceiver breakout for the Nucleo (it has none); the bus bit rate (500 kbit/s may be used on the bench until the vehicle bus is known).
* **Files:** `host/vcu_bridge/semmc_socketcan.py` (SocketCAN encode and decode), `protocol/generated/semmc_protocol.py`, `firmware/platform/host/host_main.c` (`semmc_host` produces the controller's frames), `host/telemetry_adapter/supervisor.py` (reference supervisor), [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md) 2.4.
* **Equipment:** a USB-CAN adapter on a Linux computer, a bench CAN cable with 120 Ω at both ends.
* **Test procedure:**
  1. Send the controller's frames from a recorded host run at the full rate (466 frames/s with the supervisor's) while the Nucleo writes its log, including during a forced flash stall (check E2).
  2. Run the supervisor task on the Nucleo against `semmc_host` through SocketCAN and capture its timing on a GPIO (check E1).
  3. A simulated BMS is added only when the BMS interface is known.
* **Completion evidence:** E1 and E2 records; an imported log with no bad-CRC frames and every drop counted; the ECO session established and lost on timeout as in the host demonstration.
* **Blockers:** vehicle bus type and bit rate; BMS interface (unknown).

## Stage 4. Logging and a broker outage with the real modem

* **Prerequisites:** stage 3; the A7672 variant for the event region with antenna and SIM; a broker reachable from the mobile network ([`MQTT_SETUP.md`](MQTT_SETUP.md) 4); a 1.8 V level translator for the modem UART.
* **Files:** `host/telematics/mqtt_link.py` and `host/pit/mqtt_ingest.py` (reference behaviour), `tools/mqtt/mosquitto.conf`, [`ICD.md`](ICD.md) 10.
* **Equipment:** modem board, SIM, LTE antenna, current probe for the modem supply, the pit laptop.
* **Test procedure:** checks E5 (20 s network outage), E6 (pit restart), E7 (modem supply during transmission), E9 (supply cut as the emergency stop would), and E8 (the unit's average and peak power over a simulated attempt).
* **Completion evidence:** a pit database in which every sequence number is stored, counted as dropped on the car, or reported as a gap; supply-droop captures within 3.4 to 4.2 V; the unit's consumption recorded as an energy term.
* **Blockers:** event country and operator, broker hosting, telematics board files (whether the modem and supply are on the board).

## Stage 5. Reviewed controller hardware and staged bring-up

* **Prerequisites:** battery and BMS datasheets (maximum and minimum voltage, currents), motor data, the primary datasheets in [`../hardware/selection/DATASHEET_REGISTER.md`](../hardware/selection/DATASHEET_REGISTER.md), footprints and a layout, the signed design review ([`../hardware/review/REVIEW_CHECKLIST.md`](../hardware/review/REVIEW_CHECKLIST.md)), and the STM32G4 platform layer (ADC, PWM, timers, CAN driver, precharge closing logic, watchdog servicing).
* **Files:** `hardware/`, `firmware/platform/stm32g4/README.md`, [`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md).
* **Equipment:** current-limited bench supply above the maximum pack voltage, oscilloscope with a differential probe (borrowed; not in the budget), multimeters, dummy load, SWD programmer.
* **Test procedure:** the bring-up checklist stages 1 to 5: unpowered inspection, logic only, gates with the power stage disabled, first energised switching at low voltage with both current limits set and probed, motor on a stand with the wheel free.
* **Completion evidence:** the signed review; measurement tables and scope captures for each stage; a vehicle configuration with `provenance: bench_measured` that passes hardware-mode validation.
* **Blockers:** every hardware input above. The board does not exist.

## Stage 6. Controller and telemetry integration

* **Prerequisites:** stages 4 and 5.
* **Files:** [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md), [`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 3 and 4.
* **Equipment:** both units on a bench CAN bus, the bench supply, a calibrated reference shunt and meter.
* **Test procedure:**
  1. Repeat the host fault list on hardware: stale, repeated and reordered requests, bus-off, companion disconnect, controller reset during a request.
  2. Calibrate the bus-current meter (INA228) against the reference.
  3. Compare the controller's energy with the reference.
  4. Run `tools/run_pit_replay.py` on an imported bench log.
* **Completion evidence:** a test record per fault; meter gain and offset with uncertainty; a replay report whose data class reads measured (bench) and lists what is still insufficient.
* **Blockers:** the supervision timing is provisional: a hazard and latency analysis must replace it before ECO is offered in the vehicle.

## Stage 7. Controlled vehicle measurements

* **Prerequisites:** stage 6; the vehicle integrated; the organiser's and the team's safety process; manual driving first.
* **Files:** [`ENERGY_METHODS.md`](ENERGY_METHODS.md) 2.3, [`generated/coastdown_sensitivity.md`](generated/coastdown_sensitivity.md), `models/vehicle/longitudinal.py` (`fit_coastdown`).
* **Equipment:** the vehicle, a measured track section with known grade, an anemometer.
* **Test procedure:**
  1. Coast-downs in both directions on the same section, with the grade surveyed and the wind recorded.
  2. Constant-speed runs.
  3. IMU offset calibration at rest.
  4. Cross-check the wheel channels.
  5. Measure the telemetry unit's consumption.
  6. If accessible, compare the controller meter with the joulemeter in a static test.
* **Completion evidence:** road-load coefficients with uncertainty and an identifiability verdict; a measured loss map; the vehicle configuration updated with sources.
* **Blockers:** track access; the event rules for the governing year.

## Stage 8. Fair strategy comparison

* **Prerequisites:** stage 7; a minimum useful effect and exclusion rules written down before testing ([`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 5).
* **Files:** `models/optimization/`, `tools/run_optimization.py`, `host/pit/energy.py`.
* **Equipment:** the vehicle and the same driver for every run where possible.
* **Test procedure:**
  1. Counterbalanced run order (for example ABBA).
  2. The same route and finish-time target for every run.
  3. A kinetic-energy correction between start and end.
  4. The same auxiliary loads in every run.
  5. The energy boundary stated: joulemeter, or the controller input with the difference known.
* **Completion evidence:** the run-level mean difference with a 95 % confidence interval, combined with the energy-measurement uncertainty; every run kept, including failed ones.
* **Blockers:** the number of attempts available.

CSIA stays in shadow mode through every stage. It may be considered for tightening (never commanding) supervisory bounds only after the evidence gate of [`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 6 is met on vehicle data.
