"""Uplink over a real MQTT broker (host software; paho-mqtt client).

Drop-in for `node.SimLink`: the telematics node asks `up(t)` before it hands
messages over and calls `deliver(t, topic, seq, payload)`, which returns False
when the client refuses the message. The node then keeps the message in its
own bounded uplink queue, where overflow is counted (`uplink_dropped`).

Delivery is MQTT QoS 1, at least once. A message the broker has not
acknowledged when the connection drops stays in the client and is sent again,
with the DUP flag, after the client reconnects; a message handed over while the
connection is already gone (not yet noticed) is also held and sent after
reconnection. The client holds at most `inflight_limit` such messages, so the
car-side memory stays bounded: client buffer + node queue. The pit may receive
a message twice; its (run_id, seq) key makes that harmless.

This is the host model of the uplink only. The vehicle unit's modem firmware
(AT-command MQTT client over LTE) is not implemented (docs/TELEMETRY_EMBEDDED_PORT.md).
"""
from __future__ import annotations

import threading
import time

import paho.mqtt.client as mqtt


class MqttLink:
    def __init__(self, host: str, port: int, client_id: str, keepalive_s: int = 5, inflight_limit: int = 10,
                 reconnect_delay_s: tuple[int, int] = (1, 2)):
        self.host, self.port, self.keepalive_s = host, port, keepalive_s
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True,
                                  protocol=mqtt.MQTTv311)
        self.client.max_inflight_messages_set(inflight_limit)
        self.client.max_queued_messages_set(inflight_limit)
        self.client.reconnect_delay_set(*reconnect_delay_s)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish
        self._connected = threading.Event()
        self.events: list[tuple[float, str, str]] = []      # (monotonic s, "connect" | "disconnect", detail)
        self._mid_seq: dict[int, int] = {}                   # written by the caller's thread only
        self._acked_mid: dict[int, float] = {}               # written by the network thread only
        self.handed: dict[int, float] = {}                   # seq -> monotonic time handed to the client
        self.refused = 0

    # ---- network-thread callbacks ------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.events.append((time.monotonic(), "connect", str(reason_code)))
        if not reason_code.is_failure:
            self._connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected.clear()
        self.events.append((time.monotonic(), "disconnect", str(reason_code)))

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        self._acked_mid[mid] = time.monotonic()

    # ---- caller side ---------------------------------------------------------------------------
    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=self.keepalive_s)
        self.client.loop_start()                              # background thread; reconnects on its own

    def wait_connected(self, timeout_s: float) -> bool:
        return self._connected.wait(timeout_s)

    def up(self, t_true: float) -> bool:
        return self._connected.is_set()

    def deliver(self, t_true: float, topic: str, seq: int, payload: bytes) -> bool:
        info = self.client.publish(topic, payload, qos=1)
        if info.rc == mqtt.MQTT_ERR_QUEUE_SIZE:               # client buffer full: the node keeps the message
            self.refused += 1
            return False
        # MQTT_ERR_SUCCESS, or MQTT_ERR_NO_CONN: the client holds the message and sends it after reconnecting
        self._mid_seq[info.mid] = seq
        self.handed[seq] = time.monotonic()
        return True

    def acked_seqs(self) -> dict[int, float]:
        """seq -> seconds from hand-over to the broker's PUBACK, for every acknowledged message."""
        out = {}
        for mid, t_ack in list(self._acked_mid.items()):
            seq = self._mid_seq.get(mid)
            if seq is not None:
                out[seq] = t_ack - self.handed[seq]
        return out

    def unacked_seqs(self) -> list[int]:
        acked = self.acked_seqs()
        return sorted(s for s in self.handed if s not in acked)

    def flush(self, timeout_s: float) -> list[int]:
        """Wait until every handed-over message is acknowledged or the timeout passes;
        returns the sequence numbers still unacknowledged."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and self.unacked_seqs():
            time.sleep(0.05)
        return self.unacked_seqs()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
