# Mathematical specification (v0.4)

Every equation below is implemented in the named file and checked by the named test. Every numerical example is recomputed by the code in `tests/integration/test_math_spec.py` (Python models) or `firmware/tests/test_state_machine.c::test_math_spec_examples` (controller arbitration). If code and document diverge, those tests fail. Units are SI unless stated; torque in N·m, angular speed in rad/s (mechanical unless marked e for electrical).

**Parameter status** used below:
* **SYN**: synthetic placeholder from `config/vehicle.synthetic.yaml` or a model default; not a property of the vehicle.
* **PROV**: provisional design choice, to be confirmed (timing, thresholds).
* **DER**: derived from other parameters by a stated formula.
* **MEAS**: measured on the vehicle or bench. No parameter has this status yet.

**Motor model assumption.** The controller and models assume a three-phase, sinusoidally wound, surface-mounted permanent-magnet synchronous motor (PMSM): no saliency (Ld = Lq), no magnetic saturation, amplitude-invariant dq scaling, Hall sensors for the rotor sector. The team's actual motor type, winding (sinusoidal or trapezoidal back-EMF), pole pairs, resistance, flux linkage and Hall placement are unknown (input sheet items 1–3). A trapezoidal BLDC motor would change the torque equation (2.2) and the current loop.

## 1. Vehicle dynamics (`models/vehicle/longitudinal.py`)

| # | Equation | Implementation | Example (synthetic) | Verified by | Status |
|---|---|---|---|---|---|
| 1.1 | m_eff dv/dt = F_drive − F_roll − F_aero − F_grade − F_corner − F_dt (− F_motor when coupled and unpowered) | `resistive_force` l.61 | – | `tests/simulation/test_models.py` | – |
| 1.2 | m_eff = m + J_w / r² (+ J_m G² / r² when coupled) | `VehicleParams.m_eff` l.43 | r = 1.50/(2π) = 0.238732 m; m_eff = 100 + 0.06/0.056993 = 101.053 kg; coupled 101.404 kg | `test_1_vehicle_dynamics` | m, J SYN |
| 1.3 | F_roll = C_rr m g cos θ (v > 0) | l.66 | 0.0025 × 100 × 9.80665 = 2.4517 N | same | C_rr SYN |
| 1.4 | F_aero = ½ ρ C_dA v_air abs(v_air), v_air = v − wind | l.65 | ½ × 1.20 × 0.035 × 7² = 1.029 N at 7 m/s | same | C_dA SYN |
| 1.5 | F_grade = m g sin θ | l.67 | 1 % grade: 9.81 N; F_res(7 m/s, 1 %) = 13.587 N | same | track SYN |
| 1.6 | F_drive = T G η_dt / r (motoring only) | `tractive_force` l.99 | 1 N·m: 1 × 10 × 0.95 / 0.238732 = 39.794 N | same | G, η SYN |
| 1.7 | Coast-down: −m_eff a − m g sin θ = A + C v_air² (B v optional); A ≈ C_rr m g + constant drags, C = ½ ρ C_dA; least squares with covariance and an identifiability verdict (corr(A, C), relative std) | `fit_coastdown` l.137 | – | `test_models.py` coast-down tests | to be MEAS |

Dimensions: (1.2) kg + kg·m²/m² = kg. (1.4) kg/m³ · m² · m²/s² = N. (1.6) N·m / m = N.

At 7 m/s the synthetic vehicle needs F_res = 1.029 + 2.452 + 0.300 = 3.781 N, i.e. 26.5 W at the wheel.

