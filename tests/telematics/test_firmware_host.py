"""The telematics firmware's portable code on the host (telematics/firmware): unit tests, the shared tables,
and the full data path (edges and CAN frames -> queue -> STLG blocks -> flash slots -> dump -> pit import)
through the host simulator, compared with the Python reference on the same inputs.

This runs the firmware's own C code, built for the host. It is not the target: interrupts, the timer, the
flash controller and the CAN peripheral are not exercised here (the target image is checked in
test_firmware_target.py and on the bench, telematics/firmware/BENCH.md).
"""
import json
import math
import pathlib
import re
import subprocess
import sys

import pytest

from host.pit import energy, ingest
from host.telematics import stlg, ubx
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig
from host.telematics.wheel import EdgeAccumulator, EdgeRecord, WheelConfig, WheelGroup, classify
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


def test_live_summary_tables_match_the_pit_registry_and_counter_ids(request):
    """The firmware's live summary (tm_live.c) names the pit's registry and uses its ranges and stale times for
    the unit's own signals, and its counter names are the pit's (stlg.COUNTER2_IDS)."""
    from host.telematics import signals
    root = request.config.rootpath
    h = (root / FW / "include" / "tm_live.h").read_text()
    assert f'#define TM_REGISTRY_ID "{signals.REGISTRY_ID}"' in h
    c = (root / FW / "src" / "tm_live.c").read_text()
    reg = {i: (float(lo), float(hi), int(ms)) for i, lo, hi, ms in
           re.findall(r'\{"([a-z_.*]+)", (-?[0-9.]+)f, (-?[0-9.]+)f, ([0-9]+)u\}', c)}
    own = {r.id: (r.lo, r.hi, int(round(r.stale_s * 1000))) for r in signals.REGISTRY if r.origin == "telematics"}
    assert reg == own
    ids = {k: int(v) for k, v in re.findall(r"TM_CNT_([A-Z0-9_]+) = (\d+)",
                                            (root / FW / "include" / "tm_counters.h").read_text())}
    names = re.findall(r'\{TM_CNT_([A-Z0-9_]+), "([a-z0-9_]+)"\}', c)
    assert len(names) == len(ids) and all(stlg.COUNTER2_IDS[ids[k]] == n for k, n in names)


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


