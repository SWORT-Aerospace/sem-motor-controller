# Energy and powertrain models (`models/`)

Python models for the offline energy work of the project: the longitudinal dynamics of the vehicle and the identification of its road load from a coast-down, a battery-power map of the motor and inverter, first-order inverter loss and power-stage calculations, and an offline spatial dynamic-programming (DP) optimiser with a common forward simulator for comparing driving strategies. "Spatial" means the problem is discretised in position along the track, not in time.

**Every parameter is SYNTHETIC.** `SYNTHETIC_VEHICLE`, `SYNTHETIC_MOTOR`, `SYNTHETIC_FET`, `SYNTHETIC_GATE`, `synthetic_track()`, the 3 W auxiliary load, the driver model and the guidance assumptions are invented placeholders chosen to exercise the methods. No result computed with them predicts the energy of the real vehicle. Nothing in this directory runs on the vehicle, and no part of it has been checked against a measurement or against hardware.

## 1. What the directory contains

```
models/
  vehicle/longitudinal.py     vehicle parameters, resistive and tractive forces, effective mass, coast-down fit
  vehicle/powertrain.py       battery-power maps: synthetic physics map, measured loss map, double-count check
  inverter/losses.py          two-level MOSFET inverter losses and power-stage calculations
  optimization/track.py       track description: grade, curvature, stops, corner speed limits
  optimization/dp.py          offline spatial DP optimiser, schedule and driver-guidance export
  optimization/strategies.py  common time-domain simulator, baseline strategies, DP schedule follower
  __init__.py (x4)            empty package markers
```

The quantity every model and strategy is scored on is battery-terminal energy, the energy a joulemeter at the battery terminals would measure. What that energy contains, and where each term is modelled, is set out in [../docs/ENERGY_ACCOUNTING.md](../docs/ENERGY_ACCOUNTING.md). The equations, with worked numerical examples, are in [../docs/MATH_SPEC.md](../docs/MATH_SPEC.md) sections 1, 2 and 4.

## 2. Who works here

* **Controls lead (energy strategy).** Owns the DP optimiser, the strategies and the power map. The input sheet ([../docs/INPUT_SHEET.md](../docs/INPUT_SHEET.md), item 3) assigns the measured battery-power map and the coast-down to the controls lead together with the vehicle team; those measurements are what replace the synthetic parameters here.
* **Whoever sizes the power stage.** `inverter/losses.py` is the calculation library behind [../tools/run_electrical_calcs.py](../tools/run_electrical_calcs.py) and [../tools/hardware_calcs.py](../tools/hardware_calcs.py).
* **Vehicle team.** Supplies mass with driver, gear ratio, loaded wheel circumference, freewheel arrangement, coast-down runs and the event's time limit and lap structure.

## 3. Important files

