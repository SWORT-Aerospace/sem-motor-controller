# Telemetry integration plan (v0.5)

How each measurement gets from its sensor to the pit, tied to the code that implements it on the host today. **Implemented** means host software exercised by tests; the vehicle firmware is not written (`TELEMETRY_EMBEDDED_PORT.md`). Values marked **PROV** are provisional, chosen for simulation; **UNKNOWN** values wait for the inputs in `INPUT_SHEET.md`. No motor, battery, BMS or vehicle-bus fact is assumed here.

## 1. Principles

1. **Control and protection stay local to the motor controller.** Current limits, thermal derating, under- and over-voltage trips, the brake override and manual driving use only the controller's own sensors and wired inputs. Nothing in this chain is needed to drive: not CAN, the telematics unit, LTE, MQTT, the broker, the database or CSIA. Shown on the host: `run_host_demo.py` checks `brake_keeps_authority` and `control_unaffected_by_logging_and_lte`; `run_mqtt_demo.py` checks `control_and_uplink_unaffected_by_broker_outage`.
2. **The local log is the record; the uplink is a summary.** Every CAN frame and sensor sample goes to the STLG log on the vehicle. The 2 Hz MQTT message is best effort and may be lost; it is never the only copy.
3. **Nothing is silently lost or repaired.** Every queue is bounded and counts its drops. Invalid values travel as invalid (CAN sentinels, JSON null, NaN in the database), not as zero. The pit validates before it stores and records every receipt with its outcome.
4. **Every time carries its clock domain:** controller microseconds, telematics microseconds (receive timestamps), and UTC derived from GNSS PPS edges with a quality flag (`ICD.md` 4).
5. **Power:** the telematics unit, its sensors and the modem run from the propulsion battery downstream of the joulemeter. Their energy counts in the official result (2026 Articles 56d, 57b; `RULES_COMPLIANCE.md`). An emergency stop removes their power at once (Article 37e).

## 2. Signals

Rates are the CAN periods of protocol 1.1 (`protocol/protocol.yaml`, `generated/can_messages.md`) unless stated. "Rx stamp" is the telematics receive time in its own microsecond clock; the CAN frames carry no source time except the supervisor's `src_time_ms`.

