"""VCU-side SocketCAN bridge (proposal): frame packing, filtering, decoding. No CAN interface needed."""
import struct

from host.vcu_bridge import semmc_socketcan as B
from protocol.generated import semmc_protocol as proto


def test_semmc_range_filter_matches_icd():
    assert all(B.in_semmc_range(i) for i in range(0x300, 0x340))
    assert not any(B.in_semmc_range(i) for i in list(range(0x000, 0x300)) + list(range(0x340, 0x800)))


def test_classic_frame_roundtrip_decodes_controller_status():
    data, _s, _i = proto.encode("ctrl_cmd_trace", {"requested_Nm": 1.5, "accepted_Nm": 0.5, "reason": 0x2000}, 7)
    raw = B.pack_classic(proto.MESSAGES["ctrl_cmd_trace"]["id"], data)
    assert len(raw) == B.CAN_MTU
    msg = B.decode_frame(raw)
    assert msg["status"] == "ok" and msg["name"] == "ctrl_cmd_trace" and msg["seq"] == 7
    assert abs(msg["values"]["accepted_Nm"] - 0.5) < 1e-3 and msg["values"]["reason"] == 0x2000


def test_chuds_fd_frames_and_extended_ids_are_ignored():
    fd = struct.pack("=IBBBB64s", 0x210, 8, 0x01, 0, 0, bytes(64))     # CHUDS telemetry from node 0x10
    assert B.decode_frame(fd) is None
    ext = struct.pack("=IB3x8s", 0x300 | B.CAN_EFF_FLAG, 8, bytes(8))
    assert B.decode_frame(ext) is None
    outside = B.pack_classic(0x2FF, bytes(8))
    assert B.decode_frame(outside) is None


def test_corrupted_frame_reports_bad_crc_not_values():
    data, _s, _i = proto.encode("ctrl_cmd_trace", {"requested_Nm": 1.0, "accepted_Nm": 1.0, "reason": 0}, 1)
    bad = bytearray(data)
    bad[3] ^= 0x10
    msg = B.decode_frame(B.pack_classic(proto.MESSAGES["ctrl_cmd_trace"]["id"], bytes(bad)))
    assert msg["status"] == "bad_crc" and msg["values"] == {}


def test_relocated_block_is_translated_to_protocol_numbers():
    """The bus block is a calibration choice (supervision.can_id_base); the bridge must match it."""
    base = 0x500
    assert all(B.in_semmc_range(i, base) for i in range(0x500, 0x540))
    assert not B.in_semmc_range(0x310, base)
    data, _s, _i = proto.encode("ctrl_cmd_trace", {"requested_Nm": 1.5, "accepted_Nm": 0.5, "reason": 0x2000}, 7)
    msg_id = proto.MESSAGES["ctrl_cmd_trace"]["id"]
    raw = B.pack_classic(B.to_bus_id(msg_id, base), data)
    msg = B.decode_frame(raw, base)
    assert msg["msg_id"] == msg_id and msg["id"] == msg_id - 0x300 + base
    assert msg["status"] == "ok" and msg["name"] == "ctrl_cmd_trace" and abs(msg["values"]["accepted_Nm"] - 0.5) < 1e-3
    assert B.decode_frame(raw) is None                     # the default block does not accept it
    import pytest
    with pytest.raises(ValueError):
        B.in_semmc_range(0x310, 0x310)                     # unaligned base rejected (rule 40)
