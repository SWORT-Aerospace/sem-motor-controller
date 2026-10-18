#!/usr/bin/env python3
"""Import the telematics unit's persistent log (a flash dump or a UART dump) into the pit database.

    python3 tools/telematics_import.py dump.bin --db pit.sqlite --out build/bench_import \
        [--wheel-circumference 1.50 --wheel-ppr 8] [--uart-capture capture.txt]

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
"""
from __future__ import annotations

import argparse
import json
import pathlib
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
    ap.add_argument("--db", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "telematics_import")
    ap.add_argument("--wheel-circumference", type=float, help="m (vehicle or bench fixture value)")
    ap.add_argument("--wheel-ppr", type=int, help="edges counted per revolution")
    ap.add_argument("--wheel-active-high", action="store_true", help="sensor output high when a magnet is near")
    ap.add_argument("--source", default="command line", help="where the wheel values come from (recorded)")
    ap.add_argument("--no-plots", action="store_true")
    a = ap.parse_args()
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
