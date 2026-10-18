"""The telematics firmware's portable code on the host (telematics/firmware): unit tests, the shared tables,
and the full data path (edges and CAN frames -> queue -> STLG blocks -> flash slots -> dump -> pit import)
through the host simulator, compared with the Python reference on the same inputs.

This runs the firmware's own C code, built for the host. It is not the target: interrupts, the timer, the
flash controller and the CAN peripheral are not exercised here (the target image is checked in
test_firmware_target.py and on the bench, telematics/firmware/BENCH.md).
"""
import json
import math
import re
import subprocess

import pytest

from host.pit import energy, ingest
from host.telematics import stlg
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig
from host.telematics.wheel import EdgeAccumulator
from tools import telematics_import

FW = "telematics/firmware"


def test_unit_tests_pass(telematics_build):
    r = subprocess.run([str(telematics_build / "tm_tests")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert " 0 failed" in r.stdout


def test_counter_and_record_ids_match_the_python_reference(request):
    root = request.config.rootpath
    h = (root / FW / "include" / "tm_counters.h").read_text()
    ids = {int(v): k.lower() for k, v in re.findall(r"TM_CNT_([A-Z0-9_]+) = (\d+)", h)}
    assert ids and all(stlg.COUNTER2_IDS[i] == name for i, name in ids.items())
    s = (root / FW / "include" / "tm_stlg.h").read_text()
    rec = {k: int(v) for k, v in re.findall(r"TM_REC_([A-Z0-9_]+) = (\d+)", s)}
    assert rec == {k: getattr(stlg, k) for k in rec}
    cfg = (root / FW / "include" / "tm_config.h").read_text()
    assert f"{stlg.BASE_SLACK_US}u" in cfg and "TM_SLOT_BYTES 4096u" in cfg


def _script(tmp_path, duration=40.0, restart=None, stall=None, slots=256, seed_faults=Faults(), frames=True):
    """Host-simulator script from the vehicle fixture: wheel edges, line levels, controller frames."""
    sim = VehicleSim(VehicleSimConfig(), seed_faults, profile=lambda t: 0.0 if t < 1.0 or t > duration - 8 else 6.0)
    img = tmp_path / "flash.bin"
    lines = [f"I {slots} 1500 8 {img}"]
    if stall:
        lines.append(f"S {int(stall[0] * 1e6)} {int(stall[1] * 1e6)}")
    edges, levels = [], {}
    dt = 0.001
    restarted = False
    for k in range(1, int(duration / dt) + 1):
        t = k * dt
        res = sim.step(t, dt)
        ev = []
        for te, ch in res["edges"]:
            ev.append((int(round(te * 1e6)), f"E {int(round(te * 1e6))} {ch}"))
            edges.append((int(round(te * 1e6)), ch))
        for ch in range(3):
            hi = sim.line_high(ch, t)
            if levels.get(ch) != hi:
                levels[ch] = hi
                ev.append((int(round(t * 1e6)), f"L {int(round(t * 1e6))} {ch} {int(hi)}"))
        if frames:
            for tx, cid, data in sim.frames(t):
                ev.append((int(round(tx * 1e6)), f"C {int(round(tx * 1e6))} {cid:x} {data.hex()}"))
        sim.sensors(t)
        if restart and not restarted and t >= restart:
            ev.append((int(t * 1e6), f"R {int(t * 1e6)}"))
            restarted = True
        lines += [x for _t, x in sorted(ev, key=lambda e: e[0])]
    lines += [f"P {int(duration * 1e6)}", "F", "W", "Q"]
    return "\n".join(lines) + "\n", img, edges, sim


def _run(build, script):
    r = subprocess.run([str(build / "tm_hostsim")], input=script, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_wheel_records_equal_the_python_reference_byte_for_byte(telematics_build, tmp_path):
    script, img, edges, _sim = _script(tmp_path, duration=20.0, frames=False)
    _run(telematics_build, script)
    sessions, rep = telematics_import.split(img.read_bytes())
    assert len(sessions) == 1 and rep["corrupt_header"] == 0 and rep["orphan_block"] == 0
    p = telematics_import.write_session(sessions[0], tmp_path, {})
    _meta, recs, rr = stlg.read(p)
    assert rr.blocks_corrupt == 0 and rr.block_seq_gaps == 0
    c_bodies = [(t, f) for _b, _i, t, rt, f in recs if rt == stlg.WHEEL_EDGES]
    # the Python accumulator on the same edges, taken at the same instants (every 50 ms from the start)
    acc = {ch: EdgeAccumulator(ch) for ch in range(3)}
    py, k, j = [], 1, 0
    edges.sort()
    while len(py) < len(c_bodies):
        t_take = k * 50_000
        while j < len(edges) and edges[j][0] <= t_take:
            acc[edges[j][1]].edge(edges[j][0])
            j += 1
        for ch in range(3):
            r = acc[ch].take(t_take, line_high=True)
            py.append((r.t_us, {"channel": ch, "n": r.n, "span_us": r.span_us, "total": r.total, "rec_seq": r.rec_seq,
                                "lost": r.lost}))
        k += 1
    assert len(c_bodies) > 3 * 300
    for (tc, fc), (tp, fp) in zip(c_bodies, py):
        assert tc == tp and all(fc[x] == fp[x] for x in fp), (tc, fc, tp, fp)


def test_flash_image_imports_with_speed_distance_restart_and_accounting(telematics_build, tmp_path):
    script, img, _edges, sim = _script(tmp_path, duration=40.0, restart=20.0, stall=(10.0, 13.0))
    out = _run(telematics_build, script)
    lost = [tuple(map(int, line.split()[1:])) for line in out.splitlines() if line.startswith("LOST")]
    assert len(lost) == 1
    db_path = tmp_path / "pit.sqlite"
    res = telematics_import.run(img.read_bytes(), db_path, tmp_path / "imp", {}, plots=True)
    assert [s["boot"] for s in res["sessions"]] == [1, 2]
    s1, s2 = res["sessions"]
    assert s1["reset"]["cause"] == "BOR+PIN" and s2["reset"]["cause"] == "BOR"
    i1, i2 = s1["import"], s2["import"]
    # a restart while a slot is being programmed leaves that one slot partly written: its CRC fails and the
    # reader counts it; anything else is corrupt only by a defect
    partial = 1 if lost[0][1] else 0
    assert i1["blocks_corrupt"] == partial and i2["blocks_corrupt"] == 0 and i2["block_seq_gaps"] == 0
    # boot 1 ended by the restart: no final counters record; nothing before the last counters is missing
    assert not i1["final_counters"] and i1["accounting"]["missing_from_file"] == 0
    assert "unknown" in i1["accounting"]["after_last_counters"]
    # the storage stall filled the queue: drops counted, in the counters
    assert i1["accounting"]["dropped_queue"] > 0
    # the controller frames went through the semmc fixture adapter at import
    db = ingest.connect(db_path)
    n_v = db.execute("SELECT COUNT(*) FROM measurements WHERE run_id=? AND signal='ctrl.dc_voltage'",
                     (s1["run_id"],)).fetchone()[0]
    assert n_v > 500
    # speed and distance from the firmware's records: the boot-2 distance equals the simulated distance after
    # the restart, to one pitch (the RAM lost in the restart only held edges of boot 1)
    d2 = s2["distance"]["wheel_0"]["distance_m"]
    pitch = 1.5 / 8
    t_restart = 20.0
    assert d2 is not None and s2["plot"]
    # truth: distance between the restart and the end
    sim2 = VehicleSim(VehicleSimConfig(), Faults(), profile=lambda t: 0.0 if t < 1.0 or t > 32.0 else 6.0)
    d_at, v_at = {}, [0.0]
    for k in range(1, 40001):
        t = k * 0.001
        sim2.step(t, 0.001)
        v_at.append(sim2.v)
        if k in (int(t_restart * 1000), 40000):
            d_at[k] = sim2.dist
    true2 = d_at[40000] - d_at[int(t_restart * 1000)]
    assert abs(d2 - true2) <= pitch + 1e-9, (d2, true2)
    # speed samples (edge periods) against the simulated speed at their sample time (host simulator time is
    # the simulation's time)
    err = [v - v_at[round(t / 1000)] for t, v, _u, _q in energy.series(db, s1["run_id"], "wheel.wheel_0.speed")
           if v_at[round(t / 1000)] > 1.0]
    assert len(err) > 100 and math.sqrt(sum(e * e for e in err) / len(err)) < 0.02
    # a second import of the same dump adds nothing
    again = telematics_import.run(img.read_bytes(), db_path, tmp_path / "imp2", {}, plots=False)
    assert all(s["import"]["new_records"] == 0 and s["import"]["new_measurements"] == 0 for s in again["sessions"])


def test_full_storage_refuses_blocks_and_counts_them(telematics_build, tmp_path):
    script, img, _e, _s = _script(tmp_path, duration=15.0, slots=8)
    out = _run(telematics_build, script)
    m = re.search(r"slots=(\d+)/(\d+)", out)
    assert m and m.group(1) == m.group(2) == "8"
    sessions, _rep = telematics_import.split(img.read_bytes())
    p = telematics_import.write_session(sessions[0], tmp_path, {})
    _meta, recs, _rr = stlg.read(p)
    # the log holds 8 slots (header + 7 blocks), all readable; what did not fit is counted on the unit (the
    # counters that would say so cannot be in a full log: the status line and the live summary report them)
    assert len(sessions[0]["blocks"]) == 7 and _rr.blocks_corrupt == 0
    assert int(re.search(r"drop_st=(\d+)", out).group(1)) > 0


def test_uart_dump_format_round_trips(tmp_path):
    image = bytearray(b"\xff" * (4 * 4096))
    hdr = b"STLG" + (1).to_bytes(2, "little")
    meta = json.dumps({"run_id": "X-B0001", "boot": 1}).encode()
    import zlib
    image[:14 + len(meta)] = hdr + len(meta).to_bytes(4, "little") + meta + zlib.crc32(meta).to_bytes(4, "little")
    text = "noise\nDUMP BEGIN 4\nS 0 " + bytes(image[:4096]).hex() + "\nDUMP END\n"
    assert telematics_import.from_uart(text) == bytes(image)
    sessions, rep = telematics_import.split(telematics_import.from_uart(text))
    assert len(sessions) == 1 and rep["empty"] == 3 and math.isclose(rep["slots"], 4)
