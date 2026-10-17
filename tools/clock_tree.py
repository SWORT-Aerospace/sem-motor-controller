#!/usr/bin/env python3
"""STM32G474 clock-tree alternatives and CAN bit timing, per candidate bus.

    python3 tools/clock_tree.py   -> hardware/timing/clock_tree_alternatives.md (+ .json)

Why this exists: v0.2 claimed that "CAN FD requires a 40 MHz crystal". That
claim only looked at HSE used directly and at the 170 MHz PLL outputs. It is
withdrawn. This tool enumerates complete clock trees (HSE -> PLL -> SYSCLK,
TIM1, ADC and FDCAN kernel clocks) within the register ranges ST publishes,
then computes the bit timing and the oscillator-tolerance limit for each bus
case. Receiving CAN correctly needs an exact bit rate and a valid timing;
matching another node's sample point is a robustness preference. The two are
reported separately.

Evidence tags:
  [S]  ST source code: STM32CubeG4 HAL/LL driver and CMSIS device header,
       STMicroelectronics/stm32g4xx_hal_driver @a6001282 and
       STMicroelectronics/cmsis_device_g4 @626ee412 (file:line in the report).
  [Sc] a comment in that ST source (weaker than a macro or register width).
  [R]  recalled from DS12288 / RM0440 / ISO 11898-1, NOT yet verified against
       the datasheet.
  [A]  assumption of this analysis (stated, adjustable).
Where [Sc] and [R] disagree, the narrower range is used and both are shown.
"""
from __future__ import annotations

import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "timing"

HAL = "stm32g4xx_hal_driver@a6001282"
CMSIS = "cmsis_device_g4@626ee412"
LIMITS = {
    "PLLM": ((1, 16), "S", f"{HAL} Inc/stm32g4xx_hal_rcc.h:3285 IS_RCC_PLLM_VALUE"),
    "PLLN": ((8, 127), "S", f"{HAL} Inc/stm32g4xx_hal_rcc.h:3287 IS_RCC_PLLN_VALUE"),
    "PLLP": ((2, 31), "S", f"{HAL} Inc/stm32g4xx_hal_rcc.h:3289 IS_RCC_PLLP_VALUE"),
    "PLLQ/PLLR": ((2, 4, 6, 8), "S", f"{HAL} Inc/stm32g4xx_hal_rcc.h:3291-3295"),
    "VCO input (Hz)": ((2.66e6, 8e6), "Sc",
                       f"{HAL} Inc/stm32g4xx_hal_rcc.h:2972-2973 says 2.66-8 MHz; DS12288 recalled as 2.66-16 MHz [R]. "
                       "Narrower range used."),
    "VCO output (Hz)": ((96e6, 344e6), "Sc",
                        f"{HAL} Inc/stm32g4xx_hal_rcc.h:3000-3001 says 64-344 MHz; DS12288 recalled as 96-344 MHz [R]. "
                        "Narrower range used."),
    "SYSCLK max (Hz)": ((150e6, 170e6), "Sc",
                        f"{HAL} Inc/stm32g4xx_hal_pwr_ex.h:640-645: range 1 up to 150 MHz, range 1 BOOST up to 170 MHz"),
    "HSE crystal (Hz)": ((4e6, 48e6), "Sc", f"{HAL} Src/stm32g4xx_hal_rcc.c:134 '4 to 48 MHz crystal'"),
    "FDCAN kernel sources": (("HSE", "PLL Q", "PCLK1"), "S",
                             f"{HAL} Inc/stm32g4xx_ll_rcc.h:420-422; {CMSIS} RCC_CCIPR_FDCANSEL (bits 25:24)"),
    "FDCAN kernel divider": ((1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30), "S",
                             f"{HAL} Inc/stm32g4xx_hal_fdcan.h:560-575 FDCAN_CLOCK_DIVx (FDCAN_CKDIV, common to all instances)"),
    "FDCAN kernel max (Hz)": ((48e6,), "Sc",
                              f"{HAL} Inc/stm32g4xx_hal_rcc.h:3045-3046 '48M1CLK ... FDCAN (<=48 MHz)'. Possibly inherited "
                              "from another family; not confirmed by any register limit. Treated as UNVERIFIED: options "
                              "above 48 MHz are flagged, not excluded."),
    "Nominal BRP/TSEG1/TSEG2/SJW": (((1, 512), (1, 256), (1, 128), (1, 128)), "S",
                                    f"{HAL} Inc/stm32g4xx_hal_fdcan.h:1325-1328; {CMSIS} FDCAN_NBTP field widths 9/8/7/7 bits"),
    "Data BRP/TSEG1/TSEG2/SJW": (((1, 32), (1, 32), (1, 16), (1, 16)), "S",
                                 f"{HAL} Inc/stm32g4xx_hal_fdcan.h:1329-1332; {CMSIS} FDCAN_DBTP field widths 5/5/4/4 bits"),
    "ADC kernel sources": (("PLL P", "SYSCLK", "HCLK/1,/2,/4 synchronous"), "S",
                           f"{HAL} Inc/stm32g4xx_ll_rcc.h:449-451 (ADC12SEL); CKMODE synchronous modes [R]"),
    "ADC clock max (Hz)": ((60e6,), "R", "DS12288 ADC characteristics, recalled; NOT verified"),
    "TIM1 clock": (("= PCLK2 x1 when APB2 prescaler is 1",), "R", "RM0440 RCC timer clock rule, recalled"),
}
VCO_IN = LIMITS["VCO input (Hz)"][0]
VCO_OUT = LIMITS["VCO output (Hz)"][0]
QR = LIMITS["PLLQ/PLLR"][0]
CKDIV = LIMITS["FDCAN kernel divider"][0]
F_ADC_MAX = 60e6