| File | What it does in the system | Inputs | Outputs |
|---|---|---|---|
| [vehicle/longitudinal.py](vehicle/longitudinal.py) | Defines `VehicleParams` and the force balance that every energy calculation uses. `resistive_force` sums rolling, aerodynamic, grade, cornering, drivetrain and coupled-motor drag; `tractive_force` turns motor shaft torque into wheel force; `fit_coastdown` estimates road-load coefficients from a coast-down and states whether rolling and aerodynamic resistance are separately identifiable. | vehicle parameters (`SYNTHETIC_VEHICLE` until measured); speed, grade, wind, curvature; motor torque; coast-down time and speed arrays | forces [N], effective mass [kg], motor speed [rad/s], a `CoastdownFit` with coefficients, covariance and verdict; synthetic coast-down traces for testing the fit |
| [vehicle/powertrain.py](vehicle/powertrain.py) | Converts an operating point (speed, torque, bus voltage, mode) into battery-terminal power, declaring which losses the map already contains so the vehicle model never applies one twice. `SyntheticPhysicsMap` builds the power from motor copper and iron loss, motor friction, inverter loss and an auxiliary load; `MeasuredLossMap` interpolates a measured loss grid and refuses to extrapolate. | `VehicleParams`; `MotorParams`, `MosfetParams`, `GateDriveParams`; or a measured loss CSV | battery power [W] per operating point; a per-term breakdown; `ValueError` for unmodelled or out-of-grid operating points |
| [inverter/losses.py](inverter/losses.py) | First-order power-stage arithmetic for a two-level three-phase MOSFET (metal-oxide-semiconductor field-effect transistor) bridge: conduction, switching, output-capacitance, gate-drive, dead-time and reverse-recovery losses; DC-link ripple current; precharge; junction temperature; shunt sizing; fuse coordination. The power map calls `inverter_losses` at every drive operating point. | MOSFET and gate-driver parameters, bus voltage, phase peak current, modulation index, power factor, switching frequency, dead time, junction temperature | loss breakdown [W] and switching times; ripple, thermal and sizing figures as dictionaries |
| [optimization/track.py](optimization/track.py) | Describes the route the optimiser and simulator drive: per-lap piecewise grade and curvature, mandatory stops, and the corner speed limit derived from a lateral-acceleration bound. Provides the synthetic 1.5 km lap and a flat variant. | lap length, lap count, segment lists, stop positions, lateral-acceleration and global speed limits | grade [rad], curvature [1/m] and speed limit [m/s] at any position; sampled profiles for the DP grid |
| [optimization/dp.py](optimization/dp.py) | Computes the minimum battery-energy plan for a finish-time target over a position grid, with coast, propulsion and driver braking as separate actuators, and exports it as a bounded controller schedule and as driver braking guidance. Infeasible problems are reported with a reason instead of being relaxed. | `Track`, `VehicleParams`, a `PowerMap`, a `DPConfig` (grid, torque levels, brake levels, time limit, reserve, wind) | a `DPResult` (speed, action, torque, brake force, energy and time per segment; feasibility and reason); schedule and guidance CSV files at a path the caller gives |
| [optimization/strategies.py](optimization/strategies.py) | Runs any strategy (constant speed, pulse-and-coast, DP schedule follower with optional bounded pace correction) on one time-domain simulator with the same route, start, finish condition, torque slew and bound, acceleration limit, driver braking model and auxiliary load, and reconciles tractive work against kinetic energy, resistive work and brake work. Corner overspeed and missed stops are recorded as violations, never corrected. | `Track`, `VehicleParams`, a `PowerMap`, a controller callable, a `SimConfig` (time step, torque limits, driver model, wind) | a `SimResult`: battery, brake and auxiliary energy, time, violations, counters, energy reconciliation and an optional trace |

### 3.1 Longitudinal vehicle model (`vehicle/longitudinal.py`)

Force balance, with every resisting term returned by `resistive_force`:

```
m_eff * dv/dt = F_drive - F_roll - F_aero - F_grade - F_corner - F_drivetrain  (- F_motor when the motor is coupled and unpowered)
```

Sign conventions (SI units):

| Quantity | Convention |
|---|---|
| `v` | forward ground speed [m/s], `v >= 0` |
| `wind` | component of the wind velocity along the direction of travel [m/s]; positive is a tailwind, so a headwind is a negative number. Air-relative speed `v_air = v - wind` |
| `grade` | road angle `theta` [rad], positive uphill. Tracks store the angle, for example `atan(0.01)` for a 1 % climb |
| `curvature` | `kappa = 1/R` [1/m], 0 on straights; only its magnitude is used |
| `F_drive` | tractive force at the tyre contact patch, after the drivetrain |
| motor torque | motor shaft torque [N*m], positive for forward motoring |

Terms computed by `resistive_force(p, v, grade, wind, curvature, motor_coupled_unpowered)`:

