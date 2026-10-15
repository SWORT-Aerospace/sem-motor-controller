#!/usr/bin/env python3
"""MCU timing allocation and current-sampling budget (STM32G474 + DRV835x-class CSA).

    python3 tools/timing_budget.py   -> hardware/timing/timing_budget.md (+ .json)

Every constant is tagged:
  [C]  from this project's configuration (config/vehicle.synthetic.yaml) - synthetic
  [R]  recalled from STM32G4 / DRV835x documentation, NOT verified here (st.com and
       ti.com unreachable from this environment) - check against RM0440 / DS12288 /
       SLVSDY6x before relying on it
  [A]  engineering assumption to be MEASURED at bench stage 3/4
  [D]  design value chosen in the schematic draft
Nothing here has been measured on hardware.
"""
from __future__ import annotations

import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "timing"

K = {
    "f_sysclk_Hz": (170e6, "R", "STM32G474 max SYSCLK (boost mode)"),
    "f_pwm_Hz": (20e3, "C", "inverter.pwm_frequency_Hz"),
    "t_dead_s": (200e-9, "C", "inverter.deadtime_s"),
    "duty_max": (0.98, "C", "inverter.duty_max"),
    "f_adc_Hz": (42.5e6, "R", "ADC clock = HCLK/4 synchronous (one legal choice; max ADC clock to verify)"),
    "adc_sample_cycles": (6.5, "D", "sampling time setting for the CSA channels (2.5..640.5 selectable [R])"),
    "adc_conv_cycles": (12.5, "R", "12-bit successive-approximation conversion"),
    "c_sh_F": (5e-12, "R", "ADC sample-and-hold capacitance (order of magnitude)"),
    "r_filter_ohm": (100.0, "D", "CSA output series R (current_sense sheet)"),
    "c_filter_F": (470e-12, "D", "CSA output shunt C (current_sense sheet)"),
    "t_ring_s": (500e-9, "A", "switch-node ringing settle after the low-side turns on"),
    "t_csa_settle_s": (1.0e-6, "A", "CSA output settling to 0.1 % after the step (SLVSDY6x value NOT read)"),
    "voltage_limit_fraction": (0.95, "C", "inverter.voltage_limit_fraction (FOC uses this x Vbus/sqrt(3))"),
    "t_dts_div": (1, "D", "TIM1 CKD = 1 -> t_DTS = 1/f_tim"),
    "brk_filter_samples": (4, "D", "TIM1 BKF digital filter length (N samples at f_DTS)"),
    "fast_isr_cycles_est": (None, "A", "FOC fast-step cycles: MEASURE with DWT->CYCCNT at stage 2"),
}


def v(k):
    return K[k][0]


def deadtime_code(t_dead, f_tim):
    """TIM1 BDTR.DTG encoding (RM0440 [R]): 0xxxxxxx -> DTG*tDTS; 10xxxxxx -> (64+x)*2tDTS;
    110xxxxx -> (32+x)*8tDTS; 111xxxxx -> (32+x)*16tDTS. Returns (code, achieved_s)."""
    tdts = 1.0 / f_tim
    n = t_dead / tdts
    if n <= 127:
        c = math.ceil(n)
        return c, c * tdts
    if n <= 127 * 2:
        x = math.ceil(n / 2) - 64
        return 0x80 | x, (64 + x) * 2 * tdts
    if n <= 63 * 8:
        x = math.ceil(n / 8) - 32
        return 0xC0 | x, (32 + x) * 8 * tdts
    x = min(math.ceil(n / 16) - 32, 31)
    return 0xE0 | x, (32 + x) * 16 * tdts


