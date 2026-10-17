# Identifiability of bias, timing error and load (gate 1)

Gate 1 of [`PROTOCOL.md`](PROTOCOL.md): can the evidence that exists, or that a bounded request could obtain, separate a battery-current measurement bias (HB), a relative timing error of the electrical records (HT) and an increased opposing force (HL) from each other and from normal operation (H0)? Where it cannot, which measurement would be required?

Everything below is analysis of a synthetic model. The plant is the repository's SYNTHETIC vehicle and motor (`models/vehicle/`), and the noise levels and nuisance bounds are assumptions listed in `research/bea/identifiability.py` (`Study`, `NUISANCE`, `TIMING`). The numbers come from `python3 research/run_identifiability.py`, written to [`generated/identifiability.md`](generated/identifiability.md). Tags: **[F]** fact from the repository, **[A]** assumption, **[D]** derived here, **[M]** computed by the study code.

## 1. Model

**Relationships.** Each is a residual: a measured quantity minus its nominal model, sampled on an analysis window.

| | Relationship | Records it needs | Where it applies |
|---|---|---|---|
| R1 | bus-meter power V·I against the loss model driven by iq and rotor speed | `ctrl_currents.ibatt_A`, `ctrl_motion` (iq, speed, vbus) at 100 Hz, or `ctrl_energy.p_batt_W` at 10 Hz, or the 2 Hz summary | drive |
| R2 | tractive force from iq against rolling and aerodynamic resistance plus inertia from rotor speed | `ctrl_motion` | drive |
| R3 | bus-meter current with the gates off, where the true inverter input is 0 | `ctrl_currents.ibatt_A`, or the summary's mean power divided by voltage | coast |
| R4 | coast deceleration from the wheel counts against resistance | wheel count windows (0.1 s) from the local log, or the summary's wheel speed | coast |
| R5 | force balance with the IMU's specific force in place of the measured acceleration | IMU records (local log only) plus R2's inputs | drive and coast |

R1 to R4 use records the telemetry chain defines today [F]. R5 needs the IMU of the telemetry proposal, which is not built [F]. The IMU is logged locally at 100 Hz in the host model but is not in the live summary [F] (`host/telematics/node.py`).

**Signatures.** The residual's response to a unit of each parameter [D]. Notation: V bus voltage, I bus current, P = V·I inverter-input power, iq torque current, ω rotor speed, Kt torque constant, v speed, a acceleration, f IMU specific force (a + g·sin θ), m mass, m_eff effective mass, ρ air density, CdA drag area, G/r gear ratio over wheel radius, η drivetrain efficiency.

| Parameter | R1 [W] | R2 [N] | R3 [A] | R4 [N] | R5 [N] |
|---|---|---|---|---|---|
| **HB**: bias b [A] | V | 0 (torque from iq) | 1 | 0 | 0 |
| **HT**: offset δ [s] | P(t−δ) − P(t) ≈ −δ·dP/dt | 0 | I(t−δ) | 0 | 0 |
| **HL**: extra force ΔF [N] | 0 | 1 | 0 | 1 | 1 |
| grade θ [rad] | 0 | m·g | 0 | m·g | (m − m_eff)·g |
| headwind w [m/s] | 0 | ρ·CdA·v | 0 | ρ·CdA·v | ρ·CdA·v |
| loss offset P0 [W] | 1 | | | | |
| winding resistance ΔRs [Ω] | 1.5·iq² | | | | |
| iron-loss coefficient (relative) | k_Fe·ω^1.5 | | | | |
| switching loss per ampere | \|iq\| | | | | |
| bus-meter gain (relative) | P_model (the modelled V·I) | | | | |
| motor friction ΔT_f [N m] | ω | −G·η/r | | | −G·η/r (drive) |
| torque constant (relative) | Kt·iq·ω | F_trac | | | F_trac |
| rolling resistance ΔCrr | | m·g | | m·g | m·g |
| drag area ΔCdA [m²] | | ½·ρ·v² | | ½·ρ·v² | ½·ρ·v² |
| effective mass (relative) | | m_eff·a | | m_eff·a | m_eff·f |
| bus-meter zero offset [A] | | | 1 | | |
| IMU bias [m/s²] | | | | | m_eff |