| Term | Expression in the code | Applied when |
|---|---|---|
| aerodynamic | `0.5 * rho_air * cda_m2 * v_air * abs(v_air)` | always; becomes a push (negative) when a tailwind is faster than the vehicle |
| rolling | `crr * mass_kg * g * cos(grade)` | only while moving (`v > 1e-6` m/s) |
| grade | `mass_kg * g * sin(grade)` | always; negative (assisting) on a descent |
| cornering | `F_y**2 / cornering_stiffness_N_rad`, with lateral force `F_y = mass_kg * v**2 * abs(curvature)` | curvature non-zero and a finite cornering stiffness (the default `inf` disables it) |
| drivetrain drag | constant `drivetrain_drag_N` at the wheel | only while moving |
| coupled motor drag | `(motor_drag_Nm + motor_drag_Nm_per_rad_s * w) * gear_ratio / wheel_radius_m` | only with `motor_coupled_unpowered=True` and while moving |

The total can be negative on a descent or with a strong tailwind. `resistive_force_np` is the vectorised form with the same terms, used by the DP; its docstring says it is "tested for equality" with `resistive_force`, but no test in the repository compares the two.

**Rotating inertia.** `VehicleParams.m_eff(coupled)` returns the effective translating mass `mass_kg + j_wheels_kg_m2 / r**2`, plus `j_motor_kg_m2 * gear_ratio**2 / r**2` when the motor is coupled to the wheel. Driving always uses the coupled value. Coasting uses `m_eff(coupled=not freewheel)`: with a freewheel the motor decouples and its inertia drops out.

**Gear ratio convention.** `gear_ratio` is motor speed divided by wheel speed, so a reduction has `gear_ratio > 1`.
* `VehicleParams.motor_speed(v) = v * gear_ratio / wheel_radius_m` [rad/s].
* `tractive_force(p, T) = max(T, 0) * gear_ratio * drivetrain_eff / wheel_radius_m`: motoring only, `drivetrain_eff` is the forward efficiency of the reduction, and regenerative braking is not modelled.
* `motor_torque_for_force(p, F)` is the inverse, `max(F, 0) * wheel_radius_m / (gear_ratio * drivetrain_eff)`.

**Coast-down identification.** `fit_coastdown(t, v, m_eff, mass_kg, grade=0, wind=0, with_linear=False, max_corr=0.95, max_rel_std=0.25)` takes a central-difference acceleration (`numpy.gradient`), drops two samples at each end, and solves by least squares

```
-m_eff * a - mass_kg * g * sin(grade) = A + B * v + C * v_air * abs(v_air)      (B only with with_linear=True)
```

where `A` is approximately `Crr * m * g` plus constant drags and `C = 0.5 * rho * CdA`. The returned `CoastdownFit` holds `A_N`, `B_N_s_m`, `C_N_s2_m2`, the covariance, `corr(A, C)`, the relative standard deviations of A and C, the condition number, the speed range and the sample count. `identifiable` is true only if `abs(corr(A, C)) <= max_corr`, both relative standard deviations are at most `max_rel_std` and both A and C are positive; otherwise the verdict states that only the combined resistance over the tested speed range is supported. `CoastdownFit.crr(mass_kg, const_drag_N)` returns `(A - const_drag) / (m * g)` and `CoastdownFit.cda(rho)` returns `2 * C / rho`. `simulate_coastdown(p, v0, v_end, dt, grade, wind, noise_mps, rng)` produces a synthetic coast-down (midpoint second-order integration, motor decoupled when the vehicle has a freewheel) with optional Gaussian speed noise, for testing the fit against known parameters.

**Synthetic vehicle** (`SYNTHETIC_VEHICLE`): mass 100 kg with driver; wheel radius 1.50 m / (2 pi) = 0.2387 m; gear ratio 10; Crr 0.0025; CdA 0.035 m^2; air density 1.20 kg/m^3; wheel inertia 0.06 kg*m^2 (all wheels); motor inertia 2.0e-4 kg*m^2; drivetrain efficiency 0.95; drivetrain drag 0.3 N; cornering stiffness 4000 N/rad; freewheel present; coupled motor drag 0.01 N*m + 2.0e-5 N*m per rad/s.

