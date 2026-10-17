#!/usr/bin/env python3
"""Instruction counts of the controller core on Cortex-M4F, from an instruction-level emulator.

    python3 tools/emulate_core_timing.py --elf build-g4/semmc_core_timing.elf --blob build/cal/synthetic.bin
    python3 tools/emulate_core_timing.py ... --out docs/generated/core_timing_emulated.md

The ELF is firmware/platform/stm32g4/timing/core_timing_harness.c built by the target CMake
configuration (SEMMC_TARGET_STM32G474=ON): the real core, compiled with the target's compiler, flags and
newlib, driving the host plant model. It runs in unicorn (QEMU's ARM model, Cortex-M4, Thumb-2 with
FPv4-SP). The tool counts the instructions executed between the harness's begin/end markers around
mc_core_fast_step and mc_core_slow_step.

What the numbers are: instruction counts for this code on this input (synthetic calibration, arm at
100 ms, half throttle from 110 ms), summed over the translated blocks the emulator executes. They include
instructions an IT block skips (a Cortex-M4 still issues those; a per-instruction hook that leaves them out
gives about 4 % less) and the few instructions of the harness call around the measured function. A
Cortex-M4 issues at most one instruction per cycle, so count / 160 MHz is a LOWER bound on the execution
time. Flash wait states, the ART accelerator, branch
refills, load-use stalls and FPU latencies are not modelled; the real time is measured on the board with
the DWT cycle counter (g_bench.fast_max_cycles, docs/BENCH_ACCEPTANCE.md stage 4). Requires the Python
package unicorn and arm-none-eabi binutils.
"""
from __future__ import annotations

import argparse
import bisect
import pathlib
import re
import statistics
import subprocess
import sys

FLASH, RAM = 0x08000000, 0x20000000
BLOB_ADDR = 0x2001F000
STACK_TOP = 0x20018000
RET_ADDR = 0x0807FF00
SYSCLK_HZ = 160e6


def symbols(elf: pathlib.Path) -> dict[str, int]:
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], check=True, capture_output=True, text=True).stdout
    return {p[2]: int(p[0], 16) for p in (l.split() for l in out.splitlines()) if len(p) == 3}


def instruction_addresses(elf: pathlib.Path) -> list[int]:
    dis = subprocess.run(["arm-none-eabi-objdump", "-d", str(elf)], check=True, capture_output=True, text=True).stdout
    addrs = []
    for line in dis.splitlines():
        m = re.match(r"^\s*([0-9a-f]{7,8}):\s+([0-9a-f]{4})(?: ([0-9a-f]{4}))?\s+\S", line)
        if m:
            addrs.append(int(m.group(1), 16))
    return sorted(set(addrs))


def flat_image(elf: pathlib.Path, tmp: pathlib.Path) -> bytes:
    out = tmp / "harness.bin"
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(out)], check=True)
    return out.read_bytes()


def run(elf: pathlib.Path, blob: bytes, ms: int, tmp: pathlib.Path) -> dict:
    from unicorn import UC_ARCH_ARM, UC_HOOK_BLOCK, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
    from unicorn import arm_const as A

    syms = symbols(elf)
    addrs = instruction_addresses(elf)
    img = flat_image(elf, tmp)
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(A.UC_CPU_ARM_CORTEX_M4)
    uc.mem_map(FLASH, 512 * 1024)
    uc.mem_map(RAM, 128 * 1024)
    uc.mem_write(FLASH, img)
    uc.mem_write(BLOB_ADDR, blob)
    uc.mem_write(RET_ADDR, b"\xfe\xe7")  # b . (never reached: emulation stops at this address)

    fb, fe = syms["bench_fast_begin"] & ~1, syms["bench_fast_end"] & ~1
    sb, se = syms["bench_slow_begin"] & ~1, syms["bench_slow_end"] & ~1
    pwm_addr = syms["bench_pwm_enabled"]
    state = {"on": None, "count": 0, "fast": [], "fast_pwm": [], "slow": []}

    def on_block(_uc, address, size, _ud):
        # A block starting at a marker opens or closes a window; the marker's own instructions are excluded.
        if address in (fb, sb):
            state["on"], state["count"] = ("fast" if address == fb else "slow"), 0
            return
        if address == fe and state["on"] == "fast":
            pwm = int.from_bytes(uc.mem_read(pwm_addr, 4), "little")
            (state["fast_pwm"] if pwm else state["fast"]).append(state["count"])
            state["on"] = None
            return
        if address == se and state["on"] == "slow":
            state["slow"].append(state["count"])
            state["on"] = None
            return
        if state["on"]:
            state["count"] += bisect.bisect_left(addrs, address + size) - bisect.bisect_left(addrs, address)

    uc.hook_add(UC_HOOK_BLOCK, on_block)

    uc.reg_write(A.UC_ARM_REG_SP, STACK_TOP)
    uc.reg_write(A.UC_ARM_REG_LR, RET_ADDR | 1)
    uc.reg_write(A.UC_ARM_REG_R0, BLOB_ADDR)
    uc.reg_write(A.UC_ARM_REG_R1, len(blob))
    uc.reg_write(A.UC_ARM_REG_R2, ms)
    uc.emu_start(syms["bench_run"] | 1, RET_ADDR)
    rc = uc.reg_read(A.UC_ARM_REG_R0)
    rc = rc - (1 << 32) if rc & 0x80000000 else rc
    return {"final_state": rc, **{k: state[k] for k in ("fast", "fast_pwm", "slow")}}