# ---- bus cases ------------------------------------------------------------------------------------
# Our vehicle's bus is UNKNOWN. The telematics proposal (v0.1, 14/10/2026) shows CAN 2.0B with no bit
# rate; the reference project (Cornell CHUDS) uses CAN FD 500k/2M at 80 %/80 %.
BUS_CASES = [
    {"key": "C500", "label": "CAN 2.0B 500 kbit/s (telematics proposal: CAN 2.0B, bit rate not stated)",
     "nominal": 500e3, "sp": 0.875, "data": None, "provenance": "Proposed design input (rate assumed)"},
    {"key": "C250", "label": "CAN 2.0B 250 kbit/s", "nominal": 250e3, "sp": 0.875, "data": None,
     "provenance": "Alternative (rate assumed)"},
    {"key": "C1M", "label": "CAN 2.0B 1 Mbit/s", "nominal": 1e6, "sp": 0.75, "data": None,
     "provenance": "Alternative (rate assumed)"},
    {"key": "FD", "label": "CAN FD 500 kbit/s / 2 Mbit/s, 80 % / 80 % (REFERENCE project only)", "nominal": 500e3,
     "sp": 0.80, "data": 2e6, "dsp": 0.80, "provenance": "Observed in a reference project (Cornell CHUDS)"},
]
# Propagation assumption for the nominal-phase tolerance formula (PS1 excludes the propagation segment).
T_LOOP_S = 255e-9          # [R] transceiver loop delay class (TJA1051-type); verify with the selected transceiver
CABLE_M = 10.0             # [A] worst-case bus length; harness unknown
T_PROP_S = 2 * (T_LOOP_S + CABLE_M * 5e-9)
OSC_BUDGET = 100e-6        # [A] crystal initial + temperature + ageing budget, both nodes combined per node


