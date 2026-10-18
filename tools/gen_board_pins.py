#!/usr/bin/env python3
"""Board pin header for the STM32G474VET6 target firmware, verified against ST's pin database.

    python3 tools/gen_board_pins.py           # write the header and the report
    python3 tools/gen_board_pins.py --check   # fail if either differs from the committed file

Inputs:
  hardware/interfaces/pin_allocation_STM32G474VBCETx.csv    the schematic's pin map (tools/pin_allocation.py)
  hardware/interfaces/st_open_pin_data/                      two files of ST's STM32_open_pin_data
      mcu/STM32G474V(B-C-E)Tx.xml                            pins, positions and the signals each pin carries
      mcu/IP/GPIO-STM32G47x_gpio_v1_0_Modes.xml              the alternate-function number of each pin signal

For every function the tool checks that the pin exists at the stated LQFP100 position, that ST lists
the signal on that pin, and, for digital peripheral signals, takes the AF number from ST's GPIO table
(the table STM32CubeMX uses). Analog functions are checked against the pin's ADC channel list.

Outputs:
  firmware/platform/stm32g4/src/board_pins_generated.h      pin, mode, AF, initial level per function
  docs/generated/pin_af_verification.md                     the verification table with its sources

What this does not check: electrical characteristics (5 V tolerance, drive strength), ADC sampling
time against source impedance, and errata. Those need DS12288 and ES0430.
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSV = ROOT / "hardware/interfaces/pin_allocation_STM32G474VBCETx.csv"
DB = ROOT / "hardware/interfaces/st_open_pin_data"
MCU_XML = DB / "mcu/STM32G474V(B-C-E)Tx.xml"
GPIO_XML = DB / "mcu/IP/GPIO-STM32G47x_gpio_v1_0_Modes.xml"
ST_COMMIT = "7d1f1514ed5583ec5007ad91236b4e1d377295b1"
HEADER = ROOT / "firmware/platform/stm32g4/src/board_pins_generated.h"
REPORT = ROOT / "docs/generated/pin_af_verification.md"
NS = {"st": "http://dummy.com"}

# Direction and level of each plain GPIO function, from the schematic sheets (hardware/README.md).
# Outputs start at the level that keeps power and gate drive off; inputs have external pull resistors.
GPIO_OUT = {
    "PRECHG_EN": 0,        # bypass MOSFET off (100 k pull-down on the board too)
    "DRV_ENABLE": 0,       # gate driver disabled (AND gate with HW_PERMIT, pull-down on the board)
    "DRV_SPI_NSS": 1,      # SPI chip select inactive
    "EXT_WDG_WDI": 0,      # watchdog input; toggled by the slow loop
    "LED_STATUS": 0,
    "LED_FAULT": 0,
}
GPIO_IN = {"EXT_WDG_RST_SENSE", "OUTPUT_ENABLE_FEEDBACK", "ECO_CANCEL", "BRAKE_SWITCH", "FAULT_RESET",
           "INA_ALERT", "ESTOP_CHAIN_SENSE", "ARM_SWITCH", "DEADMAN_SENSE", "MODE_SWITCH", "DRV_NFAULT"}


def load_csv() -> list[dict]:
    with CSV.open() as f:
        return list(csv.DictReader(f))


def load_mcu() -> dict:
    root = ET.parse(MCU_XML).getroot()
    pins = {}
    for p in root.findall("st:Pin", NS):
        pins[p.get("Name")] = {"position": p.get("Position"), "type": p.get("Type"),
                               "signals": [s.get("Name") for s in p.findall("st:Signal", NS)]}
    return pins


def load_af() -> dict:
    root = ET.parse(GPIO_XML).getroot()
    af = {}
    for gp in root.findall("st:GPIO_Pin", NS):
        name = gp.get("Name")
        for sig in gp.findall("st:PinSignal", NS):
            vals = [v.text for v in sig.findall("st:SpecificParameter/st:PossibleValue", NS)]
            for v in vals:
                m = re.fullmatch(r"GPIO_AF(\d+)_\w+", v or "")
                if m:
                    af[(name, sig.get("Name"))] = (int(m.group(1)), v)
    return af


def classify(row: dict) -> str:
    sig = row["signal"]
    if sig.startswith("ADC"):
        return "analog"
    if sig == "GPIO":
        if row["function"] in GPIO_OUT:
            return "output"
        if row["function"] in GPIO_IN:
            return "input"
        raise SystemExit(f"{row['function']}: GPIO direction not declared in tools/gen_board_pins.py")
    return "af"


def build() -> tuple[str, str, list[str]]:
    rows, pins, af = load_csv(), load_mcu(), load_af()
    errors, entries = [], []
    for r in rows:
        func, pin, pos, sig = r["function"], r["pin"], r["position"], r["signal"]
        mode = classify(r)
        p = pins.get(pin)
        ok_pos = p is not None and p["position"] == pos
        if not ok_pos:
            errors.append(f"{func}: {pin} not at position {pos} in {MCU_XML.name}")
        afn, afname = None, ""
        if mode == "af":
            if p is None or sig not in p["signals"]:
                errors.append(f"{func}: {sig} not listed on {pin}")
            hit = af.get((pin, sig))
            if hit is None:
                errors.append(f"{func}: no alternate function for {sig} on {pin} in {GPIO_XML.name}")
            else:
                afn, afname = hit
        elif mode == "analog":
            if p is None or sig not in p["signals"]:
                errors.append(f"{func}: {sig} not listed on {pin}")
        m = re.fullmatch(r"P([A-G])(\d+)", pin)
        if not m:
            errors.append(f"{func}: pin name {pin} is not a plain port pin")
            continue
        entries.append({"func": func, "pin": pin, "port": m.group(1), "num": int(m.group(2)), "pos": pos, "sig": sig,
                        "mode": mode, "af": afn, "afname": afname, "level": GPIO_OUT.get(func)})
    return render_header(entries), render_report(entries, errors), errors


def render_header(entries: list[dict]) -> str:
    L = ["/* Generated by tools/gen_board_pins.py from hardware/interfaces/pin_allocation_STM32G474VBCETx.csv",
         f" * and ST's STM32_open_pin_data@{ST_COMMIT[:7]}. Do not edit. */",
         "#ifndef BOARD_PINS_GENERATED_H", "#define BOARD_PINS_GENERATED_H", "",
         "#include <stdint.h>", "",
         "typedef enum { BOARD_MODE_INPUT = 0, BOARD_MODE_OUTPUT = 1, BOARD_MODE_AF = 2, BOARD_MODE_ANALOG = 3 } board_mode_t;", "",
         "typedef struct {",
         "    uint8_t port;      /* 0 = A ... 6 = G */",
         "    uint8_t pin;",
         "    uint8_t mode;      /* board_mode_t */",
         "    uint8_t af;        /* alternate function number for BOARD_MODE_AF */",
         "    uint8_t level;     /* initial output level for BOARD_MODE_OUTPUT */",
         "} board_pin_t;", ""]
    for e in entries:
        L.append(f"#define BOARD_{e['func']}_PORT {ord(e['port']) - ord('A')}u  /* P{e['port']} */")
        L.append(f"#define BOARD_{e['func']}_PIN {e['num']}u")
    L += ["", f"#define BOARD_PIN_COUNT {len(entries)}u", "",
          "/* Every allocated pin, in the order of the pin map. Pins not listed stay in their reset state",
          " * (analog, no pull), as the schematic leaves them unconnected. */",
          "static const board_pin_t board_pins[BOARD_PIN_COUNT] = {"]
    modes = {"input": "BOARD_MODE_INPUT", "output": "BOARD_MODE_OUTPUT", "af": "BOARD_MODE_AF", "analog": "BOARD_MODE_ANALOG"}
    for e in entries:
        L.append(f"    {{{ord(e['port']) - ord('A')}u, {e['num']}u, {modes[e['mode']]}, {e['af'] or 0}u, {e['level'] or 0}u}},"
                 f"  /* {e['func']}: {e['pin']} {e['sig']} */")
    L += ["};", "", "#endif /* BOARD_PINS_GENERATED_H */", ""]
    return "\n".join(L)


def render_report(entries: list[dict], errors: list[str]) -> str:
    L = ["# STM32G474VET6 pin map: alternate functions verified against ST's pin database", "",
         "Generated by `tools/gen_board_pins.py`; do not edit.", "",
         f"Source: ST `STM32_open_pin_data` at commit `{ST_COMMIT}` (BSD-3-Clause), the database STM32CubeMX uses; "
         "the two files read are vendored in `hardware/interfaces/st_open_pin_data/`. "
         "Checked for each function: the pin is at the stated LQFP100 position, ST lists the signal on the pin, and "
         "the alternate-function number is ST's. Not checked here: 5 V tolerance, drive strength, ADC sampling time "
         "against source impedance, errata (DS12288, ES0430).", "",
         f"Result: **{len(entries)} functions, {len(errors)} errors**.", ""]
    if errors:
        L += ["Errors:", ""] + [f"- {e}" for e in errors] + [""]
    L += ["| Function | Pin | Position | Signal | Mode | AF (ST) | Initial level |", "|---|---|---|---|---|---|---|"]
    for e in entries:
        afcol = f"AF{e['af']} (`{e['afname']}`)" if e["mode"] == "af" else "-"
        lvl = "-" if e["level"] is None else str(e["level"])
        L.append(f"| {e['func']} | {e['pin']} | {e['pos']} | {e['sig']} | {e['mode']} | {afcol} | {lvl} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    header, report, errors = build()
    if a.check:
        bad = [p for p, text in ((HEADER, header), (REPORT, report)) if not p.exists() or p.read_text() != text]
        for p in bad:
            print(f"OUT OF DATE: {p.relative_to(ROOT)}")
        if errors:
            print("\n".join(errors))
        return 1 if bad or errors else 0
    HEADER.parent.mkdir(parents=True, exist_ok=True)
    HEADER.write_text(header)
    REPORT.write_text(report)
    print(f"wrote {HEADER.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}: {len(errors)} errors")
    for e in errors:
        print("ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
