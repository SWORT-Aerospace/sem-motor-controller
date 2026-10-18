#!/usr/bin/env python3
"""Import the telematics unit's persistent log (a flash dump or a UART dump) into the pit database.

    python3 tools/telematics_import.py dump.bin --db pit.sqlite --out build/bench_import \
        [--wheel-circumference 1.50 --wheel-ppr 8] [--uart-capture capture.txt]
    python3 tools/telematics_import.py --status-capture capture.txt --out build/bench_status   # console only

The firmware (telematics/firmware) writes its log as 4 KiB slots in a region of storage: a session (one
boot) is a header slot ("STLG" + run metadata) followed by block slots ("BK"); unwritten slots read 0xFF.
A dump of that region is read with the board's ST-LINK (telematics/firmware/BENCH.md gives the commands for
STM32CubeProgrammer and OpenOCD) or captured from the UART "DUMP" command.

This tool:
  1. splits the dump into sessions and writes each as a standard STLG file (OUT/<run_id>.stlg), counting
     empty, corrupt and orphan slots (a block before any header);
  2. adds wheel circumference and pulses per revolution to the metadata when given (the firmware does not
     know them; recorded under `import_overrides`, with the values' source as stated on the command line);
  3. imports each session with host/pit/ingest.py (idempotent: a second import adds nothing);
  4. writes OUT/import.json and, per session, OUT/<run_id>_speed_distance.png: wheel speed from edge
     timing and distance per channel.

`--status-capture` reads the status lines ("TM t=... tov=... edges=...") of a console capture instead: evidence
that does not depend on the log storage (bench step B7). It writes OUT/status.csv and OUT/status.json with
the time continuity, every change of the timer overflow count with the slot then being filled (the DUMP range
to read back around it), and the edge rate on each side of it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import struct
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.pit import energy, ingest  # noqa: E402
from host.telematics import stlg  # noqa: E402

SLOT = 4096


def split(image: bytes) -> tuple[list[dict], dict]:
    """[{meta, header, blocks: [bytes]}], report."""
    sessions, rep = [], {"slots": len(image) // SLOT, "empty": 0, "header": 0, "block": 0, "corrupt_header": 0,
                         "orphan_block": 0, "unknown": 0, "bad_length": 0}
    cur = None
    for k in range(len(image) // SLOT):
        s = image[k * SLOT:(k + 1) * SLOT]
        if s[:16] == b"\xff" * 16:
            rep["empty"] += 1
            continue
        if s[:4] == stlg.MAGIC:
            ver, mlen = struct.unpack_from("<HI", s, 4)
            m = s[10:10 + mlen]
            ok = ver == stlg.VERSION and 14 + mlen <= SLOT and struct.unpack_from("<I", s, 10 + mlen)[0] == zlib.crc32(m)
            if not ok:
                rep["corrupt_header"] += 1
                cur = None
                continue
            rep["header"] += 1
            cur = {"meta": json.loads(m), "slot": k, "blocks": []}
            sessions.append(cur)
        elif s[:2] == b"BK":
            n = struct.unpack_from("<H", s, 14)[0]
            if 20 + n > SLOT:
                rep["bad_length"] += 1
                continue
            if cur is None:
                rep["orphan_block"] += 1
                continue
            rep["block"] += 1
            cur["blocks"].append(s[:20 + n])        # CRC is checked by the STLG reader, which counts failures
        else:
            rep["unknown"] += 1
    return sessions, rep


def write_session(sess: dict, out: pathlib.Path, overrides: dict) -> pathlib.Path:
    meta = dict(sess["meta"])
    if overrides:
        sens = dict(meta.get("sensors") or {})
        sens.update({k: v for k, v in overrides.items() if k != "source"})
        meta["sensors"] = sens
        meta["import_overrides"] = overrides
    m = json.dumps(meta, sort_keys=True).encode()
    p = out / f"{meta['run_id']}.stlg"
    p.write_bytes(stlg.MAGIC + struct.pack("<HI", stlg.VERSION, len(m)) + m + struct.pack("<I", zlib.crc32(m))
                  + b"".join(sess["blocks"]))
    return p


def from_uart(text: str) -> bytes:
    """The firmware's DUMP output: lines 'S <slot> <8192 hex digits>' between 'DUMP BEGIN <slots>' and
    'DUMP END'. Slots it did not print are empty."""
    slots, data = None, {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[:2] == ["DUMP", "BEGIN"]:
            slots = int(parts[2])
        elif len(parts) == 3 and parts[0] == "S":
            data[int(parts[1])] = bytes.fromhex(parts[2])
    if slots is None:
        raise ValueError("no 'DUMP BEGIN' line in the capture")
    return b"".join(data.get(k, b"\xff" * SLOT) for k in range(slots))


STATUS = re.compile(r"TM t=(\d+)\.(\d{3}) s tov=(\d+) boot=(\d+) edges=(\d+)/(\d+)/(\d+) wheel=([NMSAI]{3}).*?"
                    r"slots=(\d+)/(\d+) log=(\w+) left=(\S+)s thin=(\d+)")


def status_lines(text: str) -> list[dict]:
    """The firmware's status lines in a console capture, in order (other lines ignored)."""
    out = []
    for m in STATUS.finditer(text):
        g = m.groups()
        out.append({"t_s": int(g[0]) + int(g[1]) / 1000.0, "tov": int(g[2]), "boot": int(g[3]),
                    "edges": [int(g[4]), int(g[5]), int(g[6])], "wheel": g[7], "slots": int(g[8]),
                    "slots_total": int(g[9]), "log": g[10], "left_s": None if g[11] == "?" else int(g[11]),
                    "thinned": int(g[12])})
    return out