def test_wheel_plausibility_equals_the_python_rule(telematics_build, tmp_path):
    """Stuck low, disconnected, recovery and a full stop through the firmware's own code (host simulator), the
    same log through the Python rule: the same state per channel at the same instants, the same episodes."""
    img = tmp_path / "flash.bin"
    ev = [(0, "L 0 1 0")]                                     # ch1 shorted to ground: line low, no edges
    ev += [(t, f"E {t} 0") for t in range(50_000, 6_000_001, 40_000)]          # ch0 turns until 6 s
    ev += [(t, f"E {t} 2") for t in range(3_000_000, 6_000_001, 40_000)]       # ch2 connected at 3 s
    samples = [900_000, 1_500_000, 2_500_000, 4_000_000, 6_500_000, 7_500_000, 9_000_000]
    ev += [(s, f"P {s}\nQ") for s in samples]
    script = "\n".join([f"I 256 1500 8 {img}"] + [x for _t, x in sorted(ev, key=lambda e: e[0])]
                       + ["F", "W", "Q"]) + "\n"
    out = _run(telematics_build, script)
    c_states = re.findall(r"wheel=([NMSAI]{3})", out)[:len(samples)]
    assert c_states == ["MNN", "MAI", "MAI", "MAM", "SNS", "SNS", "SNS"], c_states
    sessions, _rep = telematics_import.split(img.read_bytes())
    path = telematics_import.write_session(sessions[0], tmp_path, {})
    _meta, recs, _rr = stlg.read(path)
    g = WheelGroup(WheelConfig(1.5, 8), {0: "wheel_0", 1: "wheel_1", 2: "wheel_2"}, t0_us=0)
    wr = [(t, f) for _b, _i, t, rt, f in recs if rt == stlg.WHEEL_EDGES]
    py_states, j = [], 0
    for s in samples:
        while j < len(wr) and wr[j][0] <= s:
            t, f = wr[j]
            g.update(EdgeRecord(t, f["channel"], f["n"], f["span_us"], f["total"], f["flags"], f["rec_seq"], f["lost"]))
            j += 1
        t_rec = max(t for t, f in wr if f["n"] == 0 and t <= s)          # the latest record period
        py_states.append("".join(classify(g.tracks, ch, t_rec, False)[0] for ch in range(3)))
    assert py_states == c_states
    last = [f for _b, _i, _t, rt, f in recs if rt == stlg.COUNTERS2][-1]
    db = tmp_path / "pit.sqlite"
    res = telematics_import.run(img.read_bytes(), db, tmp_path / "imp", {}, plots=False)
    ep = res["sessions"][0]["import"]["wheel_suspect_episodes"]
    assert last["wheel_suspect_active"] == ep["A"] == 1 and last["wheel_suspect_inactive"] == ep["I"] == 1
    # the import never stores a speed of 0 for a silent channel, and the suspect ones are invalid
    q = ingest.connect(db).execute("SELECT signal, validity, value FROM measurements WHERE signal LIKE "
                                   "'wheel.%.speed' AND (validity != 'valid' OR value = 0)").fetchall()
    assert q and all(v is None for _s, _q, v in q)
    assert {(s, v) for s, v, _x in q} >= {("wheel.wheel_1.speed", "invalid"), ("wheel.wheel_2.speed", "invalid"),
                                          ("wheel.wheel_0.speed", "no_evidence")}


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


def _records(img_bytes, tmp_path, tag):
    sessions, _rep = telematics_import.split(img_bytes)
    out = []
    for k, s in enumerate(sessions):
        d = tmp_path / f"{tag}{k}"
        d.mkdir()
        _meta, recs, rr = stlg.read(telematics_import.write_session(s, d, {}))
        assert rr.blocks_corrupt == 0
        out.append([(t, rt, json.dumps(f, sort_keys=True, default=str)) for _b, _i, t, rt, f in recs])
    return sessions, out


@pytest.mark.parametrize("kind", ["nor", "norslow"])
def test_nor_storage_gives_the_same_log_as_internal_flash(telematics_build, tmp_path, kind):
    """The W25Q path (driver, 256-byte pages, 4 KiB sector erase ahead, busy polling) through the firmware's
    own code: the same records as on internal flash for the same inputs, and no protocol violation."""
    script, img, _e, _s = _script(tmp_path, duration=20.0)
    nor_img = tmp_path / "nor.bin"
    nor_script = script.replace(f"I 256 1500 8 {img}", f"I 256 1500 8 {nor_img} {kind}") + "V\n"
    _run(telematics_build, script)
    out = _run(telematics_build, nor_script)
    assert "NOR violations=0 " in out
    s_int, r_int = _records(img.read_bytes(), tmp_path, "i")
    s_nor, r_nor = _records(nor_img.read_bytes(), tmp_path, "n")
    assert len(r_int) == len(r_nor) == 1 and len(r_int[0]) > 3000
    # the records up to the end of the script (a slower device takes longer to flush, adding later heartbeats)
    keep = lambda r: [x for x in r if x[1] != stlg.COUNTERS2 and x[0] <= 20_000_000]   # noqa: E731
    assert keep(r_int[0]) == keep(r_nor[0])
    assert s_nor[0]["meta"]["run_id"].endswith("-NOR-B0001") and "W25Q" in s_nor[0]["meta"]["storage"]
    assert int(re.search(r"drop_q=(\d+)", out).group(1)) == 0


