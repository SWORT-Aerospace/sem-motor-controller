# CSIA evaluation protocol (shadow mode, synthetic)

Purpose: measure whether the vehicle CSIA adapter generalises beyond the scenarios it was developed on, and which of its parts carry the benefit. This is **not** vehicle validation. The vehicle gate is `VALIDATION_PLAN.md` §6 (≥ 10 h of in-vehicle shadow data, among other conditions). Nothing here changes ADR-0008: CSIA stays in shadow mode and `restriction_permitted()` returns False.

## 1. Development set (frozen)
* Generator `host/csia_adapter/synthetic.py`, seed 7, one 120 s drive profile.
* Six faults at fixed onsets and magnitudes (`tools/run_csia_study.py` `FAULTS`).
* The adapter's thresholds, gates and attribution rules were designed and tuned on this set.
* Frozen by SHA-256 in `DEV_SET_FREEZE.json`. The frozen files are the adapter, the development generator, the baselines, the evaluation-set generator, this harness and the CSIA lock. `tools/run_csia_evaluation.py` refuses to run the evaluation if any of them has changed.

## 2. Held-out evaluation set
* Generator `host/csia_adapter/eval_set.py`, `build_eval_set(24, 5, 300, 240)`.
  * 24 fault-free scenarios of 300 s (seeds 1000–1023).
  * 14 fault kinds × 5 scenarios of 240 s (seeds 2000–2069).
* The sensor models are identical to the development generator.
* Operating conditions not in the development set: standing starts after full stops, long coasts of 25–60 s, hills to ±2.5 %, 2–5 corners of R 20–60 m, GNSS degradation and GNSS outages, randomised pulse bands and currents.
* Faults not in the development set:
  * randomised onset, duration (20–60 s) and magnitude, including smaller magnitudes than in development;
  * drifts (GNSS, IMU, phase current, DC gain);
  * dropouts (rotor samples missing; intermittent wheel);
  * unseen kinds (right-wheel dropout, rotor scale error).

## 3. Monitors and ablation
See the docstring of `host/csia_adapter/evaluation.py`. Variants V0–V3v separate three factors on identical relationships:
* **gating:** the adapter's regime gates, on or off;
* **residual design:** naive or calibrated;
* **attribution:** none, majority vote, or the adapter's corroboration logic.

TRUST isolates the TrustCore belief output. B1 is the range/freshness baseline.

**Fair calibration.** Each residual variant's threshold is the smallest value in {9, 16, 25, 36, 64, 100, 225, 400, 900} that gives zero alarms on the development nominal run, the same data the adapter was tuned on. TRUST thresholds are set 0.02 below each node's minimum trust on that run.

## 4. Metrics (per monitor)
* **False-alarm episodes per operating hour.** Contiguous alarm ticks outside fault windows `[onset, end + 5 s]`. Reported for all alarms and for false *attributions* separately. With zero observed, the 95 % upper bound 3 / hours is reported. A report that GNSS is not fresh during a designed GNSS outage is correct and is not counted.
* **Missed detections.** Fault scenarios with no alarm implicating the faulty node inside the window.
* **Misattribution.** Any other node named as suspect inside the window.
* **Ambiguity.** Fraction of in-window detection ticks in which the faulty node is implicated but not named.
* **Onset-to-detection latency** and **onset-to-attribution latency**.
* **Eligible-evidence latency.** Detection time minus the first time a relationship involving the faulty node was eligible, according to the frozen adapter's gates. This separates waiting for a regime in which the fault becomes visible from the method's own delay.
* **Unobservable intervals.** Time inside the fault with no eligible relationship for the faulty node. "Never eligible" counts faults that no relationship-based method could have seen.

## 5. Rules
* The evaluation set is run once, after the freeze commit. A post-freeze change to any frozen file must be recorded here, with its reason and the before/after results on the evaluation set. Results are never re-tuned on the evaluation set.
* Post-freeze changes before the first evaluation run: none.
* A harness check (`--smoke`) uses seeds 9000–9002, which are outside the evaluation set. During development it was used only to verify that the harness runs. It led to one **scoring** fix, applied before the freeze: a correct staleness report during a designed GNSS outage is not counted as a false alarm. The adapter was not changed after the smoke run.
