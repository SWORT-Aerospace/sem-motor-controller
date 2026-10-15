# Open parameters (unknowns that block hardware)

Every row is **null** in `config/vehicle.unconfigured.yaml` unless marked as a decision. The synthetic value (SIM) in `config/vehicle.synthetic.yaml` exists only so software can run. **It must never be copied into the hardware config.**

Legend for "how to obtain": **M** measure · **D** datasheet / manufacturer · **U** user/team decision · **R** rules (verify) · **C** calculate from other measured values.

## 1. Motor (all UNKNOWN: no motor identified in any inspected source)

| Parameter (config path) | SIM value | How to obtain | Notes / convention |
|---|---|---|---|
| `motor.type`, `motor.model` | pmsm_sinusoidal, fictional | U + D | Brushed or six-step-only motor → ADR-0003 path B/C |
| `motor.pole_pairs` | 4 | D, M (count hall cycles per mechanical revolution) | |
| `motor.phase_resistance_ohm` + `resistance_ref_temp_degC` | 0.10 Ω @ 25 °C | M: 4-wire **line-to-line** DC resistance ÷ 2 (star), with winding temperature | line-to-neutral convention |
| `motor.d_inductance_H`, `q_inductance_H` | 150 µH each | M: LCR line-to-line ÷ 2 at the rotor angle for d and q; or HF voltage injection | saliency decides MTPA value (H4) |
| `motor.flux_linkage_Wb` | 0.010 | M: spin the motor, measure **line-line peak** back-EMF e_LL at ω_e; λ = e_LL / (√3 · ω_e) | amplitude-invariant; Kt = 1.5·p·λ (N·m/A peak) |
| rated / max mechanical speed | 300 / 450 rad/s | D | max speed with back-EMF < min battery V (rule `BACKEMF_EXCEEDS_MIN_BUS`) |
| continuous RMS / peak phase current, peak duration | 15 A / 40 A / 10 s | D + M (thermal test) | |
| `motor.max_winding_temp_degC`, winding sensor type | 120 °C, — | D | NTC/PTC/KTY or none |
| `motor.rotor_sensor`, hall supply, output type, `hall_code_to_sector`, `hall_angle_offset_rad` | hall, 5 V, 1-3-2-6-4-5, 0 | M: rotate slowly, record codes vs back-EMF zero crossings | open-drain vs push-pull sets the input protection |
| `motor.inertia_kg_m2` | 2e-4 | D or spin-down test | sim only |

## 2. Battery and BMS (UNKNOWN)

| Parameter | SIM | How | Notes |
|---|---|---|---|
| chemistry, series cells | NMC, 12S | U + D | lithium assumed by rules (R?) |
| min / nominal / max-charged V | 36 / 43.2 / 50.4 V | D + M | **≤ 60 V by design at any point (R? 57a)** |
| BMS continuous / peak discharge, duration | 30 A / 60 A / 10 s | D | the controller limit must be ≤ the BMS limit |
| BMS max charge current | 5 A | D | regen deferred |
| capacity (Wh) | — | D | < 1000 Wh (R? 57d iv) |
| battery short-circuit current | — | D / M | fuse breaking capacity |

## 3. Vehicle (UNKNOWN for the target car)

| Parameter | SIM | How |
|---|---|---|
| category (Prototype vs Urban Concept) | prototype | U — the telemetry proposal reportedly says Prototype; Cornell targets UC |
| mass with driver | 100 kg | M (scales) |
| gear ratio, wheel circumference (loaded) | 10, 1.50 m | M |
| freewheel/clutch present | yes | I |
| drivetrain efficiency | 0.95 | M (or absorb into a measured power map) |
| Crr, CdA | 0.0025, 0.035 m² | M: coast-down (`models/vehicle/longitudinal.fit_coastdown` reports whether they are separately identifiable) |
| track width (CSIA E2) | 0.5 m | M |

## 4. Inverter and sensing calibration (UNFROZEN until hardware exists)

bus voltage rating · transient margin (from measured overshoot) · shunt Ω · CSA gain · ADC Vref/bits · **per-board current offsets** · Vbus divider ratio · hardware overcurrent trip · PWM frequency · dead time · FET derate/trip temperatures · duty limits (from the sampling window) · current-loop gains (from measured L, R).

v0.2 additions:
* `inverter.current_sample_settle_s`: measured at stage 4 (SIM 1.5 µs).
* `inverter.voltage_limit_fraction` (SIM 0.95): bounded by validator rule 39 (`hardware/timing/timing_budget.md`).
* FDCAN clock: the 40 MHz crystal is fixed by the CHUDS bit timing, not by calibration.

## 5. Limits and timing (decisions that need measured inputs)

max motor/manual torque · max phase current · battery current limit (≤ BMS) · η_min for the feed-forward battery limit · overspeed trip and taper · UV derate/trip, OV trip · motor temperature derate/trip · torque slew up/down/fast · unknown-temperature derate factor · throttle release/engage thresholds · software overcurrent · coast mode · **supervisory rate and timeout (hazard and latency analysis)** · limits timeout.

## 6. Competition and logistics

| Item | Status |
|---|---|
| Competition year/event/region | **U** (`vehicle.competition_event` null) |
| Edition of rules in force | **R** — 2027 Chapter I exists; contents unread |
| Attempt format (laps, time limit) | **R** — only US 2025 seen ("4 laps in 35 min", ~25 km/h) |
| Budget | $500–1,000, provisional (user). Priced draft: `docs/BUDGET.md` (not shown feasible yet) |
| Delivery deadline | **U** |
| Existing controller and its baseline performance | **U** — none identified |
| Cooling, enclosure, harness, connector constraints | **U** |
| Who performs and signs bench measurements (`calibration.measured_by`) | **U** |
| Hazard-analysis owner and reference | **U** |
