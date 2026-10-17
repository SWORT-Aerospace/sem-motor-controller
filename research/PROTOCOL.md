# Research protocol: budgeted evidence acquisition for timing-aware cross-system diagnosis

This is a research extension of the vehicle telemetry project. It is diagnostic only: nothing in it changes propulsion commands, brake behaviour, protection thresholds or control-loop sampling, and nothing in it runs on the motor controller. Everything below is host simulation unless stated otherwise; no measurement in this study comes from hardware.

Status of each statement is marked: **[F]** observed fact in the repository or a document read, **[A]** assumption, **[P]** proposal, **[M]** measured result of a run recorded in this study.

## 1. Research question

Can a diagnostic layer, given the records the telemetry chain already produces plus a small set of bounded record-acquisition actions, (1) recognise competing explanations for an inconsistency between measurements, (2) state which explanations the available evidence can and cannot separate, (3) choose additional records within byte and latency budgets, (4) reach the correct diagnosis more often than strong baselines at matched cost and coverage, and (5) abstain when no unique cause is supported?

The CSIA component's own contribution is measured separately from the scheduler's (section 7). A positive result is not assumed: each step has a falsifiable acceptance criterion, and failures are reported.

## 2. Hypotheses (initial scope)

| Label | Meaning | Parameter |
|---|---|---|
| H0 | normal operation: noise, quantisation, bounded nuisance variation (rolling resistance, drag area, motor losses, auxiliary load, small grade and wind) | none beyond the nuisance bounds |
| HB | battery-current measurement bias at the controller's bus meter | bias b [A] |
| HT | relative timing error: the electrical stream's timestamps are offset from the motor-side stream beyond the modelled transport and response delays | offset δ [s] |
| HL | increased opposing longitudinal force beyond the nuisance bounds (rubbing, dragging brake, grade or wind beyond bounds) | extra force ΔF [N] |
| HU | unmodelled: no hypothesis above, alone, fits the evidence | none |