def timing(f_ker: float, bps: float, sp: float, data: bool, brp_only: int | None = None):
    """Best exact timing for one phase: minimise |SP error|, prefer more tq. Returns dict or None."""
    (brp_r, s1_r, s2_r, sjw_r) = (LIMITS["Data BRP/TSEG1/TSEG2/SJW"] if data else LIMITS["Nominal BRP/TSEG1/TSEG2/SJW"])[0]
    best = None
    for brp in ([brp_only] if brp_only else range(brp_r[0], brp_r[1] + 1)):
        n = f_ker / brp / bps
        if abs(n - round(n)) > 1e-9:
            continue
        n = int(round(n))
        if n < (5 if data else 8):
            continue
        for s2 in range(s2_r[0], s2_r[1] + 1):
            s1 = n - 1 - s2
            if not s1_r[0] <= s1 <= s1_r[1]:
                continue
            spa = (1 + s1) / n
            key = (round(abs(spa - sp), 9), -n)
            if best is None or key < best[0]:
                best = (key, {"brp": brp, "tq": n, "tseg1": s1, "tseg2": s2, "sp": spa,
                              "sjw": min(s2, sjw_r[1]), "tq_s": brp / f_ker})
    return None if best is None else best[1]


def tolerance(nom: dict, dat: dict | None):
    """ISO 11898-1 oscillator-tolerance conditions. Classic: (I) SJW/(20 NBT); (II) min(PS1,PS2)/(2(13 NBT-PS2)),
    with PS1 = TSEG1 - propagation segment. FD data phase: (III) DSJW/(20 DBT). The further FD conditions of
    ISO 11898-1:2015 (bit-rate switch transitions) are NOT computed here [R] and must be checked with the standard."""
    nbt = nom["tq"]
    prop_tq = math.ceil(T_PROP_S / nom["tq_s"])
    ps1 = nom["tseg1"] - prop_tq
    ps2 = nom["tseg2"]
    if ps1 < 1:
        return {"df_max": 0.0, "limit": "propagation segment does not fit", "prop_tq": prop_tq}
    c = {"I": nom["sjw"] / (20 * nbt), "II": min(ps1, ps2) / (2 * (13 * nbt - ps2))}
    if dat:
        c["III"] = dat["sjw"] / (20 * dat["tq"])
    k = min(c, key=c.get)
    return {"df_max": c[k], "limit": k, "prop_tq": prop_tq, "conds": c}


def pll_configs(hse: float, sysclk: float):
    for m in range(1, 17):
        vin = hse / m
        if not VCO_IN[0] <= vin <= VCO_IN[1]:
            continue
        for n in range(8, 128):
            vco = vin * n
            if not VCO_OUT[0] <= vco <= VCO_OUT[1]:
                continue
            for r in QR:
                if abs(vco / r - sysclk) < 1.0:
                    yield {"M": m, "N": n, "R": r, "vco": vco, "vin": vin}


def kernel_options(hse: float, sysclk: float, vco: float):
    srcs = [("HSE", hse)] + [(f"PLLQ (VCO/{q})", vco / q) for q in QR] + [("PCLK1 (=SYSCLK)", sysclk)]
    seen = set()
    for name, f in srcs:
        for d in CKDIV:
            fk = f / d
            if fk < 1e6 or (round(fk), name.split()[0]) in seen:
                continue
            seen.add((round(fk), name.split()[0]))
            yield (f"{name}" + (f" / CKDIV {d}" if d > 1 else ""), fk)


def evaluate(hse: float, sysclk: float, pll: dict, case: dict):
    best = None
    for kname, fk in kernel_options(hse, sysclk, pll["vco"]):
        pairs = []
        if case["data"]:
            # independent prescalers, and every shared prescaler (same time quantum in both phases)
            pairs.append((timing(fk, case["nominal"], case["sp"], False), timing(fk, case["data"], case["dsp"], True)))
            for brp in range(1, 33):
                pairs.append((timing(fk, case["nominal"], case["sp"], False, brp),
                              timing(fk, case["data"], case["dsp"], True, brp)))
        else:
            pairs.append((timing(fk, case["nominal"], case["sp"], False), None))
        for nom, dat in pairs:
            if nom is None or (case["data"] and dat is None):
                continue
            cand = _candidate(kname, fk, nom, dat, case)
            if best is None or cand[0] < best[0]:
                best = cand
    return None if best is None else best[1]