## 2. Motor and inverter (`models/vehicle/powertrain.py`, `models/inverter/losses.py`, `firmware/src/control/`)

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 2.1 | Clarke (two measured phases): i_α = i_a, i_β = (i_a + 2 i_b)/√3; Park: i_d = i_α cos θ_e + i_β sin θ_e, i_q = −i_α sin θ_e + i_β cos θ_e | `mc_transforms.c` `mc_clarke2` l.5, `mc_park` l.30 | i_a = 1, i_b = −0.5: i_α = 1, i_β = 0; θ_e = 30°: i_d = 0.866, i_q = −0.5 | `test_control.c::test_clarke_park_roundtrip` | convention: d-first, amplitude-invariant (ST UM1052 p.41; Microchip AN1078 header l.401–441) |
| 2.2 | T_e = (3/2) p λ i_q = K_t i_q, K_t = 1.5 p λ (PMSM, Ld = Lq) | `config_tool.py` l.227; `MotorParams.kt` l.46 | 1.5 × 4 × 0.010 = 0.06 N·m/A; 1 N·m → i_q = 16.67 A | `test_2_motor_and_inverter`; `test_math_spec_examples` | p, λ SYN; K_t DER |
| 2.3 | P_cu = (3/2) R_s (i_d² + i_q²) | `powertrain.py` l.89 | 1 N·m: 1.5 × 0.10 × 16.67² = 41.67 W | same | R_s SYN |
| 2.4 | P_fe = k_fe ω^1.5 (synthetic form) | l.90 | at 7 m/s, ω = 293.2 rad/s: 2e-3 × 293.2^1.5 = 10.04 W | same | form and k_fe SYN |
| 2.5 | Inverter: P_cond = R_DS(on)(T_j) I_pk²/4 per device; P_sw = (1/π) V_bus I_pk (t_on + t_off)/2 f_sw per leg; P_gate = 6 Q_g V_drv f_sw; P_dead = 2 V_f (I_pk/π) t_dead f_sw per leg; P_oss, P_rr crude | `losses.py` l.88–98 | 46 V, 5 A pk, 20 kHz: gate 6 × 60 nC × 10 V × 20 kHz = 72 mW; total 0.686 W | same | FET data SYN; P_gate form: TI SLUA618A Eq. 9 |
| 2.6 | P_batt = T_em ω + P_cu + P_fe + P_inv + P_aux (drive); P_aux (coast, gates off) | `SyntheticPhysicsMap.p_batt` l.70 | 7 m/s, 0.1 N·m: shaft 29.32 + friction 1.47 + Cu/Fe 10.50 + inverter 0.36 + aux 3.00 = 44.65 W; coast 3.00 W | same | all SYN; preferred replacement: `MeasuredLossMap` |
| 2.7 | i_q,ref = clamp(T_accepted / K_t, ±I_max) | `mc_arbiter.c` l.206 | 0.28 N·m → 4.67 A | `test_state_machine.c` | I_max SYN |
| 2.8 | Host plant (simulation only): dq electrical model with Ld, Lq, R, back-EMF; rigid drivetrain (no freewheel); inverter loss 3 I_rms² R_DS + k_sw V I_pk; battery V = OCV − R_int I | `firmware/platform/host/sim_plant.c` l.61–124 | – | `test_core.c`, host demo | SYN; a test plant, not a vehicle model |

Dimensions: (2.2) N·m/A = V·s/rad: λ in Wb = V·s. (2.3) Ω·A² = W. (2.5) V·A·s·Hz = W; C·V·Hz = W.

Observation from (2.6): at cruise the synthetic iron loss (10 W, independent of torque) is a third of the shaft power and much larger than the copper loss (0.5 W). A torque-independent loss while driving that disappears while coasting (freewheel open, gates off) makes battery power a non-convex function of torque, which is the condition under which pulse-and-glide can beat steady speed (section 4.4). Whether the real drivetrain has that property is a measurement question (input sheet item 4).

## 3. Supervisory control and arbitration (`firmware/src/state_machine/mc_arbiter.c`, `firmware/src/telemetry/mc_freshness.c`, `firmware/src/core/mc_core.c`)

