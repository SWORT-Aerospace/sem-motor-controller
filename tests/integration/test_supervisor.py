"""Supervisor (telematics-side) behaviour on stale, duplicated and invalid controller telemetry.

The controller bounds whatever the supervisor requests, but the supervisor must
not keep requesting propulsion from a speed it no longer receives. Host-only.
"""
import math

from host.telemetry_adapter.supervisor import Supervisor, SupervisorConfig, speed_hold_policy
from protocol.generated import semmc_protocol as proto

ID = {n: m["id"] for n, m in proto.MESSAGES.items()}


def _sup():
    s = Supervisor(SupervisorConfig(max_torque_Nm=2.0), speed_hold_policy(6.0, 1.5, 1.5, 10.0, 2.0))
    data, _, _ = proto.encode("ctrl_session", {"session_tag": 0x42, "companion_session_echo": s.cfg.session_id,
                                               "proto_major": 1, "proto_minor": 1}, 0)
    s.on_frame(0.0, ID["ctrl_session"], data)
    assert s.tag == 0x42
    return s


def _motion(speed, seq):
    data, _, _ = proto.encode("ctrl_motion", {"speed_mech_rad_s": speed, "iq_A": 1.0, "vbus_V": 48.0}, seq)
    return data


def _last_request(s):
    return s.log[-1]


def test_fresh_speed_gives_bounded_propulsion():
    s = _sup()
    s.on_frame(0.10, ID["ctrl_motion"], _motion(10.0, 1))
    s.tick(0.10)
    r = _last_request(s)
    assert 0.0 < r["torque_Nm"] <= 2.0 and not r["coast"]


def test_stale_speed_stops_propulsion():
    s = _sup()
    s.on_frame(0.10, ID["ctrl_motion"], _motion(10.0, 1))
    s.tick(0.10)
    s.tick(0.30)                       # 200 ms without a new ctrl_motion sample
    r = _last_request(s)
    assert r["torque_Nm"] == 0.0 and r["coast"] and r["reason"] == "telemetry_stale"


def test_duplicate_frames_do_not_renew_speed():
    s = _sup()
    frame = _motion(10.0, 7)
    s.on_frame(0.10, ID["ctrl_motion"], frame)
    for k in range(1, 20):             # the same frame re-sent (bus replay, stuck gateway)
        s.on_frame(0.10 + 0.01 * k, ID["ctrl_motion"], frame)
    s.tick(0.30)
    r = _last_request(s)
    assert r["torque_Nm"] == 0.0 and r["reason"] == "telemetry_stale"


def test_invalid_speed_is_not_treated_as_zero_or_last_value():
    s = _sup()
    s.on_frame(0.10, ID["ctrl_motion"], _motion(10.0, 1))
    s.on_frame(0.11, ID["ctrl_motion"], _motion(math.nan, 2))   # controller reports speed invalid
    s.tick(0.12)
    r = _last_request(s)
    assert r["torque_Nm"] == 0.0 and r["coast"] and r["reason"] == "telemetry_invalid"