HL is one class. Its sub-causes (mechanical drag, grade, wind) are split only where an independent measurement supports it ([`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) sections 2 and 5); otherwise they are reported together.

## 3. Baseline at the start of the study

**Repository [F].**
- Starting commit `e8b0e03` on `eng/v0.5-telemetry-integration`: `406de15` with `main` (`3a80039`, a team edit to an archived questionnaire) merged in.
- Research branch: `research/evidence-acquisition`.
- `406de15` passed GitHub Actions: push run 38990549457 and pull-request run 38990554614. `e8b0e03` passed too: runs 38993066253 and 38993069780 (`host` and `erc`).
- Local results on `75f1b24` and later:
  - pytest 269 passed;
  - ctest 8/8 passed;
  - `tools/verify_all.py --full` in a fresh clone: 37 PASS, 0 FAIL, 1 NOT AVAILABLE (the KiCad ERC needs KiCad 8 and runs in CI).

**Tools [F].**
- Python 3.13.16 with the pinned `requirements.txt` (numpy 2.5.3; no SciPy).
- gcc 13.3.0, CMake 3.28.3, Ninja 1.11.1, arm-none-eabi-gcc 13.2.1.
- Mosquitto 2.0.18, KiCad 7.0.11.
- CSIA core at `848f556` (`third_party/csia-trust-layer.lock`, version 0.8.0). Its licence is evaluation and internal assessment only, with no production or safety-critical use without a commercial licence. A vehicle deployment of CSIA therefore needs a licence decision, whatever this study finds.

**CSIA implementation and boundary [F].**
- `host/csia_adapter/adapter.py` (v1) and `adapter_v2.py` (v2) wrap TrustCore with eight relationships:
  - E1: rotor speed against driven-wheel speed;
  - E2: left against right wheel with yaw rate;
  - E3a and E3b: GNSS against each wheel;
  - E4: IMU acceleration against left-wheel acceleration;
  - E6: the DC meter's power against a phase-current loss model;
  - E7: GNSS against the driven wheel;
  - P: phase-current consistency.
- The adapter reports a suspect node, AMBIGUOUS, or consistent. Its outputs are about which **sensor node** is wrong. It has no hypothesis for a timing error or a mechanical load, and no relationship between torque and vehicle motion.
- E6 compares the DC meter with the phase current. A larger opposing load raises both, so E6 stays consistent under HL.
- The v1 and v2 adapters, the evaluation code and the protocols are frozen. Their hashes are checked by `tests/fault_injection/test_csia_v2_freeze.py`; none of these files is changed by this study.

**Existing CSIA evidence [F].** Held-out v2 evaluation, synthetic, 94 scenarios (`docs/csia/EVALUATION_RESULTS_v2.md`):
- CSIA2 attributed 48 of 70 faults with 4 wrong causes.
- R3v (calibrated residuals with majority vote) attributed 34 of 70 with 0 wrong causes.
- The pre-registered superiority rule allowed at most 1 more wrong cause than R3v, so it failed. R3v is the selected pit-side monitor.
- Fault kinds in that set: rotor, wheel, GNSS, IMU, phase-current and DC-meter faults. None of them is a timing error or a mechanical-load change, and the v1/v2 data are used here only as development evidence.

**Telemetry chain [F]** (`docs/ICD.md`, `host/telematics/`).
- **Controller frames.** CAN protocol 1.1, 8-byte frames. `ctrl_motion` and `ctrl_currents` every 10 ms; `ctrl_energy`, `ctrl_energy_quality` and `ctrl_thermal` every 100 ms.
- **Timestamps.** The controller frames carry **no source timestamp**. The telemetry unit stamps each frame on receipt, in microseconds of its own clock. Only `sup_torque_req` carries a source time (`src_time_ms`).
- **Other sources.** GNSS PPS edges give UTC, with a quality flag and a holdover bound of 50 ppm × age. Wheel pulses are counted in 100 ms windows. GNSS fixes are logged at 10 Hz and the IMU at 100 Hz (host models).
- **Log and buffers.**
  - Local log STLG v1 in 4 KiB blocks: a log queue of 512 records, a writer at 4000 records/s (provisional), 8 MB of flash in the proposal.
  - Uplink: a 2 Hz JSON summary (`sem.telemetry.v2`) with a 30-message backlog. QoS 1 with at most 10 unacknowledged messages.
  - There is no request path from the pit to the vehicle.

**Measurements in code versus on hardware [F].**
- **Hardware:** none exists. No measurement in the repository comes from a sensor.
- **Host simulation:** every quantity above exists only there, in the C plant (`firmware/platform/host/sim_plant.c`) and the Python sensor models.
- **Draft schematic:** the controller's bus meter (INA228 class), phase shunts and Hall inputs.
- **Telemetry:** the wheel, GNSS, IMU and temperature sensors are candidates.
- **Unknown:** whether the BMS has a data interface.

## 4. Electrical measurement boundary

- **What the current measurement covers [F].** In the draft schematic the bus shunt sits between `VBAT_PROT` and `VBAT_SH` (`tools/gen_kicad_schematic.py`, sheet 01). The precharge path, DC link, bridge and motor are downstream of it. The controller's logic buck (LM5164 to +5 V, then +3.3 V) is fed from `VBAT_PROT`, **upstream** of the shunt. So the controller's current measures the inverter input, not the controller's own logic supply and not the whole vehicle.
- **Loads outside the controller's measurement [F].**
  - the controller logic (MCU, gate-driver logic, CAN transceiver, sensors on the board);
  - the telemetry unit, its sensors, the modem and a vehicle-powered display, which sit on a separate branch downstream of the organisers' joulemeter;
  - the BMS, inside the battery package.
- **Host-plant inconsistency [F].** `sim_plant.c` adds a 3 W auxiliary term inside the measured battery current, which the schematic does not. The truth generator of this study follows the schematic: auxiliary loads stay outside the inverter-input current, except gate-drive losses.
- **Stored energy over an analysis window [A].** Three stores matter:
  - the DC-link capacitors: ½ C V². C is unresolved; with an assumed 1 mF at 48 V that is 1.15 J, and it changes only with the link voltage, so over a few seconds it is negligible against tens of watts unless the voltage swings;
  - vehicle and rotor kinetic energy ½ m_eff v²: dominant in transients, included through measured acceleration;
  - winding and stator thermal energy: affects losses through temperature and is not an electrical store.
- **Battery [F].** Team-reported: 48 V nominal, 10 Ah, about 480 Wh nominal. This is not datasheet-verified. The maximum voltage, current limits, chemistry and usable energy are not inferred. No result here depends on them beyond using 48 V as a nominal operating voltage in synthetic runs, labelled as such.

## 5. Plan and decision gates

1. **Prior art** ([`PRIOR_ART.md`](PRIOR_ART.md)). Each source carries its access level. No novelty claim is made beyond what the readable sources allow.
2. **Identifiability (gate 1)** ([`IDENTIFIABILITY.md`](IDENTIFIABILITY.md)). Can the available evidence, or evidence obtainable with the actions, separate HB, HT and HL from each other and from H0? Exact ambiguity conditions are given for a simplified linear model, with numerical rank and angle checks. If a pair cannot be separated with available measurements, the limitation and the required measurement are documented, and no scheduler is built around that pair.
3. **Harness.** Truth plant, sensors, clocks and transport, fault injection, recorder and actions, and scoring, all separate. The diagnostic sees only records received by the simulated time. Fault labels are visible to the evaluator only.
4. **Diagnostic reference.** Set-valued consistency tests over physically justified relationships, with bounded nuisance and dependency tracking. Structured outcomes:
   - consistent within the tested model;
   - fault detected, cause unresolved;
   - supported hypothesis or hypothesis set;
   - insufficient evidence;
   - no modelled hypothesis fits.
5. **Actions and schedulers A to F.** Finite actions with byte and latency costs; the same diagnostic engine for every scheduler.
6. **Comparisons and ablations** on identical records (section 7).
7. **Development pilot, then pre-registration** (gate 2). Endpoint, budgets, thresholds, hypothesis definitions, parameters, scheduler rules, exclusions and the analysis are frozen in a committed manifest with hashes. The final data are generated afterwards from seeds derived from that commit, and run once.
8. **Embedded recorder interface, demonstration and physical validation plan.**

## 6. Data separation

- **Three disjoint sets:** development, calibration and final. Each is split by complete runs, plant parameter sets and operating conditions, never by adjacent samples of one trace.
- **Existing v1/v2 synthetic data:** development evidence only.
- **Final set:** generated only after the freeze commit, from seeds that are a function of that commit's hash, so it cannot have influenced any choice.

## 7. Comparisons

- **Diagnostic.** The same records go to:
  - R3v (frozen);
  - an aligned residual monitor with a fixed fault-signature table;
  - a multiple-hypothesis baseline (likelihood over HB, HT and HL with a maximum a posteriori decision and an abstention threshold);
  - CSIA2 (frozen code, with its loss model refitted on this study's development data by the frozen `calibrate_e6`);
  - the reference set-valued diagnosis.
- **Scheduling.** The same diagnostic engine with schedulers A to F:
  - A: fixed low rate;
  - B: fixed high rate;
  - C: residual-threshold capture;
  - D: random bursts at a matched budget;
  - E: information-gain;
  - F: ambiguity-directed.
- **Ablations:**
  - CSIA (scheduler F with and without CSIA's relationship and ambiguity output);
  - timing (no timing-uncertainty handling);
  - dependency (shared sources treated as independent).

If the scheduler produces the benefit and CSIA adds none, that is the result.

## 8. Reporting

The following are reported per method, at episode level, with paired comparisons and bootstrap intervals over episodes:
- wrong attribution;
- correct-diagnosis coverage;
- detection and diagnosis delay;
- false alarms per clean hour;
- unresolved outcomes and their duration;
- set size and true-hypothesis inclusion;
- bytes, memory and CPU time.

Risk is compared at matched coverage, and coverage at matched risk. Missed faults and unresolved events are reported separately. Energy is not optimised until it is measured or bounded.
