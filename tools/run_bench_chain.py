#!/usr/bin/env python3
"""The pulse-to-database chain of the telematics unit, end to end, with a known pulse train as ground truth.

    python3 tools/run_bench_chain.py --out build/bench_chain [--build build-telematics]          # host
    python3 tools/run_bench_chain.py --dump dump.bin --pulse-hz 40 [--pulses 400] --out build/bench_chain_b1
    python3 tools/run_bench_chain.py --uart-capture capture.txt --pulse-hz 40 --out build/bench_chain_b1
    python3 tools/run_bench_chain.py --rehearse-minimal --out build/minimal_rehearsal        # SIMULATED rehearsal

    pulse -> capture and timestamp -> WHEEL_EDGES record -> log storage -> dump -> host decoder (STLG)
          -> measurement and evidence state -> pit database row (raw record kept) -> query (tools/pit_query.py)
          -> shadow evidence review -> receipts (host/assurance) -> speed and distance plot

Host mode (the default) drives the firmware's own portable code in the host simulator (tm_hostsim, built from
telematics/firmware) with a scripted pulse train on wheel_0: 40 Hz for 5 s, no pulse for 3 s, 80 Hz for 5 s. The
result is SIMULATED: it shows the chain's software is consistent, not that the board captures pulses.

Bench mode reads a log taken from the NUCLEO-U575ZI-Q after a signal generator drove wheel_0 at `--pulse-hz`
(telematics/firmware/BENCH.md, B1 to B3 and B11); with `--pulses` (a generator burst of N pulses) the edge count and
distance are checked exactly too. The result is BENCH only if the log says it came from the board (its `kind`) and the
operator ran the generator as stated: the tool checks the log, not the bench. `--boot N` picks the session of boot N
(default: the last one), for a log read back after a power cycle.

`--rehearse-minimal` runs the minimal bench procedure (telematics/bench/bench.yaml, section minimal) on the host
simulator: 5 s without input, 100 Hz for 60 s, 10 s without input, a power cycle, 5 s; the flash image is printed as
the console's DUMP text (OUT/capture_M3_SIMULATED.txt) and that capture goes through the bench path with the
procedure's own arguments. The result is SIMULATED (the log's kind says so): it shows what the minimal bench's output
looks like, not that the board produces it.

Checks (each PASS or FAIL, kept in OUT/chain.json and OUT/chain.md):
  C1 every pulse is in the log (edge total of the last record = pulses sent)          [host, or bench with --pulses]
  C2 speed while pulsing is VALID and equals f x pitch                                 (pitch = circumference / ppr)
  C3 with no pulse the speed is never 0 and never VALID: UNKNOWN with an upper bound   [host: in the pause; bench:
                                                                                         every sample without edges]
  C4 distance = pulses x pitch                                                          [host, or bench with --pulses]
     distance = the log's own edge total x pitch                                        [bench without --pulses]
  C5 every measurement has its evidence row with the raw record and the schema version
  C6 the query tool shows the same states the evidence rows hold
  C7 the data class comes from the log's own kind (SIMULATED or BENCH, never assumed)
  C8 the shadow evidence review stored receipts for the run, each one complete (verdicts.receipt_problems), none
     claiming an established cause, all advisory, with the timing policy of the data class
  C9 the speed and distance plot was written from the database
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import shutil
import statistics
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.assurance import review, verdicts  # noqa: E402
from host.pit import ingest, queries  # noqa: E402
from tools import pit_query, telematics_import  # noqa: E402

CIRC_M, PPR = 1.5, 8
SEGMENTS = ((1.0, 6.0, 40.0), (6.0, 9.0, 0.0), (9.0, 14.0, 80.0))     # (from s, to s, pulse rate Hz) on wheel_0
END_S = 16.0
# the minimal bench procedure (bench.yaml, minimal): fixture 0.1 m per edge, one edge per revolution, 100 Hz for 60 s
# after 5 s without input, 10 s without input, a power cycle, 5 s on the next boot; 256 slots as internal flash bank 2
MINIMAL = {"circumference": 0.1, "ppr": 1, "pulse_hz": 100.0, "slots": 256,
           "segments": ((5.0, 65.0, 100.0), (65.0, 75.0, 0.0)), "restart_s": 75.0, "end_s": 80.0}


def host_script(img: pathlib.Path, segments=SEGMENTS, end_s: float = END_S, circ_m: float = CIRC_M, ppr: int = PPR,
                slots: int = 64, restart_s: float | None = None) -> tuple[str, int]:
    """tm_hostsim script: the pulse train of `segments` on channel 0, line held high between pulses (an open-collector
    sensor pulled up; each pulse pulls it low for 100 us); with `restart_s`, a power cycle then (RAM lost, flash
    kept)."""
    lines, n = [f"I {slots} {int(round(circ_m * 1000))} {ppr} {img} internal"], 0
    for a, b, f in segments:
        if f <= 0:
            continue
        k = 0
        while True:
            t = int(round((a + k / f) * 1e6))
            if t >= b * 1e6:
                break
            lines += [f"L {t} 0 0", f"E {t} 0", f"L {t + 100} 0 1"]
            n += 1
            k += 1
    if restart_s is not None:
        lines += [f"R {int(restart_s * 1e6)} BOR"]
    lines += [f"P {int(end_s * 1e6)}", "F", "W", "Q"]
    return "\n".join(lines) + "\n", n


def uart_dump(image: bytes, slot_bytes: int = telematics_import.SLOT) -> str:
    """The console text of the firmware's DUMP command for this flash image: every used slot (not all 0xFF)."""
    slots = len(image) // slot_bytes
    used = [k for k in range(slots) if image[k * slot_bytes:(k + 1) * slot_bytes].strip(b"\xff")]
    return "\n".join([f"DUMP BEGIN {slots}"] + [f"S {k} {image[k * slot_bytes:(k + 1) * slot_bytes].hex()}"
                                                for k in used] + ["DUMP END", ""])


