# Telematics end-to-end demonstration (HOST SIMULATION)

Unit `TLMSIM-0001`, 165 s of simulated driving, real Mosquitto broker on loopback, pit ingestion service as its own process, pace 4x, commit `c8eb971793bf` plus uncommitted changes. Command: `python3 tools/run_telematics_demo.py --out build/telematics_demo`. The external controller is a Python stand-in broadcasting the semmc simulation fixture; the node is the host model of the receive-only telematics unit, not its firmware; no supervisor takes part. Nothing here was measured on hardware.

| Check | Result | Evidence |
|---|---|---|
| `receive_only_no_command_frames` | PASS | 46143 frames on the bus, all from the external controller ({'external_controller': 46143}); the node class has no transmit or supervisor method (none found); frames with a supervisor or monitor identifier in the logs: 0 |
| `missing_or_invalid_data_is_null_never_zero` | PASS | live messages: DC voltage during controller silence {('stale', True): 5} with adapter silent 502-2502 ms; DC current while ctrl_currents was not sent {('stale', True): 20}; DC voltage with its validity flag cleared {('invalid', True): 6}; drive-wheel speed with the sensor disconnected {('no_evidence', True): 13}; GNSS speed without fix {('invalid', True): 9} (q, value null); entries with a value but not valid: 0 live, 0 in the pit's measurements table |
| `every_dropped_record_accounted_for` | PASS | boot 1: 54627 records in the log = written 54627; queue drops 451, storage drops 0; 156 records lost in the restart (queue and open block), after the last counters record, as the import reports ('unknown: the session ended without a final counters record (restart or power loss)'); boot 2: 21074 records in the log = written 21074; queue drops 0, storage drops 0; orderly close, final counters record matches the file. Uplink: boot 1: published 239 = 11 dropped on the car, 228 stored; boot 2: published 88 = 88 stored |
| `acquisition_continues_through_uplink_outage` | PASS | CAN and wheel records logged per second while the uplink was down 350-352, in the 10 s before 350-352; uplink backlog high water 30/30, 11 oldest messages dropped on the car and counted |
| `reingestion_creates_no_duplicates` | PASS | second import of each log: boot 1 0 records / 0 measurements added, boot 2 0 records / 0 measurements added; an exact copy of live message seq 0 re-published: duplicate |
| `speed_and_distance_from_edge_timing` | PASS | wheel_l speed: 2803 edge-period samples above 0.5 m/s, RMS error 0.0003 m/s against the simulated speed; distance boot 1 724.31 m (+0.000 m), boot 2 158.62 m (+0.061 m), pitch 0.1875 m; drive wheel: 220 no-evidence records while disconnected; parked at the end: {'valid': 1, 'no_evidence': 269} (0 m/s only with the line held active, otherwise no evidence) |
| `energy_from_valid_aligned_v_and_i_at_two_boundaries` | PASS | controller input 1.773 Wh, battery 2.095 Wh (difference 0.322 Wh: telematics, auxiliaries and harness); each within 0.384 % of the simulated energy over the same covered intervals; boot 1 controller-input missing intervals 5 (18.03 s): ctrl.dc_current unverified x2; ctrl.dc_voltage unverified x2 | ctrl.dc_current unverified x2; ctrl.dc_voltage unverified x2 | no valid ctrl.dc_current | ctrl.dc_voltage invalid x298 | ctrl.dc_current unverified x2; ctrl.dc_voltage unverified x1 |
| `telemetry_restart_is_a_new_session_and_a_reported_gap` | PASS | boot 2 log starts with BOOT (count 2, cause 'power loss (simulated: brown-out reset)'); 1.35 s without any record between the sessions; boot 1 ends without a final counters record (unknown: the session ended without a final counters record (restart or power loss)) |
| `live_messages_validated_before_storage` | PASS | 3 malformed messages published by another client, 3 rejected with reasons ['m.ctrl.dc_voltage: a value with q stale: a missing or invalid value must be null', 'not JSON (JSONDecodeError)', "v4 message with a 'sup' block: the receive-only node has none"]; receipts by outcome {'stored': 316, 'rejected': 3, 'duplicate': 1} |

## Energy

| Session | Boundary | Energy [Wh] | Covered [s] | Missing [s] | Missing-energy bound [Wh] | Error vs simulation |
|---|---|---|---|---|---|---|
| boot1 | controller_input | 1.5732 | 101.6 | 18.03 | 2.2449 | 0.143 % |
| boot1 | battery | 1.8515 | 118.5 | 1.10 | 0.1372 | 0.223 % |
| boot2 | controller_input | 0.2002 | 44.0 | 0.00 | 0.0000 | 0.384 % |
| boot2 | battery | 0.2438 | 44.0 | 0.00 | 0.0000 | 0.019 % |

Controller input energy is measured by the controller's own sensors at its DC terminals; battery energy by the battery-side monitor, which also sees the telematics unit and the other auxiliary loads. Missing intervals are not filled in; their bound is the largest observed power times their length.

Plots: `speed_distance.png`, `power.png`, `data_quality.png`.
