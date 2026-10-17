# Method selection (v0.4)

For each design question: the candidate methods, what each assumes and needs, its cost, the evidence for it, and the decision. "Simplest supported" means the least complex method for which the evidence below supports the claim being made; where the evidence is only synthetic, the decision says so and names the measurement that would confirm or overturn it. Decisions are owned by the controls lead and reviewed by the vehicle team before the first vehicle test.

## 0. Evidence used and its limits

* **Read sources.** Downloaded at a pinned commit from GitHub mirrors (the only reachable hosts), SHA-256 recorded, text extracted, cited page read. Every copy is third-party hosted except the Fault Diagnosis Toolbox site and Microchip's own GitHub organisation; none was compared with the publisher's file. Search snippets and abstracts are listed separately and are not used as evidence.
* **No peer-reviewed paper on pulse-and-glide or eco-driving DP could be read.** The energy-strategy rows rest on our own synthetic simulations, one ETH tool FAQ and two student documents. The event rules (time limit, energy metering) could not be read either.
* **Own evidence.** Synthetic: `docs/generated/optimization_synthetic.md` (DP and strategies on the synthetic physics map), `docs/generated/policy_comparison_host.md` (policies through the controller on the host plant), `docs/csia/EVALUATION_RESULTS_v2.md` (monitor evaluation on an untouched set), `firmware/tests/test_core_properties.c` (freshness and authority properties).

| Ref | Source (as printed) | Pinned copy | SHA-256 (prefix) |
|---|---|---|---|
| R1 | ST UM1052 "STM32F PMSM single/dual FOC SDK v4.3", Rev 9, 2016 | novaksta/STM32-MCSDK-documentation-list-hub @cdbb458 | 726a88cd |
| R2 | ST "STM32 PMSM FOC SDK" FAQ, 2016 | same repo | 8eb245fb |
| R3 | NXP AN5237 Rev 3 (J. Tkadlec), 2016 | ekremturanfirat/Documents @a46ff15 | 9e60e58d |
| R4 | TI SLUA618A (L. Balogh), 2017/2018 | same repo | d23f420a |
| R5 | Infineon AN 2012-03 (A. Huang) | same repo | 6360bc45 |
| R6 | Renesas R07AN0007EJ0110, 2022 | same repo | 0657c763 |
| R7 | Microchip AN1078 firmware `measure.c/h`, `motor_control_declarations.h` | microchip-pic-avr-solutions/mclv-48v-300w-an1078-dspic33ck256mp508 @946d5bf | 089ac286, 46a32daf, 4c20b928 |
| R8 | ETH IDSC "User FAQ - DPM Function", 2013; `dpm.m` v1.1.1 header | Lmarzi/NOC_NOC @8d39e2e | 2ef46b12, 979fab6d |
| R9 | Frisk & Krysander, IFAC WC 2017 tutorial slides | faultdiagnosistoolbox.github.io @e3005e4 | 8d7009a4 |
| R10 | Fault Diagnosis Toolbox user manual v0.13, 2024 | same | 690563b9 |
| R11 | KTH Eco Cars "Elba 2016" report (student) | KTH-EcoCars/HKReport2016 @070d4fd | 5b5d3e4a |
| R12 | AU Eco-Shell-Marathon "Coast and Burn" (student documentation) | AU-Eco-Shell-Marathon/HW_SW_Group2015 @55eed02 | 8b3ced38 |
| R13 | J. R. Mevey, MSc report, Kansas State University, 2009 | dfieschko/EE-Resources @19d7b42 | f4f8369d |

## 1. Energy strategy (supervisor)

