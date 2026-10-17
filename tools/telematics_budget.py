#!/usr/bin/env python3
"""Logging capacity, LTE data volume and auxiliary power for the combined
motor-controller + telematics architecture.

    python3 tools/telematics_budget.py   -> docs/generated/telematics_budget.md (+ .json)

Inputs and their status:
  [P]  protocol/protocol.yaml (this project's frozen v1 message set and periods): exact.
  [T]  telematics_overview / telematics_data_flow v0.1 (14/10/2026), the other engineer's PROPOSAL:
       STM32U575, QSPI flash 8 MB, optional microSD, CAN 2.0B, u-blox NEO-M9N class GNSS, 6-axis IMU,
       SIMCom A7672 LTE Cat-1, MQTT live 1-5 Hz downsampled. A design input, not built hardware.
  [A]  assumption of this analysis (stated; replace with the team's numbers).
  [R]  typical value recalled from component documentation, NOT yet verified against the datasheets.
Nothing here is a measurement. Battery voltage, BMS message set and node rates are UNKNOWN.
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "generated"

import sys  # noqa: E402
sys.path.insert(0, str(ROOT))
from protocol.generated import semmc_protocol as proto  # noqa: E402

FLASH_B = 8 * 1024 * 1024        # [T] "QSPI Flash 8 MB" (read as 8 MiB)
FLASH_USABLE = 0.90              # [A] metadata, spare blocks, wear levelling
REC_CAN_B = 16                   # [A] proposed raw record: u32 us timestamp, u16 id+flags, u8 dlc, u8 bus, 8 data
REC_GNSS_B = 32                  # [A] packed fix record
REC_IMU_B = 16                   # [A] 6 x i16 + u32 timestamp
ATTEMPTS_S = {"synthetic track model (1000 s limit)": 1000.0, "40 min attempt [A]": 2400.0}
SD_B = 32e9                      # [A] 32 GB card

# other bus nodes: (name, low frames/s, high frames/s) - ALL ASSUMED, no message definitions exist yet
OTHER_NODES = [("BMS (cell V, SOC, temps) [T] rates [A]", 10, 50),
               ("wheel speed node [T] rates [A]", 10, 100),
               ("driver input node (optional) [T] rates [A]", 10, 50)]
DIRECT = [("GNSS (NEO-M9N class) [T]", 1, 10, REC_GNSS_B), ("IMU 6-axis [T]", 50, 200, REC_IMU_B)]
DECIMATE_HZ = 10.0               # [A] logging rate for the 50/100 Hz controller messages in the reduced profile

# LTE / MQTT [A]
LTE_RATES_HZ = (1.0, 5.0)        # [T] "live, downsampled 1-5 Hz"
PAYLOAD_B = {"JSON, ~25 signals": 550, "packed binary, ~25 signals": 120}
OVERHEAD_B = 90                  # [A] MQTT + TCP/IP + TLS record per publish (ACKs not included)

# Auxiliary power, telematics unit: (item, rail V, low mA, high mA, tag)
AUX_TELEM = [
    ("STM32U575 running (SMPS/LDO dependent)", 3.3, 5, 25, "R"),
    ("GNSS receiver, continuous tracking", 3.3, 25, 40, "R"),
    ("active GNSS antenna", 3.3, 5, 20, "R"),
    ("IMU 6-axis", 3.3, 0.5, 1.5, "R"),
    ("CAN transceiver (bus-load dependent)", 5.0, 10, 50, "R"),
    ("QSPI flash, writing a few kB/s (average)", 3.3, 1, 8, "A"),
    ("microSD, if fitted (average)", 3.3, 0, 40, "A"),
    ("LTE Cat-1 modem, connected and publishing at 1-5 Hz (average)", 3.8, 60, 250, "R"),
    ("status LED + LED bar (burn/coast display)", 3.3, 2, 40, "A"),
]
AUX_MC = [  # motor-controller logic, excluding gate charge (MOSFETs unknown) and anything at battery voltage
    ("STM32G474 at 150-170 MHz", 3.3, 25, 60, "R"),
    ("CAN transceiver TJA1051-class", 5.0, 10, 70, "R"),
    ("INA228 + watchdog + logic + opto", 3.3, 2, 8, "R"),
    ("hall sensors (motor unknown)", 5.0, 0, 40, "A"),
]
ETA_DCDC = (0.85, 0.90)          # [A] buck efficiency (high, low load)
E_REF_J = 42.7e3                 # SYNTHETIC track A DP + driver guidance energy (docs/EFFICIENCY_RESEARCH.md); NOT our vehicle


def semmc_rates():
    rows = []
    for name, m in proto.MESSAGES.items():
        f = 1.0 / m["period_s"]
        rows.append((name, m["id"], m["sender"], f))
    return rows


def main() -> int:
    rows = semmc_rates()
    f_ctrl = sum(f for _n, _i, s, f in rows if s == "controller")
    f_sup = sum(f for _n, _i, s, f in rows if s != "controller")
    f_dec = sum(min(f, DECIMATE_HZ) for _n, _i, _s, f in rows)
    other_lo = sum(lo for _n, lo, _h in OTHER_NODES)
    other_hi = sum(hi for _n, _l, hi in OTHER_NODES)
    direct_lo = sum(lo * b for _n, lo, _h, b in DIRECT)
    direct_hi = sum(hi * b for _n, _l, hi, b in DIRECT)
    usable = FLASH_B * FLASH_USABLE
    profiles = {
        "semmc frames only (controller + supervisor), full rate": (f_ctrl + f_sup) * REC_CAN_B,
        "all CAN at full rate + direct sensors, LOW node rates": (f_ctrl + f_sup + other_lo) * REC_CAN_B + direct_lo,
        "all CAN at full rate + direct sensors, HIGH node rates": (f_ctrl + f_sup + other_hi) * REC_CAN_B + direct_hi,
        f"semmc decimated to <= {DECIMATE_HZ:g} Hz + others LOW + direct LOW": (f_dec + other_lo) * REC_CAN_B + direct_lo,
    }
    L = ["# Telematics logging capacity, LTE volume and auxiliary power (generated)", "",
         "> `tools/telematics_budget.py`. Tags: [P] this project's protocol (exact); [T] telematics proposal v0.1 "
         "(design input, not built); [A] assumption; [R] recalled typical value, NOT verified. Nothing here is a "
         "measurement. Other nodes' message sets do not exist yet, so their rates are assumed ranges.", "",
         "## 1. Frame rates", "",
         "| Source | Frames/s | Basis |", "|---|---|---|",
         f"| semmc controller -> bus (12 messages) | {f_ctrl:.0f} | [P] periods in protocol.yaml |",
         f"| supervisor -> controller (hello, limits, torque request, CSIA advisory) | {f_sup:.0f} | [P]; sent by whichever computer runs the supervisor |"]
    for n, lo, hi in OTHER_NODES:
        L.append(f"| {n} | {lo}-{hi} | assumed |")
    for n, lo, hi, b in DIRECT:
        L.append(f"| {n}, not on CAN, {b} B records | {lo}-{hi} | [A] |")
    L += ["", f"Raw CAN log record: {REC_CAN_B} B [A] (u32 microsecond timestamp, u16 id + flags, u8 DLC, u8 bus, "
          "8 data bytes; a periodic 64-bit time marker handles the 71-minute wrap). "
          f"QSPI flash {FLASH_B/2**20:.0f} MiB [T], {100*FLASH_USABLE:.0f} % usable [A] = {usable/1e6:.2f} MB.", "",
          "## 2. Local logging capacity", "",
          "| Logging profile | Bytes/s | QSPI flash lasts | " + " | ".join(f"fits {k}?" for k in ATTEMPTS_S) +
          " | microSD 32 GB [A] lasts |", "|---|---|---|" + "---|" * len(ATTEMPTS_S) + "---|"]
    cap = {}
    for k, bps in profiles.items():
        t = usable / bps
        cap[k] = {"bytes_per_s": bps, "flash_s": t}
        fits = " | ".join("yes" if t >= d else f"**no** ({100*t/d:.0f} %)" for d in ATTEMPTS_S.values())
        L.append(f"| {k} | {bps:,.0f} | {t/60:.1f} min | {fits} | {SD_B/bps/3600:,.0f} h |")
    L += ["", "* **The proposed 8 MB QSPI flash cannot hold one 40-minute attempt of the controller's frames at full "
          "rate**, before any other node is added. Options, in order of simplicity: make the microSD (shown optional "
          "in the proposal) the raw log and keep the QSPI flash for a decimated summary; log the 50-100 Hz controller "
          "messages at a reduced rate (row 4); or a larger flash. The controller's own rates can also be reduced, but "
          "that changes supervisor freshness margins (`docs/ICD.md` section 5) and needs the hazard analysis.",
          "* Flash write bandwidth and endurance are not limiting at a few kB/s (NOR page program and sector erase "
          "rates are orders of magnitude higher [R]); the binding constraint is capacity.", ""]
    # LTE
    L += ["## 3. LTE / MQTT volume (live, downsampled) [T][A]", "",
          "| Payload | Rate | Bytes per publish incl. overhead | kB per hour | MB per 40 min attempt |",
          "|---|---|---|---|---|"]
    lte = {}
    for pk, pb in PAYLOAD_B.items():
        for hz in LTE_RATES_HZ:
            per = pb + OVERHEAD_B
            lte[f"{pk} @ {hz:g} Hz"] = per * hz
            L.append(f"| {pk} | {hz:g} Hz | {per} | {per*hz*3600/1e3:,.0f} | {per*hz*2400/1e6:.2f} |")
    L += ["", "Volume is small for any Cat-1 plan. The cost is energy (section 4): a modem kept connected to publish "
          "every 0.2-1 s rarely reaches its low-power states. Batching (for example one publish every 10 s carrying "
          "10-50 samples) keeps the same data with far less radio-on time.", ""]
    # power
    def table(items, title):
        lo = hi = 0.0
        out = [f"### {title}", "", "| Item | Rail | Current (mA) | Power (mW) | Basis |", "|---|---|---|---|---|"]
        for n, v, a, b, tag in items:
            lo += v * a
            hi += v * b
            out.append(f"| {n} | {v:g} V | {a:g}-{b:g} | {v*a:.0f}-{v*b:.0f} | [{tag}] |")
        lo_in, hi_in = lo / ETA_DCDC[1], hi / ETA_DCDC[0]
        out += [f"| **total at the rails** | | | **{lo:.0f}-{hi:.0f}** | |",
                f"| **at the input, DC-DC {100*ETA_DCDC[0]:.0f}-{100*ETA_DCDC[1]:.0f} % [A]** | | | **{lo_in:.0f}-{hi_in:.0f}** | |", ""]
        return out, lo_in / 1e3, hi_in / 1e3
    t1, tl, th = table(AUX_TELEM, "Telematics unit (as proposed)")
    t2, ml, mh = table(AUX_MC, "Motor-controller logic (excludes gate-drive power and battery-voltage loads: MOSFETs and battery unknown)")
    L += ["## 4. Auxiliary power and energy per attempt", ""] + t1 + t2
    L += ["| Load | Power (W) | Energy, 1000 s | Energy, 2400 s | Share of 42.7 kJ (SYNTHETIC track A, not our vehicle) |",
          "|---|---|---|---|---|"]
    energy = {}
    for name, lo, hi in (("telematics unit", tl, th), ("motor-controller logic", ml, mh), ("both", tl + ml, th + mh)):
        energy[name] = (lo, hi)
        L.append(f"| {name} | {lo:.2f}-{hi:.2f} | {lo*1:.2f}-{hi*1:.2f} kJ | {lo*2.4:.2f}-{hi*2.4:.2f} kJ | "
                 f"{100*lo*1e3/E_REF_J:.1f}-{100*hi*1e3/E_REF_J:.1f} % (1000 s) |")
    L += ["", "* Excluded and still unknown: gate-drive power (Q_g x V_GS x f_PWM x 6, MOSFETs not selected), the gate "
          "driver's supply current at battery voltage, and the BMS's own consumption.",
          "* **Whether this energy counts against the vehicle depends on where the joulemeter sits** and what the 2027 "
          "rules require for auxiliary systems. Both are open questions (input sheet B3, R1). If it counts, the "
          f"telematics unit is a first-order term: about {100*tl*1e3/E_REF_J:.0f}-{100*th*1e3/E_REF_J:.0f} % of a synthetic "
          "1000 s attempt's energy, dominated by the LTE modem's duty cycle.",
          "* Measure, do not trust this table: bench-measure each board's input power with the modem in its real "
          "publishing pattern before deciding.", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "telematics_budget.md").write_text("\n".join(L))
    (OUT / "telematics_budget.json").write_text(json.dumps(
        {"frames_per_s": {"controller": f_ctrl, "supervisor": f_sup, "others_low": other_lo, "others_high": other_hi},
         "logging": cap, "lte_bytes_per_s": lte, "aux_power_W": energy}, indent=1))
    print(f"controller {f_ctrl:.0f} f/s, supervisor {f_sup:.0f} f/s; flash lasts "
          f"{cap['semmc frames only (controller + supervisor), full rate']['flash_s']/60:.1f} min for semmc frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
