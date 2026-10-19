"""The telematics bench package (tools/telematics_bench.py, telematics/bench/bench.yaml) and the console capture
(tools/uart_capture.py).

What this shows: the bench procedure is current, every pin it names is the one the firmware sets up, every
console text it quotes is in the firmware, its parts are exactly the BOM's bench lines, and the package
carries correct hashes and a blank results form. What it does not show: that any connection works. Nothing
here touches a board.
"""
import copy
import csv
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading

import pytest
import yaml

from tools import telematics_bench as B
from tools import telematics_bom as tb
from tools import uart_capture


def _fake_images(d: pathlib.Path, rev: str) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    for name in ("tm_u575", "tm_u575_can"):
        for ext in B.IMAGE_EXT:
            body = b"\x00\x20" + f"{name} {rev}".encode() + b"\x00padding" if ext == ".bin" else f"{name}{ext}".encode()
            (d / f"{name}{ext}").write_bytes(body)
    return d


def test_procedure_is_current_and_consistent():
    r = subprocess.run([sys.executable, "tools/telematics_bench.py", "render", "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert B.validate(B.load(), tb.load()) == []


def test_validation_catches_drift_from_the_firmware_and_the_bom():
    d, bom = B.load(), tb.load()
    d2 = copy.deepcopy(d)
    next(c for c in d2["connections"] if c["id"] == "wheel_0")["check"]["contains"] = "WHEEL_PIN[3] = {9u, 2u, 0u}"
    next(c for c in d2["connections"] if c["id"] == "nor_cs")["part"] = "sd_card"
    next(s for s in d2["steps"] if s["id"] == "B11")["firmware_text"][0]["contains"] = "on (normal mode)"
    next(s for s in d2["steps"] if s["id"] == "B7")["expect"] += " [[nope]]"
    del d2["parts_without_a_row"]["breadboard"]
    d2["steps"] = [s for s in d2["steps"] if s["id"] != "B5"]
    d2["connections"].append({"id": "x", "signal": "x", "mcu": "PB0", "nucleo": "x", "to": "x"})
    err = "\n".join(B.validate(d2, bom))
    for frag in ("connection wheel_0", "part sd_card", "B11: telematics/firmware/platform/u575/can_u575.c",
                 "[[nope]]", "'breadboard'", "steps must be", "connection x: MCU pin PB0 without"):
        assert frag in err, frag
    bom2 = copy.deepcopy(bom)
    bom2["lines"].append({"id": "extra", "config": "bench", "item": "x", "qty": 1, "low": 1, "high": 1,
                          "evidence": "snippet", "source": "x"})
    assert any("used nowhere" in e and "extra" in e for e in B.validate(d, bom2))


def test_bench_steps_say_what_the_findings_require():
    text = B.DOC.read_text()
    b6 = text[text.index("### B6."):text.index("### B7.")]
    assert "a held line is not standstill" in b6 and "no speed of 0 anywhere" in b6
    assert "never jumper a line the generator drives" in b6 and "standstill: line held active" not in text
    e1 = text[text.index("| E1 "):].splitlines()[0]
    assert "Isolated bus, no other node" in e1 and "control" in e1 and "acknowledge error" in e1
    assert "floods the bus" not in text
    b7 = text[text.index("### B7."):text.index("### B8.")]
    st = json.loads(B.STORAGE.read_text())
    nor = {m["id"]: m for m in st["mixes"]}["wheel"]["storages"]["W25Q128JV NOR"]["full_rate_s"]
    assert f"{nor} s" in b7 and "4294.967 s" in b7 and "DUMP n-15 n+15" in b7
    # bench power: USB only; nothing on the bench is vehicle-supplied
    assert "USB only" in text and "vehicle power connection is blocked" in text
    assert "DS18B20" not in text and "microSD" not in text


def test_package_has_hashes_parts_connections_and_a_blank_form(tmp_path):
    rev = B._git("describe", "--always", "--dirty", "--abbrev=12")
    img = _fake_images(tmp_path / "img", rev)
    out = tmp_path / "pkg"
    m = B.package(B.load(), tb.load(), img, out, allow_dirty=True, do_rebuild=False)
    on_disk = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()} - {"MANIFEST.json"}
    assert set(m["files"]) == on_disk
    for f, v in m["files"].items():
        assert hashlib.sha256((out / f).read_bytes()).hexdigest() == v["sha256"], f
    assert {i["name"]: i["revision"] for i in m["images"]} == {"tm_u575": rev, "tm_u575_can": rev}
    assert json.loads((out / "MANIFEST.json").read_text())["verified_on_board"] == "nothing"
    assert (out / "BENCH.md").read_text() == B.DOC.read_text()
    assert (out / "tools" / "uart_capture.py").read_bytes() == (B.ROOT / "tools" / "uart_capture.py").read_bytes()
    parts = list(csv.DictReader(open(out / "PARTS.csv")))
    bom = tb.load()
    assert [p["id"] for p in parts if p["kind"] == "part"] == [l["id"] for l in bom["lines"] if l["config"] == "bench"]
    assert [p["id"] for p in parts if p["kind"] == "equipment"] == B.load()["equipment"]
    rows = list(csv.DictReader(open(out / "CONNECTIONS.csv")))
    assert [r["id"] for r in rows] == [c["id"] for c in B.load()["connections"]]
    assert all(r["verified_on_board"] == "" for r in rows)
    res = yaml.safe_load((out / "results.yaml").read_text())

    def leaves(x):
        if isinstance(x, dict):
            for v in x.values():
                yield from leaves(v)
        else:
            yield x
    blank = {k: v for k, v in res.items() if k != "package"}
    assert all(v is None or v == {} for v in leaves(blank))
    assert set(res["steps"]) == set(B.STEP_IDS) and set(res["electrical"]) == {f"E{k}" for k in range(1, 7)}
    form = (out / "RESULTS_FORM.md").read_text()
    assert form.count("| Result (pass, fail, not run) | |") == len(B.STEP_IDS)
    conn = [l for l in form.splitlines() if l.startswith("| `")]
    assert len(conn) == len(rows) and all(l.endswith("| | | |") for l in conn)    # found, continuity, verified: empty


def test_package_refuses_images_from_another_revision(tmp_path):
    img = _fake_images(tmp_path / "img", "0123456789ab")
    with pytest.raises(SystemExit, match="refused"):
        B.package(B.load(), tb.load(), img, tmp_path / "pkg", allow_dirty=False, do_rebuild=False)
    m = B.package(B.load(), tb.load(), img, tmp_path / "pkg", allow_dirty=True, do_rebuild=False)
    assert not m["valid_for_recorded_run"] and any("0123456789ab" in p for p in m["problems"])


def test_uart_capture_records_bytes_and_sends_commands(tmp_path):
    master, slave = os.openpty()
    fd = uart_capture.open_port(os.ttyname(slave), 115200)
    out = tmp_path / "cap.txt"
    sent = []

    def board():
        buf = b""
        while b"\n" not in buf:
            buf += os.read(master, 64)
        sent.append(buf)
        os.write(master, b"TM t=1.000 s tov=0\r\nDUMP BEGIN 4\r\nS 0 ff\r\nDUMP END\r\nafter\r\n")
    t = threading.Thread(target=board)
    t.start()
    with open(out, "wb") as f:
        res = uart_capture.capture(fd, f, ["DUMP 0 0"], "DUMP END", 10.0)
    t.join(5)
    os.close(fd)
    os.close(slave)
    os.close(master)
    assert sent == [b"DUMP 0 0\r\n"] and res["stopped_by"] == "until"
    assert out.read_bytes().startswith(b"TM t=1.000 s tov=0\r\nDUMP BEGIN 4\r\nS 0 ff\r\nDUMP END")


@pytest.mark.skipif(shutil.which("arm-none-eabi-gcc") is None and os.environ.get("SEMMC_REQUIRE_ARM") != "1",
                    reason="arm-none-eabi-gcc not found")
def test_real_images_carry_the_tree_revision_and_rebuild_identically(tmp_path):
    build = tmp_path / "u575"
    B.rebuild(build)
    rev = B._git("describe", "--always", "--dirty", "--abbrev=12")
    for name in ("tm_u575", "tm_u575_can"):
        assert B.image_revision(name, (build / f"{name}.bin").read_bytes()) == rev
    m = B.package(B.load(), tb.load(), build, tmp_path / "pkg", allow_dirty=True, do_rebuild=True)
    assert m["reproduced_in_a_new_build_directory"] and all(m["reproduced_in_a_new_build_directory"].values())
    assert "arm-none-eabi-gcc" in m["compiler"] and m["build_type"] == "MinSizeRel"


def test_minimal_section_validation_catches_drift():
    d, bom = B.load(), tb.load()
    assert B.validate_minimal(d, bom) == []
    d2 = copy.deepcopy(d)
    m = d2["minimal"]
    m["open"].append("nor_cs")
    m["connections"].append("i2c_scl")                                 # needs the IMU, not a minimal part
    del m["equipment_use"]["scope"]
    m["steps"] = [s for s in m["steps"] if s["id"] != "M3"]
    next(s for s in m["steps"] if s["id"] == "M1")["firmware_text"][0]["contains"] = "log: SD card"
    next(s for s in m["steps"] if s["id"] == "M4")["do"] += " minimal.nope"
    d2["document_checks"][5]["code"]["contains"] = "#define KEY1 0x12345678u"
    d2["document_checks"].append({"id": "DC99", "doc": "AN0000", "before": "M9", "question": "x",
                                  "code": {"file": "telematics/firmware/src/tm_w25q.c", "contains": "0x9F"}})
    d2["documents"].append({"id": "ORPHAN", "file": "x.pdf", "title": "x", "part": "x", "maker": "x", "page": "x"})
    err = "\n".join(B.validate_minimal(d2, bom))
    for frag in ("open row nor_cs", "connection i2c_scl needs part imu", "equipment scope without its use",
                 "steps must be M0 to M4", "minimal M1: telematics/firmware/platform/u575/main_u575.c",
                 "minimal.nope", "DC06: telematics/firmware/platform/u575/flash_u575.c", "document AN0000",
                 "before M9", "document ORPHAN is asked for but no check needs it"):
        assert frag in err, frag


def test_minimal_page_names_the_chain_the_document_checks_and_what_needs_a_board():
    text = B.DOC_MIN.read_text()
    d = B.load()
    for x in d["documents"]:
        assert f"docs/reference/datasheets/{x['file']}" in text
    before = [c for c in d["document_checks"] if c["before"] in ("M0", "M1")]
    assert {c["doc"] for c in before} == {"UM2861", "DS13737", "RM0456", "ES0499"}       # the NOR comes later
    assert all(c["before"] in ("B0", "B7") for c in d["document_checks"] if c["doc"] == "W25Q128JV")
    for s in ("0x45670123", "BKER", "quad-word", "EF 40 18", "WEL", "BUSY", "tSE, tPP, tCE"):
        assert s in text, s
    assert "never run on a board" in text and "SIMULATED" in text and "## 1. Still needs a real board" in text
    assert "refused by its network policy" in text
    m = text[text.index("### M4."):text.index("## 8.")]
    assert "--boot 1" in text and "data class BENCH" in m and "nothing established" in m
    assert "propulsion" not in text.lower() or "no propulsion" in text.lower()


def test_minimal_package_has_one_image_its_rows_the_documents_and_a_simulated_rehearsal(tmp_path, telematics_build):
    rev = B._git("describe", "--always", "--dirty", "--abbrev=12")
    img = _fake_images(tmp_path / "img", rev)
    out = tmp_path / "pkg"
    d, bom = B.load(), tb.load()
    m = B.package(d, bom, img, out, allow_dirty=True, do_rebuild=False, minimal=True, host_build=telematics_build)
    on_disk = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()} - {"MANIFEST.json"}
    assert set(m["files"]) == on_disk
    for f, v in m["files"].items():
        assert hashlib.sha256((out / f).read_bytes()).hexdigest() == v["sha256"], f
    assert m["profile"] == "minimal" and [i["name"] for i in m["images"]] == ["tm_u575"]
    assert not list((out / "images").glob("tm_u575_can*"))
    assert (out / "BENCH_MINIMAL.md").read_text() == B.DOC_MIN.read_text() and not (out / "BENCH.md").exists()
    assert "The PDFs to provide" in (out / "DOCUMENT_CHECKS.md").read_text()
    assert m["verified_on_board"] == "nothing" and m["needs_a_board"] == d["minimal"]["needs_a_board"]
    assert m["build_commands"] == [d["commands"]["build_host"], d["commands"]["build_target"]]
    assert m["document_checks_before_flashing"] == [c["id"] for c in d["document_checks"] if c["before"] in ("M0", "M1")]
    rows = list(csv.DictReader(open(out / "CONNECTIONS.csv")))
    assert [r["id"] for r in rows] == d["minimal"]["connections"]
    assert {r["id"]: r["connect_to"] for r in rows}["wheel_1"] == "nothing (open)"
    parts = list(csv.DictReader(open(out / "PARTS.csv")))
    assert [p["id"] for p in parts if p["kind"] == "part"] == d["minimal"]["parts"]
    assert [p["id"] for p in parts if p["kind"] == "equipment"] == d["minimal"]["equipment"]
    # the rehearsal: the bench's chain command on host-simulated data, labelled as such, every check passing
    r = m["rehearsal"]
    assert r["pass"] and r["data_class"] == "SIMULATED" and all(c["pass"] for c in r["checks"])
    assert {"C8 shadow review: receipts stored, complete, advisory, nothing established",
            "C9 speed and distance plot written from the database"} <= {c["id"] for c in r["checks"]}
    assert (out / "rehearsal" / "chain.md").read_text().startswith("# Pulse-to-database chain (SIMULATED)")
    assert list((out / "rehearsal" / "import").glob("*_speed_distance.png"))
    assert not (out / "rehearsal" / "pit.sqlite").exists()
    res = yaml.safe_load((out / "results.yaml").read_text())
    assert set(res["steps"]) == set(B.MIN_STEP_IDS) and set(res["document_checks"]) == set(m["document_checks_before_flashing"])
    form = (out / "RESULTS_FORM.md").read_text()
    assert form.count("| Result (pass, fail, not run) | |") == len(B.MIN_STEP_IDS)
