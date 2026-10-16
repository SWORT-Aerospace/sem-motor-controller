"""Pit ingestion service: MQTT subscriber -> validation -> SQLite (host software).

    python3 -m host.pit.mqtt_ingest --port 1883 --db build/pit.sqlite [--host 127.0.0.1]
                                    [--topic sem/car/telemetry] [--client-id sem-pit-ingest]

Subscribes with QoS 1 and a persistent session (clean session off, fixed
client id): while this service is down the broker keeps the subscription and
queues the messages for it, and delivers them when it reconnects. It
re-subscribes on every connection, so a broker that lost its session state
(restart without persistence) is handled too; messages published while
neither held a session are lost, and the car-side sequence numbers make that
loss visible.

Every message is validated before it is stored (host/pit/ingest.py). The
receipt, its outcome (stored / duplicate / rejected) and the MQTT DUP flag go
to the `rx` table; connection events go to `pit_events`. The database commit
happens before the client acknowledges the message, so a crash between the two
causes a redelivery (counted as a duplicate), never a loss.

SIGTERM or SIGINT: disconnect cleanly and exit 0.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import signal
import sqlite3
import sys
import time

import paho.mqtt.client as mqtt

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host.pit import ingest  # noqa: E402

EVENTS_DDL = "CREATE TABLE IF NOT EXISTS pit_events (t_unix REAL NOT NULL, kind TEXT NOT NULL, detail TEXT);"


class PitIngest:
    def __init__(self, db: sqlite3.Connection, host: str, port: int, topic: str, client_id: str):
        self.db, self.host, self.port, self.topic = db, host, port, topic
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(EVENTS_DDL)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False,
                                  protocol=mqtt.MQTTv311)
        self.client.reconnect_delay_set(1, 2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.counts = {"stored": 0, "duplicate": 0, "rejected": 0}

    def _event(self, kind: str, detail: str) -> None:
        self.db.execute("INSERT INTO pit_events VALUES (?,?,?)", (time.time(), kind, detail))
        self.db.commit()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._event("connect", f"{reason_code}; session_present={flags.session_present}")
        if not reason_code.is_failure:
            client.subscribe(self.topic, qos=1)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._event("disconnect", str(reason_code))

    def _on_message(self, client, userdata, msg):
        outcome, _why = ingest.ingest_payload(self.db, time.time(), msg.topic, msg.payload, dup_flag=bool(msg.dup))
        self.counts[outcome] += 1

    def run(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=5)
        self.client.loop_forever(retry_first_connection=True)

    def stop(self, *_args) -> None:
        self.client.disconnect()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--db", type=pathlib.Path, required=True)
    ap.add_argument("--topic", default="sem/car/telemetry")
    ap.add_argument("--client-id", default="sem-pit-ingest")
    a = ap.parse_args(argv)
    a.db.parent.mkdir(parents=True, exist_ok=True)
    svc = PitIngest(ingest.connect(a.db), a.host, a.port, a.topic, a.client_id)
    signal.signal(signal.SIGTERM, svc.stop)
    signal.signal(signal.SIGINT, svc.stop)
    svc._event("start", json.dumps({"host": a.host, "port": a.port, "topic": a.topic}))
    svc.run()
    svc._event("stop", json.dumps(svc.counts))
    print(json.dumps(svc.counts), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
