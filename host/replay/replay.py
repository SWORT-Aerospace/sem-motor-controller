#!/usr/bin/env python3
"""Host replay: timestamped log -> validity checks, state transitions and
command arbitration (the C core) -> requested vs accepted commands with reasons.

    python3 host/replay/replay.py LOG [--cal build/cal/synthetic.bin] [--plant] [--out DIR]

By default the replay runs WITHOUT the simulated plant (--no-plant): measured
quantities come from MEAS lines in the log, exactly as a recorded vehicle log
would supply them. Output:
    DIR/replay.csv        per-step controller state (10 ms decimation)
    DIR/replay_tx.log     controller TX frames (semmc-log v1)
    DIR/commands.csv      requested vs accepted torque with decoded reason names
and a summary on stdout.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from host.logger.semmc_log import decode_tx_log  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

REASONS = {
    0x0001: "NOT_ARMED", 0x0002: "FAULT_INHIBIT", 0x0004: "HW_TRIP", 0x0008: "BRAKE_OVERRIDE",
    0x0010: "CANCEL_OVERRIDE", 0x0020: "SUPERVISOR_INVALID", 0x0040: "DRIVER_ABSENT", 0x0080: "THROTTLE_LATCH",
    0x0100: "CLAMP_TORQUE", 0x0200: "CLAMP_BATTERY", 0x0400: "CLAMP_DERATE", 0x0800: "CLAMP_SPEED",
    0x1000: "SLEW", 0x2000: "SUPERVISOR_BOUND", 0x4000: "REGEN_DISABLED", 0x8000: "COAST",
}
STATES = ["BOOT", "SELF_TEST", "DISARMED", "READY", "MANUAL", "ECO_ASSIST", "DERATED", "FAULT_LATCHED"]


def reason_names(mask: int) -> str:
    return "|".join(n for b, n in REASONS.items() if mask & b) or "-"


def run_replay(log: pathlib.Path, cal: pathlib.Path, outdir: pathlib.Path, plant: bool = False,
               exe: pathlib.Path | None = None) -> dict:
    exe = exe or ROOT / "build" / "semmc_host"
    outdir.mkdir(parents=True, exist_ok=True)
    args = [str(exe), "--cal", str(cal), "--log", str(log), "--out", str(outdir / "replay.csv"),
            "--frames", str(outdir / "replay_tx.log")]
    if not plant:
        args.append("--no-plant")
    res = subprocess.run(args, capture_output=True, text=True, check=True)
    frames = decode_tx_log(outdir / "replay_tx.log")
    rows = []
    state = None
    for t_us, name, values, info in frames:
        if info["status"] != "ok":
            raise RuntimeError(f"controller emitted an undecodable frame at {t_us}: {info}")
        if name == "ctrl_status":
            state = STATES[values["state"]]
        if name == "ctrl_cmd_trace":
            rows.append({"t_s": t_us / 1e6, "state": state, "requested_Nm": values["requested_Nm"],
                         "accepted_Nm": values["accepted_Nm"], "reason_mask": values["reason"],
                         "reasons": reason_names(values["reason"])})
    with (outdir / "commands.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["t_s"])
        w.writeheader()
        w.writerows(rows)
    transitions = []
    prev = None
    for r in rows:
        if r["state"] != prev:
            transitions.append((r["t_s"], r["state"]))
            prev = r["state"]
    return {"summary": res.stdout.strip(), "commands": rows, "transitions": transitions}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--cal", default=str(ROOT / "build" / "cal" / "synthetic.bin"))
    ap.add_argument("--plant", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "build" / "replay"))
    a = ap.parse_args()
    r = run_replay(pathlib.Path(a.log), pathlib.Path(a.cal), pathlib.Path(a.out), plant=a.plant)
    print(r["summary"])
    for t, s in r["transitions"]:
        print(f"{t:9.3f} s  -> {s}")
    changes = 0
    last = None
    for row in r["commands"]:
        key = (round(row["requested_Nm"], 3), round(row["accepted_Nm"], 3), row["reasons"])
        if key != last:
            if changes < 40:
                print(f"{row['t_s']:9.3f} s  req {row['requested_Nm']:7.3f}  acc {row['accepted_Nm']:7.3f}  {row['reasons']}")
            changes += 1
            last = key
    print(f"{changes} distinct requested/accepted/reason combinations; full table in {a.out}/commands.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
