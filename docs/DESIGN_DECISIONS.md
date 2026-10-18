# Design decisions

Each entry follows one chain: **requirement → evidence → choice or blocker → implementation → test.** "Evidence" names a document read, a computation in this repository, or a host result; nothing here is a bench or vehicle measurement, because none exists yet. Where the evidence does not support a choice, the entry says what blocks it.

The architecture decision records of v0.1 to v0.3 stay in [`decisions/`](decisions/) (ADR-0001 onwards); this page collects the decisions the integration of the telemetry and the vehicle depends on. New entries are added at the end with the next number, following [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md) 6 when an interface changes.

| # | Decision | State |
|---|---|---|
| D1 | Wheel-pulse capture instead of a sampled switch | chosen (sensor part blocked) |
| D2 | Battery power accuracy and time alignment | chosen for the design; accuracy unverified |
| D3 | Temperature measurement for protection and for logging | chosen; probe logging implemented (host), probe part open |
| D4 | Sensor and CAN electrical compatibility | partly chosen; blocked on the board files and the motor |
| D5 | Modem supply peaks | requirement set; blocked on the board files and the battery |
| D6 | Storage capacity and write behaviour | format chosen; medium open |
| D7 | Energy-strategy selection | blocked: needs vehicle measurements |
| D8 | Current sensing and over-current protection | open item: independent over-current comparator |
| D9 | Fault-reset behaviour of `SELFTEST` and `HALL_INVALID` | open: needs a controls decision |
| D10 | Live summary versioning (`sem.telemetry.v2`, `v3`) | chosen and implemented |

## D1. Wheel-pulse capture instead of a sampled switch

* **Requirement.** Count every magnet pass from standstill to the vehicle's maximum speed, so that distance and energy per distance are not biased; vehicle speed must be available when the motor is decoupled.
* **Evidence.** The team's reference part DRV5032 is a sampled switch: 20 Hz variants sample every 27 / 50 / 75 ms (minimum / typical / maximum) and the FB variant every 117 / 200 / 286 ms, with the output latched between samples (SLVSDC7F, [`TELEMETRY_CANDIDATES.md`](TELEMETRY_CANDIDATES.md)). In the reference grid it sees 11 to 17 % of passes at 10 km/h ([`generated/wheel_sensor_check.md`](generated/wheel_sensor_check.md)). A continuous switch (DRV5023-Q1 class, output delay 25 µs maximum, bandwidth 20 kHz minimum) sees every pass at any speed in the grid. Counting in 100 ms windows gives a resolution of C / (N T_w) = 0.47 m/s at 32 pulses per revolution and C = 1.5 m.
* **Choice.** A continuous (non-sampled) Hall switch on a timer input-capture channel; DRV5032 rejected for wheel speed. The firmware should also record edge periods, which removes the window quantisation at low pulse rates. **Blocked:** the part itself, magnet count and air gap wait for the wheel geometry and maximum speed (input sheet).
* **Assumptions behind the result.** The grid's magnet radius, field window and magnet count are assumptions; the detection percentages hold only for that grid and are not a property of the vehicle. They are to be replaced by the vehicle's geometry and a bench measurement of the field window.
* **Implementation.** `host/telematics/sensors.py` (counts per window), `host/telematics/node.py` and `host/pit/ingest.py` (v = counts C / (N T_w)), `host/pit/energy.py` (distance and the cross-check between wheels), `tools/wheel_sensor_check.py`.
* **Test.** `tests/hardware/test_wheel_sensor_check.py`; `tests/integration/test_pit_energy.py`; on the bench, stage 2 of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## D2. Battery power accuracy and time alignment