### 3.2 Powertrain and battery-power map (`vehicle/powertrain.py`)

A power map is any object with `p_batt(v_mps, motor_torque_Nm, v_bus, temp_C, mode)` returning battery-terminal power [W], a `label`, and an `includes` set naming which loss components it already contains (`motor_copper`, `motor_iron`, `motor_friction`, `inverter`, `drivetrain`, `aux`). The modes are `drive`, `coast_gate_off` and `coast_zero_current`. Maps return absolute battery power rather than an efficiency, because an efficiency ratio is ill-conditioned near zero torque.

`SyntheticPhysicsMap(vehicle, motor, fet, gate, f_sw_Hz=20e3, deadtime_s=200e-9, p_aux_W=3.0, tj_C=60.0)`:
* `drive`: with `w` the motor mechanical speed and `w_e = pole_pairs * w` the electrical speed, the electromagnetic torque is `T_em = T + friction_Nm` (friction only while turning) and the q-axis (torque-producing) current is `i_q = T_em / K_t` with `K_t = 1.5 * pole_pairs * lambda_Wb`. Copper loss `1.5 * R_s * i_q**2`, iron loss `k_iron * w**1.5` (a synthetic form), inverter loss from `inverter_losses` at a modulation index estimated from `v_q = R_s * i_q + w_e * lambda` (the `L * w * i_q` term is neglected; the index is capped at 2/sqrt(3)). Battery power `= T_em * w + copper + iron + inverter + p_aux`. Charging `T_em * w` rather than `T * w` includes the motor's own friction power while driving.
* `coast_gate_off`: auxiliary power only. Raises `ValueError` if the line-to-line peak back-EMF (the voltage the spinning motor generates) `sqrt(3) * lambda * w_e` reaches the bus voltage, because rectification through the body diodes is not modelled.
* `coast_zero_current`: `i_q = 0`; inverter loss at zero current plus auxiliary power. Iron and friction losses are then supplied by the vehicle's kinetic energy, not by the battery.
* `includes` is `motor_copper, motor_iron, motor_friction, inverter, aux`; drivetrain losses stay in the vehicle model (`drivetrain_eff`, `drivetrain_drag_N`).
* `breakdown(v, T, v_bus, mode)` splits battery power into shaft, motor friction, copper plus iron, inverter and auxiliary terms.

Synthetic parts: `SYNTHETIC_MOTOR` (4 pole pairs, 0.10 ohm, 0.010 Wb, so `K_t` = 0.06 N*m/A; iron coefficient 2.0e-3 W per (rad/s)^1.5; friction 0.005 N*m), `SYNTHETIC_FET` (4 mohm at 25 degC, Qg 60 nC, Qgd 12 nC) and `SYNTHETIC_GATE` (10 V drive, 0.3 A source, 0.6 A sink, 5 ohm external gate resistance).

`MeasuredLossMap.from_csv(path, vehicle, p_aux_W)` is the intended replacement once a bench map exists. The CSV has a header comment `# includes=... ; v_bus=... ; provenance=...` followed by `speed_rad_s,torque_Nm,p_loss_W` rows on a complete grid. Unknown loss components and incomplete grids are rejected. `p_batt` returns `T * w` plus the bilinearly interpolated loss plus the auxiliary load (only if `aux` is not already included), and raises `ValueError` outside the measured grid.

`check_no_double_counting(vehicle, pmap)` raises if the map includes `drivetrain` while the vehicle model also applies a drivetrain efficiency or drag.

### 3.3 Inverter losses (`inverter/losses.py`)

