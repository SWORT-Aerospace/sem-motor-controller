#!/usr/bin/env python3
"""Current-sense error budget and power-stage loss/thermal envelope (hardware draft).

    python3 tools/hardware_calcs.py
      -> hardware/calculations/current_sense_error_budget.md
      -> hardware/calculations/power_stage_envelope.md

The motor's phase current and the battery voltage are UNKNOWN, so both studies
are envelopes over the plausible range rather than a single design point.
Tags: [S] value from a web-search snippet of a manufacturer page (the primary
datasheet could not be opened here), [R] recalled, [A] assumption, [D] design
choice. Nothing is a measurement.
"""
from __future__ import annotations

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from models.inverter import losses as L  # noqa: E402
from tools.run_electrical_calcs import CANDIDATES, GATE  # noqa: E402  (snippet values, UNVERIFIED)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "calculations"

# ------------------------------------------------------------------ current-sense error budget
CSA = {
    "vref_V": (3.3, "D", "CSA VREF = ADC VREF+ = +3V3A (ratiometric bias)"),
    "headroom_V": (0.25, "S", "CSA linear output range ~0.25 V .. VREF-0.25 V (DRV8353 family snippet)"),
    "offset_V": (3e-3, "S", "CSA input offset, before calibration (a TI E2E thread quotes a +/-3 mV spec)"),
    "offset_drift_V_K": (10e-6, "A", "residual offset drift after per-board zero-current calibration"),
    "gain_err": (0.01, "A", "CSA gain error before calibration (datasheet value NOT read)"),
    "shunt_tol": (0.01, "D", "1 % shunt"),
    "shunt_tcr_K": (50e-6, "D", "50 ppm/K shunt"),
    "delta_T_K": (60.0, "A", "shunt / amplifier temperature swing after calibration"),
    "adc_bits": (12, "R", "STM32G4 ADC"),
    "adc_inl_lsb": (2.0, "R", "ADC integral non-linearity (order of magnitude)"),
    "adc_noise_lsb_rms": (1.5, "A", "including layout; measure"),
    "vref_tol": (0.01, "A", "+3V3A LDO tolerance appears as gain error: calibrate"),
    "cal_gain_residual": (0.002, "A", "single-point gain calibration with a reference current"),
}


def cv(k):
    return CSA[k][0]


def error_budget(i_fs_A: float, gain: float) -> dict:
    """Input-referred error terms in amps for a bidirectional low-side CSA whose
    full-scale current is i_fs_A at the given gain."""
    span = cv("vref_V") / 2 - cv("headroom_V")
    r_sh = span / (gain * i_fs_A)
    lsb_A = (cv("vref_V") / 2 ** cv("adc_bits")) / (gain * r_sh)
    t = {
        "offset (uncalibrated)": cv("offset_V") / r_sh,
        "offset drift after cal": cv("offset_drift_V_K") * cv("delta_T_K") / r_sh,
        "ADC INL": cv("adc_inl_lsb") * lsb_A,
        "ADC noise (rms)": cv("adc_noise_lsb_rms") * lsb_A,
    }
    g = {  # relative gain terms
        "CSA gain (uncal)": cv("gain_err"), "shunt tolerance (uncal)": cv("shunt_tol"),
        "VREF tolerance (uncal)": cv("vref_tol"), "shunt TCR over dT": cv("shunt_tcr_K") * cv("delta_T_K"),
        "gain residual after cal": cv("cal_gain_residual"),
    }
    unc_abs = [t["offset (uncalibrated)"], t["ADC INL"], t["ADC noise (rms)"]]
    unc_rel = [g["CSA gain (uncal)"], g["shunt tolerance (uncal)"], g["VREF tolerance (uncal)"], g["shunt TCR over dT"]]
    cal_abs = [t["offset drift after cal"], t["ADC INL"], t["ADC noise (rms)"]]
    cal_rel = [g["gain residual after cal"], g["shunt TCR over dT"]]

    def at(i, absl, rell, rss):
        terms = absl + [r * i for r in rell]
        return math.sqrt(sum(x * x for x in terms)) if rss else sum(abs(x) for x in terms)
    return {"r_shunt_ohm": r_sh, "lsb_A": lsb_A, "terms_A": t, "terms_rel": g,
            "uncal_zero_worst_A": at(0.0, unc_abs, unc_rel, False), "cal_zero_worst_A": at(0.0, cal_abs, cal_rel, False),
            "uncal_fs_rss_pct": 100 * at(i_fs_A, unc_abs, unc_rel, True) / i_fs_A,
            "cal_fs_rss_pct": 100 * at(i_fs_A, cal_abs, cal_rel, True) / i_fs_A,
            "cal_2A_worst_A": at(2.0, cal_abs, cal_rel, False),
            "p_shunt_W_at_fs_rms": r_sh * (i_fs_A / math.sqrt(2)) ** 2 / 2}


