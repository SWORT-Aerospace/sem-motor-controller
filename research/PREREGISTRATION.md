# Pre-registration of the final evaluation

This document and [`preregistration.json`](preregistration.json) fix the final evaluation before any final episode exists. The manifest records the SHA-256 of every file the final run depends on: the diagnosis, harness, schedulers, baselines and scoring, the calibration, the recorder, the vehicle and loss models, and the frozen CSIA adapters. [`run_final.py`](run_final.py) refuses to run if any of them has changed, or if the commit it is given is not the one that added the manifest. The final seeds are derived from that commit's hash, so no final episode can have influenced a choice made here.

Everything below was chosen from development and calibration data only ([`RESULTS.md`](RESULTS.md) sections 1 and 2). All results are host simulation with synthetic parameters; none is a vehicle or bench measurement.

## 1. Questions and endpoints

| Research question ([`PROTOCOL.md`](PROTOCOL.md) section 1) | Endpoints |
|---|---|
| (1) recognise competing explanations | S14 to S16: the reference diagnosis on identical records, against the baselines |
| (2) state which explanations the evidence can separate | S10 (coverage), the "unresolved" and "insufficient" counts in the scheduler table; the conditions themselves are in [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) |
| (3) choose records within budgets | **P1**, S1 to S5 |
| (4) correct more often than strong baselines at matched cost and coverage | P1, S2, S4, S14, S15; risk at matched coverage and coverage at the stated risk for every pair |
| (5) abstain when no unique cause is supported | S9, S11, S12 |
| the engine's own contribution (CSIA ablations) | S5 (ambiguity information), S6 and S7 (timing allowance), S8 (dependency handling) |

## 2. Primary endpoint

