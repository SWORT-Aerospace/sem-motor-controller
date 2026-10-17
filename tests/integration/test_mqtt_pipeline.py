"""Telemetry pipeline through a real MQTT broker (host software, not vehicle firmware).

Broker tests need a Mosquitto binary (docs/MQTT_SETUP.md). Without one they
are skipped with that reason, unless SEMMC_REQUIRE_MQTT=1 (set in CI), which
makes a missing broker a failure. The tests without a broker always run.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from host.pit import ingest
from host.telematics.node import NodeConfig, TelematicsNode
from tools import mqtt_broker

TOPIC = "sem/car/telemetry"


@pytest.fixture(scope="module")
def mosquitto():
    binary = mqtt_broker.find_mosquitto()
    if binary is None:
        msg = "no mosquitto binary (set SEMMC_MOSQUITTO or install it: docs/MQTT_SETUP.md)"
        if os.environ.get("SEMMC_REQUIRE_MQTT") == "1":
            pytest.fail(msg + "; SEMMC_REQUIRE_MQTT=1", pytrace=False)
        pytest.skip(msg)
    return binary


def _msg(seq, run_id="T", **kw):
    m = {"schema": "sem.telemetry.v1", "run_id": run_id, "seq": seq, "t_local_ms": 500 * seq, "utc": None,
         "utc_q": "none", "ctrl": {}, "replayed": False, "counters": {"uplink_dropped": 0}}
    m.update(kw)
    return json.dumps(m, sort_keys=True).encode()


# ---- without a broker -------------------------------------------------------------------------
def test_validation_rejects_boolean_and_inconsistent_fields():
    assert ingest.validate_live(_msg(1))[1] is None
    assert "seq" in ingest.validate_live(_msg(True))[1]                      # JSON true is not an integer
    assert "t_local_ms" in ingest.validate_live(_msg(1, t_local_ms=-5))[1]
    assert "utc" in ingest.validate_live(_msg(1, utc=1.7e9, utc_q="none"))[1]
    assert "counters" in ingest.validate_live(_msg(1, counters={"uplink_dropped": -1}))[1]
    assert "run_id" in ingest.validate_live(_msg(1, run_id=""))[1]


def _v2(seq, speeds, **kw):
    m = json.loads(_msg(seq, **kw))
    m.update(schema="sem.telemetry.v2", wheel={"speed_mps": speeds})
    return json.dumps(m, sort_keys=True).encode()


def test_v2_wheel_speed_validated_and_v1_still_accepted():
    assert ingest.validate_live(_v2(1, {"wheel_l": 6.1, "wheel_r": None}))[1] is None
    assert ingest.validate_live(_msg(1))[1] is None                                  # v1: no wheel block
    assert "wheel" in ingest.validate_live(_v2(1, {"wheel_l": -0.5}))[1]
    assert "wheel" in ingest.validate_live(_v2(1, {"wheel_l": float("nan")}))[1]
    assert "wheel" in ingest.validate_live(_v2(1, {"wheel_l": True}))[1]
    m = json.loads(_v2(1, {}))
    del m["wheel"]
    assert "wheel" in ingest.validate_live(json.dumps(m).encode())[1]                 # v2 must carry the block
    assert "schema" in ingest.validate_live(_msg(1, schema="sem.telemetry.v3"))[1]


def test_old_database_gains_schema_column_and_keeps_rows(tmp_path):
    import sqlite3
    p = tmp_path / "old.sqlite"
    old = sqlite3.connect(p)
    old.execute("CREATE TABLE live (run_id TEXT NOT NULL, seq INTEGER NOT NULL, t_local_ms INTEGER NOT NULL, "
                "utc REAL, utc_q TEXT, payload TEXT NOT NULL, received_s REAL NOT NULL, replayed INTEGER NOT NULL, "
                "PRIMARY KEY (run_id, seq))")
    old.execute("INSERT INTO live VALUES ('R', 1, 500, NULL, 'none', '{}', 1.0, 0)")
    old.commit()
    old.close()
    db = ingest.connect(p)
    assert ingest.ingest_payload(db, 2.0, TOPIC, _v2(2, {"wheel_l": 5.0}))[0] == "stored"
    rows = db.execute("SELECT seq, schema FROM live ORDER BY seq").fetchall()
    assert rows == [(1, None), (2, "sem.telemetry.v2")]                               # old row kept, read as v1


def test_node_wheel_speed_formula_staleness_and_unknown_configuration():
    from host.telematics.clocks import LocalClock

    class _Sup:
        log = []

    class _W:
        dropped_storage = 0

        def add(self, *a):
            pass

    class _L:
        def up(self, t):
            return True

        def deliver(self, *a):
            return True

    cfg = NodeConfig(wheel_circumference_m=1.5, wheel_ppr=32)
    node = TelematicsNode(cfg, LocalClock(), _W(), _L(), _Sup(), "R")
    node.on_sensor(1.0, "wheel", (0, 13, 100))
    m = node._message(1.05)
    assert m["schema"] == "sem.telemetry.v2"
    assert m["wheel"]["speed_mps"]["wheel_l"] == 13 * 1.5 / (32 * 0.1)           # 6.09375 m/s
    assert m["wheel"]["speed_mps"]["wheel_r"] is None                              # never seen: null, not 0
    assert node._message(1.5)["wheel"]["speed_mps"]["wheel_l"] is None             # older than 0.3 s: null
    unknown = TelematicsNode(NodeConfig(), LocalClock(), _W(), _L(), _Sup(), "R")  # circumference/ppr unknown
    unknown.on_sensor(1.0, "wheel", (0, 13, 100))
    assert unknown._message(1.05)["wheel"]["speed_mps"]["wheel_l"] is None


def test_every_receipt_is_recorded_with_its_outcome(tmp_path):
    db = ingest.connect(tmp_path / "p.sqlite")
    assert ingest.ingest_payload(db, 1.0, TOPIC, _msg(3))[0] == "stored"
    assert ingest.ingest_payload(db, 2.0, TOPIC, _msg(3, replayed=True), dup_flag=True)[0] == "duplicate"
    assert ingest.ingest_payload(db, 3.0, TOPIC, b"{")[0] == "rejected"
    rows = db.execute("SELECT outcome, seq, dup_flag FROM rx ORDER BY rx").fetchall()
    assert rows == [("stored", 3, None), ("duplicate", 3, 1), ("rejected", None, None)]
    assert db.execute("SELECT COUNT(*) FROM live").fetchone()[0] == 1


class _RefusingLink:
    """A link that is 'up' but refuses hand-overs, like a client whose connection just dropped."""

    def __init__(self):
        self.refuse = True
        self.got = []

    def up(self, t):
        return True

    def deliver(self, t, topic, seq, payload):
        if self.refuse:
            return False
        self.got.append(json.loads(payload))
        return True


def test_refused_messages_stay_in_the_bounded_backlog_and_are_replayed_flagged():
    from host.telematics.clocks import LocalClock

    class _Sup:
        log = []

        def tick(self, t):
            return []

    class _W:
        dropped_storage = 0

        def add(self, *a):
            pass

    link = _RefusingLink()
    node = TelematicsNode(NodeConfig(uplink_queue_capacity=5), LocalClock(), _W(), link, _Sup(), "R")
    for k in range(8):                                   # 8 uplink periods refused: 3 oldest dropped, counted
        node._uplink(0.5 * k)
    assert len(node.uq) == 5 and node.c["uplink_dropped"] == 3 and [s for *_x, s in node.drop_log] == [0, 1, 2]
    link.refuse = False
    node._uplink(4.0)
    seqs = [m["seq"] for m in link.got]
    assert seqs == [3, 4, 5, 6, 7, 8]                    # backlog oldest first, then the new message
    assert [m["replayed"] for m in link.got] == [True] * 5 + [False]


# ---- with a broker ----------------------------------------------------------------------------
def _pit(port, db, cid="sem-pit-test"):
    return subprocess.Popen([sys.executable, "-m", "host.pit.mqtt_ingest", "--port", str(port), "--db", str(db),
                             "--client-id", cid], stdout=subprocess.PIPE, text=True)


def _wait_rows(db, n, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            c = sqlite3.connect(db, timeout=5)
            got = c.execute("SELECT COUNT(*) FROM live").fetchone()[0]
            c.close()
            if got >= n:
                return got
        except sqlite3.OperationalError:
            pass
        time.sleep(0.1)
    return got


def test_persistent_session_survives_broker_crash(mosquitto, tmp_path):
    from host.telematics.mqtt_link import MqttLink
    b = mqtt_broker.Mosquitto(tmp_path / "broker", binary=mosquitto)
    b.start()
    pit = _pit(b.port, tmp_path / "pit.sqlite")
    link = MqttLink("127.0.0.1", b.port, "car-test")
    try:
        link.start()
        assert link.wait_connected(10)
        time.sleep(1.0)
        for s in range(5):
            assert link.deliver(0, TOPIC, s, _msg(s))
        assert _wait_rows(tmp_path / "pit.sqlite", 5) == 5
        b.kill()                                          # abrupt: no orderly shutdown
        time.sleep(0.3)
        assert not link.up(0)
        for s in range(5, 8):                             # handed over while the connection is gone
            assert link.deliver(0, TOPIC, s, _msg(s))
        b.start()
        assert link.wait_connected(10)
        assert link.flush(10) == []
        assert _wait_rows(tmp_path / "pit.sqlite", 8) == 8
    finally:
        pit.terminate()
        pit.wait(10)
        link.stop()
        b.stop()
    db = sqlite3.connect(tmp_path / "pit.sqlite")
    assert [r[0] for r in db.execute("SELECT seq FROM live ORDER BY seq")] == list(range(8))
    ev = [d for k, d in db.execute("SELECT kind, detail FROM pit_events") if k == "connect"]
    assert any("session_present=True" in d for d in ev)


def test_broker_acknowledgement_is_not_end_to_end_delivery(mosquitto, tmp_path):
    """A broker that loses its state (here: restarted without persistence) acknowledges
    messages that no subscriber will receive. Only the car-side sequence numbers
    (and the local log) reveal the loss; this is why the pit reports gaps by seq."""
    from host.telematics.mqtt_link import MqttLink
    b = mqtt_broker.Mosquitto(tmp_path / "broker", binary=mosquitto)
    b.conf.write_text(b.conf.read_text().replace("persistence true", "persistence false"))
    b.start()
    dbp = tmp_path / "pit.sqlite"
    pit = _pit(b.port, dbp)
    link = MqttLink("127.0.0.1", b.port, "car-test")
    try:
        link.start()
        assert link.wait_connected(10)
        time.sleep(1.0)
        link.deliver(0, TOPIC, 0, _msg(0))
        assert _wait_rows(dbp, 1) == 1
        pit.terminate()
        pit.wait(10)                                      # pit offline; its session lives only in broker memory
        b.kill()
        b.start()                                         # session gone
        assert link.wait_connected(10)
        for s in (1, 2, 3):
            link.deliver(0, TOPIC, s, _msg(s))
        assert link.flush(10) == []                       # the broker acknowledged all three
        pit = _pit(b.port, dbp)
        time.sleep(2.0)                                   # pit resubscribes (new session)
        link.deliver(0, TOPIC, 4, _msg(4))
        assert link.flush(10) == []
        _wait_rows(dbp, 2)
    finally:
        pit.terminate()
        pit.wait(10)
        link.stop()
        b.stop()
    db = sqlite3.connect(dbp)
    stored = {r[0] for r in db.execute("SELECT seq FROM live")}
    acked = set(link.acked_seqs())
    assert stored == {0, 4} and acked == {0, 1, 2, 3, 4}
    assert sorted(acked - stored) == [1, 2, 3]            # acknowledged by the broker, never at the pit
    ev = [d for k, d in db.execute("SELECT kind, detail FROM pit_events") if k == "connect"]
    assert "session_present=False" in ev[-1]


@pytest.fixture(scope="module")
def demo(mosquitto, build_dir, tmp_path_factory):
    from tools import run_mqtt_demo
    return run_mqtt_demo.run(tmp_path_factory.mktemp("mqtt_demo"), build_dir, duration=60.0, pace=3.0)


def test_every_mqtt_demo_check_passes(demo):
    failed = [c for c in demo["checks"] if not c["pass"]]
    assert not failed, failed


def test_mqtt_demo_accounts_for_every_message(demo):
    n = demo["classes"]
    assert sum(n.values()) == demo["published"] > 0
    assert n["acknowledged by broker, not at pit"] == 0 and n["never acknowledged by broker"] == 0
    assert n["dropped on car (queue full)"] == demo["counters"]["uplink_dropped"]