def write_budget():
    L_ = ["# Phase-current sense error budget (generated)", "",
          "> `tools/hardware_calcs.py`. The full-scale current depends on the UNKNOWN motor peak current, so the "
          "budget is tabulated over plausible full-scale values and CSA gains. Component values: [S] = web-search "
          "snippet (the primary datasheet could not be opened), [R] = recalled, [A] = assumption to verify, [D] = "
          "design choice. **Not a measurement.**", "",
          "Topology: three low-side shunts, gate-driver-integrated CSAs biased at VREF/2, ratiometric with the ADC "
          "reference (+3V3A). Full scale: G·R·I_fs = VREF/2 − headroom.", "",
          "## Inputs", "", "| term | value | tag | note |", "|---|---|---|---|"]
    for k, (val, tag, note) in CSA.items():
        L_.append(f"| {k} | {val:g} | [{tag}] | {note} |")
    L_ += ["", "## Results", "",
           "| I_fs A | CSA gain | R_shunt mΩ | LSB mA | zero-current error, uncalibrated (worst) A | zero-current error after offset cal (worst) A | error at 2 A after cal (worst) A | full-scale RSS uncal % | full-scale RSS cal % | shunt loss at I_fs (rms, per shunt) W |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for i_fs in (20.0, 40.0, 80.0):
        for gain in (10.0, 20.0, 40.0):
            b = error_budget(i_fs, gain)
            L_.append(f"| {i_fs:g} | {gain:g} | {b['r_shunt_ohm']*1e3:.2f} | {b['lsb_A']*1e3:.1f} | "
                      f"{b['uncal_zero_worst_A']:.2f} | {b['cal_zero_worst_A']:.3f} | {b['cal_2A_worst_A']:.3f} | "
                      f"{b['uncal_fs_rss_pct']:.2f} | {b['cal_fs_rss_pct']:.2f} | {b['p_shunt_W_at_fs_rms']:.2f} |")
    L_ += ["", "## Reading", "",
           "* **Uncalibrated offset dominates at low current.** It is the H7 finding in numbers: a few mV of CSA "
           "offset on a milliohm shunt is amperes of error, at a cruise current of a few amperes. Per-board "
           "zero-current offset calibration at every enable (DRV auto-calibration plus an MCU zero sample with "
           "gates off) is **mandatory**, not optional.",
           "* **For a given I_fs, raising the CSA gain shrinks the shunt and its loss, but not the offset error in "
           "amperes**: V_os/R grows as R shrinks. Choose the shunt from loss and the gain from the ADC span, then "
           "calibrate.",
           "* **VREF tolerance and shunt tolerance are gain errors.** A single-point calibration with a reference "
           "current at stage 4 removes them; temperature drift remains.",
           "* **Energy is not computed from these currents.** The INA228-class DC meter is the energy instrument "
           "(VALIDATION_PLAN §4).",
           "* **Choose I_fs from the measured motor peak current** with margin above the software over-current "
           "trip, then pick the row. Until then the shunt value stays UNRESOLVED.", ""]
    (OUT / "current_sense_error_budget.md").write_text("\n".join(L_))


# ------------------------------------------------------------------ power-stage envelope
def write_envelope():
    t_amb, tj_lim, rth_cs = 40.0, 110.0, 0.5
    L_ = ["# Power-stage loss and thermal envelope (generated)", "",
          "> `tools/hardware_calcs.py` with `models/inverter/losses.py`. MOSFET parameters are **web-search snippet "
          "values of candidate parts, UNVERIFIED** against the primary datasheets. The phase current and bus voltage "
          "are swept because the motor and battery are unknown. Synchronous conduction R·I_pk²/4 per device; "
          "switching from gate-charge transition times (synthetic gate-drive settings). **Not a measurement.**", "",
          f"Assumptions: T_amb {t_amb:.0f} °C [A]; design junction limit {tj_lim:.0f} °C [D] (a derating policy, far "
          "below the 175 °C **absolute maximum** quoted for these parts [S]; operating near an absolute-maximum "
          f"rating is never a design point); case-to-sink {rth_cs} K/W (TIM) [A]; f_sw 20 kHz [C]; dead time 200 ns "
          "[C]; m 0.8; cos φ 0.9.", ""]
    for vbus in (36.0, 48.0, 60.0):
        L_ += [f"## V_bus = {vbus:.0f} V (battery maximum UNKNOWN)", "",
               "| candidate (snippet values) | I_ph,pk A | inverter loss W | hottest device W | max R_th(sink-amb) per device for Tj ≤ 110 °C, K/W |",
               "|---|---|---|---|---|"]
        for name, fet in CANDIDATES.items():
            for ipk in (10.0, 20.0, 40.0, 80.0):
                op = L.InverterOperatingPoint(vbus, ipk, 0.8, 0.9, 20e3, 200e-9, 100.0, 1)
                tj, res = L.solve_tj(fet, GATE, op, t_amb, rth_cs, 5.0)
                pdev = res["per_device_hottest_W"]
                rsa = (tj_lim - t_amb) / pdev - fet.rth_jc_K_W - rth_cs if pdev > 0 else float("inf")
                L_.append(f"| {name} | {ipk:g} | {res['total_W']:.1f} | {pdev:.2f} | "
                          f"{'n/a (exceeds limit even on an ideal sink)' if rsa <= 0 else f'{rsa:.1f}'} |")
        L_.append("")
    L_ += ["## DC-link ripple current (sizing input for the bulk capacitors)", "",
           "| I_ph,rms A | m 0.5 | m 0.8 | m 1.0 |", "|---|---|---|---|"]
    for irms in (7.0, 14.0, 28.0, 57.0):
        L_.append(f"| {irms:g} | " + " | ".join(f"{L.dc_link_ripple_rms(irms, m, 0.9):.1f} A" for m in (0.5, 0.8, 1.0))
                  + " |")
    L_ += ["", "Kolar–Round approximation, cos φ 0.9 (verified against a switching simulation in `tests/simulation`).", "",
           "## What this decides and what it does not", "",
           "* With the motor's continuous and peak currents unknown, **no MOSFET, heatsink or capacitor can be "
           "frozen**. The table shows the decision space: a single 2.4–5 mΩ device per switch keeps "
           "per-device dissipation at a few watts up to ~40 A peak, which a modest heatsink handles. At ~80 A the "
           "required sink resistance becomes demanding for the higher-R_DS(on) parts.",
           "* Selection requires the motor's peak current and duration, continuous current, and the battery's "
           "maximum charged voltage (V_DS rating ≥ 1.5 × V_bat,max for ringing margin [D], verified with overshoot "
           "measurements at stage 4).", ""]
    (OUT / "power_stage_envelope.md").write_text("\n".join(L_))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    write_budget()
    write_envelope()
    print("wrote", OUT / "current_sense_error_budget.md", OUT / "power_stage_envelope.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
