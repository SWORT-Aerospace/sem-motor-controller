# Telemetry pipeline through a real MQTT broker (HOST SOFTWARE)

Run `HOSTMQTT-0001`, 120 s of controller time at 2x wall-clock speed, commit `e1b59a60614f` plus uncommitted changes. Broker: mosquitto version 2.0.18 on loopback; client: paho-mqtt 2.1.0. Command: `python3 tools/run_mqtt_demo.py --out build/mqtt_demo`. Synthetic plant and sensors; the car side is the host model of the telematics unit, not its firmware, and no LTE modem is involved. Nothing here was measured on hardware.

| Check | Result | Evidence |
|---|---|---|
| `broker_outage_detected_and_recovered` | PASS | broker killed at 40.0 s, client saw the disconnect 1 ms later (wall); broker restarted at 60.0 s, client reconnected 0.95 s later (wall), i.e. 1.9 s of controller time |
| `control_and_uplink_unaffected_by_broker_outage` | PASS | supervisor requests/s while the broker was unreachable [50]; ECO_ASSIST in 2191/2191 steps; telematics service step (log writer + uplink) wall time p99/max: normal 0.31/1.75 ms, broker_down 0.07/0.12 ms, after_broker 0.30/1.41 ms, pit_down 0.30/0.49 ms, after_pit 0.31/1.26 ms (supervisor period 20 ms) |
| `local_log_complete_during_broker_outage` | PASS | records written 71525 = imported 71525 (286 blocks ok, 0 corrupt, 0 sequence gaps); log queue and storage drops 0/0; CAN records per second while the broker was down 454-464, before it 444-464 |
| `uplink_backlog_bounded_and_drops_counted` | PASS | backlog high water 30/30; dropped on the car 14 (counter) = 14 (sequence numbers 79..92); none of them reached the pit |
| `every_sequence_number_accounted` | PASS | published 240: stored at pit 226, dropped on car (queue full) 14, never acknowledged by broker 0, acknowledged by broker, not at pit 0, never handed to the link 0 |
| `replayed_messages_flagged` | PASS | 33 messages stored with replayed=true, equal to the backlog messages sent after reconnection |
| `invalid_messages_rejected_before_storage` | PASS | 4 malformed messages published, 4 rejected with reasons ['ctrl.vbus_V=9999.0 outside [0.0, 100.0]', 'field seq missing or not an integer', 'not JSON (JSONDecodeError)', 'wrong or missing schema']; none stored |
| `duplicates_ignored_and_ingest_idempotent` | PASS | 1 duplicate receipts (the injected copy of seq 0; MQTT DUP flag set on 0); re-ingesting all 226 stored payloads added 0 rows |
| `pit_restart_without_loss` | PASS | 20 car messages published while the pit service was down (75-85 s): all stored after it reconnected (session resumed 2 time(s)) |
| `live_wheel_speed_v2_matches_log_and_v1_still_accepted` | PASS | 678 live wheel speeds (schema sem.telemetry.v2) compared with the speed derived from the latest logged wheel window: 0 differ; 0 null (no fresh window); a valid sem.telemetry.v1 message from another producer was stored as v1: True |
| `timestamps_and_missing_data_explicit` | PASS | car time t_local_ms increases with seq: True; UTC quality {'none': 3, 'pps': 206, 'holdover': 17}; 15 messages in the GNSS outage carry utc_q=holdover, gnss speed null, fix false; pit receive time recorded for all; generation-to-storage delay (wall clock) live median 2 ms, max 5.09 s; replayed max 7.5 s |
| `pit_shadow_replay_reports_missing_ground_truth` | PASS | R3v and CSIA2 replayed in shadow mode over 1200 ticks of the imported log; no faults were injected, so the report lists attributions without scoring them (R3v 0, CSIA2 0 episodes); report pit_replay/report.md |

Wall-clock figures (delays, service times) vary from run to run; the checks test invariants, not those numbers.
