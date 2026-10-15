# Phase-current sense error budget (generated)

> `tools/hardware_calcs.py`. The full-scale current depends on the UNKNOWN motor peak current, so the budget is tabulated over plausible full-scale values and CSA gains. Component values: [S] = web-search snippet (the primary datasheet could not be opened), [R] = recalled, [A] = assumption to verify, [D] = design choice. **Not a measurement.**

Topology: three low-side shunts, gate-driver-integrated CSAs biased at VREF/2, ratiometric with the ADC reference (+3V3A). Full scale: G·R·I_fs = VREF/2 − headroom.

## Inputs

| term | value | tag | note |
|---|---|---|---|
| vref_V | 3.3 | [D] | CSA VREF = ADC VREF+ = +3V3A (ratiometric bias) |
| headroom_V | 0.25 | [S] | CSA linear output range ~0.25 V .. VREF-0.25 V (DRV8353 family snippet) |
| offset_V | 0.003 | [S] | CSA input offset, before calibration (a TI E2E thread quotes a +/-3 mV spec) |
| offset_drift_V_K | 1e-05 | [A] | residual offset drift after per-board zero-current calibration |
| gain_err | 0.01 | [A] | CSA gain error before calibration (datasheet value NOT read) |
| shunt_tol | 0.01 | [D] | 1 % shunt |
| shunt_tcr_K | 5e-05 | [D] | 50 ppm/K shunt |
| delta_T_K | 60 | [A] | shunt / amplifier temperature swing after calibration |
| adc_bits | 12 | [R] | STM32G4 ADC |
| adc_inl_lsb | 2 | [R] | ADC integral non-linearity (order of magnitude) |
| adc_noise_lsb_rms | 1.5 | [A] | including layout; measure |
| vref_tol | 0.01 | [A] | +3V3A LDO tolerance appears as gain error: calibrate |
| cal_gain_residual | 0.002 | [A] | single-point gain calibration with a reference current |

## Results

| I_fs A | CSA gain | R_shunt mΩ | LSB mA | zero-current error, uncalibrated (worst) A | zero-current error after offset cal (worst) A | error at 2 A after cal (worst) A | full-scale RSS uncal % | full-scale RSS cal % | shunt loss at I_fs (rms, per shunt) W |
|---|---|---|---|---|---|---|---|---|---|
| 20 | 10 | 7.00 | 11.5 | 0.47 | 0.126 | 0.136 | 2.78 | 0.58 | 0.70 |
| 20 | 20 | 3.50 | 11.5 | 0.90 | 0.212 | 0.222 | 4.63 | 0.94 | 0.35 |
| 20 | 40 | 1.75 | 11.5 | 1.75 | 0.383 | 0.393 | 8.75 | 1.76 | 0.17 |
| 40 | 10 | 3.50 | 23.0 | 0.94 | 0.252 | 0.262 | 2.78 | 0.58 | 1.40 |
| 40 | 20 | 1.75 | 23.0 | 1.79 | 0.423 | 0.433 | 4.63 | 0.94 | 0.70 |
| 40 | 40 | 0.87 | 23.0 | 3.51 | 0.766 | 0.776 | 8.75 | 1.76 | 0.35 |
| 80 | 10 | 1.75 | 46.0 | 1.88 | 0.504 | 0.514 | 2.78 | 0.58 | 2.80 |
| 80 | 20 | 0.87 | 46.0 | 3.59 | 0.847 | 0.857 | 4.63 | 0.94 | 1.40 |
| 80 | 40 | 0.44 | 46.0 | 7.02 | 1.533 | 1.543 | 8.75 | 1.76 | 0.70 |

## Reading

* **Uncalibrated offset dominates at low current.** It is the H7 finding in numbers: a few mV of CSA offset on a milliohm shunt is amperes of error, at a cruise current of a few amperes. Per-board zero-current offset calibration at every enable (DRV auto-calibration plus an MCU zero sample with gates off) is **mandatory**, not optional.
* **For a given I_fs, raising the CSA gain shrinks the shunt and its loss, but not the offset error in amperes**: V_os/R grows as R shrinks. Choose the shunt from loss and the gain from the ADC span, then calibrate.
* **VREF tolerance and shunt tolerance are gain errors.** A single-point calibration with a reference current at stage 4 removes them; temperature drift remains.
* **Energy is not computed from these currents.** The INA228-class DC meter is the energy instrument (VALIDATION_PLAN §4).
* **Choose I_fs from the measured motor peak current** with margin above the software over-current trip, then pick the row. Until then the shunt value stays UNRESOLVED.
