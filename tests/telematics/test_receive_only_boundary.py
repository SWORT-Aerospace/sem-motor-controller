"""The receive-only boundary to the motor controller (docs/CURRENT_STATE.md, ADR-0013).

The telematics unit may receive, log, validate, cross-check, display and transmit telemetry to the pit; it may
never command propulsion. These tests prove that the production code has no path that could put a frame on the
controller's bus:

* production = every Python file the scope file classifies as `telematics`, outside tests: none of them, nor
  anything they import from this repository, reaches the out-of-scope modules that hold controller authority
  (the legacy supervisor, the SocketCAN bridge's former transmit path, the controller firmware), opens a CAN
  socket, or calls the semmc encoder;
* the node, the adapters and the assurance code expose no method that sends a frame or names a propulsion
  quantity as something to set;
* the adapters turn frames into measurements only, also for random, malformed and companion frames;
* the firmware's CAN driver has no transmit function and runs in bus-monitoring mode (the register-level checks
  are in test_firmware_target.py).

What this does not show: the electrical behaviour of the transceiver (BENCH.md E1 to E6).
"""
import ast
import inspect
import pathlib
import random
import re

import pytest

from host.telematics import controller_adapter as CA
from host.telematics import node as N
from host.vcu_bridge import semmc_socketcan as B
from protocol.generated import semmc_protocol as proto
from tools import scope

ROOT = pathlib.Path(__file__).resolve().parents[2]
# modules that hold or exercise controller authority: out of scope for the telematics delivery
OUT_OF_SCOPE = ("host.telemetry_adapter", "host.logger", "host.replay", "tools.run_host_demo", "tools.run_mqtt_demo",
                "tools.bench_read", "tools.bench_package", "tools.acceptance")
PROPULSION_WORDS = re.compile(r"(set|command|request|write|send|apply|override)_?(torque|throttle|speed|current|"
                              r"limit|limits|state|mode|arm|enable|propulsion|controller)", re.I)


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _production_files() -> list[pathlib.Path]:
    data = scope.load()
    out = []
    for rel in scope.tracked():
        if rel.endswith(".py") and not rel.startswith("tests/") and rel != "conftest.py" \
                and scope.module_suite(rel, data) == "telematics":
            out.append(ROOT / rel)
    return out


def _imports(path: pathlib.Path) -> set[str]:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
            mods |= {f"{node.module}.{a.name}" for a in node.names}
    return mods


def _repo_file(mod: str) -> pathlib.Path | None:
    p = ROOT.joinpath(*mod.split("."))
    for cand in (p.with_suffix(".py"), p / "__init__.py"):
        if cand.exists():
            return cand
    return None


def _reachable(start: list[pathlib.Path]) -> dict[str, pathlib.Path]:
    seen, todo = {}, list(start)
    while todo:
        f = todo.pop()
        name = _module_name(f)
        if name in seen:
            continue
        seen[name] = f
        for m in _imports(f):
            rf = _repo_file(m)
            if rf is not None and _module_name(rf) not in seen:
                todo.append(rf)
    return seen


def test_production_code_is_listed_and_reaches_no_controller_authority():
    prod = _production_files()
    names = {_module_name(p) for p in prod}
    for must in ("host.telematics.node", "host.telematics.controller_adapter", "host.pit.ingest",
                 "tools.telematics_import", "tools.run_telematics_demo"):
        assert must in names, must
    reach = _reachable(prod)
    bad = sorted(m for m in reach if m.startswith(OUT_OF_SCOPE) or m.startswith("firmware"))
    assert bad == [], bad
    # the bridge is reachable only for decoding; it has no transmit function any more
    assert not hasattr(B, "send")


