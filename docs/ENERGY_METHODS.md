# Energy methods: what can be measured and decided now (v0.5)

The goal is lower energy per attempt as the organisers measure it. This page keeps the findings so far, adds what v0.5 read and computed, and states for each method whether it can be used now or needs motor maps, a coast-down or vehicle data. Nothing here is a vehicle result: every number comes from synthetic models, the host plant or documents.

## 1. Findings kept from earlier work

1. **Pulse-and-coast is not automatically more efficient.** On the host plant, which has no loss that is independent of torque while driving, pulse-and-coast used 11.4 to 23.8 % more energy per metre than speed hold (`generated/policy_comparison_host.md`). On the synthetic physics map, which has iron loss, it saved about 13 % (`generated/optimization_synthetic.md`, `METHOD_SELECTION.md` 1). The condition is that battery power is non-convex in torque at cruise (`MATH_SPEC.md` 4.5). Which case the vehicle is in has to be measured.
2. **Comparisons need matched route, time and kinetic energy.** The policy comparison integrates whole pulse-and-coast cycles at the same mean speed and reports the residual kinetic-energy change (at most 0.01 J/m). A first version compared windows ending at different speeds, and one configuration appeared 1.7 % better than it was (`VERIFICATION_REPORT.md` 4).
3. **Battery-side accounting needs valid, synchronised measurements and explicit gaps.** The controller integrates voltage times current only over valid samples and reports the integrated and skipped time (`ctrl_energy_quality`, protocol 1.1). Before v0.4 it integrated across invalid samples without trace. On the host, the controller-input energy and the simulated battery-terminal energy agree within 0.14 % (`generated/host_demo/summary.md`).
4. **CSIA v2 did not meet its pre-registered superiority criterion against R3v:** 14 more attributions, but 4 more wrong causes where the rule allowed at most 1 (`csia/EVALUATION_RESULTS_v2.md`). R3v is the pit-side monitor; CSIA stays experimental and in shadow mode. The frozen v2 files (`csia/V2_FREEZE.json`, protocol and results) are not changed, and the held-out results are not used for tuning. A new CSIA iteration needs a new development set and a new, untouched evaluation set with its protocol frozen first.

## 2. Added in v0.5

### 2.1 What the official result counts (2026 Chapter I, read; `RULES_COMPLIANCE.md`)

* Battery Electric results are in km/kWh from the organisers' joulemeter (Article 54d), installed "between the battery and the vehicle electrical system" (56c i).
* "All electrical energy used by the vehicle", propulsion and non-propulsion, is measured, except the horn and the built-in batteries of Article 57i devices (56d). The telematics unit, LTE modem, GNSS, sensors and a vehicle-powered display all count.
* The controller's input meter is therefore not the joulemeter. The joulemeter also sees every other load downstream of it, plus the wiring between it and the controller. The BMS sits inside the battery package, powered directly by the battery (57d i 3), so it lies outside both.

### 2.2 Telemetry is an energy term

Figures read in the manufacturer documents (`TELEMETRY_CANDIDATES.md`):

| Load | Figure | Power |
|---|---|---|
| GNSS NEO-M9N, tracking with 4 GNSS | 36 mA at VCC 3.0 V typ (UBX-19014285 pp. 10-11) | about 0.11 W, plus an active antenna (up to 50 mA from VCC_RF) |
| IMU LSM6DSV, accelerometer + gyroscope, high performance | 0.65 mA (DS13476 p. 13) | about 2 mW at 3.3 V |
| LTE A7672, average current while transmitting at 23 dBm | up to 859 mA (Hardware Design V1.04 p. 62) at 3.8 V recommended | about 3.3 W while transmitting |
| LTE idle and sleep, MCU, regulators | not read | unknown |