def svpwm_duties(theta, m):
    """Min-max (zero-sequence) centred duties for a reference of magnitude m (fraction of Vbus/sqrt(3))."""
    va = m / math.sqrt(3) * math.cos(theta)
    vb = m / math.sqrt(3) * math.cos(theta - 2 * math.pi / 3)
    vc = m / math.sqrt(3) * math.cos(theta + 2 * math.pi / 3)
    off = -(max(va, vb, vc) + min(va, vb, vc)) / 2
    return [0.5 + x + off for x in (va, vb, vc)]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    f_tim = v("f_sysclk_Hz")
    T = 1.0 / v("f_pwm_Hz")
    arr = f_tim / (2 * v("f_pwm_Hz"))
    code, t_dead_ach = deadtime_code(v("t_dead_s"), f_tim)
    tau = v("r_filter_ohm") * v("c_filter_F")
    n_tau = math.log(2 ** 12)                    # settle to 1 LSB of 12 bits
    t_rc = n_tau * tau
    t_samp = v("adc_sample_cycles") / v("f_adc_Hz")
    t_conv = (v("adc_sample_cycles") + v("adc_conv_cycles")) / v("f_adc_Hz")
    kick = v("c_sh_F") / (v("c_sh_F") + v("c_filter_F"))
    # sampling at the centre of the low-side on-interval (counter valley)
    t_need_before = t_dead_ach + v("t_ring_s") + max(v("t_csa_settle_s"), t_rc)
    d_max_sample = 1.0 - 2.0 * t_need_before / T
    d_max_sample2 = 1.0 - 2.0 * t_samp / T     # sampling must also end before low-side turn-off
    d_lim = min(d_max_sample, d_max_sample2)
    # coverage over SVPWM angles at the configured duty limit
    worst_valid, worst_theta, m_lin = 3, None, v("voltage_limit_fraction")
    for i in range(3600):
        th = 2 * math.pi * i / 3600
        d = [min(max(x, 1 - v("duty_max")), v("duty_max")) for x in svpwm_duties(th, m_lin)]
        n_ok = sum(1 for x in d if x <= d_lim)
        if n_ok < worst_valid:
            worst_valid, worst_theta = n_ok, th
    # sensitivity: largest voltage-limit fraction that keeps two phases sampleable (rule 39)
    sens = []
    for f_pwm in (10e3, 16e3, 20e3, 25e3):
        row = {"f_pwm_kHz": f_pwm / 1e3}
        for settle in (0.5e-6, 1.0e-6, 1.5e-6, 2.0e-6, 3.0e-6):
            dwin = 1.0 - 2.0 * (t_dead_ach + settle) * f_pwm
            row[f"{settle*1e6:.1f}us"] = max(0.0, min(1.0, (dwin - 0.5) / 0.4330127018922193))
        sens.append(row)
    # break path
    t_brk_filter = v("brk_filter_samples") / f_tim
    res = {
        "constants": {k: {"value": val, "tag": tag, "note": note} for k, (val, tag, note) in K.items()},
        "pwm": {"T_s": T, "center_aligned_ARR": arr, "timer_resolution_s": 1 / f_tim,
                "duty_resolution": 1 / arr, "deadtime_code": code, "deadtime_achieved_s": t_dead_ach},
        "adc": {"t_sample_s": t_samp, "t_sample_plus_conv_s": t_conv, "rc_tau_s": tau, "rc_settle_12bit_s": t_rc,
                "kickback_fraction": kick},
        "window": {"t_needed_before_sample_s": t_need_before, "d_max_sampleable": d_lim,
                   "duty_max_config": v("duty_max"),
                   "min_valid_phases_over_svpwm_angles": worst_valid,
                   "worst_angle_deg": None if worst_theta is None else math.degrees(worst_theta)},
        "break": {"filter_latency_s": t_brk_filter},
        "m_max_sensitivity": sens,
    }
    (OUT / "timing_budget.json").write_text(json.dumps(res, indent=1))
    L = ["# MCU timing allocation and current-sampling budget (generated)", "",
         "> Generated by `tools/timing_budget.py`. Tags: [C] project config (synthetic), [R] recalled from ST/TI "
         "documentation and **not verified** here, [A] assumption to be measured at bench stage 3/4, [D] design "
         "value in the schematic draft. Nothing here is a hardware measurement.", "",
         "## Inputs", "", "| constant | value | tag | note |", "|---|---|---|---|"]
    for k, (val, tag, note) in K.items():
        L.append(f"| {k} | {val if val is not None else 'TBD'} | [{tag}] | {note} |")
    L += ["", "## PWM (TIM1, centre-aligned, complementary, 6-PWM to the gate driver)", "",
          f"* Period {T*1e6:.1f} us; ARR = f_tim / (2 f_pwm) = {arr:.0f} (duty resolution {100/arr:.3f} %).",
          f"* Dead time {v('t_dead_s')*1e9:.0f} ns -> BDTR.DTG = 0x{code:02X} -> {t_dead_ach*1e9:.1f} ns achieved "
          f"(t_DTS = {1e9/f_tim:.2f} ns). The gate driver may add its own dead time; the effective dead time is "
          "the larger of the two and must be measured at the gate (stage 3).",
          "", "## Simultaneous phase-current sampling", "",
          "* Phase A on ADC1, phase B on ADC2 (dual simultaneous injected mode), phase C on ADC3, injected, with "
          "the same external trigger TIM1_TRGO2 [R]. The three sample-and-hold instants coincide to within ADC "
          "clock synchronisation (< 1 ADC clock); in v0.1 phase C sat behind phase A in ADC1 by "
          f"{(v('adc_sample_cycles') + v('adc_conv_cycles')) / v('f_adc_Hz') * 1e9:.0f} ns.",
          "* Pins (generated, `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`): PA0 ADC1_IN1, PA1 ADC2_IN2, "
          "PE7 ADC3_IN4, all IN1..IN5 \"fast\" channels [R].",
          f"* Sampling time {v('adc_sample_cycles')} cycles = {t_samp*1e9:.0f} ns; with conversion "
          f"{t_conv*1e9:.0f} ns. External RC tau = {tau*1e9:.0f} ns; settling to 1 LSB (12 bit) = {t_rc*1e9:.0f} ns. "
          f"Charge kick-back from C_SH: {100*kick:.2f} % of the step between successive samples on the same input, "
          "absorbed by the 470 pF reservoir (re-check with the real C_SH).",
          "", "## Sampling window (low-side shunts, sample at the PWM valley)", "",
          f"* Time needed between low-side turn-on and the sample: dead time + ringing + max(CSA settle, RC settle) = "
          f"{t_need_before*1e6:.2f} us ([A] ringing {v('t_ring_s')*1e9:.0f} ns, [A] CSA settle "
          f"{v('t_csa_settle_s')*1e6:.1f} us).",
          f"* Largest sampleable duty: **{d_lim:.3f}** (configured duty_max {v('duty_max')}).",
          f"* Over all SVPWM angles at the configured voltage limit ({v('voltage_limit_fraction')} x Vbus/sqrt(3)), the minimum number of phases with a valid window is "
          f"**{worst_valid}**. Firmware rule: a phase is valid only when its duty is <= {d_lim:.3f}. With one invalid "
          "phase, the controller reconstructs it from the other two (`mc_currents_resolve`; reconstructed phase "
          "flagged, KCL residual unavailable). With two or more invalid phases, it would need to reduce duty_max; "
          "not reached at these values.",
          "", "### Largest safe voltage-limit fraction (validator rule 39)", "",
          "Rule 39: 0.5 + (sqrt(3)/4) m <= 1 - 2 (t_dead + t_settle) f_pwm, where t_settle = "
          "`inverter.current_sample_settle_s` is measured at stage 4. The second-highest min-max SVPWM duty peaks "
          "at 60 deg; satisfying the rule leaves two sampleable phases at every angle.", "",
          "| f_pwm kHz | " + " | ".join(f"settle {k}" for k in sens[0] if k != "f_pwm_kHz") + " |",
          "|---|" + "---|" * (len(sens[0]) - 1)]
    for r in sens:
        L.append(f"| {r['f_pwm_kHz']:g} | " + " | ".join(f"{r[k]:.3f}" for k in r if k != "f_pwm_kHz") + " |")
    s_max = (1.0 - (0.5 + 0.4330127018922193 * v("voltage_limit_fraction"))) / (2.0 * v("f_pwm_Hz")) - t_dead_ach
    L += ["", f"With the configured limit {v('voltage_limit_fraction')} at {v('f_pwm_Hz')/1e3:g} kHz, the rule holds "
          f"while the measured settle stays at or below {s_max*1e6:.2f} us. Above that, the validator rejects the "
          "calibration until the limit or the PWM frequency is lowered (synthetic value 1.5 us).",
          "", "## Break (hardware shutdown) routing", "",
          "| source | path | polarity | action |", "|---|---|---|---|",
          "| Gate-driver nFAULT (VDS over-current, UVLO, thermal, ...) [R] | PE15 TIM1_BKIN | active low, open drain + 10 k pull-up | MOE cleared asynchronously; outputs to idle state |",
          "| Bus over-voltage comparator (TLV7041) | PC3 TIM1_BKIN2 | active low, open drain | as above |",
          "| (option) MCU COMPx on CSA outputs | internal to TIM1_BKIN2 [R] | configurable | phase over-current without a pin; not used in the draft |",
          "", f"* Idle state: OSSI = 1, OISx = OISxN = 0, so every INHx/INLx is driven low and the driver holds all "
          "gates off. AOE = 0: MOE is never re-set automatically; only firmware does it, after a fault reset.",
          f"* BKF digital filter: {v('brk_filter_samples')} samples -> {t_brk_filter*1e9:.0f} ns added latency [D]. "
          "Measure the total input-to-gate-off latency at stage 3.",
          "", "## Startup pin states (reset until firmware configures the pins)", "",
          "| signal | state during/after reset | why it is safe |", "|---|---|---|",
          "| MCU GPIOs | analog / high impedance [R] (debug pins PA13/PA14/PB3 excepted) | nothing below depends on an MCU pin being driven |",
          "| DRV ENABLE | low: MCU_DRV_EN pulled down 100 k and ANDed with HW_PERMIT (74LVC1G08); output pulled down 100 k | gate driver disabled, all gates off [R] |",
          "| INHx / INLx | low: driver internal pull-downs [R]; DNP 100 k pads | no switching command |",
          "| Precharge bypass | off: PRECHG_EN pulled down 100 k | DC link charges only through the precharge resistor |",
          "| CAN TXD | recessive: transceiver TXD pull-up [R] | no bus disturbance during reset |",
          "| BOOT0 (PB8) | low: 10 k pull-down | boots from flash |",
          "", "## Interrupt and task timing allocation", "",
          "| priority | source | rate | budget | content |", "|---|---|---|---|---|",
          "| 0 (highest) | TIM1 BRK / BRK2 | event | < 2 us | latch fault flag; hardware has already stopped the outputs |",
          f"| 1 | ADC JEOC (injected end of conversion) | {v('f_pwm_Hz')/1e3:.0f} kHz | <= 40 % of {T*1e6:.0f} us = {0.4*T*1e6:.0f} us | `mc_core_fast_step`: hall, currents, FOC, duty update (preloaded) |",
          "| 2 | FDCAN RX FIFO | <= 2 kHz | <= 5 us | copy the frame to a queue; decoding runs in the slow task |",
          "| 3 | SysTick / slow task | 1 kHz | <= 300 us | `mc_core_slow_step`, CAN RX decoding, TX polling, watchdog kick |",
          "| background | idle | - | - | logging over UART (bench only) |",
          "", "The fast-step cycle count is **not measured**. The host build shows no double-precision calls in "
          "`mc_core_fast_step` (objdump, MinSizeRel). It uses `sinf`/`cosf` from newlib. Measure DWT->CYCCNT "
          "around the ISR at stage 2 and replace `fast_isr_cycles_est`. If it exceeds the budget, use a "
          "table-based sin/cos, or run the FOC every second PWM period with ADC sampling every period.", ""]
    (OUT / "timing_budget.md").write_text("\n".join(L))
    print(json.dumps(res["window"], indent=1), res["pwm"]["deadtime_code"], res["pwm"]["deadtime_achieved_s"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