def overflow_check(rows: list[dict], channel: int = 0, rate_tol: float = 0.002) -> dict:
    """Time continuity and the edge rate around each change of the timer overflow count (B7)."""
    rows = [r for r in rows if r["boot"] == rows[-1]["boot"]] if rows else []
    dts = [b["t_s"] - a["t_s"] for a, b in zip(rows, rows[1:])]
    rates = [(b["edges"][channel] - a["edges"][channel]) / (b["t_s"] - a["t_s"])
             for a, b in zip(rows, rows[1:]) if b["t_s"] > a["t_s"]]
    med = sorted(rates)[len(rates) // 2] if rates else None
    changes = []
    for k, (a, b) in enumerate(zip(rows, rows[1:])):
        if b["tov"] != a["tov"]:
            around = [r for r in rates[max(0, k - 5):k + 6]]
            changes.append({"t_s": b["t_s"], "tov": [a["tov"], b["tov"]], "slot": b["slots"],
                            "rate_around": [round(x, 3) for x in around],
                            "steady": bool(med) and all(abs(x - med) <= rate_tol * med for x in around)})
    return {"lines": len(rows), "t_first_s": rows[0]["t_s"] if rows else None, "t_last_s": rows[-1]["t_s"] if rows else None,
            "dt_min_s": round(min(dts), 3) if dts else None, "dt_max_s": round(max(dts), 3) if dts else None,
            "time_monotonic": all(d > 0 for d in dts), "median_rate_hz": round(med, 3) if med else None,
            "tov_changes": changes,
            "pass": bool(rows) and all(d > 0 for d in dts) and max(dts, default=0) < 2.5 and bool(changes)
                    and all(c["steady"] for c in changes)}


def plot(db, run_id: str, out: pathlib.Path) -> str | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    meta = json.loads(db.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()[0])
    chans = [v for _k, v in sorted((meta.get("sensors") or {}).get("wheel_channels", {}).items())]
    fig, ax = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
    t0 = None
    any_data = False
    for ch in chans:
        sp = energy.series(db, run_id, f"wheel.{ch}.speed")
        ds = energy.series(db, run_id, f"wheel.{ch}.distance", usable_only=False)
        if not sp and not ds:
            continue
        any_data = True
        t0 = t0 if t0 is not None else min(r[0] for r in (sp or ds))
        ax[0].plot([(r[0] - t0) / 1e6 for r in sp], [r[1] for r in sp], ".", ms=2, label=ch)
        ax[1].plot([(r[0] - t0) / 1e6 for r in ds], [r[1] for r in ds], lw=1, label=ch)
    if not any_data:
        plt.close(fig)
        return None
    ax[0].set_ylabel("speed [m/s]")
    ax[1].set_ylabel("distance [m]")
    ax[1].set_xlabel("time since the first sample [s] (telematics clock)")
    ax[0].legend(fontsize=7)
    fig.suptitle(f"{run_id}: wheel speed from edge timing and distance")
    name = f"{run_id}_speed_distance.png"
    fig.savefig(out / name, dpi=110)
    plt.close(fig)
    return name


def run(image: bytes, db_path: pathlib.Path, out: pathlib.Path, overrides: dict, plots: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sessions, rep = split(image)
    db = ingest.connect(db_path)
    res = {"slots": rep, "sessions": []}
    for s in sessions:
        p = write_session(s, out, overrides)
        imp = ingest.import_log(db, p)
        run_id = s["meta"]["run_id"]
        sess = {"run_id": run_id, "file": p.name, "header_slot": s["slot"], "blocks": len(s["blocks"]),
                "boot": s["meta"].get("boot"), "reset": s["meta"].get("reset"), "import": imp,
                "distance": {}, "plot": None}
        for _k, ch in sorted((s["meta"].get("sensors") or {}).get("wheel_channels", {}).items()):
            sess["distance"][ch] = energy.wheel_distance(db, run_id, ch)
        if plots:
            sess["plot"] = plot(db, run_id, out)
        res["sessions"].append(sess)
    (out / "import.json").write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    db.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dump", type=pathlib.Path, nargs="?", help="binary dump of the log region")
    ap.add_argument("--uart-capture", type=pathlib.Path, help="text capture of the UART DUMP command instead")
    ap.add_argument("--status-capture", type=pathlib.Path, help="console capture: check the status lines only (B7)")
    ap.add_argument("--db", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "telematics_import")
    ap.add_argument("--wheel-circumference", type=float, help="m (vehicle or bench fixture value)")
    ap.add_argument("--wheel-ppr", type=int, help="edges counted per revolution")
    ap.add_argument("--wheel-active-high", action="store_true", help="sensor output high when a magnet is near")
    ap.add_argument("--source", default="command line", help="where the wheel values come from (recorded)")
    ap.add_argument("--no-plots", action="store_true")
    a = ap.parse_args()
    if a.status_capture:
        rows = status_lines(a.status_capture.read_text(errors="replace"))
        a.out.mkdir(parents=True, exist_ok=True)
        with open(a.out / "status.csv", "w") as f:
            f.write("t_s,tov,boot,edges_0,edges_1,edges_2,wheel,slots,log,left_s,thinned\n")
            for r in rows:
                f.write(f"{r['t_s']:.3f},{r['tov']},{r['boot']},{','.join(map(str, r['edges']))},{r['wheel']},"
                        f"{r['slots']},{r['log']},{'' if r['left_s'] is None else r['left_s']},{r['thinned']}\n")
        chk = overflow_check(rows)
        (a.out / "status.json").write_text(json.dumps(chk, indent=2) + "\n")
        print(f"STATUS {chk['lines']} lines, t {chk['t_first_s']} to {chk['t_last_s']} s, step {chk['dt_min_s']} to "
              f"{chk['dt_max_s']} s, median edge rate {chk['median_rate_hz']} Hz; overflow count changes: "
              + (", ".join(f"{c['tov'][0]}->{c['tov'][1]} at {c['t_s']} s, slot {c['slot']} "
                           f"({'steady' if c['steady'] else 'NOT steady'}; DUMP {max(0, c['slot'] - 15)} {c['slot'] + 15})"
                           for c in chk["tov_changes"]) or "none") + f"; {'PASS' if chk['pass'] else 'FAIL'}")
        return 0 if chk["pass"] else 1
    if a.db is None:
        ap.error("--db is required to import a log")
    if a.uart_capture:
        image = from_uart(a.uart_capture.read_text())
    elif a.dump:
        image = a.dump.read_bytes()
    else:
        ap.error("a dump file or --uart-capture")
    ov = {}
    if a.wheel_circumference is not None:
        ov["wheel_circumference_m"] = a.wheel_circumference
    if a.wheel_ppr is not None:
        ov["wheel_ppr"] = a.wheel_ppr
    if a.wheel_active_high:
        ov["wheel_active_high"] = True
    if ov:
        ov["source"] = a.source
    res = run(image, a.db, a.out, ov, plots=not a.no_plots)
    r = res["slots"]
    print(f"IMPORT slots {r['slots']}: {r['header']} session headers, {r['block']} blocks, {r['empty']} empty, "
          f"{r['corrupt_header']} corrupt headers, {r['orphan_block']} orphan blocks, {r['unknown']} unknown")
    for s in res["sessions"]:
        i = s["import"]
        d = ", ".join(f"{c} {v['distance_m']:.2f} m" + (" (lower bound)" if v["lower_bound"] else "")
                      for c, v in s["distance"].items() if v["distance_m"] is not None) or "no distance"
        print(f"IMPORT {s['run_id']} boot {s['boot']} reset {(s['reset'] or {}).get('cause')}: {i['records']} records, "
              f"{i['blocks_corrupt']} corrupt blocks, {i['block_seq_gaps']} sequence gaps; {d}"
              + (f"; plot {s['plot']}" if s["plot"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