The four-layer contract of `docs/CONTROL_CONTRACT.md`: L0 hardware shutdown, L1 immediate inhibits, L2 local hard ceilings, L3 supervisory envelope, L4 comfort slew.

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 3.1 | T_static = min(T_max, K_t I_max) | l.128 | min(2.0, 0.06 × 40) = 2.0 N·m | `test_math_spec_examples` | SYN |
| 3.2 | Battery feed-forward ceiling T_batt = η_min V_bus I_batt,max / ω (ω above a floor, speed valid) | l.140 | 0.7 × 46 × 30 / 300 = 3.22 N·m (not binding at 300 rad/s) | same | η_min PROV, I_batt,max SYN (BMS) |
| 3.3 | Closed-loop battery trim: s ← clamp(s − k (I_batt − I_max) dt) when over, recover otherwise; T_cl = T_static s | l.144–156 | – | `test_state_machine.c` contract tests | gains PROV |
| 3.4 | Derate T_der = T_static d (thermal, undervoltage); speed taper T_spd = T_static ramp(ω; ω_taper, ω_trip) | l.158–167 | ω = 440: (450 − 440)/(450 − 400) = 0.2 → 0.4 N·m, applied on the same update | same | thresholds SYN |
| 3.5 | Hard ceiling H = min(T_static, T_batt, T_cl, T_der, T_spd); accepted ≤ H on every update | l.170–199 | – | property P1 in `test_core_properties.c` | – |
| 3.6 | ECO envelope E = min(T_sup,max, P_sup,max η_min / ω); target = clamp(min(request, E), 0, H) | l.173–189 | 100 W at 250 rad/s: 100 × 0.7 / 250 = 0.28 N·m | `test_math_spec_examples` | supervisor values PROV |
| 3.7 | Slew: next = slew(min(prev, H), target, s_up, s_down, dt); above the envelope next ≤ max(E, prev − s_fast dt); final clamp [0, H] | l.192–199 | s_up 5 N·m/s → 0.005 N·m per 1 ms; worst-case ramp 2.0 / 100 = 20 ms ≤ supervision timeout 100 ms | same; property P7 | PROV |
| 3.8 | Freshness lag (telescoping): λ_k = λ_{k−1} + (t_rx,k − t_rx,k−1) − (t_src,k − t_src,k−1) − δ_drift, δ_drift = 0.02 × local advance toward 0; reject if λ > τ; fresher (λ < 0) becomes reference; λ < −τ is a candidate that re-anchors on a consistent second sample | `lag_from` l.82, `judge` l.94 | 20 ms late sample after an on-time one: λ = 0 + 40 − 20 − 0.8 = 19.2 ms ≤ τ = 100 ms → accepted; data ageing 10 ms per 20 ms frame is rejected once Σ > 100 ms | `test_freshness.c` (12 tests); properties P5, P8 | τ, drift PROV |
| 3.9 | Controller-input energy E = Σ V_bus I_batt dt over intervals with V and I valid and dt ≤ 20 ms; all other dt counted as gap | `mc_core.c` l.242–252 | 200 ms of missing I → gap 0.2 s, no energy added | `test_core.c::test_energy_gaps_are_counted_not_hidden` | boundary: bus shunt (controller input); logic rails excluded |

Dimensions: (3.2) V·A / (rad/s) = W·s = N·m (rad dimensionless). (3.6) same. (3.7) N·m/s · s = N·m. (3.8) ms throughout.

## 4. Energy optimisation (`models/optimization/dp.py`, `strategies.py`, `tools/run_optimization.py`)

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 4.1 | min Σ_k E_batt,k s.t. Σ_k Δt_k ≤ T_max − reserve, 0 ≤ v_k ≤ v_lim(s_k), v = 0 at stops, (F_drive − F_res)/m ≤ a_max; controls per segment: COAST, PROPEL(T), DRIVER_BRAKE (guidance only) | `dp.py` header, `_backward` l.261 | – | `tests/simulation/test_models.py` DP tests | T_max, track SYN (event rules unread) |
| 4.2 | Segment transition: v_{i+1}² = v_i² + 2 Δs (F_drive − F_res(v_mid) − F_brake)/m_eff; Δt = 2 Δs/(v_i + v_{i+1}); E = P_batt(v_mid, u) Δt | `dp.py` l.32–33 | v_i = 7 m/s, Δs = 10 m, T = 0.5 N·m: F_drive = 19.897 N, v_{i+1} = 7.2230 m/s, Δt = 1.4062 s, E = 246.8 J | `test_4_dp_transition` | – |
| 4.3 | Lagrangian relaxation J = E + λ t, λ by bisection until the time constraint binds | `dp.py` l.270 | – | DP tests | optimal only within the grid (Δs, Δv, control set) |
| 4.4 | Grid convergence: compare successive grids; reported relative change in DP energy between the two finest grids 0.13 % | `run_optimization.py`, `docs/generated/optimization_synthetic.md` | 20 m/0.40 m/s 44 227 J → 2.5 m/0.05 m/s 41 125 J | `verify_all.py` optimisation check | follows the DPM FAQ advice (fine reference grid; no general rule) |
| 4.5 | Pulse-and-glide benefit condition: with P_batt(T) non-convex in T at the cruise point (torque-independent losses while driving that vanish while coasting), time-averaging two operating points uses less energy than the constant point with the same mean tractive force | consequence of (2.6) and Jensen's inequality | – | DP results vs constant speed in `optimization_synthetic.md` | literature support read only as abstracts (`docs/METHOD_SELECTION.md`) |

