#!/usr/bin/env python3
"""CAN bus-load and worst-case response-time (WCRT) estimate.

Classic-CAN response-time analysis after Davis, Burns, Bril & Lukkien (2007),
"Controller Area Network (CAN) schedulability analysis: Refuted, revisited and
revised", Real-Time Systems 35:239-272 (formulae used from memory of the
published method; not re-derived here):
    C_m  = (55 + 10 n) * tau_bit          worst-case 11-bit frame incl. stuffing + IFS
    B_m  = max C_k over lower-priority k  (non-preemptive blocking)
    w    = B_m + sum_{k in hp(m)} ceil((w + J_k + tau_bit) / T_k) * C_k
    R_m  = J_m + w + C_m                  (single-instance busy period; valid while U < 1)

A REFERENCE-PROJECT load case (v0.3 label): Cornell CHUDS frames (ids < 0x300,
CAN-FD with BRS 2 Mbit/s, from cornellev/urban-concept c422c0f, provisional
table). Our vehicle's bus and its other traffic are UNKNOWN. They are modelled
CONSERVATIVELY as if every bit were sent at the 500 kbit/s nominal rate with
their padded FD length. Their periods are from the audit where stated; the
BodyState period is ASSUMED 100 ms (not stated in the source).

This is a planning estimate for the pending hazard/latency analysis, not a
measurement. The 50 Hz / 100 ms supervisory timing remains provisional.
"""
from __future__ import annotations

import math
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "protocol" / "protocol.yaml"

# id, name, payload bytes (padded FD length for CHUDS), period s, source note
CHUDS_FRAMES = [
    (0x000, "chuds_stop (sporadic, assumed min 100 ms)", 8, 0.100, "assumed"),
    (0x108, "chuds_body_state", 8, 0.100, "period assumed"),
    (0x210, "chuds_front_aux", 12, 0.100, "audit: 100 ms"),
    (0x220, "chuds_back_aux", 12, 0.100, "audit: 100 ms"),
    (0x230, "chuds_joulemeter", 20, 0.500, "audit: 500 ms"),
]
JITTER_S = 0.001  # 1 ms slow-loop scheduling jitter on every sender (assumption)


def frame_time(n_bytes: int, bitrate: float) -> float:
    return (55 + 10 * n_bytes) / bitrate


def analyse(bitrate: float | None = None, include_chuds: bool = True) -> dict:
    spec = yaml.safe_load(SPEC.read_text())
    br = bitrate or spec["protocol"]["nominal_bitrate"]
    tau = 1.0 / br
    frames = []
    if include_chuds:
        for cid, name, n, T, note in CHUDS_FRAMES:
            frames.append({"id": cid, "name": name, "C": frame_time(n, br), "T": T, "J": JITTER_S, "ours": False,
                           "note": note})
    for m in spec["messages"]:
        frames.append({"id": m["id"], "name": m["name"], "C": frame_time(8, br), "T": m["period_s"],
                       "J": JITTER_S, "ours": True, "note": "provisional" if m.get("provisional") else ""})
    frames.sort(key=lambda f: f["id"])
    U = sum(f["C"] / f["T"] for f in frames)
    U_ours = sum(f["C"] / f["T"] for f in frames if f["ours"])
    out = []
    for i, f in enumerate(frames):
        hp = frames[:i]
        lp = frames[i + 1:]
        B = max((k["C"] for k in lp), default=0.0)
        w = B
        for _ in range(1000):
            w_new = B + sum(math.ceil((w + k["J"] + tau) / k["T"]) * k["C"] for k in hp)
            if abs(w_new - w) < 1e-12:
                break
            w = w_new
        R = f["J"] + w + f["C"]
        out.append({"id": f"0x{f['id']:03X}", "name": f["name"], "ours": f["ours"], "period_ms": f["T"] * 1e3,
                    "C_us": f["C"] * 1e6, "wcrt_ms": R * 1e3, "note": f["note"]})
    return {"bitrate": br, "utilisation": U, "semmc_utilisation": U_ours, "messages": out}


def main() -> int:
    r = analyse()
    print(f"Nominal bit rate {r['bitrate']/1e3:.0f} kbit/s; total utilisation {100*r['utilisation']:.1f} % "
          f"(semmc frames {100*r['semmc_utilisation']:.1f} %), plus a REFERENCE-PROJECT load case (Cornell CHUDS, "
          "modelled conservatively); our vehicle bus's other traffic is UNKNOWN.\n")
    print("| id | message | ours | period ms | C us | WCRT ms | note |")
    print("|---|---|---|---|---|---|---|")
    for m in r["messages"]:
        print(f"| {m['id']} | {m['name']} | {'yes' if m['ours'] else 'no'} | {m['period_ms']:.0f} | "
              f"{m['C_us']:.0f} | {m['wcrt_ms']:.2f} | {m['note']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