**P1.** Over the fault episodes (bias, timing error, extra force including grade), the paired difference in the proportion diagnosed correctly between F (ambiguity-directed) and D (random requests from the same action set, with a byte budget equal to F's mean in the pilot, 36 245 B).

- **Criterion:** the lower end of the 95 % bootstrap interval is above 0.
- **Why this endpoint:** it isolates the choice of records. F and D use the same engine, the same actions, the same byte limit and nearly the same bytes; only the rule that chooses differs. The protocol names D as the matched-budget control.
- **Pilot value:** +0.150 [+0.025, +0.300] on 40 development episodes.
- **If it is not met:** the result is that ambiguity-directed acquisition did not beat random acquisition at a matched budget on these data, and it is reported as such.

## 3. Secondary endpoints

Each has its own interval. Only P1 is confirmatory; a secondary endpoint that meets its criterion is reported as a secondary finding, without a multiplicity correction. The pilot value is given so that the reader can see what was expected before the final data existed.

| Id | Question | Criterion | Pilot |
|---|---|---|---|
| S1 | F against the summary alone (A) | correct: lower bound > 0 | +0.175 [+0.050, +0.325] |
| S2 | F against information gain (E) | correct: lower bound > 0 | +0.025 [0.000, +0.075]: **not expected to be met** |
| S3 | F against fetching everything (B) | correct: lower bound > −0.05, and bytes: upper bound < 0 | +0.150 [0.000, +0.300]; −145 907 B |
| S4 | F against capture on detection (C) | correct: lower bound > 0 | +0.150 [+0.025, +0.300] |
| S5 | F against F without the engine's ambiguity information | bytes: upper bound < 0, and correct: lower bound > −0.05 | −20 997 B [−25 094, −16 891]; correct +0.050 [−0.075, +0.175] |
| S6 | F against F without the timing allowance, on timing-error episodes | correct: lower bound > 0 | 7 of 10 against 0 of 10 |
| S7 | the same, over all fault episodes | descriptive | +0.200 [+0.075, +0.325] |
| S8 | F against F counting the summary and the frames as independent | descriptive | no difference |
| S9 | wrong cause among F's supported decisions on fault episodes | upper end of the Wilson 95 % interval < 0.05 | 0 of 36 |
| S10 | fault episodes F diagnoses correctly | descriptive | 36 of 40 |
| S11 | unmodelled faults F reports as "no modelled cause fits" | descriptive | 5 of 10 |
| S12 | unmodelled faults F attributes to a modelled cause | descriptive | 2 of 10 |
| S13 | clean episodes with an alarm | descriptive | 1 of 20 |
| S14 | identical full-rate records: reference diagnosis against the calibrated multiple-hypothesis baseline, correct on fault windows | descriptive | 39 against 38 of 40 |
| S15 | identical full-rate records: reference diagnosis against the aligned residual monitor | correct: lower bound > 0 | 39 against 24 of 40 |
| S16 | identical records: reference diagnosis against the frozen R3v | descriptive | 39 against 0 of 40 |

**Also reported for every scheduler and every pair** ([`PROTOCOL.md`](PROTOCOL.md) section 8): wrong attribution, coverage, detection and decision delay, false alarms per clean hour, unresolved outcomes, set size and inclusion of the true cause, bytes and CPU time, risk at matched coverage, and coverage at a risk of 0.05. In the pilot no scheduler made a wrong attribution on a fault episode, so the matched-risk comparisons may carry no information; they are reported all the same.

## 4. Episodes and sample size

| Kind | Episodes |
|---|---|
| clean | 60 |
| current bias | 40 |
| timing error (pure delay) | 40 |
| extra force | 30 |
| uphill grade (counted as extra force: without the IMU, grade and drag are one class) | 30 |
| unmodelled (bus-meter gain error) | 30 |
| **total** | **230** |

**Why 140 fault episodes.** In the pilot, F and D disagreed on 8 of 40 fault episodes (discordance 0.20). With that discordance, 140 paired episodes give a standard error of about 0.036 for the paired difference: a true difference of 0.10 would give a lower bound above 0 with a probability of about 0.8. The pilot's +0.15 would be detected with a probability above 0.95. Timing errors get 40 episodes because S6 is evaluated on them alone. The run takes about 35 minutes on four cores.

**How episodes are drawn** (`research/bea/harness.py`, `draw_episode`, split "final"): 90 s per episode; the drive cycle (pulse and coast, speed hold, or mixed) drawn at random; nuisance parameters drawn within 0.9 times their known bounds; fault size 0.6 to 2 times nominal (bias 0.2 A, delay 0.1 s, force 3 N, grade 0.01 rad, gain 8 %), with a random sign where the fault can have either sign; onset uniform in 25 to 45 s; uplink outages in 20 % of episodes. The kind of timing error is a pure delay, as in the pilot; lag and averaging windows are not part of this evaluation.

## 5. Frozen settings

- **Budgets:** 200 kB of requested bytes per episode; every scheduler decides within 40 s of detection; the fixed schedulers decide 20 s after detection; D's budget 36 245 B.
- **Calibration** ([`generated/pilot/calibration.json`](generated/pilot/calibration.json), from 24 and 16 fault-free calibration episodes): the per-relationship noise factors, the consistency thresholds z (3.41 on frames, 4.68 on the summary), the rejection margins κ, the aligned monitor's thresholds, the multiple-hypothesis prior for normal operation (0.93 on frames, 0.76 on the summary), and the frozen monitors' refitted loss model and thresholds.
- **Engine comparison:** records of 45 to 70 s of every episode; the multiple-hypothesis baseline accepts a cause at a posterior of 0.95.
- **Schedulers and ablations:** A to F, and F without ambiguity information, without timing allowance, and with double counting, as in [`DIAGNOSIS.md`](DIAGNOSIS.md).

## 6. Analysis

- **Unit of analysis: the episode.** Episodes are independent draws (separate seeds). Windows inside one episode are not independent, so no inference is made at the window level, and no distribution-free coverage or false-alarm guarantee is claimed.
- **Paired differences:** mean over episodes of (F's outcome − the other's outcome), with a percentile bootstrap 95 % interval over episodes (4000 resamples, seed 1).
- **Proportions:** Wilson 95 % intervals.
- **Risk against coverage:** decisions ranked by the gap between the fit of the supported cause and the next cause; risk at the lower of the two schedulers' coverages, and coverage at a risk of 0.05, each with a bootstrap interval.
- **Exclusions:** none. Every episode counts. An episode that raises an error stops the run; nothing is dropped silently.
- **Evaluation:** `run_final.py` evaluates each criterion mechanically and writes the verdicts to `generated/final/summary.md`. The criteria are not changed after the results are seen; a criterion found to be ill-posed is reported as such, next to its verdict.

## 7. What the final evaluation cannot show

- anything about the vehicle, the bench or real sensor noise (synthetic host simulation);
- timing errors other than a pure delay, faults present at the same time, or faults with the IMU fitted;
- the separation of drag from grade or headwind (not identifiable without the IMU or an air-speed sensor, [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md));
- worst-case execution time on the telemetry unit (the recorder's host timings are not a WCET, [`RECORDER.md`](RECORDER.md)).

**Code check before the freeze.** The final runner was exercised on 6 episodes whose seeds were derived from the string "smoketest", to check the code path. Those episodes are not part of the final set, and their outcomes were not used for any choice.