def _violations(text: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and node.attr in ("AF_CAN", "CAN_RAW", "CAN_ISOTP", "CAN_J1939"):
            out.append(f"{node.lineno}: opens a CAN socket ({node.attr})")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "encode":
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in ("proto", "semmc_protocol"):
                out.append(f"{node.lineno}: builds a semmc frame")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and PROPULSION_WORDS.search(node.name):
            out.append(f"{node.lineno}: function {node.name} names a command")
    return out


def test_production_code_opens_no_can_socket_and_calls_no_frame_encoder():
    bad = {str(f.relative_to(ROOT)): v for f in _production_files() if (v := _violations(f.read_text()))}
    assert bad == {}, bad


def test_the_boundary_scan_catches_a_planted_transmit_path():
    """Negative control: the scan above is not vacuous."""
    planted = ("import socket\nfrom protocol.generated import semmc_protocol as proto\n"
               "def set_torque(nm):\n    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)\n"
               "    s.send(proto.encode('sup_torque_req', {'torque_Nm': nm}, 0)[0])\n")
    v = _violations(planted)
    assert any("AF_CAN" in x for x in v) and any("semmc frame" in x for x in v) and any("set_torque" in x for x in v)


def test_node_and_adapters_expose_no_transmit_path():
    # the node's only outward channel is the uplink link (MQTT to the pit); it is given no CAN interface
    params = list(inspect.signature(N.TelematicsNode.__init__).parameters)
    assert not [p for p in params if re.search(r"can|bus|socket|tx", p, re.I)], params
    for cls in (N.TelematicsNode, CA.SimFixtureAdapter, CA.DbcAdapter, CA.NullAdapter):
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction):
            assert not re.search(r"^(tx|transmit|send_frame|write_frame)|_frame$", name), (cls.__name__, name)
            assert not PROPULSION_WORDS.search(name), (cls.__name__, name)
    assert set(dir(B.ReceiveOnlySocket)) & {"send", "sendall", "sendto", "sendmsg", "write"} == set()


def test_adapter_turns_any_frame_into_measurements_only():
    """Random, malformed, extended, FD and companion frames: the result is measurements or nothing, never a
    frame, and a frame whose CRC fails gives no value."""
    rng = random.Random(7)
    a = CA.SimFixtureAdapter()
    ids = [m["id"] for m in proto.MESSAGES.values()] + [0x123, 0x7FF]
    for k in range(5000):
        f = CA.Frame(rng.choice(ids), bytes(rng.randrange(256) for _ in range(rng.choice((0, 3, 8, 12)))),
                     extended=rng.random() < 0.05, fd=rng.random() < 0.05)
        r = a.decode(k * 100, f)
        assert r.kind in ("decoded", "ignored", "unknown_id", "invalid")
        assert all(type(m).__name__ == "Measurement" for m in r.measurements)
        if r.kind == "invalid":
            assert r.measurements == []
    # companion messages (the old supervisor's torque request, limits, hello, the CSIA advisory) are ignored
    for name in ("sup_torque_req", "sup_limits", "sup_hello", "csia_advisory"):
        m = proto.MESSAGES[name]
        assert m["sender"] == "companion"
        vals = {f["name"]: 0 for f in m["fields"]} if "fields" in m else {}
        try:
            data, _s, _i = proto.encode(name, vals, 1)          # the test builds the frame, not the product
        except Exception:
            data = bytes(8)
        r = a.decode(0, CA.Frame(m["id"], data))
        assert r.measurements == [] and r.kind in ("ignored", "invalid"), (name, r.kind)


def test_firmware_can_driver_has_no_transmit_function():
    u5 = ROOT / "telematics" / "firmware" / "platform" / "u575"
    hdr = (u5 / "drivers_u575.h").read_text()
    can_api = re.findall(r"^\S.*\bcan_\w+\s*\(", hdr, re.M)
    assert can_api and not [d for d in can_api if re.search(r"tx|send|transmit|write", d, re.I)], can_api
    src = (u5 / "can_u575.c").read_text()
    assert "FDCAN_CCCR_MON" in src and not re.search(r"TXBAR|TXBC|TXFQS|TXBTIE", src)
    app = "\n".join(p.read_text() for p in (ROOT / "telematics" / "firmware" / "src").glob("*.c"))
    assert not re.search(r"\bcan_tx|\bcan_send|\bcan_transmit", app)


def test_out_of_scope_modules_are_classified_as_controller_or_reference():
    data = scope.load()
    for rel in ("host/telemetry_adapter/supervisor.py", "host/telemetry_adapter/legacy_node.py",
                "tools/run_host_demo.py", "tools/run_mqtt_demo.py", "firmware/src/core/mc_core.c"):
        assert (ROOT / rel).exists(), rel
        assert scope.module_suite(rel, data) == "controller", rel
    assert scope.module_suite("host/vcu_bridge/semmc_socketcan.py", data) == "reference"