def _hostsim(build: pathlib.Path, script: str) -> None:
    exe = build / "tm_hostsim"
    if not exe.exists():
        subprocess.run(["cmake", "-S", str(ROOT / "telematics" / "firmware"), "-B", str(build)], check=True)
        subprocess.run(["cmake", "--build", str(build)], check=True)
    r = subprocess.run([str(exe)], input=script, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit(f"tm_hostsim failed: {r.stderr}")


def _check(cid: str, ok: bool, detail: str) -> dict:
    return {"id": cid, "pass": bool(ok), "detail": detail}


def stop_check(ser: list[tuple]) -> dict:
    """C3 on a bench log, whose operator timing is not in the log: every sample without edges is checked. Before the
    first edge there is no bound (nothing has been measured); after it, the time since the last edge bounds the speed.
    `ser` holds (t_us, value, validity, upper) of wheel_0's speed in time order."""
    first = next((t for t, _v, val, _u in ser if val == "valid"), None)
    silent = [(t, v, up) for t, v, val, up in ser if val == "no_evidence"]
    after = [(v, up) for t, v, up in silent if first is not None and t > first]
    zeros = sum(1 for _t, v, _val, _u in ser if v == 0)
    return _check("C3 no pulse: never 0, never VALID, UNKNOWN with a bound", bool(after) and not zeros and all(
        v is None for _t, v, _up in silent) and all(up is not None and up > 0 for _v, up in after),
        f"{len(silent)} samples without edges ({len(silent) - len(after)} before the first edge, unbounded; "
        f"{len(after)} after it, each with an upper bound), {zeros} speeds of 0" +
        ("" if after else "; the log holds no interval without pulses after pulses (run the procedure's stop)"))


def analyse(db, run_id: str, pitch: float, pulses: int | None, segments, pulse_hz: float | None) -> list[dict]:
    out = []
    sig = "wheel.wheel_0.speed"
    ser = [(t, v, val, up) for t, v, val, up in db.execute(
        "SELECT COALESCE(t_sample_us, t_rx_us), value, validity, upper FROM measurements WHERE run_id=? AND signal=? "
        "ORDER BY 1", (run_id, sig))]
    last = db.execute("SELECT raw FROM raw_records r JOIN records c USING (run_id, block, idx) WHERE c.run_id=? AND "
                      "c.rtype=9 ORDER BY c.t_local_us DESC", (run_id,)).fetchall()
    totals = [json.loads(r[0]) for r in last]
    total0 = max((x["total"] for x in totals if x.get("channel") == 0), default=None)
    if pulses is not None:
        out.append(_check("C1 every pulse is in the log", total0 == pulses, f"edge total {total0}, pulses {pulses}"))
    t_boot = db.execute("SELECT MIN(t_local_us) FROM records WHERE run_id=? AND rtype=12", (run_id,)).fetchone()[0] or 0
    for a, b, f in segments:
        if f <= 0:
            continue
        lo, hi = t_boot + int((a + 0.5) * 1e6), t_boot + int(b * 1e6)
        vs = [(v, val) for t, v, val, _u in ser if lo <= t <= hi]
        good = [v for v, val in vs if val == "valid"]
        want = f * pitch
        err = max((abs(v - want) / want for v in good), default=None)
        out.append(_check(f"C2 speed at {f:g} Hz is VALID and f x pitch", bool(good) and len(good) == len(vs) and
                          err is not None and err < 1e-3,
                          f"{len(good)}/{len(vs)} VALID samples, expected {want:.4f} m/s, worst relative error "
                          f"{'-' if err is None else f'{err:.2e}'}"))
    for a, b, f in segments:
        if f > 0:
            continue
        lo, hi = t_boot + int((a + 0.5) * 1e6), t_boot + int(b * 1e6)
        vs = [(v, val, up) for t, v, val, up in ser if lo <= t <= hi]
        out.append(_check("C3 no pulse: never 0, never VALID, UNKNOWN with a bound", bool(vs) and all(
            v is None and val == "no_evidence" and up is not None and up > 0 for v, val, up in vs),
            f"{len(vs)} samples, validities {sorted({val for _v, val, _u in vs})}, values "
            f"{sorted({v for v, _val, _u in vs}, key=str)}"))
    if not segments:
        out.append(stop_check(ser))
    d = db.execute("SELECT value FROM measurements WHERE run_id=? AND signal='wheel.wheel_0.distance' ORDER BY "
                   "t_rx_us DESC LIMIT 1", (run_id,)).fetchone()
    if pulses is not None:
        out.append(_check("C4 distance = pulses x pitch", d is not None and abs(d[0] - pulses * pitch) < 1e-9,
                          f"distance {d[0] if d else None} m, expected {pulses * pitch} m"))
    elif total0 is not None:
        out.append(_check("C4 distance = the log's edge total x pitch", d is not None and
                          abs(d[0] - total0 * pitch) < 1e-6 * max(1.0, total0 * pitch),
                          f"distance {d[0] if d else None} m, edge total {total0} x {pitch} m"))
    n_m = db.execute("SELECT COUNT(*) FROM measurements WHERE run_id=?", (run_id,)).fetchone()[0]
    n_e = db.execute("SELECT COUNT(*) FROM evidence_records WHERE run_id=? AND raw IS NOT NULL AND schema_version=1",
                     (run_id,)).fetchone()[0]
    out.append(_check("C5 one evidence row with the raw record per measurement", n_m == n_e > 0,
                      f"{n_m} measurements, {n_e} evidence rows with raw record"))
    rows = queries.aligned(db, run_id, [sig], step_s=0.5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pit_query.main(["--db", str(db_path_of(db)), "aligned", "--run", run_id, "--signal", sig, "--step", "0.5"])
    printed = [ln.split("\t")[1] for ln in buf.getvalue().splitlines()[1:] if not ln.startswith("#")]
    states = [r[sig]["state"] for r in rows]
    same = len(printed) == len(states) and all((p == s) or (s == "VALID" and p[0].isdigit())
                                               for p, s in zip(printed, states))
    out.append(_check("C6 the query tool shows the evidence states", same and "VALID" in states,
                      f"{len(states)} rows; states seen {sorted(set(states))}"))
    meta = json.loads(db.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
    dc = review.data_class(meta)
    out.append(_check("C7 data class from the log's own kind", dc in ("SIMULATED", "BENCH"),
                      f"kind '{meta.get('kind')}' -> {dc}"))
    if pulse_hz:
        good = [v for _t, v, val, _u in ser if val == "valid"]
        med = statistics.median(good) if good else None
        out.append(_check("C2 median VALID speed equals the generator rate x pitch", med is not None and
                          abs(med - pulse_hz * pitch) / (pulse_hz * pitch) < 2e-3,
                          f"median {med} m/s, expected {pulse_hz * pitch:.4f} m/s (generator {pulse_hz} Hz)"))
    return out


def db_path_of(db) -> str:
    return db.execute("PRAGMA database_list").fetchone()[2]


def review_check(db, run_id: str, dc: str) -> tuple[dict, dict]:
    """C8: run the shadow evidence review on the stored run and check every receipt it stored."""
    res = review.run(db, run_id)
    snaps = [json.loads(r[0]) for r in db.execute("SELECT snapshot_json FROM receipt_snapshots WHERE run_id=?",
                                                   (run_id,))]
    n_rc = db.execute("SELECT COUNT(*) FROM receipts WHERE run_id=?", (run_id,)).fetchone()[0]
    problems = [p for rc in snaps for p in verdicts.receipt_problems(rc)]
    concl = [c for rc in snaps for c in rc.get("conclusions", [])]
    established = sum(1 for c in concl if c.get("level") == "established")
    advisory = all(rc.get("advisory_only") is True for rc in snaps)
    verdict_counts = (res.get("counts") or {}).get("verdicts", {})
    ok = (n_rc > 0 and bool(snaps) and not problems and not established and advisory and res.get("data_class") == dc)
    return _check("C8 shadow review: receipts stored, complete, advisory, nothing established", ok,
                  f"{n_rc} receipts, {len(snaps)} snapshots, {len(problems)} receipt problems"
                  f"{' (' + problems[0] + ')' if problems else ''}, {established} established, verdicts "
                  f"{dict(sorted(verdict_counts.items()))}, data class {res.get('data_class')}, "
                  f"{res.get('timing_policy')}"), {
        "receipts": n_rc, "snapshots": len(snaps), "problems": problems, "verdicts": verdict_counts,
        "timing_policy": res.get("timing_policy"), "common_cause": res.get("common_cause")}


def render(res: dict) -> str:
    L = [f"# Pulse-to-database chain ({res['data_class']})", "", res["note"], "",
         "| Check | Result | Detail |", "|---|---|---|"]
    L += [f"| {c['id']} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |" for c in res["checks"]]
    L += ["", f"Run `{res['run_id']}` (boot {res['boot']}); database `{res['db']}`. Inspect it with "
          f"`python3 tools/pit_query.py --db {res['db']} aligned --run {res['run_id']} --signal wheel.wheel_0.speed`.",
          ""]
    if res.get("plot"):
        L += [f"Speed and distance plot: `{res['plot']}`.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "bench_chain")
    ap.add_argument("--build", type=pathlib.Path, default=ROOT / "build-telematics", help="host build with tm_hostsim")
    ap.add_argument("--dump", type=pathlib.Path, help="bench: binary dump of the board's log region")
    ap.add_argument("--uart-capture", type=pathlib.Path, help="bench: capture of the UART DUMP command")
    ap.add_argument("--rehearse-minimal", action="store_true",
                    help="the minimal bench procedure on the host simulator, through the bench path (SIMULATED)")
    ap.add_argument("--pulse-hz", type=float, help="bench: the generator's rate on wheel_0")
    ap.add_argument("--pulses", type=int, help="bench: a burst of exactly this many pulses (checks count and distance)")
    ap.add_argument("--circumference", type=float, default=CIRC_M, help="m, as set for the import (bench fixture)")
    ap.add_argument("--ppr", type=int, default=PPR)
    ap.add_argument("--boot", type=int, help="the session of this boot number (default: the last session)")
    a = ap.parse_args(argv)
    if a.out.exists():
        shutil.rmtree(a.out)
    a.out.mkdir(parents=True)
    if a.rehearse_minimal:
        m = MINIMAL
        script, n = host_script(a.out / "flash.bin", m["segments"], m["end_s"], m["circumference"], m["ppr"],
                                m["slots"], m["restart_s"])
        _hostsim(a.build, script)
        a.uart_capture = a.out / "capture_M3_SIMULATED.txt"
        a.uart_capture.write_text(uart_dump((a.out / "flash.bin").read_bytes()))
        # exactly the bench's chain command (bench.yaml minimal.chain): no --pulses, the operator cannot count them
        a.pulse_hz, a.circumference, a.ppr, a.boot, a.pulses = m["pulse_hz"], m["circumference"], m["ppr"], 1, None
    pitch = a.circumference / a.ppr
    if a.dump or a.uart_capture:
        if not a.pulse_hz:
            ap.error("bench mode needs --pulse-hz (the generator's rate)")
        image = a.dump.read_bytes() if a.dump else telematics_import.from_uart(a.uart_capture.read_text())
        segments, pulses = (), a.pulses
        note = (f"Bench log; generator {a.pulse_hz} Hz on wheel_0 as stated by the operator; circumference "
                f"{a.circumference} m and {a.ppr} pulses per revolution set at import (bench fixture values).")
        if a.rehearse_minimal:
            note = (f"REHEARSAL, HOST SIMULATION: the minimal bench procedure ({n} pulses at 100 Hz on wheel_0 over "
                    "60 s, a stop, a power cycle) run on tm_hostsim, its flash printed as the console's DUMP text and "
                    "read back with the bench's own chain command. Not the board: interrupt, timer and flash "
                    "behaviour are not exercised.")
    else:
        img = a.out / "flash.bin"
        script, pulses = host_script(img)
        _hostsim(a.build, script)
        image = img.read_bytes()
        segments = SEGMENTS
        note = ("HOST SIMULATION: the firmware's portable code in tm_hostsim, scripted pulses on wheel_0 (40 Hz, "
                "none, 80 Hz). Not the board: interrupt and timer behaviour are not exercised.")
    dbp = a.out / "pit.sqlite"
    imp = telematics_import.run(image, dbp, a.out / "import",
                                {"wheel_circumference_m": a.circumference, "wheel_ppr": a.ppr,
                                 "source": "run_bench_chain (fixture values)"}, plots=True)
    if not imp["sessions"]:
        print("no session in the log")
        return 1
    if a.boot is None:
        sess = imp["sessions"][-1]
    else:
        found = [x for x in imp["sessions"] if x.get("boot") == a.boot]
        if not found:
            print(f"no session of boot {a.boot} in the log (boots: {[x.get('boot') for x in imp['sessions']]})")
            return 1
        sess = found[-1]
    run_id = sess["run_id"]
    db = ingest.connect(dbp)
    checks = analyse(db, run_id, pitch, pulses, segments, a.pulse_hz if (a.dump or a.uart_capture) else None)
    meta = json.loads(db.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
    dc = review.data_class(meta)
    c8, rv = review_check(db, run_id, dc)
    checks.append(c8)
    plot = sess.get("plot")
    checks.append(_check("C9 speed and distance plot written from the database", bool(plot) and
                         (a.out / "import" / plot).exists(), f"{'import/' + plot if plot else 'no plot'}"))
    res = {"run_id": run_id, "boot": sess.get("boot"), "sessions": [x["run_id"] for x in imp["sessions"]],
           "db": str(dbp), "data_class": dc, "note": note, "checks": checks,
           "pass": all(c["pass"] for c in checks), "pulses": pulses, "pitch_m": pitch, "review": rv,
           "plot": f"import/{plot}" if plot else None}
    (a.out / "chain.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    (a.out / "chain.md").write_text(render(res))
    for c in checks:
        print(f"{'PASS' if c['pass'] else 'FAIL'} {c['id']}: {c['detail']}")
    print(f"BENCH CHAIN {run_id} ({res['data_class']}): {'PASS' if res['pass'] else 'FAIL'}")
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