Every input is explicit; nothing selects a part. Currents are kept apart: phase peak `I_ph_pk`, phase RMS (root mean square) `I_ph_pk / sqrt(2)` for sinusoidal current, and battery average `P_dc / V_bus`. The modulation index `M` is the phase-voltage peak divided by `V_bus / 2`.

| Function | What it computes |
|---|---|
| `switching_times(m, g)` | turn-on and turn-off times `(Qgs2 + Qgd) / I`, with the driver current limited by its setting and by the gate resistance |
| `inverter_losses(m, g, op)` | whole-bridge losses by mechanism: conduction `R_DS(on)(T_j) * I_pk**2 / 4` per device (synchronous bridge, independent of M and power factor), hard switching `(1/pi) * V * I_pk * (t_on + t_off) / 2 * f_sw` per leg, output capacitance, gate drive `6 * n * Qg * V_drive * f_sw`, dead-time body-diode conduction, reverse recovery; plus total, hottest-device loss and switching times; `n_parallel` devices per switch |
| `phase_currents`, `battery_current` | torque and phase peak and RMS currents from mechanical power, speed and torque constant; battery current from DC power and bus voltage |
| `dc_link_ripple_rms` | RMS current in the DC-link (direct-current bus) capacitor for sinusoidal PWM (pulse-width modulation), Kolar and Round form |
| `capacitor_check`, `bus_voltage_ripple_pp` | per-capacitor ripple current, loss in the equivalent series resistance (ESR) and voltage derating; worst-case switching-frequency bus ripple |
| `max_bus_voltage` | design bus voltage from maximum charged voltage, margin and measured ringing |
| `precharge` | resistor-capacitor precharge: time constant, time to a fraction of the voltage, resistor energy and peak power |
| `junction_temperature`, `solve_tj` | junction temperature from a thermal path; fixed-point iteration between junction temperature and losses |
| `shunt`, `amplifier_settling_ok` | low-side shunt dissipation, full-scale current, resolution of the analogue-to-digital converter (ADC) and offset error; whether the sampling window fits dead time, settling and sampling |
| `conductor_loss`, `fuse_coordination`, `aux_energy_per_run` | wiring loss; first-order fuse checks; auxiliary energy over a run |

### 3.4 Track (`optimization/track.py`)

`Track(lap_length_m, laps, grade_segments, curvature_segments, stop_positions_m, a_lat_max=1.5, v_max_global=12.0)` holds per-lap lists of `(start_m, end_m, value)` that repeat every lap. `grade(s)` and `curvature(s)` look up the value at any position, `v_limit(s) = min(v_max_global, sqrt(a_lat_max / abs(kappa)))`, `is_stop(s, ds)` marks stop nodes and `sample(ds)` returns the profiles on a grid. `synthetic_track()` is a 1.5 km lap driven 4 times, with a 300 m climb at 1 % (200 m to 500 m), a 300 m descent at 1 % (700 m to 1000 m) and four corners of radius 25, 40, 20 and 35 m. `synthetic_track_flat()` is the same lap without the climb and descent. Both are invented for software development and are not any real Shell Eco-marathon circuit.

### 3.5 Spatial DP optimiser (`optimization/dp.py`)

Problem (discretised in position `s`):

```
minimise    sum_k E_batt,k
subject to  sum_k dt_k <= t_max_s - reserve_s
            0 <= v_k <= v_limit(s_k)          overspeed is infeasible; nothing brakes implicitly
            v_k = 0 at mandatory stops         at rest within stop_zone_m before the stop line
            (F_drive - F_res) / m <= a_max     a torque level that exceeds it is not available
```

One actuator per segment, never mixed: `COAST` (gates off, no brake; auxiliary power only), `PROPEL(T)` with `n_torque` levels evenly spaced up to `torque_max_Nm`, and `DRIVER_BRAKE` at each of `brake_decel_levels` (brake force `m_eff * level`, gates off). The controller cannot command the brake, so a plan that brakes is issued to the driver as guidance. Policy `propulsion_coast_brake` uses all three; `propulsion_coast` is torque only and reports the problem infeasible if corners and stops cannot be met by coasting.

