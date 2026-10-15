# Energy-efficiency research and models

**Evidence status: no paper could be read in this session.** mdpi.com, mdpi-res.com, doi.org and every other scholarly host were blocked by the environment's network policy. The evidence matrix therefore records identification only. **No result from any paper is used** in this project. Every number below comes from SYNTHETIC models in this repository and is labelled as such.

## 1. Evidence matrix

| Ref | Vehicle | Motor | Battery | Track | Objective | Constraints | Baseline | Measured vs simulated | Test count | Uncertainty | Transferability | Implementation consequence | Access |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P1 *Vehicle Model-Based Driving Strategy Optimization for Lightweight Vehicle*, Energies 15(10) 3631, 2022, doi:10.3390/en15103631 | — | — | — | — | — | — | — | — | — | — | — | none until read | **INACCESSIBLE** (title/DOI from search index only) |
| P2 *Eco-Driving Strategy Implementation for Ultra-Efficient Lightweight Electric Vehicles in Realistic Driving Scenarios*, Energies 16(3) 1394, 2023, doi:10.3390/en16031394 | — | — | — | — | — | — | — | — | — | — | — | none until read | **INACCESSIBLE** |
| P3 *Implementation of Optimized Regenerative Braking in Energy Efficient Driving Strategies*, Energies 16(6) 2682, 2023, doi:10.3390/en16062682 | — | — | — | — | — | — | — | — | — | — | — | none until read; regen also deferred by ADR-0007 | **INACCESSIBLE** |
| TI TIDA-010056 / TIDUEQ9A (Rev A 2019) | — | — | 54 V (15S) | — | power-stage reference | — | — | snippet says efficiency > 99 % — **conditions unknown** | — | — | layout/power stage only; trapezoidal, not FOC | — | **[S] snippet only** |

Search summaries attributed specific claims to P1 and P3: a measurement-based model with cornering resistance and a powertrain efficiency map; SEM London 2019 telemetry; TT Circuit Assen; "2.97 % improvement". These are **not evidence**. They are listed only as items to check once the texts are readable. Candidate further sources were identified by title only and are listed in the session research notes for later retrieval.

**Action:** allow `www.mdpi.com` and `mdpi-res.com` in the environment's network settings (or supply PDFs) and fill the matrix from the full texts. Record test counts and uncertainty, and whether each result was measured or simulated.

## 2. Strategy classes (status in this project)

| Strategy | Implemented | Evidence |
|---|---|---|
| Constant speed (feedback cruise) | `models/optimization/strategies.py::constant_speed` | synthetic only |
| Smooth variable torque | implicit in the DP (torque levels) | synthetic only |
| Pulse-and-coast | `pulse_and_coast` (band and torque swept) | synthetic only |
| Offline dynamic programming | `models/optimization/dp.py` (spatial, Lagrangian time constraint, grid-convergence report) | synthetic only |
| iLQR / direct trajectory optimization | **not implemented** (DP baseline first, as required) | — |
| Constrained online correction | bounded pace correction only (`PaceCorrector`) | synthetic only |

## 3. Vehicle and powertrain model

`m_eff·dv/dt = F_drive − F_roll − F_aero − F_grade − F_cornering − F_drivetrain` (`models/vehicle/longitudinal.py`):
* **Aerodynamics** uses the air-relative speed `v − wind` (wind component along travel; > 0 = tailwind).
* **Grade** enters as `m g sin θ` and rolling resistance as `Crr m g cos θ`, applied only while moving.
* **Cornering** drag is `F_y² / C_α` with `F_y = m v² κ`; C_α is synthetic.
* **Drivetrain** has an efficiency plus a constant drag. Motor drag is applied **only when the motor is coupled and unpowered** (no freewheel).
* **m_eff** includes wheel inertia, plus motor inertia only when coupled.
* **Coast-down identification** (`fit_coastdown`) fits `A + C·v_air²` with covariance. It reports `identifiable = False` with an explicit verdict when A and C are strongly correlated or poorly determined. Tested: a 14→2 m/s coast identifies both; a 7→6 m/s coast is refused.
* **Battery power** comes from maps `P_batt = f(v, T, V, θ, mode)` that declare which losses they contain. `check_no_double_counting` refuses a map that already includes drivetrain losses if the vehicle model also applies them. `MeasuredLossMap` interpolates absolute loss (W), never efficiency ratios, which are ill-conditioned near zero torque, and refuses to extrapolate.

## 4. Offline DP - SYNTHETIC result, v0.2 actuator model (`docs/generated/optimization_synthetic.md`)

> **The v0.1 figures in this section (39.7 / 46.2 / 55.1 kJ and the "savings" derived from them) are SUPERSEDED and withdrawn.**
> * The v0.1 DP exported mechanical braking as coast.
> * Its simulator braked every strategy automatically to an envelope.
> * Its power map omitted the motor friction power.
> * Its DP checked corner limits only at grid nodes.

v0.2 represents **coast**, **propulsion** (controller torque) and **driver braking** (friction brake, issued as guidance with reaction and tracking assumptions) as separate actuators. All strategies run on one simulator with identical route, start, terminal condition, finish target, actuator limits, driver model and auxiliary load. Nothing brakes automatically, and battery-terminal energy is reconciled per run (`docs/ENERGY_ACCOUNTING.md`).