Dimensions: (4.2) m²/s² = m²/s² + m · N / kg; J = W · s.

## 5. CSIA residuals (`host/csia_adapter/adapter.py` v1 frozen, `adapter_v2.py`)

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 5.1 | Normalised residual Λ = r² / σ², fail Λ > 9 (3σ), pass Λ ≤ 4 | `adapter.py` l.147, l.239 | r = 3σ → Λ = 9 | `test_5_csia_power_balance_v2` | thresholds PROV |
| 5.2 | E1 rotor ↔ driven wheel: r = mean(ω, window) r/G − v_drive, gated on freewheel engaged and v ≥ 0.8 m/s | `_rel` | – | `tests/fault_injection/test_csia_adapter.py` | gate thresholds PROV |
| 5.3 | E2 wheel L/R with yaw: r = (v_R − v_L) − ω_z b; E3 GNSS vs wheel on the centreline: r = v_w ± ω_z b/2 − v_GNSS | `_rel` | – | same | track width b SYN |
| 5.4 | E4 IMU vs wheel acceleration: r = mean(a_x) − (dv/dt_LS + g sin θ) | `_rel` | – | same | – |
| 5.5 | E6 v1: expected = p_mech + 0.08 abs(p_mech) + 3 W, σ² = (0.08 abs(p_mech) + 4)² + σ_pdc² (latest samples, not time-aligned) | `adapter.py` `_rel` | – | v1 evaluation (frozen) | superseded by 5.6 |
| 5.6 | E6 v2: iq, ω interpolated to the p_dc sample time; expected = K_t i_q ω + 1.5 R i_q² + c_sw abs(i_q) + P0; σ² = (0.15 · 1.5 R i_q²)² + (0.03 p_mech)² + s0² + σ_pdc²; R, c_sw, P0, s0 fitted by least squares on development data | `adapter_v2.py` `_e6` l.84, `calibrate_e6` | i_q = 15 A, ω = 250 rad/s, fitted R = 0.0997 Ω, c_sw = 0.125 W/A, P0 = 3.16 W, s0 = 2.20 W: p_mech 225.0 W, P_cu 33.65 W, expected 263.69 W, σ = 8.77 W | `test_5_csia_power_balance_v2`; v2 evaluation | fitted on synthetic data; must be refitted on bench data |
| 5.7 | Wheel speed from hall edges: v = n C / (ppr · window); quantisation q = C / (ppr · window), σ = q/√12 + 0.01 v | `ingest.py`, `csia_replay.py` | 5 edges in 100 ms with C = 1.50 m, ppr 32: 2.344 m/s; q = 0.469 m/s | `test_6_telematics_and_protocol` | ppr, C PROV |

Dimensions: (5.6) N·m/A · A · rad/s = W; Ω · A² = W; W/A · A = W.

