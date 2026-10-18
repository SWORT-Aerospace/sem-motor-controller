#!/usr/bin/env python3
"""Recording duration of the telematics log, measured with the firmware's own code.

    python3 tools/telematics_storage.py [--build build-telematics]          # writes docs/generated/telematics_storage.*
    python3 tools/telematics_storage.py --check                             # exit 1 if the committed files are stale

The host simulator (telematics/firmware/platform/host/tm_hostsim.c) runs the portable application, the same
code as the target images, against the record mix of each bench step and of the fixture vehicle. The slots
it uses per second (block packing, the 2 s flush of a partly filled block, the counters, every record's
header) give the seconds per 4 KiB slot; the durations follow for the internal flash (256 slots) and the
W25Q128JV NOR (4096 slots), each with its session header and its reserve for sparse logging (tm_config.h).

The record sizes do not depend on the edge rate (a wheel record has the same size for 1 or 1000 edges), so
B3, B5 and B7 (100 Hz, 5 kHz, 1 kHz on wheel_0) share one mix. Measured on the host model, not on the board:
the bench check is the `left=` estimate and `slots=` of the status line.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from protocol.generated import semmc_protocol as proto  # noqa: E402

OUT_MD = ROOT / "docs/generated/telematics_storage.md"
OUT_JSON = ROOT / "docs/generated/telematics_storage.json"
STORAGES = {"internal flash bank 2": 256, "W25Q128JV NOR": 4096}


def _cfg() -> dict:
    h = (ROOT / "telematics/firmware/include/tm_config.h").read_text()
    get = lambda n: int(re.search(rf"#define {n} (\d+)u", h).group(1))  # noqa: E731
    return {"reserve": get("TM_RESERVE_SLOTS"), "sparse_period_s": get("TM_SPARSE_PERIOD_US") / 1e6,
            "flush_s": get("TM_BLOCK_FLUSH_US") / 1e6}


CTRL_RATES = {n: 1.0 / m["period_s"] for n, m in proto.MESSAGES.items()
              if m["sender"] == "controller" and m.get("period_s")}

MIXES = [
    {"id": "wheel", "steps": "B1 to B11 (signal generator on wheel_0; edge rate does not matter)", "imu_hz": 0,
     "temp_hz": 0, "can_hz": 0},
    {"id": "wheel_imu_temp", "steps": "B12 (IMU at 100 Hz and one TMP117 at 1 Hz added)", "imu_hz": 100,
     "temp_hz": 1, "can_hz": 0},
    {"id": "fixture_vehicle", "steps": "vehicle with the semmc fixture's controller broadcast "
                                      f"({sum(CTRL_RATES.values()):.0f} frames/s), IMU and three TMP117",
     "imu_hz": 100, "temp_hz": 3, "can_hz": sum(CTRL_RATES.values())},
]


def _hostsim(build: pathlib.Path, script: str) -> str:
    r = subprocess.run([str(build / "tm_hostsim")], input=script, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout


def _seconds_per_slot(build: pathlib.Path, mix: dict, duration_s: float = 120.0, warm_s: float = 20.0) -> float:
    with tempfile.TemporaryDirectory() as d:
        img = pathlib.Path(d) / "img.bin"
        ev = [(0, f"I 1024 1500 8 {img}")]
        end = int(duration_s * 1e6)
        if mix["imu_hz"]:
            step = int(1e6 / mix["imu_hz"])
            ev += [(t, f"K {t} 4 0000000000000000") for t in range(step, end, step)]
        for k in range(mix["temp_hz"]):                            # one probe per 1 Hz record stream
            ev += [(t + k, f"K {t + k} 8 {k:02x}000000") for t in range(1_000_000, end, 1_000_000)]
        if mix["can_hz"]:
            for n, hz in CTRL_RATES.items():
                per = int(round(1e6 / hz))
                ev += [(t, f"C {t} {proto.MESSAGES[n]['id'] + 0x300:x} 0011223344556677")
                       for t in range(per, int(duration_s * 1e6), per)]
        ev += [(int(warm_s * 1e6), f"P {int(warm_s * 1e6)}\nQ"), (int(duration_s * 1e6), f"P {int(duration_s * 1e6)}\nQ")]
        ev.sort(key=lambda e: e[0])
        out = _hostsim(build, "\n".join(x for _t, x in ev) + "\n")
    slots = [int(m) for m in re.findall(r"slots=(\d+)/", out)]
    used = slots[-1] - slots[0]
    return (duration_s - warm_s) / used


def _sparse_seconds_per_slot(build: pathlib.Path) -> float:
    """512 slots, reserve 32: the full-rate region (479 slots of 2 s) is used by about 960 s, then sparse. No
    edges are needed: a wheel record has the same size whatever its edge count."""
    with tempfile.TemporaryDirectory() as d:
        img = pathlib.Path(d) / "img.bin"
        marks = [1000, 8000]
        out = _hostsim(build, "\n".join([f"I 512 1500 8 {img}"] + [f"P {s * 1_000_000}\nQ" for s in marks]) + "\n")
    st = re.findall(r"slots=(\d+)/\d+ log=(\w+)", out)
    assert len(st) == 2 and all(m == "sparse" for _s, m in st), st
    return (marks[1] - marks[0]) / (int(st[1][0]) - int(st[0][0]))


def measure(build: pathlib.Path) -> dict:
    cfg = _cfg()
    sparse = _sparse_seconds_per_slot(build)
    rows = []
    for mix in MIXES:
        sps = _seconds_per_slot(build, mix)
        st = {}
        for name, slots in STORAGES.items():
            reserve = min(cfg["reserve"], slots // 8)
            full_s = (slots - 1 - reserve) * sps
            st[name] = {"slots": slots, "reserve": reserve, "full_rate_s": round(full_s),
                        "sparse_s": round(reserve * sparse), "total_s": round(full_s + reserve * sparse)}
        rows.append({**mix, "seconds_per_slot": round(sps, 3), "storages": st})
    return {"config": cfg, "sparse_seconds_per_slot": round(sparse, 1), "mixes": rows,
            "timer_overflow_s": round(2 ** 32 / 1e6, 1)}


def render(res: dict) -> str:
    c = res["config"]
    ovf = res["timer_overflow_s"]
    L = ["# Recording duration of the telematics log", "",
         "Generated by `tools/telematics_storage.py` from the firmware's own code in the host simulator; do not edit. "
         "Measured on the host model, not on the board: on the bench, the status line's `slots=` and `left=` show the "
         "real figures.", "",
         f"Full-rate logging until only the reserve ({c['reserve']} slots at most, 1/8 of a small storage) is left; then "
         f"sparse logging: one wheel record per channel and the counters every {c['sparse_period_s']:.0f} s, nothing else "
         f"(counted as `log_thinned`), {res['sparse_seconds_per_slot']:.0f} s per slot. A partly filled block is written "
         f"after {c['flush_s']:.0f} s, so at low record rates a slot holds {c['flush_s']:.0f} s.", "",
         "| Record mix | Steps | s per slot | Storage | Full rate | Then sparse | Total |", "|---|---|---|---|---|---|---|"]
    for m in res["mixes"]:
        for name, s in m["storages"].items():
            L.append(f"| `{m['id']}` | {m['steps']} | {m['seconds_per_slot']:.2f} | {name} ({s['slots']} slots) | "
                     f"{s['full_rate_s'] / 60:.1f} min | {s['sparse_s'] / 60:.0f} min | {s['total_s'] / 60:.0f} min |")
    w = res["mixes"][0]["storages"]
    nor, intl = w["W25Q128JV NOR"], w["internal flash bank 2"]
    L += ["", f"**Step B7 (75 min across the 32-bit timer overflow at {ovf / 60:.1f} min).** With the NOR fitted, the "
          f"full-rate log lasts {nor['full_rate_s'] / 60:.0f} min: the overflow is in the full-rate log. On internal "
          f"flash alone the full-rate log ends after {intl['full_rate_s'] / 60:.1f} min and sparse logging carries on "
          f"to {intl['total_s'] / 60:.0f} min, so the overflow is still in the log, in records 10 s apart: a time "
          "extension error at the overflow would show as a 4295 s jump in a record's time or span. The console capture "
          "(`tov=` and `t=` every second) is evidence independent of either storage.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", type=pathlib.Path, default=ROOT / "build-telematics")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    res = measure(a.build)
    md, js = render(res), json.dumps(res, indent=2, sort_keys=True) + "\n"
    if a.check:
        stale = [p.name for p, x in ((OUT_MD, md), (OUT_JSON, js)) if not p.exists() or p.read_text() != x]
        if stale:
            print("stale: " + ", ".join(stale) + " (run tools/telematics_storage.py)")
            return 1
        print("telematics storage durations current")
        return 0
    OUT_MD.write_text(md)
    OUT_JSON.write_text(js)
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.name}")
    for m in res["mixes"]:
        print(m["id"], m["seconds_per_slot"], {k: v["total_s"] for k, v in m["storages"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