Segment transition at speed `v_i` over length `ds`, with the resistance evaluated at the mid-segment speed from a predictor step:

```
v_{i+1}^2 = v_i^2 + 2 * ds * (F_drive - F_res(v_mid) - F_brake) / m_eff
dt        = 2 * ds / (v_i + v_{i+1})
E_batt    = P_batt(v_mid, action) * dt          E_brake = F_brake * distance
```

The finish-time constraint is handled by Lagrangian relaxation, minimising `J = E + lambda * t` with `lambda` found by bisection between 0 and `lambda_hi`. Each solve is a backward recursion of the cost-to-go over the speed grid followed by a forward pass from rest at `s = 0`; the final speed is free. Corner limits are checked over the whole of each segment (sampled every 1 m), and an exact upper feasibility envelope (strongest available deceleration) prunes dead ends.

| `DPConfig` field | Default | Meaning |
|---|---|---|
| `ds_m`, `dv_mps` | 10.0 m, 0.2 m/s | position and speed grid steps |
| `n_torque`, `torque_max_Nm` | 10, 2.0 N*m | propulsion torque levels |
| `v_bus` | 46.0 V | bus voltage passed to the power map |
| `policy` | `propulsion_coast_brake` | actuator set |
| `brake_decel_levels` | 0.5, 1.0, 1.5, 2.0 m/s^2 | nominal driver braking levels (synthetic) |
| `a_max` | 1.5 m/s^2 | acceleration bound |
| `stop_zone_m` | 2.0 m | assumed stopping zone before a stop line |
| `v_margin_mps` | 0.0 | planning margin below every corner limit |
| `t_max_s`, `reserve_s` | 1000 s, 30 s | finish-time limit and reserve (placeholders, not the event's rules) |
| `wind_mps` | 0.0 | wind, same sign convention as above |
| `lambda_hi`, `bisection_iters` | 400, 28 | bisection range and iterations |

Functions:
* `solve(track, veh, pmap, cfg)` returns a `DPResult` with node speeds and times, per-segment action (`kind`), torque, brake force, battery and brake energy, totals, `lam`, `feasible` and `infeasible_reason`. `DPResult.u_coast` marks gate-off segments without braking.
* `precompute` and `solve_for_lambda` expose the transition table and a single solve for a fixed `lambda`.
* `coast_envelope(track, veh, ds, wind_mps)` returns the highest speed at each position from which coasting alone stays under every downstream corner limit, and the first position where no such speed exists (for example a descent into a corner).
* `export_schedule(res, path, torque_bound_Nm, model_label)` writes the position-indexed schedule CSV with a metadata header. Controller torque is clipped to the bound; `driver_brake` rows carry zero controller torque.
* `brake_blocks(res)` groups contiguous braking segments; `export_guidance(res, path, GuidanceAssumptions)` writes driver braking cues advanced by the assumed reaction distance (`v * reaction_s`), with the assumptions in the header.

The result is optimal only within the discretised model (grid, control set and parameters).

### 3.6 Strategies and forward simulator (`optimization/strategies.py`)

`simulate(track, veh, pmap, ctrl, cfg, record=False)` integrates from rest at `s = 0` to the finish line with an explicit time step (`SimConfig.dt`, default 0.05 s). On every step:
* the driver model (`DriverModel`: reaction 1.0 s, release 0.7 s, achieved-to-requested force ratio 1.0) applies the friction brake that the strategy cues;
* while the brake is applied the controller torque is zero (brake override); otherwise the requested torque is bounded by `torque_max_Nm` (2.0), slewed (5 N*m/s up, 10 N*m/s down) and reduced so that the acceleration stays within `a_max`, and the reduced torque is the one whose battery power is charged;
* battery power comes from the power map (`drive` while torque is positive, otherwise `coast_gate_off`);
* corner overspeed (beyond `overspeed_tol_mps`) and passing a stop above 0.2 m/s are counted as violations.

The run reconciles `tractive work = delta kinetic energy + resistive work + brake work`; a non-zero `residual_J` would mean a force was applied without being charged. `SimResult.valid` is true only if the run finished with no overspeed event and no missed stop.

Controllers are callables `(s, v, t) -> Command(torque_Nm, coast, brake_cue_N)`:
* `constant_speed(v_set, veh, kp, brake, v_cap)`: feed-forward torque for the flat-road resistance at the set speed plus a proportional term; optional braking cues or a coast envelope cap.
* `pulse_and_coast(v_lo, v_hi, torque_Nm, brake, v_cap)`: fixed-torque pulses up to `v_hi`, gate-off coasting down to `v_lo`.
* `schedule_follower(...)`: executes a DP plan segment by segment and turns each braking block into a target-speed cue for the driver.
* `EnvelopeBrakeCue`: baseline braking guidance for non-optimised strategies, from `braking_envelope` at a reduced planning deceleration with a speed margin and a reaction look-ahead.
* `PaceCorrector(k_Nm_per_s=0.05, bound_Nm=0.3)`: bounded pace correction `delta_T = clip(k * (t - t_plan(s)), -bound, +bound)`, positive when behind schedule, acting on propulsion torque only.
* `bisect_param(f_time, lo, hi, t_target)`: bisection of a strategy parameter to the smallest value that meets the finish-time target.

## 4. Inputs and outputs of the directory

**Inputs.** Parameter objects defined in code (the `SYNTHETIC_*` constants and track functions), objects built by the calling tool, and optionally a measured loss-map CSV read by `MeasuredLossMap.from_csv`. The models do not read [../config/vehicle.synthetic.yaml](../config/vehicle.synthetic.yaml) or any other configuration file.

**Outputs.** Python objects returned to the caller. The only files written from inside the package are the schedule and guidance CSV files of `export_schedule` and `export_guidance`, at paths the caller supplies. The study tools turn these results into the generated reports:

| Tool | Uses | Writes |
|---|---|---|
| [../tools/run_optimization.py](../tools/run_optimization.py) | DP, strategies, track, vehicle, power map | `docs/generated/optimization_synthetic.md` and `.json`, `dp_schedule_synthetic.csv`, `dp_driver_guidance_synthetic.csv`, `dp_schedule_torque_only_flat_synthetic.csv`, `docs/figures/dp_plan_synthetic.png` |
| [../tools/run_electrical_calcs.py](../tools/run_electrical_calcs.py) | `inverter/losses.py` | `docs/generated/electrical_calcs_synthetic.md`, `docs/figures/electrical_sensitivity_synthetic.png` |
| [../tools/hardware_calcs.py](../tools/hardware_calcs.py) | `inverter/losses.py` | `hardware/calculations/current_sense_error_budget.md`, `hardware/calculations/power_stage_envelope.md` |
| [../tools/coastdown_sensitivity.py](../tools/coastdown_sensitivity.py) | `simulate_coastdown`, `fit_coastdown` | `docs/generated/coastdown_sensitivity.md` |

## 5. Dependencies on other directories

* **Python packages:** NumPy and the standard library only (pinned in [../requirements.txt](../requirements.txt)). Plotting is done by the tools, not by the models.
* **Inside `models/`:** `optimization/` imports `vehicle/`; `vehicle/powertrain.py` imports `inverter/losses.py`.
* **Other directories:** none are imported. Nothing in `firmware/`, `host/` or `protocol/` imports `models/`; the controller co-simulation uses its own C plant (`firmware/platform/host/sim_plant.c`, described in [../docs/MATH_SPEC.md](../docs/MATH_SPEC.md) 2.8).
* **Users:** the four tools above and three test files: [../tests/simulation/test_models.py](../tests/simulation/test_models.py); [../tests/integration/test_math_spec.py](../tests/integration/test_math_spec.py), which recomputes every numerical example of `docs/MATH_SPEC.md` with this code, so a model change fails it until the document is updated; and [../tests/integration/test_pit_energy.py](../tests/integration/test_pit_energy.py), which checks the worked example in the root README against `resistive_force`, `motor_torque_for_force` and `tractive_force`.

## 6. How to run and test

From the repository root, inside the virtual environment created from `requirements.txt`:

```sh
python3 -m pytest tests/simulation/test_models.py          # model tests (vehicle, inverter, DP, simulator)
python3 -m pytest tests/integration/test_math_spec.py      # MATH_SPEC examples recomputed with this code
python3 tools/coastdown_sensitivity.py --check             # committed coast-down table is current (writes nothing)
python3 tools/run_optimization.py --quick                  # strategy study on the two coarsest grids, as in CI
python3 tools/run_optimization.py                          # full study: grids 20 m to 2.5 m, comparisons on 5 m
python3 tools/run_electrical_calcs.py                      # inverter loss study
python3 tools/hardware_calcs.py                            # current-sense and power-stage envelopes
```

`tests/simulation/test_models.py` needs no C build. The tests in [../tests/README.md](../tests/README.md) describe the wider suite.

**Quick run:** since v0.5, `run_optimization.py --quick` writes its coarse-grid results to `build/optimization_quick/` and leaves the committed outputs of section 4 alone. The committed files come from the full run (the schedule header records `ds=5.0 m dv=0.1 m/s`; a quick run writes `ds=20.0 m dv=0.4 m/s`). On an x86-64 host the quick run took about 1.5 minutes.

## 7. Generated files

No file in `models/` is generated; everything here is edited by hand. The reports produced from these models (section 4) are generated and must not be edited by hand. Regenerate them with the tool named in the table; `python3 tools/coastdown_sensitivity.py --check` confirms that the committed coast-down table matches the code.

## 8. Current limitations

* All parameters are synthetic (section 1). The time limit, reserve, lap count and track are placeholders, not the event's rules.
* Regenerative braking is not modelled: `tractive_force` clamps negative torque to zero and braking exists only as the driver's friction brake.
* Gate-off coasting with back-EMF above the bus voltage (rectification) is not modelled; `SyntheticPhysicsMap` raises instead.
* The inverter formulas are first-order approximations that must be checked against the chosen parts' datasheets and measurements.
* `SyntheticPhysicsMap` ignores its `temp_C` argument (the junction temperature is fixed at 60 degC) and neglects the `L * w * i_q` voltage term. The iron-loss form `k * w**1.5` is itself synthetic.
* `MeasuredLossMap` ignores its `v_bus`, `temp_C` and `mode` arguments (it returns `T * w` + loss + auxiliary power in every mode) and does not extrapolate beyond the measured grid.
* `check_no_double_counting` checks only the drivetrain term; its motor-friction branch performs no check.
* The DP is optimal only within its grid and control set; one actuator per segment; final speed free, so no credit is given for kinetic energy left at the finish; the 2 m stop zone is an assumption.
* The forward simulator uses an explicit Euler step of 0.05 s, and the driver model and braking-cue logic are synthetic.
* The synthetic values that also appear in `config/vehicle.synthetic.yaml` (mass, gear ratio, wheel circumference, pole pairs, phase resistance, flux linkage) are written separately in Python; no test compares the two.
* `fit_coastdown` treats grade and wind as known inputs. `tools/coastdown_sensitivity.py` shows the bias when they are not.
* `resistive_force` (simulator, coast-down) and `resistive_force_np` (DP) are separate implementations of the same terms. They agree to floating-point rounding today, but no test guards that, so a change to one must be copied to the other by hand.
