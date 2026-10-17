#!/usr/bin/env python3
"""Peripheral / pin-resource feasibility check for the STM32G474 baseline.

Source data: STMicroelectronics/STM32_open_pin_data (BSD-3-Clause), the pin
database ST publishes for STM32CubeMX, cloned at a pinned commit:
    python3 tools/pin_allocation.py --db /path/to/stm32_open_pin_data [--commit SHA]

For every G474 package it tries to allocate the controller's required
functions (signal names exactly as in the ST XML) to distinct pins, honouring
peripheral-instance groups (all hall inputs on one timer, SPI pins on one SPI,
...). Output: docs/generated/pin_allocation.md and
hardware/interfaces/pin_allocation_<package>.csv.

LIMITS (stated in the output): this checks signal availability and pin
uniqueness only. It does not check alternate-function numbers, ADC fast/slow
channel timing, OPAMP/COMP internal routing, clock trees, the errata sheet, or
PCB escape - those need CubeMX/datasheet review.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
NS = {"st": "http://dummy.com"}
RESERVED = {"PA13": "SWDIO", "PA14": "SWCLK", "PB3": "SWO (debug trace)", "PF0-OSC_IN": "HSE_IN",
            "PF1-OSC_OUT": "HSE_OUT", "PG10-NRST": "NRST", "PB8-BOOT0": "BOOT0 strap",
            "PC14-OSC32_IN": "LSE (unused, kept free)", "PC15-OSC32_OUT": "LSE (unused, kept free)"}

# Pins kept to slow GPIO duty: PC13 is in the backup domain with limited drive
# strength/speed on STM32 parts (recalled, NOT verified here against DS12288 -
# not yet checked against the datasheet). Never used for PWM, SPI or CAN.
SLOW_ONLY = {"PC13"}

# (function, regex on signal name, group key or None, note)
REQUIRED = [
    ("PWM_A_HI", r"^TIM1_CH1$", None, "gate driver INHA"),
    ("PWM_A_LO", r"^TIM1_CH1N$", None, "gate driver INLA (6-PWM mode)"),
    ("PWM_B_HI", r"^TIM1_CH2$", None, "INHB"),
    ("PWM_B_LO", r"^TIM1_CH2N$", None, "INLB"),
    ("PWM_C_HI", r"^TIM1_CH3$", None, "INHC"),
    ("PWM_C_LO", r"^TIM1_CH3N$", None, "INLC"),
    ("PWM_BREAK", r"^TIM1_BKIN$", None, "hardware trip input: gate-driver nFAULT (open drain, active low)"),
    ("PWM_BREAK2", r"^TIM1_BKIN2$", None, "hardware trip input: independent bus over-voltage comparator (open drain, wired-OR; a dedicated over-current comparator is an open option)"),
    # Phase currents: three DIFFERENT ADCs started by the same TIM1 trigger, so
    # the three samples are taken at the same instant (ADC1+ADC2 dual-
    # simultaneous injected, ADC3/4/5 injected on the same TIM1 TRGO2 edge).
    # v0.1 put phase C on ADC1 as a second injected rank, one conversion
    # (~15 ADC clocks) after phase A. IN1..IN5 are required because they are
    # recalled to be the direct "fast" channels on STM32G4 (RM0440, NOT
    # verified here against the datasheet).
    ("ISENSE_A", r"^ADC1_IN[1-5]$", None, "CSA A -> ADC1 fast channel (dual simultaneous with ADC2: proposed)"),
    ("ISENSE_B", r"^ADC2_IN[1-5]$", None, "CSA B -> ADC2 fast channel"),
    ("ISENSE_C", r"^ADC[345]_IN[1-5]$", None, "CSA C -> ADC3/4/5 fast channel, same TIM1 trigger edge"),
    ("VBUS_SENSE", r"^ADC[345]_IN\d+$", None, "bus voltage divider (separate ADC from currents)"),
    ("TEMP_FET", r"^ADC[345]_IN\d+$", None, "power-stage NTC"),
    ("TEMP_MOTOR", r"^ADC[345]_IN\d+$", None, "motor winding NTC/PTC"),
    ("THROTTLE_A", r"^ADC[345]_IN\d+$", None, "pedal track A"),
    ("THROTTLE_B", r"^ADC[345]_IN\d+$", None, "pedal track B (redundant)"),
    ("HALL_A", r"^TIM(3|4)_CH1$", "hall", "hall interface timer (XOR input)"),
    ("HALL_B", r"^TIM(3|4)_CH2$", "hall", ""),
    ("HALL_C", r"^TIM(3|4)_CH3$", "hall", ""),
    ("DRV_SPI_SCK", r"^SPI(1|2|3)_SCK$", "spi", "DRV8353S/RS configuration + status"),
    ("DRV_SPI_MISO", r"^SPI(1|2|3)_MISO$", "spi", ""),
    ("DRV_SPI_MOSI", r"^SPI(1|2|3)_MOSI$", "spi", ""),
    ("CAN_RX", r"^FDCAN(1|2|3)_RX$", "can", "to TCAN1042-class transceiver"),
    ("CAN_TX", r"^FDCAN(1|2|3)_TX$", "can", ""),
    ("I2C_SCL", r"^I2C(1|2|3|4)_SCL$", "i2c", "INA228-class DC-bus energy monitor"),
    ("I2C_SDA", r"^I2C(1|2|3|4)_SDA$", "i2c", ""),
    ("DBG_UART_TX", r"^USART(1|2|3)_TX$", "uart", "bench console (no field use)"),
    ("DBG_UART_RX", r"^USART(1|2|3)_RX$", "uart", ""),
]
GPIO_FUNCS = ["DRV_SPI_NSS", "DRV_ENABLE", "DRV_NFAULT", "INA_ALERT", "ARM_SWITCH", "MODE_SWITCH", "ECO_CANCEL",
              "BRAKE_SWITCH", "FAULT_RESET", "ESTOP_CHAIN_SENSE", "DEADMAN_SENSE", "EXT_WDG_WDI", "EXT_WDG_RST_SENSE",
              "OUTPUT_ENABLE_FEEDBACK", "LED_STATUS", "LED_FAULT", "PRECHG_EN"]


def load(path: pathlib.Path):
    root = ET.parse(path).getroot()
    pins = []
    for p in root.findall("st:Pin", NS):
        sigs = [s.get("Name") for s in p.findall("st:Signal", NS)]
        pins.append({"name": p.get("Name"), "pos": p.get("Position"), "type": p.get("Type"), "signals": sigs})
    return root.get("RefName"), root.get("Package"), pins


def allocate(pins):
    usable = [p for p in pins if p["type"] == "I/O" and p["name"] not in RESERVED]
    groups = {}
    for fn, rx, grp, _ in REQUIRED:
        if grp:
            groups.setdefault(grp, []).append((fn, rx))
    # enumerate instance choices per group (e.g. TIM3 vs TIM4)
    inst_choices = {}
    for g, items in groups.items():
        insts = set()
        for p in usable:
            for s in p["signals"]:
                m = re.match(items[0][1], s)
                if m:
                    insts.add(s.split("_")[0])
        inst_choices[g] = sorted(insts)
    best = None
    for combo in itertools.product(*[inst_choices[g] for g in groups]):
        chosen = dict(zip(groups, combo))
        used, assign, missing = set(), {}, []
        # scarcest first: count candidates
        reqs = []
        for fn, rx, grp, note in REQUIRED:
            def ok(s, rx=rx, grp=grp):
                return re.match(rx, s) and (not grp or s.startswith(chosen[grp] + "_"))
            cands = [(p, s) for p in usable if p["name"] not in SLOW_ONLY for s in p["signals"] if ok(s)]
            reqs.append((len({c[0]["name"] for c in cands}), fn, cands, note))
        for _, fn, cands, note in sorted(reqs, key=lambda r: r[0]):
            pick = next(((p, s) for p, s in cands if p["name"] not in used), None)
            if pick is None:
                missing.append(fn)
                continue
            used.add(pick[0]["name"])
            assign[fn] = (pick[0], pick[1], note)
        free = [p for p in usable if p["name"] not in used]
        # GPIO functions: prefer pins with fewest special signals (keep rich pins free)
        free.sort(key=lambda p: len(p["signals"]))
        for fn in GPIO_FUNCS:
            if free:
                p = free.pop(0)
                used.add(p["name"])
                assign[fn] = (p, "GPIO", "")
            else:
                missing.append(fn)
        score = (len(missing), -len(free))
        if best is None or score < best[0]:
            best = (score, chosen, assign, missing, len(free))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to a clone of STM32_open_pin_data")
    ap.add_argument("--commit", default="unknown")
    a = ap.parse_args()
    files = sorted((pathlib.Path(a.db) / "mcu").glob("STM32G474*.xml"))
    md = ["# STM32G474 pin / resource feasibility (generated)", "",
          f"Source: STMicroelectronics/STM32_open_pin_data (BSD-3-Clause) commit `{a.commit}`. "
          "Generated by `tools/pin_allocation.py`.", "",
          "Checks signal availability and pin uniqueness only. **Not checked:** alternate-function numbers, "
          "ADC channel speed classes and sampling-time feasibility, internal OPAMP/COMP routing, errata (ES0430), "
          "clock tree, PCB escape/layout. These require CubeMX and datasheet review.", "",
          f"Required functions: {len(REQUIRED)} peripheral-bound + {len(GPIO_FUNCS)} GPIO; reserved pins: "
          + ", ".join(f"{k} ({v})" for k, v in RESERVED.items()), "",
          "| part (package) | I/O pins | all required allocated | missing | spare I/O after allocation | instance choice |",
          "|---|---|---|---|---|---|"]
    outdir = ROOT / "hardware" / "interfaces"
    outdir.mkdir(parents=True, exist_ok=True)
    details = []
    for f in files:
        ref, pkg, pins = load(f)
        (_score, chosen, assign, missing, spare) = allocate(pins)
        nio = sum(1 for p in pins if p["type"] == "I/O")
        md.append(f"| {ref} ({pkg}) | {nio} | {'yes' if not missing else 'NO'} | {', '.join(missing) or '-'} | "
                  f"{spare} | {', '.join(f'{k}={v}' for k, v in chosen.items())} |")
        if pkg in ("LQFP100", "LQFP64", "LQFP80"):
            csv_path = outdir / f"pin_allocation_{ref.replace('(', '').replace(')', '').replace('-', '')}.csv"
            with csv_path.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["function", "pin", "position", "signal", "note", "status"])
                for fn, (p, s, note) in sorted(assign.items(), key=lambda kv: int(kv[1][0]["pos"]) if kv[1][0]["pos"].isdigit() else 0):
                    w.writerow([fn, p["name"], p["pos"], s, note, "CANDIDATE - AF/timing not verified"])
            details.append((ref, pkg, assign, missing))
    md += ["", "Proposed baseline package: **LQFP100 (STM32G474VET6-class)** - all functions allocate with spare I/O "
           "for revisions; LQFP64 is listed for comparison. Exact order code remains UNFROZEN.", ""]
    for ref, pkg, assign, missing in details:
        md += [f"## {ref} ({pkg})", "", "| function | pin | position | signal | note |", "|---|---|---|---|---|"]
        for fn, (p, s, note) in sorted(assign.items()):
            md.append(f"| {fn} | {p['name']} | {p['pos']} | {s} | {note} |")
        if missing:
            md.append(f"\n**Missing:** {', '.join(missing)}\n")
        md.append("")
    (ROOT / "docs" / "generated").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "generated" / "pin_allocation.md").write_text("\n".join(md))
    print("\n".join(md[:12 + len(files)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