**Each watt of continuous telemetry load costs 3.6 kJ per hour**, 2.1 kJ over 35 minutes (an attempt length used for scale only; the event's time limit is in its Chapter II, not read). For scale only: the synthetic optimisation study's attempt energy is about 40 kJ, so one watt would be about 5 % of it. The real share depends on the vehicle and on the measured consumption of the unit (bench check E8, `TELEMETRY_EMBEDDED_PORT.md`). It can be lowered by keeping the modem's transmit duty cycle low (batched publishing at 1 to 5 Hz), by keeping logging local, and by not running unneeded sensors.

### 2.3 Coast-down: what the measurement needs

The repository already fits a coast-down (`models/vehicle/longitudinal.py fit_coastdown`, tests in `tests/simulation/test_models.py`). v0.5 adds `tools/coastdown_sensitivity.py`, with results in `generated/coastdown_sensitivity.md`, run on the synthetic vehicle with known truth:

* An unmodelled 0.1 % grade raises the fitted rolling resistance by 40 %, and a 0.5 % grade by 200 %. Averaging runs in both directions on the same section removes it.
* A steady 1 m/s wind moves the drag coefficient by about 12 % in one direction; both directions cancel it.
* With 0.05 m/s speed noise (the NEO-M9N velocity figure) the fit reports that rolling resistance and drag are no longer separately identifiable instead of giving a confident split; wheel-sensor speed with less noise keeps them apart.
* The IMU cannot replace a flat section: its 12 mg offset is a 1.2 % grade equivalent before calibration.

## 3. Methods and what each needs

| Method | Status | Needs before it is meaningful | Evidence | Next step |
|---|---|---|---|---|
| Controller-input energy with gap accounting | implemented (host and core) | synchronised voltage and current, valid samples | host demo energy boundary; firmware tests | compare with the joulemeter on the vehicle |
| Auxiliary (telemetry, display) energy | figures read for parts; total unknown | the unit's measured consumption | section 2.2 | bench check E8 |
| Coast-down road load | method implemented and tested on synthetic data | coast-downs in both directions on a flat section; mass, rotating inertia, freewheel state; wind | `generated/coastdown_sensitivity.md` | input sheet item 3 |
| Battery-power map (speed x torque) | not possible yet | the motor and controller on a bench or the vehicle | `METHOD_SELECTION.md` | bench stage 6, input sheet item 3 |
| Constant speed (speed hold) | implemented policy | controller tuning on the vehicle | baseline in every comparison | first powered tests |
| Pulse-and-coast | implemented policy; adoption conditional | the measured map shows non-convexity at cruise | section 1, item 1 | decide after the map |
| Offline spatial DP schedule | implemented (synthetic) | road load, power map, track profile, time limit (Chapter II) | `generated/optimization_synthetic.md` | real inputs |
| Online MPC | not selected | as DP, plus a real-time solver | `METHOD_SELECTION.md` | none |
| Minimum gate-off dwell or hysteresis | open decision | the decision (speed hold switched the gates 2752 times in 260 s on the host plant) | `generated/policy_comparison_host.md` | input sheet item 12 |
| Energy per metre and per lap in the pit | data stored (SQLite `signals`: energy, wheel and GNSS distance) | an analysis script; vehicle runs | `host/pit/ingest.py` | write the analysis on host logs |

## 4. Literature read for these methods

Read in v0.5, in the document text itself (copies hosted on GitHub; identity from the title page and revision). The scholarly publishers' sites (arXiv, IEEE, ScienceDirect, MDPI, SAE, UNECE, OSTI) could not be accessed for this work. `METHOD_SELECTION.md` 0 lists the sources read in v0.4 (R1 to R13).

| Source | What it supports here | What it does not support |
|---|---|---|
| UNECE WLTP draft GTR, ECE/TRANS/WP.29/GRPE/2013/13, Annex 4 "Road load and dynamometer setting" (draft, 2013) | A complete coast-down recipe: runs in both directions combined by a harmonic mean of the times, a stopping rule of statistical accuracy p ≤ 3 %, least-squares fit of f0 + f1 v + f2 v², the equivalent rotating mass, corrections for temperature, pressure and wind; limits such as a road slope within ±1 % and speed logged at 5 Hz or more | Written for cars between 115 and 15 km/h with reference speeds 20 km/h apart; an Eco-marathon prototype runs at about 25 to 30 km/h, so speed bands, the rotating-mass rule and the tyre correction need re-justifying. It is a draft with bracketed values |
| US EPA 40 CFR 1066 Subpart D "Coastdown" (eCFR snapshot 2025-02-06) | The SAE J1263 and J2263 framework, averaging over opposite directions, grade modelled as a function of distance when it exceeds 0.02 %, wind limits, about 10 Hz speed sampling, rejection of runs beyond 2 standard deviations | The SAE texts themselves and any accuracy statement were not readable; the heavy-vehicle details are not parameters for this vehicle |
| Sivert et al., Revue Technologie 199 (2015), eco-marathon tricycle characterisation | A simple coast-to-stop rolling-resistance estimate below 15 km/h, where aerodynamic drag is small; order-of-magnitude coefficients for faired light vehicles | No uncertainty, grade or wind correction, no separation of bearing and drivetrain drag from the tyres |
| Imperial Eco-Marathon team, SEM 2025 design report | That a leading team splits its losses with telemetry and coast-downs | No method, data or uncertainty |
| Thomsen and Nissen, Aarhus University bachelor thesis (2013), SEM battery-electric prototype | A pulse-and-glide simulation with a hysteresis band around the required mean speed, energy through a speed and torque dependent efficiency map, and the extra costs per cycle (clutch, motor spin-up, freewheel drag) | It never simulates constant speed as a baseline, uses datasheet efficiencies and an assumed C_rr, and has no optimal-control proof; it does not show when pulse-and-glide beats steady speed |
| Aarhus AU2 team documentation (2016) | How a team implemented pulse-and-glide as an on/off speed hysteresis; a joulemeter placed between battery and power electronics; a rolling-road bench with shaft torque and DC power sensing | The efficiency argument is asserted, not measured; the vehicle was not validated. Its calculated copper-wire shunt is a cautionary example for D2 ([`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md)) |
| TI INA228 (SLYS021) and INA229 (SLYS023) datasheets | Gain error ±0.05 %, energy and charge error ±1 % at full-scale power; power and energy computed from the previous current conversion and the latest bus voltage | No general error budget for coulomb counting (shunt temperature coefficient, offset integration, time base) was found |
| Munusamy, Coventry University MSc project (2025), hub PMSM used on SEM cars | A basic recipe for the stator resistance (line-to-line value divided by two) and a list of practical error sources | No efficiency map, iron or inverter loss; its numbers are internally inconsistent, so its parameter values are not used |

**Gaps.** No readable peer-reviewed source on: coast-down accuracy for low-speed prototypes; when pulse-and-glide beats constant speed for an electric drive (a 2019 Automatica paper by Han, Vahidi and Sciarretta addresses it, but only its abstract was seen); measured PMSM and inverter efficiency maps; coulomb-counting error budgets. Every energy-strategy conclusion in this repository therefore rests on the vehicle's own measurements (stages 6 to 8 of [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)), not on literature values.