| Method | Assumptions | Required measurements | Compute | Effort | Evidence (quality) | Relevance | Decision |
|---|---|---|---|---|---|---|---|
| Constant speed at the required average, with pace correction | battery power convex in torque near cruise, or losses mostly torque-proportional | coast-down (A, C), lap length, time limit | negligible | done (`speed_hold_policy`) | host plant: best of four policies, pulse-and-coast +11 to +24 % per metre (own, synthetic plant); R11 used it as the baseline (student) | high | **Baseline, always available** |
| Pulse-and-coast band with pace correction | a torque-independent loss while driving that disappears while coasting (freewheel open or gates off), i.e. battery power non-convex in torque | measured battery-power map near cruise, freewheel behaviour, coast-down | negligible | done (`pulse_and_coast_policy`, two set points, one torque) | synthetic physics map: −13 % vs constant speed on the flat track (37.1 vs 42.9 kJ, own); host plant without such a loss: +11 to +24 % (own); R12 describes the method without data (student); abstracts of So et al. and arXiv 2012.11435 state the same condition but were not read | high | **Conditional**: adopt only if the measured map is non-convex at cruise (MATH_SPEC 4.5); set the band from the DP |
| Offline spatial DP, schedule tracked with bounded pace | models accurate enough that a planned schedule stays feasible; time limit known | track geometry and grade, loss map, coast-down, rules | 6–75 s per solve on a 4-core host | planner done (`models/optimization/dp.py`); tracking supervisor not done | synthetic: −21 % vs constant speed (33.9 vs 42.9 kJ, own); a fixed plan exceeds the time limit with C_rr +20 %, mass +5 % or a 2 m/s headwind, bounded pace restores it at +10 % energy (own); grid convergence 0.13 % following R8 p.2 ("start with a very fine grid ... compare"); R11 reports 12 % in their own simulation (student, different vehicle) | high | **Offline planner and benchmark**; supplies the pulse band and the pace reference; not run on the car until the models are measured |
| Online eco-driving MPC | as DP, plus a real-time solver | as DP | high (optimisation every step) | high | none read (README and abstracts only) | medium | Not selected |
| Pontryagin (analytic) | smooth models, no state constraints | as DP | low | medium | abstract only | low | Not selected |

**How the choice is tested.** (1) Host: `tools/run_policy_comparison.py` and the optimisation study already run each policy through the controller or the forward simulator with identical constraints. (2) Bench: measure the battery-power map near cruise (speed × torque grid, bus shunt boundary) and check convexity; with the measured map, rerun the DP and both policies. (3) Track: alternate constant-speed and pulse-and-coast laps at matched lap time and compare `ctrl_energy` per lap with `ctrl_energy_quality` gap 0 s, plus the event joulemeter.

## 2. Phase-current sensing (controller)

| Method | Assumptions | Required measurements | Compute | Effort | Evidence | Relevance | Decision |
|---|---|---|---|---|---|---|---|
| Three low-side shunts; sample the two phases with the longest low-side on-time (sector-based), third from KCL; centre sampling; duty clamp | the low-side window exceeds dead time + noise + sampling time | CSA settling and ringing, dead time (bench) | low | done (`mc_currents_resolve`, `tools/timing_budget.py`) | R1 p.52 ("I1 + I2 + I3 = 0"), p.54 ("current reading cannot be performed on a phase where the duty cycle applied to the low side transistor is either null or very short"), p.55–57 (cases 1–4; "reduce the maximum modulation index or ... decrease the PWM frequency"); R3 p.5, p.25 | high | **Selected** |
| Single shunt with reconstruction | minimum pulse T_MIN = T_rise + T_sample + DT | as above | low | medium | R1 p.66–67 (T_MIN, D_MIN); R2 p.14 (lower loop bandwidth for 1-shunt) | medium | Not selected: tighter modulation limits, no KCL residual |
| Offset calibration at standstill, phases unpowered | motor at rest | none | negligible | done | R3 p.26 (8-sample moving average), R7 `measure.h` l.67–68 (1024 samples) | high | **Selected** |
| Gain calibration | – | known-current injection on the bench | – | procedure in `VALIDATION_PLAN.md` | no read source | high | bench procedure; gap noted |

## 3. Motor control

| Method | Assumptions | Required measurements | Compute | Effort | Evidence | Relevance | Decision |
|---|---|---|---|---|---|---|---|
| FOC with Hall sectors and interpolation, d-axis current 0, PI with back-calculation anti-windup | sinusoidal surface PMSM | R_s, L_d, L_q, λ, Hall offset | low: 0 soft-double calls in the fast step on Cortex-M4F | done | R1 p.29 (T = 3/2 p Φ i_q; i_d = 0 optimal for SM-PMSM), p.40–42 (Clarke, Park, circle limitation); R7 l.401–490 (Clarke, Park, anti-windup); R13 p.142–143 (amplitude vs power invariance) | high if the motor is a PMSM | **Selected, conditional on the motor type** |
| Six-step (block) commutation | trapezoidal BLDC | Hall order | very low | medium (not done) | no read source | high if the motor is BLDC | Fallback if the motor turns out trapezoidal |
| Sensorless observer (SMO / PLL) | back-EMF observable above a minimum speed | R_s, L_s | medium | high | R3 (sensorless FOC, read); AN1078 itself not read | low (Halls are fitted) | Not selected |
| PWM 16–20 kHz | – | phase inductance | – | configuration | R2 p.12 ("about 16 kHz should be sufficient"; 30 kHz for low-inductance motors); gate loss P = V_DRV Q_G f (R4 p.12) | high | 20 kHz in the synthetic configuration; final value from the measured inductance |

## 4. Sensor monitoring and attribution (pit side)