## 6. Telematics and protocol

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 6.1 | UTC from PPS: least squares utc = a + b t_local over the last 8 edges; holdover after 2.5 s without an edge; error bound 1 µs + 50 ppm × age | `clocks.py` `UtcEstimator` l.92–110 | 4 edges with a 40 ppm fast clock, t_local = 12.5 s: utc = t0 + 2.5/1.00004 s (error < 1 µs); demo: 0.72 µs with PPS, 7.4 µs after 15 s holdover | `test_6_telematics_and_protocol`; host demo | drift bound PROV |
| 6.2 | CRC-8/SAE-J1850 (poly 0x1D, init 0xFF, xorout 0xFF) over the 16-bit data ID (major << 11 | id) then bytes 1–7 | `protocol/generated/semmc_protocol.*` | check value of "123456789" = 0x4B | `test_protocol_python.py`, `test_math_spec.py` | – |
| 6.3 | Worst-case frame time C = (55 + 10 n) τ_bit for 11-bit IDs, which equals 47 + 8n + floor((34 + 8n − 1)/4) for n = 8; WCRT R = J + w + C with w = B + Σ_hp ceil((w + J + τ)/T) C (Davis et al. 2007, method as recalled in `bus_load.py`) | `tools/bus_load.py` l.8–11 | n = 8 at 500 kbit/s: 135 bits × 2 µs = 270 µs; semmc utilisation 12.6 % | `test_math_spec.py`, `test_protocol_python.py::test_bus_load_budget` | other bus traffic UNKNOWN |
| 6.4 | Log storage: t_full = capacity / (bytes per second) | `node.py`, `stlg.py` | 8 MiB at 9.35 KiB/s: 14.6 min (demo) | host demo | rates PROV |

## 7. What is not modelled

* Regenerative braking (disabled in configuration; the DP has no regen control).
* Tyre slip beyond a start-slip ramp in the CSIA generator; lateral dynamics beyond the induced-drag term (1.1).
* Battery dynamics beyond open-circuit voltage minus R_int I (host plant); no SOC, no temperature.
* Motor saliency, saturation, trapezoidal back-EMF, dead-time voltage distortion in the current loop.
* Event rules (time limit, laps, stops): the DP uses synthetic values. The 2026 Chapter I was read in v0.5 (`RULES_COMPLIANCE.md`), but the team's event, track, time limit and lap count are not entered (input sheet).

## 8. Pit energy per distance (`host/pit/energy.py`, added in v0.5)

| # | Equation | Implementation | Example | Verified by | Status |
|---|---|---|---|---|---|
| 8.1 | v = C f / N with f = counts / T_w (fixed counting window) | `wheel_speed_mps`; the same form in `node.py` `_message` and `ingest.py` `import_log` | 13 counts, C = 1.5 m, N = 32, T_w = 0.1 s: 6.09375 m/s; resolution C / (N T_w) = 0.469 m/s | `test_pit_energy.py::test_formulas`, `test_mqtt_pipeline.py` | C SYN, N PROV |
| 8.2 | E_Wh = E_J / 3600, E_J the controller's `energy_J` (sum of V I dt over valid slow steps, 3.x) | `energy_wh`, `run_summary` | 7200 J = 2 Wh | `test_pit_energy.py` | – |
| 8.3 | d = Σ v_k T_w over the windows between the first and last energy sample; Wh/km = E_Wh / (d / 1000); km/kWh = 1000 / (Wh/km) | `run_summary`, `wh_per_km` | 2 Wh over 100 m = 20 Wh/km; README worked example 4.762 Wh/km = 210 km/kWh | `test_pit_energy.py` | – |
| 8.4 | Wheel cross-check: a channel whose distance is more than 2 % below the longest is flagged | `compare_channels` | host demonstration: `wheel_l` 635.0 m against 695.9 m (injected dropout) | `test_pit_energy.py` | tolerance PROV |
| 8.5 | E_nom = V_nom Q_rated | `nominal_pack_wh` | 48 V x 10 Ah = 480 Wh (team-reported; not measured usable energy) | `test_pit_energy.py` | team-reported |

Limits: the energy is the controller-input figure, not the joulemeter's (2026 Articles 56c, 56d: the joulemeter also counts the telemetry unit, sensors, display and wiring). A gap in the controller's integration makes the energy a lower bound; a wheel dropout reads as zero counts and makes the distance a lower bound, so Wh/km from a channel with a dropout is too high. The README worked example (section D) is recomputed by `test_pit_energy.py::test_readme_worked_example_matches_independent_arithmetic_and_the_model`.