def _candidate(kname, fk, nom, dat, case):
    tol = tolerance(nom, dat)
    sp_err = abs(nom["sp"] - case["sp"]) + (abs(dat["sp"] - case["dsp"]) if dat else 0.0)
    same_tq = dat is None or abs(nom["tq_s"] - dat["tq_s"]) < 1e-15
    # Order: feasible first; for FD, the same time quantum in both phases and a data prescaler <= 2
    # (CiA 601-3 practice [R]); kernel <= 48 MHz (unverified note); then sample-point error; then tolerance.
    key = (tol["df_max"] <= 0.0, not same_tq, bool(dat) and dat["brp"] > 2, fk > 48e6,
           round(sp_err, 6), -tol["df_max"])
    cand = {"kernel": kname, "f_kernel": fk, "nominal": nom, "data": dat, "tol": tol, "sp_err": sp_err,
            "same_tq": same_tq, "above_48MHz": fk > 48e6}
    return (key, cand)


def adc_clock(sysclk: float, vco: float):
    """Fastest ADC kernel clock <= 60 MHz [R] from PLLP, or synchronous HCLK/2, /4."""
    opts = [(f"PLLP (VCO/{p})", vco / p) for p in range(2, 32)] + [("HCLK/2 sync", sysclk / 2), ("HCLK/4 sync", sysclk / 4)]
    ok = [o for o in opts if o[1] <= F_ADC_MAX + 1]
    return max(ok, key=lambda o: o[1])


def dtg(t_dead: float, f_tim: float):
    """TIM1 BDTR.DTG encoding [R RM0440] with tDTS = 1/f_tim (CKD = 0). Returns (code, achieved s)."""
    t = 1 / f_tim
    best = None
    for code in range(256):
        if code < 128:
            v = code * t
        elif code < 192:
            v = (64 + (code & 63)) * 2 * t
        elif code < 224:
            v = (32 + (code & 31)) * 8 * t
        else:
            v = (32 + (code & 31)) * 16 * t
        if v >= t_dead - 1e-12 and (best is None or v < best[1]):
            best = (code, v)
    return best