| Signal | Physical source | Receiving node | Units, scaling, invalid value | Acquisition / transmission | Timestamp | Validity and timeout | Use | Status |
|---|---|---|---|---|---|---|---|---|
| Battery-side voltage `vbus_V` | controller DC-link divider + ADC | controller; telematics via CAN | V, 0.01 V/bit, invalid 65535 | control-rate sampling; `ctrl_motion` 10 ms | rx stamp | `ctrl_validity.v_vbus` (missing, stale, invalid, flagged), 100 ms | protection (controller UV/OV), energy, logging | implemented (host) |
| Battery current `ibatt_A` | controller bus shunt + monitor | controller; telematics via CAN | A, 0.01 A/bit, discharge positive, invalid -32768 | `ctrl_currents` 10 ms | rx stamp | `v_ibatt`, 100 ms | protection (battery current limit), energy | implemented (host) |
| Battery power and energy `p_batt_W`, `energy_J` | controller: v x i integrated each control step | telematics via CAN | W (1 W/bit), J (0.1 J/bit) | `ctrl_energy` 100 ms | rx stamp | `ctrl_energy_quality`: `integrated_s`, `gap_s` (time integrated vs skipped), 100 ms | energy accounting at the controller input | implemented (host) |
| Rotor speed `speed_mech_rad_s` | motor halls / observer in the controller | controller; telematics; supervisor | rad/s, 0.05/bit, invalid -32768 | `ctrl_motion` 10 ms | rx stamp | `v_speed`; the supervisor drops speed older than 50 ms (PROV, `telemetry_max_age_s`) or repeated | control (controller), supervisor input, analysis | implemented (host) |
| Phase currents `iq_A`, `id_A` | controller shunts | telematics via CAN | A, 0.01/bit | `ctrl_motion`, `ctrl_currents` 10 ms | rx stamp | `v_ia..v_ic`, reconstruction masks | loss analysis, CSIA | implemented (host) |
| Controller state, derating, trips | controller state machine | telematics via CAN | enums, flags | `ctrl_status` 20 ms; `ctrl_fault` 1 s + on change | rx stamp | session tag, boot id | logging, analysis; supervisor gating | implemented (host) |
| Torque requested / accepted, reason | controller arbiter | telematics via CAN | N*m, 0.002/bit | `ctrl_cmd_trace` 20 ms | rx stamp | invalid -32768 | analysis (which layer limited torque) | implemented (host) |
| Brake, throttle, cancel, dead-man, e-stop chain | wired driver controls at the controller | controller (acts at once); telematics via CAN | flags; throttle 0-1 (1e-4/bit) | `driver_controls` 20 ms | rx stamp | `throttle_valid`, `v_throttle` | **control and protection at the controller**; logging | implemented (host); electrics UNKNOWN |
| Power-stage and motor temperature | controller NTC at the low-side MOSFETs (TH701), motor sensor (J701) | controller; telematics via CAN | °C, 0.1/bit | `ctrl_thermal` 100 ms | rx stamp | `v_t_fet`, `v_t_motor`; unknown temperature derates | **protection at the controller**, logging | implemented (host); sensor type UNKNOWN |
| Slow temperatures (battery surface, motor case, ambient) | DS18B20-class probes on 1-Wire (candidate) | telematics | °C | 1 Hz or slower (12-bit conversion up to 750 ms) | sample time, telematics clock | CRC on 1-Wire, conversion timeout 1 s, range | logging, loss-model temperature | **deliberately excluded** from the first milestones: no STLG record type (ICD 8); the controller's FET and motor temperatures are logged |
| Wheel speed | continuous Hall switch per instrumented wheel (DRV5032 rejected, `TELEMETRY_CANDIDATES.md`) | telematics timer input capture | counts per window; m/s = counts x C / (ppr x window) at the pit | 100 ms windows (PROV); STLG `WHEEL` record | window end, telematics clock | a dropout reads as 0 counts, indistinguishable from standstill: cross-checked against rotor speed | distance, speed, energy per metre | implemented (host model, ppr 32 PROV); geometry UNKNOWN |
| GNSS fix, speed, accuracy | NEO-M9N-class receiver on UART (candidate) | telematics | m/s, sAcc m/s, satellites, fix | 10 Hz (PROV; the module allows 25 Hz); STLG `GNSS` record | rx stamp | no fix -> null speed; `sacc` and satellite count kept | lap and position analysis, distance cross-check | implemented (host model) |
| PPS edges | GNSS time pulse | telematics timer capture | edge time, UTC second | 1 Hz; STLG `PPS` record | capture, 1 µs (PROV) | missing edges -> holdover (bound 50 ppm x age), none before two edges | UTC alignment of all records | implemented (host model) |
| Longitudinal acceleration, yaw rate | 6-axis IMU on SPI (candidate) | telematics | m/s², rad/s | 100 Hz (PROV); STLG `IMU` record | data-ready capture (proposed) | self-test at boot (proposed); offset calibration at rest | events, grade (calibrated), lap segmentation | implemented (host model) |
| Steering angle (optional) | AS5600 on I2C (candidate) | telematics | rad | up to 100 Hz (PROV) | sample time | magnet-status bits | analysis | **proposed** |
| BMS cell voltages, SOC, temperatures | the BMS, if it has a data interface | telematics | per the BMS | UNKNOWN | rx stamp | UNKNOWN | analysis only | **UNKNOWN** (no BMS documentation) |
| Supervisor requests and limits | telematics supervisor task | controller | N*m, W | `sup_torque_req` 20 ms (PROV), `sup_limits` 100 ms | `src_time_ms` + rx at the controller | session tag, freshness and ordering rules, 100 ms timeout (PROV): ECO exits to zero torque | ECO assistance only (driver-selected, cancellable) | implemented (host) |
| Telematics counters | node | log and uplink | counts | STLG `COUNTERS` 1 s; every uplink message | telematics clock | n/a | data-quality accounting | implemented (host) |
| Live summary | node | pit over LTE/MQTT | JSON `sem.telemetry.v2` (v1 still accepted), unknown = null; v2 adds wheel speed per channel | 2 Hz (proposal: 1-5 Hz) | `t_local_ms` + `utc`, `utc_q`, `utc_err_s`; pit receive time | pit validation; backlog 30 messages; `replayed` flag; wheel speed null when older than 0.3 s or unconfigured | monitoring only | implemented (host, real broker) |