def test_nor_worst_case_timing_with_every_sector_dirty_keeps_up_with_the_bench_rate(telematics_build, tmp_path):
    """Slow device (400 ms sector erase, 3 ms page program) whose every sector needs erasing (no blank sector
    to skip), with the B12 record mix (wheel records, IMU at 100 Hz, TMP117 at 1 Hz): nothing dropped."""
    img = tmp_path / "nor.bin"
    img.write_bytes(b"\x00" * 64 * 4096)          # loaded as the device content: every sector dirty...
    ev = [f"I 64 1500 8 {img} norslow"]
    # ...except that the scan reads all-zero slots as used: start from a log whose first sector is erased
    img.write_bytes(b"\xff" * 4096 + b"\x00" * 63 * 4096)
    ev += [f"E {t} 0\nK {t} 4 0000000000000000" for t in range(10_000, 40_000_000, 10_000)]
    ev += [f"K {t} 8 00000000" for t in range(1_000_000, 40_000_000, 1_000_000)]
    ev = [ev[0]] + sorted(ev[1:], key=lambda s: int(s.split()[1]))
    out = _run(telematics_build, "\n".join(ev + ["P 40000000", "Q", "V"]) + "\n")
    assert int(re.search(r"drop_q=(\d+)", out).group(1)) == 0 and "NOR violations=0 " in out
    assert int(re.search(r"erases=(\d+)", out).group(1)) >= 20     # the erases happened, at worst-case time
    assert int(re.search(r"slots=(\d+)/", out).group(1)) >= 20


def test_nor_restart_and_erase(telematics_build, tmp_path):
    img = tmp_path / "nor.bin"
    ev = [f"I 64 1500 8 {img} nor"] + [f"E {t} 0" for t in range(10_000, 8_000_000, 10_000)]
    ev += ["R 8000000", "P 14000000", "F", "Q", "W", "V", "X", "Q", "P 20000000", "F", "Q", "V"]
    out = _run(telematics_build, "\n".join(ev) + "\n")
    q = re.findall(r"slots=(\d+)/64", out)
    assert int(q[0]) > 4 and q[1] == "0" and int(q[2]) >= 2       # two sessions, then erased, then new data
    assert re.findall(r"NOR violations=(\d+)", out) == ["0", "0"]
    assert re.findall(r"chip_erases=(\d+)", out)[-1] == "0"        # 64 of 4096 slots: page by page
    sessions, recs = _records(img.read_bytes(), tmp_path, "r")      # the image written before the erase
    assert [s["meta"]["boot"] for s in sessions] == [1, 2]