| Method | Assumptions | Required measurements | Compute (host CPython) | Effort | Evidence | Relevance | Decision |
|---|---|---|---|---|---|---|---|
| B1 range / NaN / freshness | – | – | 0.07 ms/tick | done | v2 evaluation: the only channel that sees dropped rotor samples; 209 GNSS false episodes from degraded fixes (own) | high | **Selected**, with a GNSS fix-quality gate to add before display |
| R3v: calibrated residuals, regime gates, majority vote, 3-tick persistence | calibrated power balance, sensor sigmas | bench loss data, sensor noise | 0.20 ms/tick | done | v2 evaluation on an untouched set: 1.0 FA/h, 34/70 attributed, 0 wrong (own); thresholds from a false-alarm criterion and no exoneration, R9 p.31, p.33 | high | **Selected** |
| CSIA2 corroboration attribution | as R3v | as R3v | 0.36 ms/tick | done | v2: +14 attributed, +4 wrong causes; pre-registered rule not met (own) | medium | Shadow research only |
| TrustCore belief threshold | – | – | 0.35 ms/tick | done | v2: 53.5 FA/h, 22 wrong (own) | low | Not selected |
| Structural analysis for residual design (MSO sets) | equation model of the vehicle | – | offline | medium | R9 p.14–23 (MSO residuals, isolability), R10 | medium | Future: check the completeness and isolability of the residual set |

## 5. Supervisor message freshness

| Method | Evidence | Decision |
|---|---|---|
| Per-step skew check (v0.3) | own property test and unit tests: a delayed cached sample locked the stream out for up to 30 s, and delay could grow by the tolerance on every frame | Replaced |
| Reference lag with candidate re-anchoring and an ordering floor (v0.4, `mc_freshness.c`) | own: 15 freshness unit tests, property test P5/P8, soaks 100 × 30 s and 300 × 30 s with 0 failures; no published source read for this design | **Selected** |

## 6. Loss modelling

| Method | Evidence | Decision |
|---|---|---|
| Datasheet formulas (conduction R_DS(on) I², switching, gate V Q f, dead time) | R4 p.12–14 ("calculating the exact switching losses is almost impossible"), R5 p.17, R6 p.18 | For component sizing only |
| Measured battery-power map near the operating region | `models/vehicle/powertrain.py` `MeasuredLossMap`; R4 p.14 | **Required** before any energy claim; the efficiency ratio is ill-conditioned near zero torque, so absolute power is mapped |

## 7. Documents that could not be read (please supply)

1. K. M. So et al., "On the Optimal Speed Profile for Electric Vehicles," IEEE Access 8:78504–78518, 2020, doi:10.1109/ACCESS.2020.2982930 (open access).
2. K. M. So et al., pulse-and-glide for electric vehicles with several powertrain topologies, IEEE Access 14:50609–50627, 2026 (title and DOI not verified).
3. Shell Eco-marathon Global Rules Chapter I and the event's Chapter II (time limit, laps, stops, energy metering).
4. O. Sundström, L. Guzzella, "A Generic Dynamic Programming Matlab Function," IEEE CCA 2009, pp. 1625–1630; O. Sundström, D. Ambühl, L. Guzzella, Oil & Gas Sci. Technol. 65(1), 2010.
5. Targosz, Skarka, Przystałka, "Model-Based Optimization of Velocity Strategy for Lightweight Electric Racing Cars," J. Adv. Transp. 2018, doi:10.1155/2018/3614025.
6. A. Sciarretta, G. De Nunzio, L. L. Ojeda, "Optimal Ecodriving Control," IEEE Control Systems Magazine 35(5), 2015.
7. D. Graovac, M. Pürschel, A. Kiep, "MOSFET Power Losses Calculation Using the Data-Sheet Parameters," Infineon, 2006.
8. Microchip AN1299 (single-shunt reconstruction); NXP DRM148 (sensorless PMSM FOC).
9. R. Isermann, "Model-based fault-detection and diagnosis," Annual Reviews in Control 29(1), 2005; J. Gertler, Fault Detection and Diagnosis in Engineering Systems, 1998.
10. From the vehicle team: `telemetry.pdf` and `bk4000tg_kicad.zip` (referenced in the integration request, not received), the motor and BMS datasheets.

## 8. Open item found while selecting

Under the speed-hold policy the controller switched its gates on 2752 times in 260 s (host plant): the policy's request falls to zero just above the set point, and in gate-off coast mode the arbiter turns the gates off whenever the accepted torque and the target are both zero. Harmless in simulation; on hardware it is a source of switching transients and EMI. A minimum gate-off dwell, or hysteresis in the policy, should be decided before the first powered test (input sheet item 9).