def summarise(xs: list[int]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    return {"n": len(s), "mean": statistics.fmean(s), "p99": s[int(0.99 * (len(s) - 1))], "max": s[-1]}


STATES = {0: "BOOT", 1: "SELF_TEST", 2: "DISARMED", 3: "READY", 4: "MANUAL", 5: "ECO_ASSIST", 6: "DERATED",
          7: "FAULT_LATCHED"}


def report(res: dict, elf: pathlib.Path, ms: int, compiler: str) -> str:
    f, fp, sl = summarise(res["fast"]), summarise(res["fast_pwm"]), summarise(res["slow"])

    def row(name, d, budget_us):
        if not d["n"]:
            return f"| {name} | 0 | - | - | - | - | {budget_us:g} us |"
        lb = d["max"] / SYSCLK_HZ * 1e6
        return (f"| {name} | {d['n']} | {d['mean']:.0f} | {d['p99']} | {d['max']} | {lb:.1f} us | {budget_us:g} us |")

    L = ["# Controller core on Cortex-M4F: emulated instruction counts", "",
         "Generated by `tools/emulate_core_timing.py`; do not edit. EMULATED, not measured on hardware.", "",
         f"Harness `firmware/platform/stm32g4/timing/core_timing_harness.c`, built with {compiler} for "
         "`-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard`, CMake build type MinSizeRel (the "
         "target image's), newlib-nano. Run in unicorn (QEMU's Cortex-M4 model) with the synthetic "
         f"calibration and the host plant model: {ms} ms simulated, armed at 100 ms, half throttle from 110 ms. "
         f"Final state: {STATES.get(res['final_state'], res['final_state'])}.", "",
         "| Step | Calls | Mean instructions | p99 | Max | Lower bound at 160 MHz (max / f) | Period |",
         "|---|---|---|---|---|---|---|",
         row("fast step, current control active", fp, 50.0),
         row("fast step, outputs off", f, 50.0),
         row("slow step", sl, 1000.0), "",
         "How to read this:", "",
         "- The lower bound assumes one instruction per cycle, the most a Cortex-M4 issues. The real time is "
         "longer: flash wait states (4 at 160 MHz, partly hidden by the ART accelerator), branch refills, "
         "load-use stalls and FPU divide/square-root latencies are not modelled.",
         "- Counts include instructions skipped by IT blocks (the core still issues them) and a few instructions "
         "of the harness's call around the measured function.",
         "- The platform's own interrupt code (ADC result reads, hall pins, duty writes) is not included.",
         "- The fast step must finish within half a PWM period (`firmware/platform/stm32g4/src/pwm.h`): 25 us "
         "at 20 kHz. The measured worst case comes from `g_bench.fast_max_cycles` on the board "
         "(docs/BENCH_ACCEPTANCE.md, stage 4).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--elf", type=pathlib.Path, required=True)
    ap.add_argument("--blob", type=pathlib.Path, required=True)
    ap.add_argument("--ms", type=int, default=300)
    ap.add_argument("--out", type=pathlib.Path)
    a = ap.parse_args()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        res = run(a.elf, a.blob.read_bytes(), a.ms, pathlib.Path(d))
    compiler = subprocess.run(["arm-none-eabi-gcc", "-dumpversion"], capture_output=True, text=True).stdout.strip()
    text = report(res, a.elf, a.ms, f"arm-none-eabi-gcc {compiler}")
    if a.out:
        a.out.write_text(text)
    print(text)
    return 0 if res["fast_pwm"] else 1


if __name__ == "__main__":
    sys.exit(main())