def test_sparse_logging_keeps_speed_and_distance_evidence_across_2_32_us(telematics_build, tmp_path):
    """A 40-slot internal store with the IMU logging fills its full-rate region before the 64-bit time crosses
    2^32 us; sparse logging then keeps one wheel record per channel every 10 s, so the crossing is in the log
    with its speed and distance (the target's 32-bit timer overflow is the same instant, BENCH.md B7)."""
    img = tmp_path / "f.bin"
    t0 = 2 ** 32 - 120_000_000                                       # sparse from about 50 s, crossing at 120 s
    ev = [(t0, f"T {t0}"), (t0, f"I 40 1500 8 {img}")]
    end = t0 + 300_000_000
    ev += [(t, f"E {t} 0") for t in range(t0 + 10_000, end, 10_000)]                   # 100 Hz: 18.75 m/s
    ev += [(t, f"K {t} 4 0000000000000000") for t in range(t0 + 10_000, end, 10_000)]
    ev += [(end, f"P {end}"), (end + 1, "F\nQ\nW")]
    out = _run(telematics_build, "\n".join(x for _t, x in sorted(ev, key=lambda e: e[0])) + "\n")
    assert "log=sparse" in out and int(re.search(r"thin=(\d+)", out).group(1)) > 10_000
    assert "tov=1" in out
    sessions, _rep = telematics_import.split(img.read_bytes())
    _meta, recs, rr = stlg.read(telematics_import.write_session(sessions[0], tmp_path, {}))
    assert rr.blocks_corrupt == 0
    ev_rec = [f for _b, _i, t, rt, f in recs if rt == stlg.EVENT]
    assert ev_rec and ev_rec[0]["code"] == 2 and "sparse logging" in ev_rec[0]["text"]
    t_sparse = [t for _b, _i, t, rt, f in recs if rt == stlg.EVENT][0]
    w0 = [(t, f) for _b, _i, t, rt, f in recs if rt == stlg.WHEEL_EDGES and f["channel"] == 0 and t > t_sparse + 15e6]
    assert w0 and w0[0][0] < 2 ** 32 < w0[-1][0]                    # sparse records on both sides of 2^32 us
    gaps = [b[0] - a[0] for a, b in zip(w0, w0[1:])]
    assert all(9_900_000 <= g <= 10_100_000 for g in gaps), gaps     # no jump at the crossing
    db = tmp_path / "pit.sqlite"
    res = telematics_import.run(img.read_bytes(), db, tmp_path / "imp", {}, plots=False)
    rid = res["sessions"][0]["run_id"]
    sp = [(t, v, q) for t, v, _u, q in energy.series(ingest.connect(db), rid, "wheel.wheel_0.speed")
          if t > t_sparse + 15e6]
    assert sp and all(q == "valid" and abs(v - 18.75) < 0.01 for _t, v, q in sp), sp[:5]
    assert any(t < 2 ** 32 for t, _v, _q in sp) and any(t > 2 ** 32 for t, _v, _q in sp)
    d = res["sessions"][0]["distance"]["wheel_0"]["distance_m"]
    # distance is the last record's edge total; in sparse logging that record is at most 10 s (1000 edges) old
    last_total = [f["total"] for _b, _i, _t, rt, f in recs if rt == stlg.WHEEL_EDGES and f["channel"] == 0][-1]
    assert math.isclose(d, last_total * 0.1875) and 29_999 - 1000 <= last_total <= 29_999


def test_console_status_lines_are_overflow_evidence_without_the_log(telematics_build, tmp_path):
    """B7's console evidence: status lines every second across the timer overflow (here the simulated 64-bit
    time crossing 2^32 us), parsed and checked by the import tool; a time jump makes the check fail."""
    t0 = 2 ** 32 - 30_000_000
    ev = [(t0, f"T {t0}"), (t0, f"I 16 1000 1 {tmp_path / 'f.bin'}")]
    ev += [(t, f"E {t} 0") for t in range(t0 + 1000, t0 + 60_000_000, 1000)]          # 1 kHz
    ev += [(t, f"P {t}\nQ") for t in range(t0 + 1_000_000, t0 + 60_000_001, 1_000_000)]
    out = _run(telematics_build, "\n".join(x for _t, x in sorted(ev, key=lambda e: e[0])) + "\n")
    rows = telematics_import.status_lines("garbage line\n" + out)
    assert len(rows) == 60 and rows[0]["tov"] == 0 and rows[-1]["tov"] == 1
    chk = telematics_import.overflow_check(rows)
    assert chk["pass"] and len(chk["tov_changes"]) == 1 and abs(chk["median_rate_hz"] - 1000.0) < 1.0
    assert 29.5 <= chk["tov_changes"][0]["t_s"] <= 31.5
    assert chk["tov_changes"][0]["slot"] == next(r["slots"] for r in rows if r["tov"] == 1)
    jumped = out.replace("TM t=40.000 s", "TM t=4335.000 s")                           # a 2^32 us error
    assert not telematics_import.overflow_check(telematics_import.status_lines(jumped))["pass"]