HL has no R1 signature because R1 uses the measured iq: a larger load draws more torque and more power, and the loss model predicts that power correctly. This is why the frozen CSIA relationship E6 stays consistent under HL ([`PROTOCOL.md`](PROTOCOL.md) section 3).

Motor friction and the torque constant appear in both R1 and R2. They are one parameter each, shared between the two relationships, not two independent ones. A study that gave each relationship its own copy would overstate what the data can separate.

**Hypotheses** [A]. Each one changes the bounds of H0:

- **H0**: every nuisance term within its bound; b = 0, ΔF = 0, |δ| within the timing bound.
- **HB**: b free.
- **HT**: |δ| up to 0.5 s.
- **HL**: ΔF ≥ 0, free.
- **Sub-causes of HL**: grade beyond its H0 bound (HL_grade) and headwind beyond its bound (HL_wind). They are separated from HL only where section 3 shows the evidence supports it.

Two bound levels are used: "known" (after a calibration run) and "uncertain" (nominal values only).

**Separation** [D]. Let r_h be the noise-free residual with hypothesis h true at a given size and every nuisance at its nominal value. Let Σ = L·Lᵀ be the noise covariance.

```
d(h -> g) = min over (x, δ) allowed by g of || L^-1 (r_h - C x - s(δ)) ||
```