def main() -> int:
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "vehicle.synthetic.yaml").read_text())
    f_pwm = float(cfg["inverter"]["pwm_frequency_Hz"])
    t_dead = float(cfg["inverter"]["deadtime_s"])
    hses = [8e6, 12e6, 16e6, 20e6, 24e6, 25e6, 40e6]
    sysclks = [170e6, 160e6, 150e6, 144e6]
    rows = []
    for hse in hses:
        for sc in sysclks:
            plls = list(pll_configs(hse, sc))
            if not plls:
                rows.append({"hse": hse, "sysclk": sc, "pll": None})
                continue
            # prefer the lowest VCO input divider that keeps a high VCO-input frequency (less jitter) [A]
            pll = max(plls, key=lambda p: (p["vin"], -p["M"]))
            row = {"hse": hse, "sysclk": sc, "pll": pll, "boost": sc > 150e6,
                   "f_tim1": sc, "adc": adc_clock(sc, pll["vco"]),
                   "pwm_counts": sc / (2 * f_pwm), "dtg": dtg(t_dead, sc),
                   "cycles_per_pwm": sc / f_pwm, "bus": {}}
            for case in BUS_CASES:
                row["bus"][case["key"]] = evaluate(hse, sc, pll, case)
            rows.append(row)

    mhz = lambda f: f"{f/1e6:g}"  # noqa: E731
    L = ["# STM32G474 clock-tree alternatives and CAN bit timing (generated)", "",
         "> `tools/clock_tree.py`. **No crystal is selected by this report.** The vehicle bus is UNKNOWN: the telematics "
         "proposal (v0.1, 14/10/2026) shows CAN 2.0B without a bit rate; CAN FD 500k/2M is only observed in a reference "
         "project. Select the crystal after the bus and the full timing requirements are confirmed.", "",
         "> **The v0.2 statement \"CAN FD requires a 40 MHz crystal\" is withdrawn.** It considered only HSE used directly "
         "and the PLL outputs of a 170 MHz VCO. An 8 MHz crystal reaches 500k/2M at exactly 80 %/80 % with a 160 MHz CPU "
         "(PLLQ = 40 MHz); at 170 MHz it still gives exact 500k/2M timings, with fewer time quanta per data bit and a kernel "
         "above the unverified 48 MHz note (section 3).", "",
         "## 1. Constraints used and their evidence", "",
         "| Constraint | Value used | Evidence | Source |", "|---|---|---|---|"]
    for k, (v, tag, src) in LIMITS.items():
        vs = ", ".join(mhz(x) + " MHz" if isinstance(x, float) else str(x) for x in v) if not isinstance(v[0], tuple) else \
            "; ".join(f"{a}..{b}" for a, b in v)
        L.append(f"| {k} | {vs} | [{tag}] | {src} |")
    L += ["", f"Assumptions: propagation for the nominal phase = 2 x (transceiver loop {T_LOOP_S*1e9:.0f} ns [R] + "
          f"{CABLE_M:g} m x 5 ns/m [A]) = {T_PROP_S*1e9:.0f} ns; crystal budget {OSC_BUDGET*1e6:.0f} ppm per node [A]. "
          f"PWM {f_pwm/1e3:g} kHz centre-aligned and dead time {t_dead*1e9:.0f} ns from `config/vehicle.synthetic.yaml` (SYNTHETIC).", "",
          "## 2. Complete clock trees", "",
          "| HSE | SYSCLK = TIM1 | PLL M / N / R (VCO in, VCO) | boost | ADC kernel (<= 60 MHz [R]) | PWM counts per half-period | dead-time DTG | CPU cycles per PWM period |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["pll"] is None:
            L.append(f"| {mhz(r['hse'])} MHz | {mhz(r['sysclk'])} MHz | no integer PLL setting in range | | | | | |")
            continue
        p = r["pll"]
        code, ach = r["dtg"]
        L.append(f"| {mhz(r['hse'])} MHz | {mhz(r['sysclk'])} MHz | {p['M']} / {p['N']} / {p['R']} "
                 f"({p['vin']/1e6:.3g}, {p['vco']/1e6:.4g} MHz) | {'yes' if r['boost'] else 'no'} | "
                 f"{r['adc'][0]} = {r['adc'][1]/1e6:.4g} MHz | {r['pwm_counts']:.1f} | 0x{code:02X} = {ach*1e9:.1f} ns | "
                 f"{r['cycles_per_pwm']:.0f} |")
    L += ["", "## 3. CAN bit timing per bus case (best exact option per clock tree)", "",
          "Columns: FDCAN kernel clock; nominal BRP/tq/TSEG1/TSEG2/SJW and sample point; data phase likewise (FD only); "
          "whether both phases use the same time quantum (CiA 601-3 recommendation [R]); kernel above the unverified "
          "48 MHz note; tolerance limit df_max (and the binding condition); margin = df_max / crystal budget.", ""]
    for case in BUS_CASES:
        L += [f"### {case['label']}", f"Provenance: {case['provenance']}. Target sample point "
              f"{100*case['sp']:.1f} %" + (f", data {100*case['dsp']:.0f} %." if case["data"] else "."), "",
              "| HSE | SYSCLK | FDCAN kernel | nominal | data | same tq | > 48 MHz | df_max (cond.) | margin |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["pll"] is None:
                continue
            b = r["bus"][case["key"]]
            if b is None:
                L.append(f"| {mhz(r['hse'])} | {mhz(r['sysclk'])} | **no exact timing** | | | | | | |")
                continue
            n, d = b["nominal"], b["data"]
            fmt = lambda t: f"{t['brp']}/{t['tq']}/{t['tseg1']}/{t['tseg2']}/{t['sjw']} @ {100*t['sp']:.1f} %"  # noqa: E731
            tol = b["tol"]
            L.append(f"| {mhz(r['hse'])} | {mhz(r['sysclk'])} | {b['kernel']} = {b['f_kernel']/1e6:.4g} MHz | {fmt(n)} | "
                     f"{fmt(d) if d else '-'} | {'yes' if b['same_tq'] else 'no'} | {'FLAG' if b['above_48MHz'] else 'no'} | "
                     f"{100*tol['df_max']:.3f} % ({tol['limit']}) | {tol['df_max']/OSC_BUDGET:.0f}x |")
        L.append("")
    fd = [r for r in rows if r["pll"] and r["bus"]["FD"] and r["bus"]["FD"]["sp_err"] < 1e-9 and not r["bus"]["FD"]["above_48MHz"]]
    L += ["## 4. What this means", "",
          "* **Receiving CAN correctly requires** the exact bit rate, a timing inside the field ranges, a propagation "
          "segment that fits, and an oscillator tolerance inside the ISO 11898-1 limits. Every row above with a timing meets "
          "the first three; the tolerance margins are large for any crystal (the limits are 0.1-1 %, a crystal budget is "
          "~0.01 %).",
          "* **Matching a particular sample point is a robustness preference** (CiA 601-3 recommends the same data-phase "
          "sample point on all FD nodes [R]). It matters for CAN FD data phases, and only if our bus is FD.",
          "* **Classic CAN 2.0B (the telematics proposal)**: every listed crystal and CPU frequency gives an exact 250k, 500k and 1M "
          "timing near the usual sample points. The crystal choice is then free and should follow other criteria (jitter, "
          "USB or none, availability, the telematics unit's own clock plan).",
          "* **CAN FD 500k/2M at exactly 80 %/80 % with the kernel <= 48 MHz** is reached by "
          + ", ".join(sorted({f"{mhz(r['hse'])} MHz / {mhz(r['sysclk'])} MHz" for r in fd})) + " (HSE / SYSCLK). "
          "Other combinations reach 2 Mbit/s with a different data sample point, a kernel above the unverified 48 MHz note, "
          "or a data prescaler above 2 (rows above).",
          "* **At SYSCLK 170 MHz**: " + "; ".join(
              f"{mhz(r['hse'])} MHz crystal -> {r['bus']['FD']['kernel']}, data {100*r['bus']['FD']['data']['sp']:.1f} % "
              f"with {r['bus']['FD']['data']['tq']} tq" + (" (kernel above the 48 MHz note)" if r['bus']['FD']['above_48MHz'] else "")
              for r in rows if r["pll"] and r["sysclk"] == 170e6 and r["bus"]["FD"]) + ".",
          "* **Not yet verified against the datasheet:** DS12288 PLL ranges, the FDCAN kernel maximum, the ADC clock "
          "maximum, flash wait states per frequency, and ISO 11898-1:2015 FD conditions IV-V. Each is tagged above.",
          "* **Decision rule**: confirm the vehicle bus (classic or FD; bit rates; sample points; transceivers; cable "
          "length), then pick the crystal from these tables, then re-run this tool and `tools/timing_budget.py` with the "
          "chosen SYSCLK.", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "clock_tree_alternatives.md").write_text("\n".join(L))
    (OUT / "clock_tree_alternatives.json").write_text(json.dumps(
        {"limits": {k: {"value": v, "tag": t, "source": s} for k, (v, t, s) in LIMITS.items()},
         "assumptions": {"t_loop_s": T_LOOP_S, "cable_m": CABLE_M, "osc_budget": OSC_BUDGET},
         "rows": rows}, indent=1, default=str))
    print(f"wrote {OUT / 'clock_tree_alternatives.md'} ({len(rows)} clock trees x {len(BUS_CASES)} bus cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
