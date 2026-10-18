# CSIA evaluation protocol v2 (shadow mode, synthetic)

Version 2.0, written and hash-frozen (`V2_FREEZE.json`) before any evaluation seed was generated. Protocol v1 (`EVALUATION_PROTOCOL.md`) and its results (`EVALUATION_RESULTS.md`) are unchanged and remain the record of the v1 adapter. Nothing here changes ADR-0008: CSIA stays in shadow mode and `restriction_permitted()` returns False. Owner of the protocol: the controls lead (decision rule in section 6); the result is reviewed by whoever owns the telematics firmware before any CSIA output is displayed to the pit.

## 1. Why a v2

The host end-to-end demonstration (`docs/generated/host_demo/summary.md`) replayed a run through the frozen v1 adapter and found 507 power-balance (E6) failures outside the injected fault in 1200 ticks. Two causes were measured on that run:

1. E6 compared the latest p_dc (10 Hz in protocol 1.1) with the latest iq and rotor speed (100 Hz) at the tick, without time alignment. At cruise the residual standard deviation was 28.9 W, against 1.4 W when iq and speed were interpolated to the p_dc sample time.
2. The v1 loss model (8 % of mechanical power + 3 W) has no copper-loss term. The plant's loss fitted as 0.159 iq² + 3.02 W.

The v1 synthetic generators produced p_dc with the adapter's own loss form and constant current within pulses, so the v1 evaluation could not see either cause. v1 also recorded current drift misattributed to the rotor in 4 of 5 held-out cases.

## 2. What changed

| Part | v1 | v2 |
|---|---|---|
| Adapter | `adapter.py` (frozen) | `adapter_v2.py`: subclass; E6 time-aligned; E6 loss model 1.5 R iq² + c_sw abs(iq) + P0 with R, c_sw, P0, s0 fitted on development nominal data; with a freewheel, phase_current is an auxiliary input of E1 (the freewheel-engagement gate uses iq) |
| Generator | `eval_set.py`: p_dc = p_mech + 6 % abs(p_mech) + 3 W at 50 Hz, pulse-and-glide only | `eval_set_v2.py`: p_dc = p_mech + 1.5 R(T) iq² + k_sw abs(iq) + P_fixed + noise at 10 Hz; per scenario R0 ±10 %, winding temperature with tau 240–480 s, k_sw 0.05–0.15 W/A, P_fixed 2–5 W; speed-hold segments with filtered command noise in addition to pulse-and-glide; all other physics, sensors, clocks and faults as v1 |
| Debounce | 3 ticks per relationship in the residual monitors, none in the adapter path | one shared 3-tick node-level persistence filter on every monitor |

## 3. Data

* **Development set** (design and calibration; may be run any number of times): `eval_set_v2.dev_set()`: 8 fault-free scenarios of 300 s (seeds 3000–3007) and 14 fault kinds × 2 scenarios of 240 s (seeds 3100–3127).
* **Evaluation set** (run once, after the freeze commit): `eval_set_v2.eval_set()`: 24 fault-free scenarios of 300 s (seeds 6000–6023) and 14 fault kinds × 5 scenarios of 240 s (seeds 7000–7069). No scenario with these seeds was generated before the freeze.
* The v1 held-out set (seeds 1000–1023, 2000–2069) is not reused for evaluation.

Development iterations, all on the development set (`docs/generated/csia_v2_development_synthetic.md` holds the last):

1. v2 E6 (alignment + loss model): CSIA2 0.5 FA/h, 18/28 correctly attributed, 3 misattributed (current drift → rotor 2, intermittent wheel → IMU 1).
2. E1 auxiliary input phase_current: CSIA2 0.5 FA/h, 18/28 correctly attributed, 1 misattributed (intermittent wheel → IMU). No further change.

## 4. Monitors and calibration

| Monitor | Definition |
|---|---|
| B1 | range / NaN / freshness checks (`baselines.py`) |
| R3 | calibrated residuals on the v2 relationship set with the adapter's gates; detection only |
| R3v | R3 + majority vote: a node in ≥ 2 failing relationships, unique |
| CSIA1 | frozen v1 adapter (its own relationships and corroboration attribution) |
| CSIA2 | v2 adapter (v2 E6, E1 auxiliary input) with the v1 corroboration attribution |
| TRUST2 | TrustCore beliefs of the v2 adapter, thresholded per node |
| B1+CSIA2 | union |

Calibration, on development nominal scenarios only, recorded in `V2_FREEZE.json` and reused unchanged for the evaluation:
* E6 model: least squares, `adapter_v2.calibrate_e6`.
* Residual threshold of R3 and R3v: the smallest value in {9, 16, 25, 36, 64, 100, 225, 400, 900} with zero debounced alarms.
* TRUST2 thresholds: 0.02 below each node's minimum belief after a 10 s burn-in.

## 5. Metrics (per monitor)

As protocol v1 section 4, with the v1 scoring code (`evaluation.score`, GRACE 5 s, designed GNSS outages not counted):
* false-alarm episodes per operating hour (all alarms; false attributions separately; 95 % upper bound 3/h when zero);
* coverage: fault scenarios with any alarm implicating the faulty node inside the window, over all fault scenarios;
* correctly attributed, misattributed (wrong cause), median ambiguity fraction;
* median onset-to-detection latency and median eligible-evidence latency;
* unobservable fraction of each fault window and scenarios never eligible, per fault kind;
* host CPU per tick (ingest + tick) and peak traced Python memory over 60 s of one fault-free scenario. Both are x86-64 CPython figures, not target figures.

## 6. Decision rule (pre-registered)

The adapter's attribution (CSIA2) is preferred over the simpler majority vote (R3v) only if, on the evaluation set, CSIA2 has:
* at least 5 more correctly attributed fault scenarios than R3v, and
* at most 1 more misattributed fault scenario than R3v, and
* at most 1.0 more false-alarm episode per hour than R3v.

Otherwise R3v is the recommended monitor, and CSIA attribution remains a shadow research component. The same rule judges TRUST2 against R3v. B1's freshness channel is kept in either case, because dropped samples are visible only to it.

## 7. Rules

* `tools/run_csia_evaluation_v2.py --eval` refuses to run if any frozen file differs from `V2_FREEZE.json` or if the evaluation results already exist.
* The evaluation uses the calibration recorded at the freeze, never a re-calibration.
* A post-freeze change to any frozen file is recorded here with its reason and the before/after results; results are never re-tuned on the evaluation set.
* Post-freeze changes before the evaluation run: none.

## 8. Limitations

* Synthetic data only. The generator and the adapter were written by the same team. The v2 generator differs from the v2 E6 model by the winding-temperature dependence of R and by per-scenario parameters the adapter does not know, but its loss structure (I², abs(I), constant) is the adapter's. A real drivetrain adds iron loss that depends on speed and inverter losses that are non-linear in current (dead time), which neither models. E6 results here are therefore an upper bound until E6 is calibrated on bench data of the real motor and controller.
* Sensor noise models, clocks and fault kinds are v1's.
* The vehicle gate of `VALIDATION_PLAN.md` section 6 (≥ 10 h of in-vehicle shadow data) is unaffected.