* **Grid convergence.** 41.18 kJ at 5 m / 0.1 m/s and 41.13 kJ at 2.5 m / 0.05 m/s differ by 0.13 %. Coarser grids (20 m, 10 m) were 6–7 % higher; the comparisons use 5 m.
* **Track A (synthetic, 1 % descent into an R = 20 m corner), executed at matched time:**
  * DP with driver-braking guidance: 42.7 kJ (7.3 kJ dissipated in the friction brake, 8 brake applications);
  * pulse-and-coast with driver braking: 52.5 kJ;
  * constant speed with driver braking: 54.5 kJ.
* **A torque-only policy is physically infeasible on track A.** Coasting from rest at the top of the descent reaches 5.99 m/s at a corner limited to 5.48 m/s. Braking (driver now, regeneration later) is structurally required there. The optimiser reports this; it does not hide it.
* **Track B (the same lap without grades), where torque-only is feasible:**
  * DP torque-only: 33.9 kJ, the same as the DP with braking available (no braking chosen);
  * pulse-and-coast torque-only: 37.1 kJ;
  * constant speed torque-only: 42.9 kJ;
  * the braking-cued baselines did worse than their torque-only versions (45.0 and 50.4 kJ).
* **Driver guidance robustness.**
  * With a 0.3 m/s planning margin, the plan stays within corner limits for driver reactions of 0.5–1.5 s and ±20 % deceleration tracking, except a fast driver braking 20 % weak (+0.16 m/s overspeed).
  * Without the margin, fast reactions overspeed.
  * The margin costs ≈ 2.5 kJ.
* **Model error.** The fixed plan exceeds the 1000 s **limit** with +20 % Crr (1034 s), +5 % mass (1003 s) or a 2 m/s headwind (1053 s). With bounded pace correction, every case finishes at ≈ 958 s, at an energy cost. The reserve and the correction bound must be sized from measured uncertainty.
* **Execution gap.** The executed time exceeds the DP's internal time by up to ≈ 8 s (slew, driver model). The matched comparison re-plans with an internal allowance until the executed run meets the target.
* **Final speed.** The DP finishes slower (≈ 3.8 m/s versus ≈ 6.3 m/s for the cruise baselines). Remaining kinetic energy gets no credit under the terminal condition, and that is part of the DP's advantage.

## 5. Efficiency hypotheses (each evaluated separately, synthetic data)

| # | Hypothesis | Synthetic finding | What would confirm it | Status |
|---|---|---|---|---|
| H1 | Smaller switching losses at an appropriate PWM frequency | Run-weighted inverter + ripple-copper loss has a minimum near 20–30 kHz with L = 150 µH (6.5 W at 5 kHz vs 1.3 W at 20–30 kHz) | measured L; loss-map sweep at stage 6 | open |
| H2 | Better gate-drive and dead-time tuning | Dead time 100→400 ns changes run-weighted loss by only ~0.04 W in the model (voltage distortion not modelled) | measured transitions; dead-time sweep | open — likely small |
| H3 | Lower light-load and coast consumption | Gate-off coasting removes switching and gate losses (~0.2–0.7 W at zero current for the candidates) versus zero-current control. **Gate-off is only valid while line-line back-EMF < Vbus**, or the diodes conduct and brake (validator rule). With no freewheel the motor's iron and friction drag stay in both modes. | coast-down with gate-off vs zero-current, freewheel locked/unlocked | open |
| H4 | Better motor operating-point selection | With Ld = Lq (synthetic) MTPA gives **no** gain; the value depends on saliency | measured Ld, Lq | deferred |
| H5 | Fewer unnecessary accelerations and braking events | v0.2: on track A the DP plan dissipated 7.3 kJ in driver braking vs 12.5 kJ (constant speed) and 12.4 kJ (pulse-and-coast); on the flat track the braking-cued baselines were worse than their torque-only versions (v0.1 figures withdrawn) | matched-time track runs (VALIDATION_PLAN §5) | open |
| H6 | Reduced telemetry/compute/modem consumption | Synthetic electronics budget: 6.5 kJ per 1000 s run (Pi-class computer 4 kJ) against ~40 kJ propulsion, i.e. **~16 %**. If the joulemeter measures everything after the battery (R? 57b/56c), this is first-order. | measured rail currents (stage 2) | open — high priority |
| H7 | Better calibration prevents biased decisions | An uncalibrated 3 mV CSA offset on 1 mΩ = 3 A against ~2 A cruise current; any strategy using that current would be badly biased | per-board offset calibration; INA228 cross-check | open — mandatory |

## 6. Not assumed
* FOC does **not** always beat six-step for this motor (motor unknown; ADR-0003 path C).
* Pulse-and-coast does **not** always beat constant speed (track-dependent; see the caveat in §4).
* More parallel MOSFETs do **not** always improve efficiency. In the synthetic calcs, 2–3 devices per switch **increased** run-weighted loss (gate and Coss at light load).
* MTPA is **not** universally useful (H4).
* Regeneration is **not** assumed to beat avoiding unnecessary acceleration (deferred, rules unknown).
* CdA and Crr are **not** assumed separately identifiable (identifiability check).

## 7. Deferred until baseline benefit and hazard are measured
Field weakening · variable switching frequency · discontinuous PWM · active regeneration · online parameter adaptation · iLQR/direct methods (after the DP baseline is validated on measured data).
