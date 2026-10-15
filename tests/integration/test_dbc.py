"""The generated DBC agrees with the golden-vector-tested codec, checked with an
independent DBC parser (cantools). Host-only; says nothing about any real bus."""
import pathlib
import subprocess
import sys

import pytest
import yaml

cantools = pytest.importorskip("cantools")

from protocol.generated import semmc_protocol as proto  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "protocol" / "protocol.yaml").read_text())
sys.path.insert(0, str(ROOT / "tools"))
import gen_dbc  # noqa: E402


def _db(base=0x300):
    return cantools.database.load_string(gen_dbc.build(gen_dbc.gen_protocol.load_spec(), base), "dbc")


def test_committed_dbc_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_dbc.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("base", [0x300, 0x500])
def test_golden_vectors_decode_identically(base):
    db = _db(base)
    assert len(SPEC["vectors"]) >= 10
    for v in SPEC["vectors"]:
        m = proto.MESSAGES[v["msg"]]
        data, _sat, _inv = proto.encode(v["msg"], v["values"], v["seq"])
        msg = db.get_message_by_frame_id(m["id"] - 0x300 + base)
        assert msg.name == v["msg"]
        got = msg.decode(bytes(data), decode_choices=False, scaling=True)
        assert got["seq"] == v["seq"] and got["crc8"] == data[0]
        ours, _info = proto.decode(m["id"], data)
        for f in m["fields"]:
            a, b = got[f["name"]], ours[f["name"]]
            if b != b:  # NaN = invalid sentinel in our codec; the DBC carries the raw sentinel
                continue
            tol = f.get("scale", 1) / 2 + 1e-6 * max(1.0, abs(b))
            assert abs(float(a) - float(b)) <= tol, (v["msg"], f["name"], a, b)


def test_unaligned_base_rejected():
    with pytest.raises(ValueError):
        gen_dbc.build(gen_dbc.gen_protocol.load_spec(), 0x310)
