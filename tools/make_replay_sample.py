#!/usr/bin/env python3
"""Generate tests/simulation/replay_sample.semmc.log - a SYNTHETIC "recorded"
vehicle log for the replay demonstration (no plant: measurements are MEAS
lines, as a recorded log would supply them).

The supervisor's session tag is learned the way a real companion learns it:
a first pass replays the HELLO and reads ctrl_session from the controller's TX
frames; the second pass writes the full log. Contents (times in s):
  0.10 arm        0.30 eco switch ON     0.05.. supervisor frames at 50 Hz
  2.00 duplicate frames (must not renew)  2.50 reordered old frame
  3.00-3.20 supervisor silent (stale -> ECO exits)
  3.50 driver toggles eco OFF/ON (new edge) -> ECO again
  5.00 NaN torque request (invalid -> ECO exits)
  6.00 manual: throttle 0.6 with bus sag into the derate band
  7.00 FET temperature into the derate band
  8.00 brake
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from host.logger.semmc_log import Event, can_event, decode_tx_log, io_event, kv_event, write_log  # noqa: E402
from protocol.generated import semmc_protocol as proto  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "simulation" / "replay_sample.semmc.log"
US = 1_000_000
SESSION = 0x5E550001
BOOT_ID = 0x1234  # semmc_host default; replay must use the same boot id


def hello(t_us, seq):
    d, _, _ = proto.encode("sup_hello", {"proto_major": 1, "proto_minor": 0, "role": 1,
                                         "companion_session": SESSION}, seq)
    return can_event(t_us, proto.MESSAGES["sup_hello"]["id"], d)


def learn_tag(host: pathlib.Path, cal: pathlib.Path) -> int:
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        log = write_log(td / "h.log", [hello(50_000, 0), Event(200_000, "END")])
        subprocess.run([str(host), "--cal", str(cal), "--log", str(log), "--out", str(td / "o.csv"), "--no-plant",
                        "--frames", str(td / "tx.log")], check=True, capture_output=True)
        for _t, name, v, _i in decode_tx_log(td / "tx.log"):
            if name == "ctrl_session" and v["companion_session_echo"] == SESSION and v["session_tag"]:
                return v["session_tag"]
    raise RuntimeError("controller did not assign a session tag")


def build(tag: int) -> list[Event]:
    ev = [io_event(0, arm=False, throttle=0.0, eco=False),
          kv_event(0, "MEAS", vbus=46.0, ibatt=0.5, tfet=35.0, tmotor=35.0, hall=1),
          io_event(int(0.1 * US), arm=True), io_event(int(0.3 * US), eco=True), hello(int(0.05 * US), 0)]
    seq = {"req": 0, "lim": 0}
    lseq = 0
    silent = (3.0, 3.2)
    for k in range(int(0.06 / 0.02), int(6.0 / 0.02)):
        t = k * 0.02
        t_us = int(round(t * US))
        if silent[0] <= t < silent[1]:
            continue
        if k % 5 == 0:
            lseq = (lseq + 1) & 0xFF
            d, _, _ = proto.encode("sup_limits", {"session_tag": tag, "limits_seq": lseq, "max_torque_Nm": 1.5,
                                                  "max_batt_power_W": 800.0}, seq["lim"])
            seq["lim"] = (seq["lim"] + 1) & 0xFF
            ev.append(can_event(t_us, proto.MESSAGES["sup_limits"]["id"], d))
        torque = 1.2 if t < 2.4 else 0.8
        if abs(t - 5.0) < 1e-9:
            torque = float("nan")
        d, _, _ = proto.encode("sup_torque_req", {"session_tag": tag, "limits_ref": lseq & 0xF, "coast_request": False,
                                                  "reserved": 0, "torque_Nm": torque,
                                                  "src_time_ms": int(round(t * 1000)) & 0xFFFF}, seq["req"])
        seq["req"] = (seq["req"] + 1) & 0xFF
        ev.append(can_event(t_us, proto.MESSAGES["sup_torque_req"]["id"], d))
        if abs(t - 2.0) < 1e-9:  # exact duplicates 5 and 10 ms later
            ev += [can_event(t_us + 5000, proto.MESSAGES["sup_torque_req"]["id"], d),
                   can_event(t_us + 10000, proto.MESSAGES["sup_torque_req"]["id"], d)]
        if abs(t - 2.5) < 1e-9:  # a stale frame from 60 ms ago arrives late
            old, _, _ = proto.encode("sup_torque_req", {"session_tag": tag, "limits_ref": lseq & 0xF,
                                                        "coast_request": False, "reserved": 0, "torque_Nm": 1.5,
                                                        "src_time_ms": int(round((t - 0.06) * 1000))},
                                     (seq["req"] - 4) & 0xFF)
            ev.append(can_event(t_us + 3000, proto.MESSAGES["sup_torque_req"]["id"], old))
    ev += [io_event(int(3.5 * US), eco=False), io_event(int(3.6 * US), eco=True),
           io_event(int(5.5 * US), eco=False),
           io_event(int(5.9 * US), throttle=0.0), io_event(int(6.0 * US), throttle=0.6),
           kv_event(int(6.0 * US), "MEAS", vbus=37.0, ibatt=12.0, tfet=40.0, tmotor=40.0, hall=1),
           kv_event(int(7.0 * US), "MEAS", vbus=44.0, ibatt=12.0, tfet=100.0, tmotor=45.0, hall=1),
           io_event(int(8.0 * US), brake=True), Event(int(9.0 * US), "END")]
    return ev


def main() -> int:
    host = ROOT / "build" / "semmc_host"
    cal = ROOT / "build" / "cal" / "synthetic.bin"
    tag = learn_tag(host, cal)
    write_log(OUT, build(tag))
    print(f"wrote {OUT.relative_to(ROOT)} (session tag {tag} learned from ctrl_session)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