def _firmware_range_dump(image: bytes, slots: int, first: int, last: int) -> str:
    """'DUMP <first> <last>' as main_u575.c prints it: the session header at or before <first>, then the range."""
    hdr = next(k for k in range(first, -1, -1) if image[k * 4096:k * 4096 + 4] == b"STLG")
    ks = ([hdr] if hdr < first else []) + list(range(first, last + 1))
    return "\n".join([f"DUMP BEGIN {slots}"] + [f"S {k} {image[k * 4096:(k + 1) * 4096].hex()}" for k in ks]
                     + ["DUMP END"]) + "\n"


def test_b7_procedure_on_the_nor_finds_and_reads_back_the_overflow(telematics_build, tmp_path):
    """B7 as BENCH.md writes it, on the host model: NOR log, 1 kHz on wheel_0 across 2^32 us, the status
    capture names the slot being filled at the overflow, and 'DUMP n-15 n+15' imports with a valid, steady
    speed on both sides of the crossing (10 mm per edge: 10 m/s)."""
    img = tmp_path / "nor.bin"
    t0 = 2 ** 32 - 90_000_000
    end = t0 + 180_000_000
    ev = [(t0, f"T {t0}"), (t0, f"I 512 10 1 {img} nor")]
    ev += [(t, f"E {t} 0") for t in range(t0 + 1000, end, 1000)]
    ev += [(t, f"P {t}\nQ") for t in range(t0 + 1_000_000, end + 1, 1_000_000)]
    ev += [(end + 1, "F\nW\nV")]
    out = _run(telematics_build, "\n".join(x for _t, x in sorted(ev, key=lambda e: e[0])) + "\n")
    assert "NOR violations=0 " in out
    chk = telematics_import.overflow_check(telematics_import.status_lines(out))
    assert chk["pass"] and len(chk["tov_changes"]) == 1
    n = chk["tov_changes"][0]["slot"]
    assert 30 < n < 60                                              # 2.04 s per slot: about 44 slots in 90 s
    image = img.read_bytes()
    text = _firmware_range_dump(image, 512, n - 15, n + 15)
    part = telematics_import.from_uart(text)
    assert part[:4] == b"STLG" and part[4096:(n - 15) * 4096] == b"\xff" * ((n - 16) * 4096)
    db = tmp_path / "pit.sqlite"
    res = telematics_import.run(part, db, tmp_path / "imp", {"wheel_circumference_m": 0.01, "wheel_ppr": 1,
                                                             "source": "test"}, plots=False)
    rid = res["sessions"][0]["run_id"]
    sp = [(t, v, q) for t, v, _u, q in energy.series(ingest.connect(db), rid, "wheel.wheel_0.speed")]
    assert sp and all(q == "valid" and abs(v - 10.0) < 0.001 for _t, v, q in sp), sp[:5]
    assert min(t for t, _v, _q in sp) < 2 ** 32 < max(t for t, _v, _q in sp)
    ts = [t for t, _v, _q in sp]
    assert max(b - a for a, b in zip(ts, ts[1:])) < 200_000          # no time jump at the crossing