* **Requirement.** Energy at the controller input with a stated uncertainty; voltage and current aligned in time; every gap in the integration visible, never filled in.
* **Evidence.** INA228 (SLYS021, read in v0.5 from a GitHub-hosted copy of the TI document): shunt gain error ±0.05 % maximum; energy and charge total error ±1 % at full-scale power. "Power and energy are calculated based on the previous current calculation and the latest bus voltage measurement" (p. 13), so V and I in the meter's own power are one conversion apart. On the host, the controller's integrated energy and the simulated battery-terminal energy differ by 0.139 % (synthetic plant, [`generated/host_demo/summary.md`](generated/host_demo/summary.md)). The official result uses the organisers' joulemeter, which also counts every load downstream of it (2026 Articles 56c, 56d).
* **Choice.** Energy from the bus shunt with an INA228-class monitor, never from the phase shunts. The controller computes P = V I at each slow step only when both values are valid, integrates steps of at most 20 ms, and reports integrated and skipped time (`ctrl_energy_quality`). The meter is calibrated against a reference before any comparison ([`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 4). Whether the controller uses the INA228's own energy accumulator or integrates its readings is open until the conversion-time settings are chosen on the bench.
* **Implementation.** `mc_core_slow_step` in `firmware/src/core/mc_core.c`; `ctrl_energy`, `ctrl_energy_quality` in `protocol/protocol.yaml`; `host/pit/energy.py`.
* **Test.** `firmware/tests/test_core.c` (gap accounting: nothing integrated across invalid samples or late steps); host demonstration check `energy_boundary_and_gaps_reported`; on the bench, stage 6.

## D3. Temperature measurement for protection and for logging

* **Requirement.** Protection temperatures fast and local to the controller; slow temperatures for loss models at the pit.
* **Evidence.** DS18B20: up to 750 ms per 12-bit conversion, ±0.5 °C from -10 to +85 °C, no thermal time constant in the datasheet (Maxim 19-7487 Rev 5). The controller draft reads a 10 kΩ NTC at the low-side MOSFETs and a motor-temperature input; an unknown temperature derates instead of faulting.
* **Choice.** Protection uses only the controller's NTC and motor sensor. DS18B20-class probes are for logging only. Since v0.6 they have a log record (STLG `TEMP`, [`ICD.md`](ICD.md) 8) with a per-sample status, and the live summary carries them (`sem.telemetry.v3`). **Open:** the probe part and its placements (proposed: battery surface, motor case, ambient), and each probe's time constant on its mounting.
* **Implementation.** `firmware/src/protection/mc_protection.c` (trip and derating); sheet 07 of the schematic; `host/telematics/stlg.py` (record), `host/telematics/sensors.py` (synthetic probes), `host/telematics/node.py` (live block), `host/pit/ingest.py` (import and validation).
* **Test.** `firmware/tests/test_state_machine.c` and `test_core.c` (derating and trips); `tests/integration/test_host_demo.py` (`test_stlg_temperature_record_roundtrip_and_pit_import`), `tests/integration/test_mqtt_pipeline.py` (v3 validation, node staleness and invalid readings); MQTT demonstration check `live_wheel_and_temperature_match_log_and_v1_still_accepted`. Still to do once probes are fitted: a step test of each probe's time constant.

## D4. Sensor and CAN electrical compatibility

* **Requirement.** Every signal's supply and logic level matches its receiver, without stressing an input.
* **Evidence.** A7672 main UART at 1.8 V logic; NEO-M9N VCC 2.7 to 3.6 V; AS5600 at 3.3 V only with VDD5V and VDD3V3 tied; the ST IMUs run from 3.3 V I/O; the NUCLEO-U575ZI-Q has no CAN transceiver ([`TELEMETRY_CANDIDATES.md`](TELEMETRY_CANDIDATES.md)). On the controller: Hall inputs with 4.7 kΩ pull-ups to 3.3 V assume open-collector outputs; the Hall supply is 5 V or 3.3 V by jumper; the TJA1051T/3 candidate has a 5 V supply and a 3.3 V logic side; CAN termination is a split network that is fitted only at a bus end.
* **Choice.** One 3.3 V logic domain on the telemetry unit; a level translator on the modem UART; an external CAN transceiver for the Nucleo; termination only at the two bus ends. **Blocked:** the Hall output stage and supply (motor datasheet), the telemetry board's own interfaces (board files not received), the bus bit rate.
* **Implementation.** Schematic sheets 09 and 11; [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md) 2 and 3.
* **Test.** `tools/hw_consistency.py` for the controller side; on the bench, stages 2 and 3.

## D5. Modem supply peaks

* **Requirement.** The modem's VBAT stays within 3.4 to 4.2 V during transmit peaks; the telemetry unit is powered from the propulsion battery downstream of the joulemeter; no accessory battery.
* **Evidence.** A7672X Hardware Design V1.04: peak current "can reach 2A" at maximum GSM transmit power (p. 26); bulk capacitance at least 300 µF if the supply can deliver 2 A, otherwise at least 600 µF (p. 27); average LTE transmit current up to 859 mA at 23 dBm (p. 62). Rules: Articles 56d and 57b (2026 Chapter I). The proposal's BQ25622E charger implies an on-board battery, which Article 57b does not allow on a Battery Electric vehicle.
* **Choice.** A dedicated supply for the modem sized for 2 A peaks with the bulk capacitance above, fed from a fused DC-DC on the propulsion battery. **Blocked:** the DC-DC input rating needs the maximum pack voltage and its transients (battery datasheet), not the 48 V nominal; whether the board already has this supply (board files).
* **Implementation.** None yet (procurement line "Protected DC-DC supply").
* **Test.** Check E7 of [`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md) (current probe on VBAT during transmission), stage 4.

## D6. Storage capacity and write behaviour

* **Requirement.** A whole attempt logged; a power cut loses at most the block being written; writing never blocks the CAN receive or the supervisor.
* **Evidence.** 9.35 KiB/s with every frame and the unit's sensors (host demonstration); the proposal's 8 MB flash lasts 14.6 minutes, while a 40-minute attempt needs about 22 MB. In the host demonstration a forced flash stall dropped 396 records, all counted, and the supervisor kept its rate.
* **Choice.** STLG v1 with 4 KiB blocks, sequence numbers and CRC-32; bounded queues with counted drops. The medium is open: microSD for the raw log (recommended), or compression or decimation on the flash. That choice belongs to the telematics engineer.
* **Implementation.** `host/telematics/stlg.py`, `host/telematics/node.py`.
* **Test.** STLG reader tests; host demonstration checks `log_drops_counted_not_hidden` and `offline_import_complete_and_idempotent`; on the bench, E4 (100 power cuts during writing).

## D7. Energy-strategy selection

* **Requirement.** Minimise the energy the joulemeter measures over an attempt, within the time limit, with the driver in control.
* **Evidence.** On the host plant, which has no torque-independent loss while driving, pulse-and-coast used 11.4 to 23.8 % more energy per metre than speed hold; on the synthetic physics map with iron loss it saved about 13 % ([`ENERGY_METHODS.md`](ENERGY_METHODS.md) 1). The deciding property, whether battery power is non-convex in torque at cruise, is a measurement. Coast-down identification is sensitive: in the synthetic study a 0.1 % unmodelled grade biases C_rr by about +40 % in one direction, 1 m/s of unmodelled tailwind in one direction lowers the fitted C_dA by about 12 %, and at 0.05 m/s speed noise the two coefficients are not separately identifiable ([`generated/coastdown_sensitivity.md`](generated/coastdown_sensitivity.md)). Averaging both directions removes a constant grade and a steady wind to first order in that study; the cancellation there is ideal (same section, same speeds, steady conditions) and is not guaranteed on a real track.
* **Choice. Blocked:** no strategy is selected. Manual driving is the default; ECO assistance is offered only after measured loss maps (stage 7) and a fair comparison (stage 8). Speed hold is the baseline every other strategy is compared with.
* **Implementation.** `models/optimization/`, `tools/run_optimization.py`; policies `speed_hold_policy` and `pulse_and_coast_policy` in `host/telemetry_adapter/supervisor.py`.
* **Test.** `tests/simulation/test_models.py`; the matched comparison rules in README section D and [`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 5.

## D8. Current sensing and over-current protection

* **Requirement.** Phase current limited in hardware, independently of firmware; battery current limited; energy measured on the bus.
* **Evidence.** The draft uses three low-side phase shunts read by the gate driver's amplifiers into three ADCs (simultaneous sampling proposed, not substantiated), a bus shunt with the INA228, a software over-current check in every fast step, and the battery-current ceiling of arbiter layer L2. Hardware over-current shutdown relies on the gate driver's drain-source monitoring through nFAULT to TIM1_BKIN; there is no independent over-current comparator (OPEN item in [`../hardware/review/CONSISTENCY_CHECK.md`](../hardware/review/CONSISTENCY_CHECK.md)). A bench-supply current limit bounds only the battery-input current, not the phase current ([`VALIDATION_PLAN.md`](VALIDATION_PLAN.md) 2).
* **Choice. Open:** whether to add an over-current comparator on TIM1_BKIN2 (wired-OR with the over-voltage comparator). It is decided once the motor's peak current and the MOSFETs are known.
* **Implementation.** `mc_core_fast_step` (software over-current), `mc_arbiter.c` (L2 ceilings); sheets 03, 05, 06 of the schematic.
* **Test.** `firmware/tests/test_core.c`, `test_state_machine.c`; `tools/hw_consistency.py`; bring-up stage 4 (trip threshold and latency measured).

## D9. Fault-reset behaviour of `SELFTEST` and `HALL_INVALID`

* **Requirement.** A fault reset clears only faults whose cause is gone, and the controller re-checks what the self-test checks before torque is possible again.
* **Evidence (from the code, [`../firmware/README.md`](../firmware/README.md) 9).** `MC_F_SELFTEST` is never an active condition, so a fault reset clears it, and the self-test is not repeated before the next arming. The Hall invalid flag is cleared only by `mc_hall_init()`, so a `HALL_INVALID` fault cannot be cleared with the fault-reset input; it needs a re-initialisation.
* **Choice. Open:** the controls lead decides whether a reset after `SELFTEST` must return to `SELF_TEST`, and whether `HALL_INVALID` should become resettable once valid Hall codes return. No behaviour is changed until then.
* **Implementation.** `firmware/src/state_machine/mc_state_machine.c`, `firmware/src/control/mc_hall.c`.
* **Test.** To be added with the decision: a test that fails on the current behaviour if it is changed.

## D10. Live summary versioning (`sem.telemetry.v2`, `v3`)

* **Requirement.** Vehicle speed in the live summary when the motor is decoupled or GNSS has no fix (v2), and temperatures (v3), without breaking a pit that still receives an older version.
* **Evidence.** Rotor speed is not vehicle speed with a freewheel; GNSS speed is null without a fix. The controller's temperatures were only in the log as CAN frames, and the probes had no record at all.
* **Choice.** A new schema name for each added required block; the pit accepts v1, v2 and v3 and stores the schema per row. Wheel speed is null when older than 0.3 s or when the circumference or pulses per revolution are not configured; controller temperatures are null when the `ctrl_thermal` frame is older than 0.3 s or invalid; probe temperatures are null when the latest sample is older than 3 s (PROV) or invalid, and the live value is the logged value, so live and log agree exactly.
* **Implementation.** `host/telematics/node.py`, `host/pit/ingest.py`; [`ICD.md`](ICD.md) 10.
* **Test.** `tests/integration/test_mqtt_pipeline.py` (`test_v2_wheel_speed_validated_and_v1_still_accepted`, `test_v3_temperatures_validated_and_older_schemas_still_accepted`, migration of an old database); MQTT demonstration check `live_wheel_and_temperature_match_log_and_v1_still_accepted`.
