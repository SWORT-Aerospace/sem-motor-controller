"""Python codec: golden vectors, independent hand calculation, generator freshness."""
import json
import math
import pathlib
import subprocess
import sys

import pytest

from protocol.generated import semmc_protocol as proto

ROOT = pathlib.Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "protocol" / "golden_vectors" / "vectors.json").read_text())


def _crc8_bitwise_reference(data: bytes) -> int:
    """Independent CRC-8/SAE-J1850 written from the definition (MSB-first)."""
    reg = 0xFF
    for byte in data:
        for i in range(7, -1, -1):
            bit = (byte >> i) & 1
            top = (reg >> 7) & 1
            reg = (reg << 1) & 0xFF
            if top ^ bit:
                reg ^= 0x1D
    return reg ^ 0xFF


def test_crc_check_value():
    assert _crc8_bitwise_reference(b"123456789") == 0x4B
    assert proto._crc8(b"123456789") ^ 0xFF == 0x4B


@pytest.mark.parametrize("vec", VECTORS["vectors"], ids=lambda v: f"{v['index']}-{v['msg']}")
def test_golden_vector_roundtrip(vec):
    values = {k: (float("nan") if v == "NaN" else v) for k, v in vec["values"].items()}
    data, sat, inv = proto.encode(vec["msg"], values, vec["seq"])
    assert data.hex() == vec["bytes"]
    assert sat == vec["saturated"] and inv == vec["invalid"]
    dec, info = proto.decode(vec["msg"], data)
    assert info["status"] == "ok" and info["seq"] == vec["seq"]
    for k, v in vec["decoded"].items():
        if v == "NaN":
            assert math.isnan(dec[k])
        else:
            assert dec[k] == v


def test_hand_calculated_sup_torque_req():
    """Byte-by-byte from protocol.yaml, without using the codec's encoder.

    sup_torque_req id 0x308, major 1 => DataID = (1 << 11) | 0x308 = 0x0B08.
    seq=0, session_tag=0x5A, limits_ref=3, coast=0, torque=1.234 N*m, src=1000 ms.
      byte1 = 0x00 (seq)
      byte2 = 0x5A
      byte3 = limits_ref (bits 24..27) | coast<<4 = 0x03
      bytes4-5 = round(1.234/0.002) = 617 = 0x0269 -> 69 02
      bytes6-7 = 1000 = 0x03E8 -> E8 03
      byte0 = CRC8_J1850([08 0B] ++ bytes1..7)
    """
    payload = bytes([0x00, 0x5A, 0x03, 0x69, 0x02, 0xE8, 0x03])
    crc = _crc8_bitwise_reference(bytes([0x08, 0x0B]) + payload)
    expected = bytes([crc]) + payload
    data, _, _ = proto.encode("sup_torque_req", {"session_tag": 0x5A, "limits_ref": 3, "coast_request": False,
                                                 "reserved": 0, "torque_Nm": 1.234, "src_time_ms": 1000}, 0)
    assert data == expected
    assert proto.MESSAGES["sup_torque_req"]["data_id"] == 0x0B08


def test_hand_calculated_negative_and_wrap():
    """torque -0.5 N*m => raw -250 => 0xFF06 two's complement => 06 FF; seq 255."""
    data, _, _ = proto.encode("sup_torque_req", {"session_tag": 1, "limits_ref": 15, "coast_request": True,
                                                 "reserved": 0, "torque_Nm": -0.5, "src_time_ms": 65535}, 255)
    assert data[1] == 0xFF
    assert data[3] == 0x1F  # limits_ref 15 | coast << 4
    assert data[4:6] == bytes([0x06, 0xFF])
    assert data[6:8] == bytes([0xFF, 0xFF])


def test_wrong_major_version_fails_crc():
    data, _, _ = proto.encode("ctrl_status", {f["name"]: 0 for f in proto.MESSAGES["ctrl_status"]["fields"]}, 1)
    m = proto.MESSAGES["ctrl_status"]
    other_major_data_id = (2 << 11) | m["id"]
    assert proto.crc8_with_data_id(other_major_data_id, data[1:]) != data[0]


def test_malformed_inputs():
    assert proto.decode("ctrl_status", b"\x00" * 7)[1]["status"] == "bad_length"
    assert proto.decode("ctrl_status", b"\x00" * 8)[1]["status"] == "bad_crc"
    assert proto.decode(0x7FF, b"\x00" * 8)[1]["status"] == "unknown_id"
    with pytest.raises(proto.CodecError):
        proto.encode("sup_limits", {"session_tag": 1, "limits_seq": 1, "max_torque_Nm": float("nan"),
                                    "max_batt_power_W": 1.0}, 0)


def test_generated_files_are_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_protocol.py"), "--check"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_config.py"), "--check"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_bus_load_budget():
    from tools.bus_load import analyse
    res = analyse()
    assert res["semmc_utilisation"] < 0.30
    for m in res["messages"]:
        assert m["wcrt_ms"] < m["period_ms"], m
