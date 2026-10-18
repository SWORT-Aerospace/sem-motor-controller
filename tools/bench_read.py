#!/usr/bin/env python3
"""Read the controller's bench values (g_bench) from a running board through OpenOCD, without halting it.

    openocd -f interface/stlink.cfg -f target/stm32g4x.cfg          # in another terminal
    python3 tools/bench_read.py --elf build-g4/semmc_stm32g474.elf             # one reading, printed
    python3 tools/bench_read.py --elf ... --samples 20 --period 0.5 --json out.json

g_bench is defined in firmware/platform/stm32g4/src/main.c; its layout is fixed by a _Static_assert
there and decoded here with FORMAT. OpenOCD reads target memory through the debug port while the core
runs (TCL server on port 6666, commands ending in 0x1a). The JSON output is the structured record the
acceptance procedures ask for (docs/BENCH_ACCEPTANCE.md): every reading with its host time, the ELF's
SHA-256 and the firmware revision string found in the image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import socket
import struct
import subprocess
import sys
import time

FORMAT = "<6I3f5H2x3f2f2f3I6I"
FIELDS = ["platform_faults", "can_status", "fast_count", "fast_max_cycles", "fast_overruns", "slow_max_cycles",
          "raw_current_avg_a", "raw_current_avg_b", "raw_current_avg_c",
          "raw_vbus", "raw_temp_fet", "raw_temp_motor", "raw_throttle_a", "raw_throttle_b",
          "offsets_measured_a", "offsets_measured_b", "offsets_measured_c",
          "pedal_frac_a", "pedal_frac_b", "f_pwm_Hz", "deadtime_s", "state", "precharge_state", "inputs",
          "fast_isr_max_cycles", "fast_margin_min_ticks", "fast_late_writes", "adc_wait_max_cycles", "slow_overruns",
          "stack_unused_min_bytes"]
INPUT_BITS = ["brake", "cancel", "mode_eco", "arm", "fault_reset", "driver_present", "hw_permit",
              "drv_en_gated", "drv_nfault", "ext_wdg_reset", "ina_alert", "break_driver", "break_overvolt",
              "break_system", "outputs_on"]
PLATFORM_FAULTS = ["gate_driver_not_configured", "battery_meter_not_read", "pwm_not_configured", "can_off",
                   "adc_init", "offsets", "enable_path", "precharge", "adc_resolution"]
STATES = ["BOOT", "SELF_TEST", "DISARMED", "READY", "MANUAL", "ECO_ASSIST", "DERATED", "FAULT_LATCHED"]
PRECHARGE = ["DISABLED", "WAIT_BATTERY", "CHARGING", "CLOSED", "FAULT"]
SIZE = struct.calcsize(FORMAT)
assert SIZE == 112 and len(FIELDS) == len(struct.unpack(FORMAT, bytes(SIZE)))


def symbol_address(elf: pathlib.Path, name: str) -> int:
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    raise SystemExit(f"{name} not in {elf}")


def revision(elf: pathlib.Path) -> str:
    out = subprocess.run(["arm-none-eabi-strings", str(elf)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("semmc stm32g474 "):
            return line.split(" ", 2)[2].strip()
    return "unknown"


class OpenOcd:
    def __init__(self, host: str, port: int):
        self.s = socket.create_connection((host, port), timeout=5)

    def cmd(self, c: str) -> str:
        self.s.sendall(c.encode() + b"\x1a")
        buf = b""
        while not buf.endswith(b"\x1a"):
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("OpenOCD closed the connection")
            buf += chunk
        return buf[:-1].decode()

    def read_words(self, addr: int, n: int) -> bytes:
        # read_memory returns a Tcl list of words (OpenOCD 0.12); mdw is the fallback for older versions.
        r = self.cmd(f"read_memory 0x{addr:08x} 32 {n}")
        try:
            words = [int(x, 0) for x in r.split()]
        except ValueError:
            r = self.cmd(f"mdw 0x{addr:08x} {n}")
            words = [int(x, 16) for line in r.splitlines() for x in line.split(":", 1)[1].split()]
        if len(words) != n:
            raise RuntimeError(f"expected {n} words, got {r!r}")
        return struct.pack(f"<{n}I", *words)


def decode(raw: bytes) -> dict:
    d = dict(zip(FIELDS, struct.unpack(FORMAT, raw)))
    d["platform_faults_named"] = [n for i, n in enumerate(PLATFORM_FAULTS) if d["platform_faults"] >> i & 1]
    d["state_name"] = STATES[d["state"]] if d["state"] < len(STATES) else str(d["state"])
    d["precharge_state_name"] = PRECHARGE[d["precharge_state"]] if d["precharge_state"] < len(PRECHARGE) else "?"
    d["inputs_named"] = [n for i, n in enumerate(INPUT_BITS) if d["inputs"] >> i & 1]
    d["hall_code"] = (d["inputs"] >> 16) & 7
    d["fast_max_us"] = d["fast_max_cycles"] / 160.0
    d["slow_max_us"] = d["slow_max_cycles"] / 160.0
    d["fast_isr_max_us"] = d["fast_isr_max_cycles"] / 160.0
    # TIM1 counts at the 160 MHz timer clock; UINT32_MAX means no compare write has been made yet
    m = d["fast_margin_min_ticks"]
    d["fast_margin_min_us"] = None if m == 0xFFFFFFFF else m / 160.0
    d["adc_wait_max_us"] = d["adc_wait_max_cycles"] / 160.0
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--elf", type=pathlib.Path, required=True, help="the image that is flashed")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6666)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--json", type=pathlib.Path)
    a = ap.parse_args()
    addr = symbol_address(a.elf, "g_bench")
    ocd = OpenOcd(a.host, a.port)
    readings = []
    for i in range(a.samples):
        d = decode(ocd.read_words(addr, SIZE // 4))
        d["host_time"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        readings.append(d)
        print(json.dumps({k: d[k] for k in ("host_time", "state_name", "precharge_state_name", "platform_faults_named",
                                            "inputs_named", "hall_code", "fast_count", "fast_max_us",
                                            "fast_overruns")}))
        if i + 1 < a.samples:
            time.sleep(a.period)
    if a.json:
        rec = {"elf": str(a.elf), "elf_sha256": hashlib.sha256(a.elf.read_bytes()).hexdigest(),
               "firmware_revision": revision(a.elf), "g_bench_address": f"0x{addr:08x}", "readings": readings}
        a.json.write_text(json.dumps(rec, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