Wheel speed was added to the summary in v0.5 (`sem.telemetry.v2`): rotor speed is not vehicle speed when the motor is decoupled, and GNSS may have no fix. Still only in the log: IMU and the controller's temperatures (as CAN frames). Telematics temperature probes are excluded for now (no record type); see the row above.

## 3. What energy accounting needs

| Priority | Measurement | Why |
|---|---|---|
| Essential | battery-side voltage and current at the controller with `ctrl_energy_quality` | energy into propulsion, with integrated and gap time stated |
| Essential | a timestamped distance: at least one wheel channel, rotor speed as a cross-check | energy per metre and per lap; matched comparisons need the same distance |
| Essential | brake state, controller state and torque trace | separates driver braking and limiting from strategy |
| Essential | telematics receive timestamps and PPS-derived UTC with quality | aligning controller, telematics and GNSS data |
| Essential | the telematics unit's own consumption (bench measurement or its own current monitor) | it is inside the joulemeter's boundary but outside the controller's (Article 56c i) |
| Recommended | GNSS speed and position | lap positions, a second distance |
| Recommended | slow temperatures (battery, motor case, ambient) | temperature correction of loss models |
| Optional | IMU (calibrated) | grade and events; not accurate enough alone for rolling resistance |
| Optional | steering angle, BMS data, CSIA advisory | analysis |

The controller's input meter differs from the official joulemeter: the joulemeter also sees the telematics unit, display and sensors downstream of it, and does not see the BMS inside the battery package (Article 57d i 3). The comparison is part of the validation plan (`VALIDATION_PLAN.md` 5).

## 4. Uplink milestone implemented in v0.5 (host)

The host telemetry chain now runs through a real MQTT broker (`MQTT_SETUP.md`):

* car side: `host/telematics/mqtt_link.py`, a paho-mqtt client at QoS 1 behind the node's bounded backlog (`host/telematics/node.py`); it hands over only while connected, and the client holds at most 10 unacknowledged messages;
* broker: Mosquitto 2.0.18 on loopback with persistence (`tools/mqtt_broker.py`);
* pit: `host/pit/mqtt_ingest.py`, a separate process with a persistent session; it validates (`host/pit/ingest.py validate_live`), stores idempotently on (run_id, seq) and records every receipt in `rx` with its outcome and the MQTT DUP flag;
* demonstration: `tools/run_mqtt_demo.py`. A broker crash and restart, a pit crash and restart, malformed and duplicate messages, and a GNSS outage. Twelve checks, including local-log completeness through the outage, bounded backlog with counted drops, and accounting for every sequence number (`generated/mqtt_demo/summary.md`); tests in `tests/integration/test_mqtt_pipeline.py`.

Found while building it: **a broker acknowledgement is not delivery to the pit.** A broker that loses its state acknowledges messages that no subscriber receives (test `test_broker_acknowledgement_is_not_end_to_end_delivery`). The pit therefore reports gaps by sequence number, and the local log remains the complete record.

## 5. Pit replay in shadow mode: R3v and CSIA2

