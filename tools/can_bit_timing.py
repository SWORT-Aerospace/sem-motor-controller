#!/usr/bin/env python3
"""FDCAN bit timing for the Cornell CHUDS CAN-FD bus (REFERENCE project; superseded, see clock_tree.py).

    python3 tools/can_bit_timing.py   -> docs/generated/can_bit_timing.md

The bus is CAN FD: 500 kbit/s nominal and 2 Mbit/s data, both at an 80 %
sample point. Source: urban-concept@c422c0f, cev-lib/chuds/frame.hpp:16-19 and
tools/can_link_args.cpp. EVERY node on an FD bus must sample the data phase
correctly, including a node that transmits only classic frames. If it did not,
it would see CRC errors in every FD frame and send error frames. So the
controller's FDCAN runs with FD operation enabled and a data-phase timing
matching the bus.

STM32G4 FDCAN field limits are recalled (RM0440 not readable here) [R]:
NBRP 1..512, NTSEG1 1..256 (incl. propagation), NTSEG2 1..128;
DBRP 1..32, DTSEG1 1..32, DTSEG2 1..16.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOM_BPS, DATA_BPS, SP = 500_000, 2_000_000, 0.80
LIM = {"nominal": (512, 256, 128), "data": (32, 32, 16)}


def best(f_ker: float, bps: int, phase: str):
    brp_max, s1_max, s2_max = LIM[phase]
    best_ = None
    for brp in range(1, brp_max + 1):
        tq = f_ker / brp / bps
        if abs(tq - round(tq)) > 1e-9:
            continue
        n = int(round(tq))
        if n < 4:
            continue
        for s2 in range(1, s2_max + 1):
            s1 = n - 1 - s2
            if not (1 <= s1 <= s1_max):
                continue
            sp = (1 + s1) / n
            cand = (abs(sp - SP), -n, brp, s1, s2, sp)
            if best_ is None or cand < best_:
                best_ = cand
    if best_ is None:
        return None
    _, mn, brp, s1, s2, sp = best_
    return {"brp": brp, "tq_per_bit": -mn, "tseg1": s1, "tseg2": s2, "sample_point": sp}


def main() -> int:
    clocks = {"HSE 8 MHz (v0.2 draft crystal)": 8e6, "PLLQ 42.5 MHz (from 170 MHz VCO/8)": 42.5e6,
              "PLLQ 85 MHz": 85e6, "HSE 20 MHz": 20e6, "HSE 40 MHz": 40e6, "HSE 24 MHz": 24e6}
    L = ["# FDCAN bit timing for the CHUDS CAN-FD bus (generated)", "",
         "> `tools/can_bit_timing.py`. Bus parameters from Cornell `urban-concept@c422c0f` "
         "`cev-lib/chuds/frame.hpp:16-19` and `tools/can_link_args.cpp`: 500 kbit/s nominal and 2 Mbit/s data, "
         "both at an 80 % sample point, `fd on`. STM32G4 FDCAN field limits are recalled [R], not read from RM0440.", "",
         "| FDCAN kernel clock | nominal: BRP / tq / TSEG1 / TSEG2 / SP | data: BRP / tq / TSEG1 / TSEG2 / SP | both at exactly 80 %? |",
         "|---|---|---|---|"]
    for name, f in clocks.items():
        n, d = best(f, NOM_BPS, "nominal"), best(f, DATA_BPS, "data")
        fmt = lambda r: "impossible" if r is None else (  # noqa: E731
            f"{r['brp']} / {r['tq_per_bit']} / {r['tseg1']} / {r['tseg2']} / {100*r['sample_point']:.2f} %")
        ok = n is not None and d is not None and abs(n["sample_point"] - SP) < 1e-9 and abs(d["sample_point"] - SP) < 1e-9
        L.append(f"| {name} | {fmt(n)} | {fmt(d)} | {'**yes**' if ok else 'no'} |")
    L += ["", "**v0.3: the v0.2 conclusion drawn from this table (\"change the HSE crystal to 40 MHz\") is WITHDRAWN.** "
          "This table only considers kernel clocks taken directly from HSE or from a 170 MHz VCO. A complete analysis "
          "(PLL-derived kernel clocks, the FDCAN clock divider, other CPU frequencies, classic CAN 2.0B buses) is in "
          "`hardware/timing/clock_tree_alternatives.md`. The bus analysed here (CHUDS, 500k/2M FD) belongs to a "
          "REFERENCE project; our vehicle's bus is not confirmed, and the telematics proposal shows CAN 2.0B.", ""]
    (ROOT / "docs" / "generated" / "can_bit_timing.md").write_text("\n".join(L))
    print("\n".join(L[5:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