def test_storage_durations_are_current_and_cover_b7(telematics_build):
    r = subprocess.run([sys.executable, "tools/telematics_storage.py", "--check", "--build", str(telematics_build)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    res = json.loads(pathlib.Path("docs/generated/telematics_storage.json").read_text())
    wheel = {m["id"]: m for m in res["mixes"]}["wheel"]["storages"]
    assert wheel["W25Q128JV NOR"]["full_rate_s"] > 75 * 60          # B7 at full rate on the NOR
    assert wheel["internal flash bank 2"]["total_s"] > 75 * 60      # and still in the log on internal flash


def test_full_storage_refuses_blocks_and_counts_them(telematics_build, tmp_path):
    script, img, _e, _s = _script(tmp_path, duration=15.0, slots=8)
    # 8 slots, 1 in reserve: sparse logging after 6 blocks; the last slot fills (about 260 s), then storage drops
    script = script.replace("P 15000000\nF", "P 15000000\nP 400000000\nF")
    out = _run(telematics_build, script)
    m = re.search(r"slots=(\d+)/(\d+)", out)
    assert m and m.group(1) == m.group(2) == "8"
    sessions, _rep = telematics_import.split(img.read_bytes())
    p = telematics_import.write_session(sessions[0], tmp_path, {})
    _meta, recs, _rr = stlg.read(p)
    # the log holds 8 slots (header + 7 blocks), all readable; what did not fit is counted on the unit (the
    # counters that would say so cannot be in a full log: the status line and the live summary report them)
    assert len(sessions[0]["blocks"]) == 7 and _rr.blocks_corrupt == 0
    assert int(re.search(r"drop_st=(\d+)", out).group(1)) > 0 and int(re.search(r"thin=(\d+)", out).group(1)) > 0
    assert any(f.get("code") == 2 for _b, _i, _t, rt, f in recs if rt == stlg.EVENT)


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


def test_gnss_and_pps_through_the_firmware_give_gnss_records_and_utc(telematics_build, tmp_path):
    """UBX-NAV-PVT bytes and PPS edges into the firmware's GNSS driver (tm_gnss.c) in the host simulator, then the
    pit import: GNSS speed, accuracy and satellites as logged, the PPS edges labelled with their UTC second, the
    unit's clock mapped to UTC, and the GNSS counters. A fix outage from 12 s to 14 s: no PPS, speed invalid."""
    utc0 = 1_792_141_200.25                  # UTC at host-simulator time 0 (clocks.py PpsModel)
    img = tmp_path / "flash.bin"
    ev, expect_utc = [], []
    for k in range(10, 211):                 # 1.0 s to 21.0 s of UTC epochs at 10 Hz
        e_utc = round(math.floor(utc0) + 1 + k / 10, 1)        # solution epochs on tenths of a UTC second
        t_local = e_utc - utc0
        out = 12.0 <= t_local < 14.0
        sec = int(math.floor(e_utc))
        nano = int(round((e_utc - sec) * 1e9))
        msg = ubx.nav_pvt(sec, nano, 0x00 if out else 0x07, 0 if out else 3, 0 if out else 0x01, 3 if out else 14,
                       int(round(6.0 * 1000)), 2000 if out else 150)
        ev.append((int(round((t_local + 0.06) * 1e6)), f"G {int(round((t_local + 0.06) * 1e6))} {msg.hex()}"))
        if nano == 0 and not out:
            ev.append((int(round(t_local * 1e6)), f"U {int(round(t_local * 1e6))}"))
            expect_utc.append((int(round(t_local * 1e6)), sec))
    lines = [f"I 64 1500 8 {img}"] + [x for _t, x in sorted(ev)] + [f"P {int(23e6)}", "F", "W"]
    _run(telematics_build, "\n".join(lines) + "\n")
    db_path = tmp_path / "pit.sqlite"
    res = telematics_import.run(img.read_bytes(), db_path, tmp_path / "imp", {}, plots=False)
    (s,) = res["sessions"]
    i = s["import"]
    assert i["accounting"]["missing_from_file"] == 0 and i["blocks_corrupt"] == 0
    (tmp_path / "w").mkdir()
    p = telematics_import.write_session(telematics_import.split(img.read_bytes())[0][0], tmp_path / "w", {})
    _meta, recs, _rr = stlg.read(p)
    pps = [(t, f["utc_s"]) for _b, _i, t, rt, f in recs if rt == stlg.PPS]
    assert sorted(pps) == expect_utc and len(pps) >= 18            # every edge, with the second it marks
    gnss = [f for _b, _i, _t, rt, f in recs if rt == stlg.GNSS]
    assert len(gnss) == 201 and sum(not f["fix"] for f in gnss) == 20
    assert all(abs(f["speed_mps"] - 6.0) < 1e-6 and abs(f["sacc_mps"] - 0.15) < 1e-6 and f["num_sv"] == 14
               for f in gnss if f["fix"])
    db = ingest.connect(db_path)
    rows = db.execute("SELECT t_rx_us, value, validity, utc, utc_q FROM measurements WHERE run_id=? AND "
                      "signal='gnss.speed' ORDER BY t_rx_us", (s["run_id"],)).fetchall()
    assert len(rows) == 201 and sum(r[2] == "valid" for r in rows) == 181
    inside = [r for r in rows if r[4] == "pps"]
    assert len(inside) > 150
    for t_us, _v, _val, utc, _q in inside:                         # the receive time on the UTC scale
        assert abs(utc - (utc0 + t_us / 1e6)) < 1e-5
    cnt = {k: v for k, v in db.execute("SELECT name, value FROM signals WHERE run_id=? AND name LIKE 'cnt_%' "
                                       "ORDER BY t_local_us", (s["run_id"],)).fetchall()}
    assert cnt["cnt_gnss_frames"] == 201 and cnt["cnt_gnss_checksum_errors"] == 0
    assert cnt["cnt_pps_edges"] == len(expect_utc) and cnt["cnt_pps_unlabelled"] == 0


def test_firmware_in_the_loop_vehicle_drive_through_the_pit(telematics_build, tmp_path):
    """tools/run_firmware_vehicle_sim.py on a 30 s drive with a GNSS outage from 12 s to 16 s and a live-link
    outage from 10 s to 28 s: the simulated vehicle drives the firmware's tm_app, tm_gnss and tm_live, the log goes
    through import, evidence review and the shadow replay, the live messages through the pit's validation. Every
    record accounted for, GNSS speed as simulated, UTC from the firmware's PPS records exact, no PPS edge left
    unlabelled, the outage attributed to GNSS by B1, every live sequence number accounted for. SIMULATED."""
    from tools import run_firmware_vehicle_sim as fwsim
    s = fwsim.run(tmp_path / "out", 30.0, Faults(gnss_outage=((12.0, 16.0),)), telematics_build,
                  link_outage=((10.0, 28.0),))
    acc = s["accounting"]
    assert s["import"]["blocks_corrupt"] == 0 and s["import"]["block_seq_gaps"] == 0
    assert acc["missing_from_file"] == 0 and acc["dropped_queue"] == 0 and acc["dropped_storage"] == 0
    g = s["gnss"]
    assert g["records"] == 300 and g["valid"] == 260                # 10 Hz, 4 s without a fix
    assert g["speed_rms_error_mps"] < 0.1 and g["utc_max_error_s"] < 1e-5 and g["utc_pps_share"] > 0.75
    c = s["firmware_counters"]
    assert c["gnss_checksum_errors"] == 0 and c["pps_unlabelled"] == 0
    # the counters record is periodic: the last one may precede the last edge
    assert s["inputs"]["pps_edges"] - 1 <= c["pps_edges"] <= s["inputs"]["pps_edges"]
    assert "0 ambiguous" in s["evidence_review"]
    rep = s["replay"]
    assert rep["returncode"] == 0 and rep["episodes"]["R3v"] == []
    (b1,) = rep["episodes"]["B1"]
    assert b1["suspects"] == ["gnss"] and 12.0 <= b1["start_s"] <= 13.0 and 16.0 <= b1["end_s"] <= 17.0
    # the firmware's live summary: an 18 s link outage holds 30 messages and drops the 6 oldest, counted; every
    # message passes the pit's validation; every live value equals the pit's import of the log at that time
    lv = s["live"]
    assert lv["outcomes"] == {"stored": lv["messages"]} and lv["seq_last"] == 59 and lv["accounted"]
    assert lv["uplink_dropped"] == 6 and lv["replayed"] == 30 and lv["uplink_queue_high_water"] == 30
    assert lv["value_mismatches"] == 0 and lv["values_compared"] > 500
    assert lv["utc_q"].get("holdover", 0) > 0 and lv["utc_q"].get("pps", 0) > 40
