# Local MQTT broker for the telemetry pipeline (host)

The pit side of the telemetry chain runs on a computer with a Mosquitto broker. The tests and `tools/run_mqtt_demo.py` start and stop their own broker on a free loopback port. They only need to find the binary.

## 1. Get Mosquitto

| Option | Command | Status |
|---|---|---|
| Ubuntu 24.04 package (2.0.18) | `sudo apt-get install mosquitto` | used by CI (GitHub-hosted ubuntu-24.04) |
| Container (2.0.18) | `docker compose -f tools/mqtt/compose.yaml up` (broker on 127.0.0.1:1883) | not run yet (the tests and demonstrations use a local Mosquitto instead); image tag checked on Docker Hub |
| Binary elsewhere | `export SEMMC_MOSQUITTO=/path/to/mosquitto` | how the development environment ran it (Ubuntu's 2.0.18 package extracted locally) |

The tools find the broker from `$SEMMC_MOSQUITTO`, then `mosquitto` on `PATH`, then `/usr/sbin/mosquitto` (`tools/mqtt_broker.py`).

## 2. Run

```sh
pip install -r requirements.txt                    # paho-mqtt 2.1.0
cmake -S firmware -B build -G Ninja && cmake --build build
python3 tools/run_mqtt_demo.py --out build/mqtt_demo
python3 -m pytest tests/integration/test_mqtt_pipeline.py -rs
```

Without a broker, the demo exits with code 2 ("NOT AVAILABLE") and the broker tests are skipped with that reason. With `SEMMC_REQUIRE_MQTT=1`, as in CI, a missing broker fails the tests.

Against a long-running broker (for example the container), start the pit service by itself and point the car side at it:

```sh
python3 -m host.pit.mqtt_ingest --port 1883 --db build/pit.sqlite     # Ctrl-C to stop
```

## 3. What the demonstration shows

`tools/run_mqtt_demo.py` runs 120 s of controller time at twice wall-clock speed through the real broker. Twelve checks; the latest summary is in `generated/mqtt_demo/summary.md`:

| Check | What it shows |
|---|---|
| `broker_outage_detected_and_recovered` | the car-side client notices a killed broker and reconnects after the restart |
| `control_and_uplink_unaffected_by_broker_outage` | supervisor rate and ECO operation unchanged; the telematics step stays well under the 20 ms period |
| `local_log_complete_during_broker_outage` | the STLG log keeps every record; nothing dropped |
| `uplink_backlog_bounded_and_drops_counted` | the backlog stays at or under 30; drops counted by sequence number and absent at the pit |
| `every_sequence_number_accounted` | each message is stored, dropped on the car (counted), unacknowledged, or acknowledged but missing at the pit |
| `replayed_messages_flagged` | backlog messages arrive with `replayed = true` |
| `invalid_messages_rejected_before_storage` | four malformed messages rejected with reasons; none stored |
| `duplicates_ignored_and_ingest_idempotent` | a duplicate and re-ingestion add no rows |
| `pit_restart_without_loss` | messages published while the pit was down are delivered after it reconnects |
| `live_wheel_speed_v2_matches_log_and_v1_still_accepted` | the live wheel speed (`sem.telemetry.v2`) equals the speed from the logged wheel window; a v1 message is still stored |
| `timestamps_and_missing_data_explicit` | car time, UTC quality, null GNSS fields in an outage, pit receive time |
| `pit_shadow_replay_reports_missing_ground_truth` | R3v and CSIA2 replay over the imported log in shadow mode; with no injected faults the report lists attributions without scoring them |

Delays and service times vary between runs; the checks test invariants, not those numbers.

## 4. Limits

* The car side is the host model of the telematics unit, not its firmware. There is no LTE modem, SIM or radio link: the outage is a killed broker on loopback.
* Loopback without authentication or TLS. A pit broker reachable over a network needs authentication and TLS; the A7672's MQTT client supports TLS up to 1.2 (`TELEMETRY_CANDIDATES.md`).
* Where the broker runs at the event is not decided. The modem connects out from the operator's network, so the broker needs an address reachable from there: a hosted server, or a tunnel to the pit computer. A pit laptop on venue Wi-Fi normally sits behind address translation and cannot accept that connection directly. This is the "Internet-reachable MQTT broker" line in `PROCUREMENT.md`.
* A broker acknowledgement is not delivery to the pit. A broker that loses its state can acknowledge messages that never reach the pit; the pit reports gaps by sequence number, and the local log is the complete record.
