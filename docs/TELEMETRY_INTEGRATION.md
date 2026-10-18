# Telemetry integration (v0.7)

How each measurement gets from its source to the pit report, and what the analysis can do with what the controller team sends. The interfaces themselves are in [`ICD.md`](ICD.md) Part A; this page is the integration view. **Implemented** means host software exercised by tests or firmware compiled for the target; nothing has run on hardware ([`TELEMETRY_EMBEDDED_PORT.md`](TELEMETRY_EMBEDDED_PORT.md)). No fact about the vehicle's controller, battery or bus is assumed: what the controller sends is UNKNOWN until its team answers [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md).

## 1. Principles

1. **The unit only listens.** It sends nothing to the controller: no torque request, no arming, no fault reset, no configuration change, and it takes no part in protection or precharge ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)). The vehicle drives the same with the unit absent, off or failed. Shown on the host: the demonstration check `receive_only_no_command_frames`; on the target the CAN controller is in bus-monitoring mode. Electrical noninterference is a separate matter, checked on the bench (`telematics/firmware/BENCH.md` section 7).
2. **The local log is the record; the uplink is a summary.** Every received frame and sensor sample goes to the STLG log on the vehicle. The 2 Hz live message is best effort; it is never the only copy.
3. **Nothing is silently lost, invented or repaired.** Every queue is bounded and counts its drops. A missing, stale or invalid value travels as null with its validity, never as zero. A sample time or sequence number is recorded only when the source provides one; local record identifiers are separate from them. A wheel line held at one level never proves standstill (a stopped wheel and a stuck or disconnected sensor read the same); a silent channel is "no evidence", and one that stays silent while another wheel turns is suspect and invalid ([`ENERGY_METHODS.md`](ENERGY_METHODS.md) 0.2).
4. **Every time names its clock:** the telematics clock (receive and capture times), the source's own time when it has one, and UTC from GNSS PPS edges with a quality flag ([`ICD.md`](ICD.md) A.4).
5. **Power:** the unit runs from the propulsion battery downstream of the joulemeter, so its energy counts in the official result (2026 Articles 56d, 57b; [`RULES_COMPLIANCE.md`](RULES_COMPLIANCE.md)). The emergency stop removes its power.
6. **Analysis is offline or advice.** No result feeds back to the vehicle; there is no automatic speed control. CSIA and R3v run in shadow mode at the pit.

## 2. Signals by role

The signal registry ([`../host/telematics/signals.py`](../host/telematics/signals.py)) defines each signal once: unit, origin, role, plausible range and staleness limit. Controller signals may all be absent; staleness limits for them are provisional until the controller team states its broadcast periods.

| Role | Signals | Source | Status |
|---|---|---|---|
| Essential energy (controller input) | `ctrl.dc_voltage` (V), `ctrl.dc_current` (A, positive on discharge) | the external controller's broadcast, through an adapter | adapters implemented (semmc fixture; DBC with a unit-checked mapping); the controller's actual frames UNKNOWN |
| Total energy (battery) | `batt.voltage`, `batt.current` | a battery-side monitor on the telematics unit (optional hardware) | host model and STLG `BATT`; part not chosen |
| Optional diagnostics | `ctrl.dc_power`, `ctrl.energy_counter`, `ctrl.energy_integrated_time`, `ctrl.energy_gap_time`, `ctrl.motor_speed`, `ctrl.phase_current_q`, `ctrl.phase_current_d`, `ctrl.kcl_residual`, `ctrl.torque_reference`, `ctrl.fet_temp`, `ctrl.motor_temp`, `ctrl.state`, `ctrl.fault_code` | the external controller, if it broadcasts them | nothing depends on them; the shadow relationships that need them are disabled without them |
| Motion | `wheel.<channel>.speed`, `wheel.<channel>.distance` (edge timing), `gnss.speed`, `gnss.speed_acc`, `gnss.num_sv`, `imu.ax`, `imu.gz` | the unit's own sensors | wheel capture and IMU on the target (not run); GNSS on the host model only |
| Environment | `temp.<probe>` | the unit's own probes | TMP117 on the target (not run); probe part and placements open |

The unit's own health (queue high water, drops, stalls, restarts, lost edges, uplink backlog) is not a measurement; it is in the counters (STLG `COUNTERS2`, the live message's `counters`) and the `BOOT` record.

## 3. What energy accounting needs

| Priority | Measurement | Why |
|---|---|---|
| Essential | DC voltage and current at the controller input, at 10 Hz or faster, aligned in time (same frame, a sample time, or receive times with their uncertainty) | energy into the drive; the request sheet section 3.1 |
| Essential | a distance: at least one wheel channel by edge timing | energy per metre and per lap; matched comparisons need the same distance |
| Essential | the unit's own consumption (bench measurement, or the battery-side monitor) | it is inside the joulemeter's boundary but outside the controller's |
| Recommended | battery-side voltage and current | total battery energy, the boundary closest to the joulemeter |
| Recommended | GNSS speed and position, PPS | lap positions, a second distance, UTC |
| Optional | IMU, temperatures, the controller's diagnostic signals | grade and events, temperature corrections, the shadow monitors |

The method (pairing within 20 ms, gaps beyond three median spacings reported as missing intervals with their causes, the bound on the missing energy, the two boundaries) is in [`ENERGY_METHODS.md`](ENERGY_METHODS.md) section 0. The controller's own energy counter, when it sends one, is a cross-check, not the figure.

## 4. Shadow-mode monitors

The pit replay ([`../host/pit/shadow_replay.py`](../host/pit/shadow_replay.py), `tools/run_pit_replay.py`) runs B1, R3v (selected) and CSIA2 (experimental) over an imported log. It reads the pit database and writes files; it has no path to the vehicle. Each relationship lists its inputs ([`ENERGY_METHODS.md`](ENERGY_METHODS.md) 0.3); one whose input is absent, or below half coverage, is disabled and reported, and on a vehicle run the road grade is not assumed (E4 disabled). For a measured run, simulator fields in the run's metadata (ground truth, plant, injected faults) are ignored and named in the report; detections are listed, not scored. The frozen evaluation and its result favouring R3v are unchanged ([`csia/EVALUATION_RESULTS_v2.md`](csia/EVALUATION_RESULTS_v2.md)).

## 5. Uplink findings kept from v0.5

The live path runs through a real MQTT broker (Mosquitto 2.0.18) with a persistent pit session ([`MQTT_SETUP.md`](MQTT_SETUP.md)). **A broker acknowledgement is not delivery to the pit:** a broker that loses its state acknowledges messages that no subscriber receives (`tests/integration/test_mqtt_pipeline.py::test_broker_acknowledgement_is_not_end_to_end_delivery`). The pit therefore reports gaps by sequence number, and the local log remains the complete record. The v0.7 demonstration repeats this with the receive-only node: every sequence number is stored, counted as dropped on the car, or reported as a gap ([`generated/telematics_demo/summary.md`](generated/telematics_demo/summary.md)).

## 6. Next steps

In the order of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md): the controller team's answer and a DBC mapping (T1); the first bench run of the firmware (T2); the CAN receive image against a bus and the electrical checks (T3); the modem (T4); vehicle data (T5).