After a run, the pit imports the vehicle's log and replays the sensor-consistency monitors over it. The replay is advisory: it reads the pit database and writes files. It has no CAN, MQTT or controller interface, so it cannot command torque or change protection (`tests/integration/test_shadow_replay.py::test_shadow_replay_has_no_command_path`).

**Commands.**

```sh
python3 tools/run_host_demo.py --out build/host_demo          # or: import a vehicle log with host/pit/ingest.py import_log
python3 tools/run_pit_replay.py --db build/host_demo/pit.sqlite --run HOSTSIM-0001 --out build/pit_replay
```

Exit 0 when a report was written (whatever it found), 2 when the run is not in the database. The vehicle parameters come from the configuration the run's metadata names, checked against its SHA-256; a changed configuration is reported in the evidence list.

**Monitors.** B1 (range, NaN and freshness checks), R3v (calibrated residuals with majority-vote attribution: the selected monitor) and CSIA2 (the frozen v2 adapter: experimental), each behind the shared 3-tick persistence filter. Classes, threshold and power-balance model are the frozen ones (`csia/V2_FREEZE.json`); only wheel radius, gear ratio, torque constant and freewheel state come from the run. Nothing is re-tuned.

**Signals the replay uses** (10 Hz ticks; a signal fresh in fewer than half of them is reported as insufficient):

| Signal | Source in the log | Relationships that use it |
|---|---|---|
| `rotor` | `ctrl_motion.speed_mech_rad_s` | E1 (rotor against driven wheel), E6 (power balance) |
| `iq` | `ctrl_motion.iq_A` | E6, P (phase-current consistency) |
| `iq_ref` | `ctrl_cmd_trace.accepted_Nm` / K_t | P |
| `kcl` | `ctrl_currents.kcl_residual_A` | P |
| `p_dc` | `ctrl_energy.p_batt_W` | E6 |
| `wheel_l`, `wheel_r`, `wheel_drive` | STLG `WHEEL` records (counts per window) | E1, E2 (left against right with yaw rate), E3a, E3b, E4, E7 |
| `gnss` | STLG `GNSS` speed, null without a fix | E3a, E3b, E7 |
| `imu_ax`, `imu_gz` | STLG `IMU` records | E2, E3a, E3b, E4 |
| `grade` | none: assumed flat (0 rad, σ 0.003) | E4 |

**Outputs** in `--out`: `report.md` and `report.json` (data class, signal coverage, active ticks per relationship, attribution episodes per monitor, scoring when the metadata records injected faults, insufficient-evidence notes), `timeline.csv` (per tick and monitor), and `energy.json` (controller-input energy, distance and Wh/km per wheel channel, with the cross-check between wheels; `host/pit/energy.py`).

**Synthetic against measured data.** The data class comes from the run metadata: `HOST SIMULATION` runs and runs with synthetic calibration are reported as synthetic. For a measured run the report states that the parameters and the power-balance model are the frozen synthetic ones and must be identified on that vehicle before any result is used. Without injected faults in the metadata (any real run), detections are listed, not scored: there is no ground truth. CSIA2 did not meet its pre-registered superiority criterion against R3v (`csia/EVALUATION_RESULTS_v2.md`); its output is for comparison only.

**Shown on the host.** The host demonstration injects a dropout on `wheel_l`: R3v and CSIA2 attribute it 0.3 s after onset with no wrong attribution (check `pit_shadow_replay_r3v_and_csia2_reported`), and `energy.json` flags `wheel_l` as 8.8 % short of the other wheels. The MQTT demonstration has no injected fault and reports that its detections cannot be scored. Both are synthetic.

## 6. Next steps

1. Inputs that unblock parts: wheel and magnet geometry and maximum speed; the telematics board files; the event country and operator; the display decision (`PROCUREMENT.md`).
2. STLG record types for slow temperatures and steering angle when those sensors are fitted.
3. The embedded port and its bench acceptance checks (`TELEMETRY_EMBEDDED_PORT.md`).