Here C holds the signature columns and s(δ) is the exact shifted power. d is the expected excess, in noise standard deviations, of g's fit statistic over h's (h's own is 0). The study treats d ≥ 4 as separable: a one-sided test at about 1 % false rejection then keeps about 95 % power. d = 0 means g reproduces h's residual exactly, so no amount of data of that kind separates them.

The minimum is computed exactly, by bounded least squares (`bvls`, checked against exhaustive enumeration in `tests/research/test_bvls.py`) plus a one-dimensional search over δ. Noise: white per sample for R1, R3 and R5; for R2 and R4, the banded covariance of differenced speeds or wheel distances, so that adjacent intervals share their end samples.

## 2. Exact ambiguity conditions

Each condition holds for the model of section 1. The study code checks it numerically ([M], `tests/research/test_identifiability.py`); the numerical rank is supporting evidence, not the proof.

**General condition** [D]. For linear parameters without bounds, d(h → g) = 0 exactly when r_h lies in the span of the columns g may use. A higher sampling rate samples the same functions at more points. A signature that is a linear combination of g's signatures as functions of time therefore stays one at every rate, and d = 0 at every rate. With bounds, d = 0 when some admissible parameter vector reproduces r_h: then only the size of the fault, measured against the nuisance bounds, decides.

**P1. A timing error is unobservable at steady power** [D]. If dP/dt = 0 over the window, P(t−δ) = P(t) and I(t−δ) = I(t), so s(δ) = 0 for every δ. HT then has no signature at all: d(HT → g) = 0 for every g, size and rate. It is also harmless: a time shift of a constant changes no energy total. HT can only be diagnosed from records that contain a power transient.

**P2. A bias at drive power competes with the loss model** [D]. In R1 the bias enters as b·V. On a window at one operating point, V and every loss column are constant, so b·V lies in the span of the loss offset P0. HB is then separable from H0 only by size:

```
|b|·V  >  P0_max + (the largest constant the other loss terms can produce at that operating point)
```

Most of those terms grow with power: ΔKt·Kt·iq·ω is a fixed fraction of the electromagnetic power. So the smallest bias R1 can detect grows with power: at the 40 W cruise it is a small fraction of an ampere, and at the 300 to 750 W ramp a 0.2 A bias disappears entirely into a 2 % torque-constant uncertainty.

**P3. Coasting with the gates off measures the bias directly** [D]. With the gates off, the true inverter-input current is 0, and the bus meter's only other term is its zero offset. On R3 alone, with n samples of noise σ_I and offset bound I_off:

```
d(HB -> H0) = (|b| - I_off) · sqrt(n) / σ_I        for |b| > I_off, else 0
```

This holds exactly (checked to 1e-6 by `test_p3_coast_current_closed_form`). R3 has no HL signature and, away from the mode changes, no HT signature (P1). A coast segment therefore separates HB from HT and HL whenever |b| > I_off + 4·σ_I/√n, independently of the loss model.

**P4. A timing error against a bias in drive** [D]. With R1 only, HT is separable from HB when dP/dt on the drive samples does not lie in the span of {V, 1, iq², ω^1.5, |iq|, ω, iq·ω}.

- If the power is linear in time, dP/dt is constant, so it lies in span{1}: HT is then indistinguishable from a loss offset and from HB, whatever the rate.
- At a torque step, dP/dt is a pulse as wide as the torque rise time. None of the slowly varying columns can produce a pulse, so HT is separable at any rate that samples the pulse.
- The 2 Hz summary does not sample it. The summary carries a 0.5 s mean power next to an instantaneous iq [F], so R1 on the summary is usable only on steady intervals, where P1 applies.

**P5. Rate.** Where the signature is not in the span, d grows with the square root of the number of independent samples. That growth assumes white noise per sample, which favours the higher rate. Where the signature is in the span (P1, P6, P7), the rate does not matter: d stays 0.

**P6. Load against grade needs the IMU** [D]. In R2 and R4, ΔF has the signature 1, grade has m·g, and rolling resistance has m·g: all three are constant, so all three are collinear. With R1 to R4, d(HL → HL_grade) = d(HL_grade → HL) = 0 exactly, at every rate, condition and size (`test_p6_grade_and_drag_collinear_without_imu`). Records that do not depend on grade the way the force balances do are needed. The IMU's specific force f = a + g·sin θ provides them: in R5 the extra force enters with 1 and the grade only with (m − m_eff)·g, about 1.4 % of m·g. The separable size is then set by the IMU bias after mounting calibration: about m_eff·b_imu in force and b_imu/g in grade.

**P7. Load against headwind is not separable with any sensor in the design** [D]. A headwind adds about ρ·CdA·v·w. At constant speed this is constant in every relationship, including R5: the IMU feels the deceleration from wind and from drag alike. So it is collinear with ΔF and ΔCrr. Over the 6 to 10 m/s range the vehicle uses, v also lies close to span{1, v²}, the rolling-resistance and drag-area columns. No air-speed measurement exists in the design [F], so headwind is reported as part of HL, never as a separate cause.

**P8. Shared sources** [D]. If the torque were computed from the bus current instead of iq, R1 would become an identity and would carry no evidence, and R2 would gain an HB column η·V/v. At constant speed that column is constant: collinear with ΔF. HB and HL would then be indistinguishable in drive (d = 0) and separable only by a coast segment (P3) or a speed change. The design measures the phase currents with shunts separate from the bus shunt [F] (`tools/gen_kicad_schematic.py`), so iq is an independent source. A diagnosis that used the bus-current torque and also counted R1 as evidence would count the same bias twice.

## 3. Cases A to E

Numbers from [`generated/identifiability.md`](generated/identifiability.md), at the known nuisance level unless stated. Nominal sizes: b = 0.2 A, δ = 0.1 s, ΔF = 3 N, grade 0.01 rad, headwind 3 m/s.

**A. Distinguishable** [M]. On a pulse-and-coast window, with the full-rate controller frames and wheel counts from the local log, every pair among HB, HT and HL separates by a wide margin. The minimum over alternatives is:

| True | d against H0 | against HB | against HT | against HL |
|---|---|---|---|---|
| HB, 0.2 A | 402 | | 402 | 402 |
| HT, 0.1 s | 2382 | 2380 | | 2382 |
| HL, 3 N | 76 | 76 | 76 | |

The three faults leave their marks in different places: HB in R3 during the coast, HT in R1 at the two power edges, and HL in R2 and R4.

**B. Not distinguishable with the available evidence** [M].

- **HT at steady power.** At the 40 W cruise, d(HT → H0) is 0 to round-off at 2, 10 and 100 Hz, even for δ = 0.4 s (P1).
- **HB at high drive power.** On the 300 to 750 W ramp with full-rate frames, d(HB → H0) = 0.02 at 0.2 A (P2). It takes 0.4 A to separate; with uncertain nuisance, more than 0.8 A.
- **Drag against headwind.** In cruise with frames and IMU, d is 0 to round-off in both directions (P7).

**C. Additional synchronised records resolve B** [M]. These are records from the same clock that cover a segment where the signatures differ:

| Window | d(HB → H0), 0.2 A |
|---|---|
| ramp alone (case B) | 0.02 |
| ramp plus the 5 s of cruise before it, from the buffered pre-event window ("onset") | 155 |
| a window with a coast segment ("pulse_coast") | 402 |

The same holds for an extra force during a coast:

| Records | d(HL → H0), 3 N |
|---|---|
| 2 Hz summary wheel speeds | 2.25 |
| full-rate wheel counts | 186 |

**D. A higher rate cannot resolve** [M]. Drag (12 N) against grade (0.04 rad) with R1 to R4, at 2 and 10 Hz (R4 cannot go faster: the wheel counts come in 0.1 s windows), and at 100 Hz without the wheel counts. Under cruise, pulse-and-coast and coast, d is 0 to round-off in both directions at every rate (P6). HT at steady power is the second example (case B).

**E. An independent measurement is required** [M]. The IMU's specific force separates drag from grade (P6):

| IMU bias after mounting calibration | Smallest separable drag | Smallest separable grade |
|---|---|---|
| 0.005 m/s² ("known") | 3 N | 0.0025 rad or less (0.25 % slope) |
| 0.05 m/s² ("uncertain") | 12 N | 0.02 rad |

These sizes are the same in cruise and in coast. The IMU is in the telemetry proposal but not built [F].

The second example is the source of the torque estimate (P8). In cruise, d(HB → HL) is 243 with torque from the phase currents, and 0 to round-off with torque from the bus current. On a window with a coast it is 402 either way, because R3 does not depend on the torque source.

## 4. Timing phenomena

The six phenomena are kept apart in the record model (`research/bea/records.py`) and enter the diagnosis differently [D]:

| Phenomenon | In this architecture | How it enters | Signature |
|---|---|---|---|
| Transport delay | Controller frames carry no source time; the telemetry unit stamps them on receipt, in one clock [F] | the acquisition interval [t_rx − delay_hi, t_rx − delay_lo]; within the known timing bound (5 ms) [A] | a shift bounded by the interval |
| Wrong source stamp | Not applicable to controller frames, which carry no source stamp. Applies to `sup_torque_req.src_time_ms`, and to any record merged from another device | HT when beyond the stated bound | −δ·dP/dt |
| Physical response delay | A bus meter that averages, or a filter in the controller's power calculation [A]. A property of the channel, not of the stamp | HT (one class) | lag or boxcar: equal to a delay to first order, different near the time constant |
| Different sampling rates | 10 ms and 100 ms frames, 0.1 s wheel windows, 2 Hz summary [F] | alignment error bounded by `alignment_bound` (max \|f''\|·T²/8 for linear interpolation) | a bounded nuisance, not a hypothesis |
| Clock drift | One stamping clock for every controller frame and for the wheel and IMU records, so no relative drift between them [F]. Between devices (vehicle against pit, or an external logger) the drift is bounded by the UTC mapping's error (`utc_err_s`) [F] | bound on the clock error: offset + drift × time since synchronisation | grows linearly within a window: about 40 ppm × 24 s = 1 ms [A], below the 5 ms bound |
| Packet loss and stale samples | Every frame has a per-message 8-bit sequence counter [F]; `ctrl_validity` carries a stale bit per signal [F] | `sequence_gaps` and `duplicates` find losses and re-deliveries exactly, as long as fewer than 128 frames are lost in a row; stale samples are taken from the validity bit | not inferred from timing |

A stale sample cannot be found reliably by spotting an exactly repeated value [D]. At 0.01 A quantisation [F] and the study's 0.02 A noise [A], consecutive bus-current readings repeat by chance. The controller's stale flag is the evidence to use.

**Can the kinds of timing error be told apart?** [M] A pure delay, a first-order response and an averaging window, compared on R1 with the loss-model nuisance:

| Edge or signal | Records | Delay against lag | Delay against averaging window | Lag against averaging window |
|---|---|---|---|---|
| torque step (onset, pulse edges) | 100 Hz | separable (d 119 to 200) | separable (70 to 122) | separable (65 to 105) |
| torque step | 10 Hz | at the onset in one direction only (0.7 and 5.0); separable at the pulse (5.1 and 9.1) | **not separable** at the onset (0 and 0.02); at the pulse in one direction only (1.4 and 6.0) | **not separable** at the onset (0.8 and 1.7); separable at the pulse (8.5) |
| 0.25 Hz power modulation (sine) | 100 Hz | not separable (1.1) | not separable (0.45) | not separable (0.53) |

Each cell gives the range of d over both directions of the pair. True values: 0.04 s delay, 0.04 s first-order time constant, 0.08 s averaging window. Full table in the generated file.

For slow signals the three are equivalent to a delay, to first order (δ = τ for the lag, δ = T/2 for the window), and differ only in the second-order term. They can be told apart only from records that contain content near the time constant and that are sampled fast enough to see it. The diagnosis therefore reports HT as one class. It names the kind only when full-rate records of a sharp edge separate them, and the generated table says when that happens.

## 5. Identifiability matrix

Each row is backed by the generated full matrix ([`generated/identifiability.md`](generated/identifiability.md), section "Full matrix"). Sizes are the smallest separable size found on the ladder of 0.25 to 4 times nominal.

| Hypothesis pair | Operating condition | Required evidence | Available action | Expected outcome | Assumptions |
|---|---|---|---|---|---|
| HB against H0, HT and HL | coast with the gates off | R3: bus current while the inverter draws nothing; the live summary's mean power suffices | if the buffer holds no coast: wait for an informative condition (the next coast) | separable at 0.05 A or less, at both nuisance levels | zero offset within 5 mA (known) or 30 mA (uncertain); true inverter input 0 with the gates off |
| HB against H0 | steady low power (40 W cruise) | R1 | none beyond the summary | 0.1 A on the summary and with full-rate frames; 0.4 A with uncertain loss model | loss model within the stated bounds (P2) |
| HB against H0 | acceleration at 300 to 750 W | R1 alone separates only 0.4 A or more (more than 0.8 A with uncertain nuisance); the summary has no usable sample | retrieve the buffered pre-event window that includes steady driving (0.1 A), or wait for a coast | unresolved on the acceleration window alone; resolved with the buffer or the coast | as above |
| HT against any | steady power (cruise, coast) | none: HT leaves no signature (P1) | wait for a power transient | not observable at any rate; harmless to energy totals | none |
| HT against H0 and HB | torque step (onset, pulse edges) | R1 at 100 Hz across the edge | retrieve the buffered window around the edge, or capture a bounded future window at the next edge | separable at 0.025 s or less with the 5 ms timing bound | records stamped by one clock; the bound holds (section 4) |
| HT against H0 | torque step, timing known only to 100 ms (records from different devices, or the summary) | as above, plus a smaller timing bound | retrieve clock-synchronisation metadata (stamp clock, UTC mapping and its error), which reduces the bound to 5 ms where it applies | separable from 0.2 s with the 100 ms bound; 0.025 s or less once the bound is 5 ms | metadata bounds the relative timing |
| HT against any | any condition, live summary only | none: R1 on the summary is usable only on steady intervals | export the controller frames at full rate (less decimation) | not observable from the summary | the summary pairs a 0.5 s mean with an instantaneous iq [F] |
| HL against H0, HB and HT | cruise | R2; the summary suffices | none | 3 N known, 12 N uncertain | rolling resistance, drag area, torque constant and mass within bounds |
| HL against H0 | coast | R4 from full-rate wheel counts | export the wheel-count records | 3 N with counts; 6 N on the summary (d = 2.25 at 3 N) | provisional 32 pulses per revolution and 1.5 m circumference |
| HL against H0 | acceleration | R2 together with R1 (R1 constrains the torque constant shared with R2) | retrieve the buffered window at full rate | 3 N with frames; 6 N on the summary | torque constant shared between R1 and R2 |
| HL drag against HL grade | any | a measurement in which grade and drag enter differently: the IMU's specific force (R5) | export the IMU records (needs the IMU, not built) | without the IMU: collinear at every rate. With it: 3 N or 0.0025 rad (calibrated mounting); 12 N or 0.02 rad (uncalibrated) | IMU mounting calibrated; IMU on the telemetry unit's clock |
| HL drag against HL headwind | any | an air-speed measurement; none in the design | none: report HL as one class | collinear at constant speed, IMU included | none |
| HB against HL, torque computed from bus current | steady drive | a coast segment (R3), or torque from the phase currents | wait for a coast | collinear in steady drive; separable with a coast | the dependency of P8 |
| Delay against lag against averaging window (kinds of HT) | sharp torque edge | R1 at 100 Hz | retrieve the buffered window at full rate | separable at 100 Hz; at 10 Hz not at the onset, and delay against averaging window in one direction only at the pulse; none on smooth signals | as section 4 |

## 6. Gate decision

**Decision.** Gate 1 passes for the class-level hypotheses H0, HB, HT and HL, under the conditions in the matrix. Each pair can be separated with records the chain keeps or a bounded action can obtain, but only on the right operating condition:

- **HB:** a coast, or steady low power.
- **HT:** a full-rate power transient.
- **HL:** steady driving, or full-rate coast records.

Each hypothesis also has conditions under which it cannot be separated. The diagnosis must report "unresolved" on those conditions rather than guess.

**What follows for the next steps.**

1. **What the scheduler targets.** It is built only around pairs that some available action can separate. The actions are:
   - retrieve a buffered window at full rate;
   - capture a bounded future window;
   - wait for a coast or a power transient;
   - retrieve clock-synchronisation metadata;
   - export the IMU records, when an IMU exists.
2. **No scheduler for drag against headwind.** No action separates them. HL is reported as one class, with "headwind not distinguishable" stated.
3. **Drag against grade needs the IMU.** This is an exact remaining physical requirement: the IMU of the telemetry proposal, fitted with a calibrated mounting. Without its records, the diagnosis reports "extra opposing force; grade or drag not distinguishable".
4. **Timing kind.** It is named only from full-rate records of a sharp edge. Otherwise the diagnosis reports HT with the kind unresolved.
5. **The live summary alone cannot diagnose HT.** Exporting full-rate frames is the action for it.

**Limits of this gate, and how it can fail later.**

- **What the analysis assumes:**
  - linear signatures, apart from the exact time shift;
  - Gaussian noise of the stated levels;
  - nuisance terms at their nominal values in the truth;
  - synthetic plant parameters.

  Nothing is measured.
- **How the harness tests it.** The causal harness of step 4 adds quantisation, clock and transport effects, nuisance terms drawn inside their bounds, and the fault onsets.
- **How the prediction is falsified.** If the harness's decisions contradict the predicted separability, the analysis is wrong for that pair, and the study corrects it before any scheduler result is reported. Two examples: an HB on a window with a coast that is not attributed, or an HT claimed from the summary.
