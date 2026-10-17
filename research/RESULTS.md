# Results: development, pre-registration and final evaluation

All results are host simulation with synthetic parameters ([`HARNESS.md`](HARNESS.md)). None is a vehicle or bench measurement.

## 1. Development: failures found and changes made

Development data only (development and calibration splits). Each change below was made **before** the protocol was frozen, and each was found by a test, a probe or pilot round 1. Round 1's raw results are kept in [`generated/pilot/round1/`](generated/pilot/round1/).

**Found while building the diagnosis (single-episode probes):**

| Problem | Effect | Change |
|---|---|---|
| The torque-constant error entered the power balance with +Kt·iq·ω but the force balances with the same sign, although a larger torque constant makes the model under-estimate the force | the shared parameter forced R1 and R2 to opposite bounds; correct biases were rejected ("no modelled cause fits") | each column is the change of its residual for a positive change of the parameter; R2 and R5 use −F_trac |
| Motor friction had a column in the power balance | an extra, unphysical nuisance direction in R1 (with iq measured, the electrical power does not depend on how torque splits) | removed from R1; the bus-meter zero offset added to R1 (V·Ioff, shared with R3) |
| Interpolating records onto a uniform grid averaged neighbouring samples | the fit statistic was 25 to 40 % below its expectation on fault-free windows | frames are placed in their 10 ms controller cycle, never averaged |
| A power edge inside a sample interval cannot be placed by interpolation | about 17 W errors (against about 1 W of noise) whenever the timing offset was not a multiple of 10 ms | an alignment variance taken from the measured signal's second difference |
| Under a timing offset, the loss terms were evaluated at t instead of t − δ | about 10 W left at every transient (2 % of 500 W through the torque-constant term) | R1's columns follow the offset; R3 carries the delayed drive current with its loss terms |
| R1 and R3 near the window ends had no data at t − δ | false residuals at window starts | 0.5 s margins at both ends |
| The drive state came from the 50 Hz command trace | the edge could be placed about 20 ms off, which looks like a timing error | the 100 Hz q current places each transition, within 30 ms of where the trace puts it |
| A first attempt used low q current to mean "coast" | false bias alarms whenever the gates were on at zero torque | reverted; the trace decides the state |
| Clock-metadata jitter counted a lost frame as jitter | the timing bound never tightened | jitter between consecutive sequence numbers only |
| One rejection margin of 9 for every hypothesis | the timing hypothesis's search over ±0.5 s gained about 20 by chance on fault-free windows | margins calibrated per hypothesis and per evidence source |
| The minimum segment length equalled the edge window (2 s) | fetched edge windows were silently dropped from the decision | 1.2 s |
| Solver round-off on collinear, badly scaled columns | "collinear" tests failed at d of about 0.002 | column scaling in the solver; collinearity judged relative to the signal (1e-5) |

**Found by pilot round 1** (70 development episodes per scheduler). Round 1 measured:

- **False alarms:** 7 to 10 of the 20 clean episodes, for every scheduler.
- **Timing errors:** at most 2 of 10 correct.
- **Load:** 7 of 20 ended "no modelled cause fits", most of them after a detection before the fault began.

| Cause | Change |
|---|---|
| The summary's mean power over the previous 0.5 s was compared with the model's power at the message instant: under speed hold this left a systematic offset, and the timing hypothesis fitted it (summary margin for HT 32) | the model is averaged over the same interval (mean of its values at the two ends); the summary margin for HT fell to 10.8, the floor |
| The first alarm ended the episode, so an alarm before a fault hid the fault | an alarm cleared by a "consistent" decision re-arms the monitor; cleared alarms are counted |
| F did not remember which hypotheses a fetched window had already tested | audits kept fetching the cheapest window (a coast) and never tested the timing hypothesis | hypotheses tested by a fault-free window stay tested for 30 s |
| The frames and the wheel counts of one coast window came back as separate responses and were diagnosed separately | the load hypothesis was never tested by a coast audit | requests for one window form one segment |
| The proxy that predicts a window turned a drive onset into a step | F predicted that full-rate edges could not show a timing error | proxies ramp the onset with the interpolated current and carry no interpolation-error term |
| Audits looked back 20 s, but pulse-and-coast cycles last 70 to 80 s (two power edges per cycle) | no edge was available to audit | look back 60 s; one window per untested hypothesis, at most two per audit |
| The harness charged an STLG block framing | about 4 % fewer bytes than the recorder's chunk framing | costs follow the recorder's wire format |

**A property of the problem, not a defect.** In pulse-and-coast driving a 90 s episode holds only two or three power edges, so a timing error can be seen only a few times a minute. The 2 Hz summary never shows one (P1 and P4 of [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md)).

**Found by pilot round 2** (the same 70 development episodes; raw results in [`generated/pilot/round2/`](generated/pilot/round2/)). Correct outcomes per scheduler:

| Scheduler | bias (10) | timing (10) | load (20) | unmodelled reported as no fit (10) | clean episodes with an alarm (20) |
|---|---|---|---|---|---|
| A | 8 | 0 | 10 | 3 | 7 |
| B | 8 | 3 | 12 | 5 | 7 |
| C | 8 | 0 | 14 | 6 | 7 |
| D | 8 | 2 | 12 | 4 | 7 |
| E | 9 | 3 | 14 | 8 | 7 |
| F | 9 | 1 | 14 | 8 | 7 |

The alarms on clean episodes were the same seven episodes for every scheduler: they came from the summary monitor. Two of them ended "no modelled cause fits" under F. Every bias or load episode that ended "no modelled cause fits" had an alarm before the fault began, so its decision window straddled the onset.

| Cause | Change |
|---|---|
| On the summary, a torque-balance interval could bridge a gap where fetched frames had replaced the summary: the speed difference then spanned several seconds and the residual reached 43 standard deviations | an interval needs a sample at its end; intervals that bridge a gap are dropped |
| One noise scale for all summary relationships (0.67) was set mostly by the power balance, whose noise model is about 2.2 times too large there; the torque balance, modelled about right, became 1.5 times too confident and gave z of 3 to 5 on clean speed-hold windows | a scale factor per relationship and evidence source; the consistency threshold z is calibrated per source by the same rule as κ |
| On the summary, the coast deceleration paired wheel windows five messages (2.5 s) apart but divided by 0.5 s, overstating the deceleration fivefold; the wheel-count quantisation (0.47 m/s per count in a 0.1 s window) hid this in most windows, not all (−287 N in one calibration window) | windows are paired by their actual spacing |
| Audits chose, among windows of equal value and cost, the oldest one in the 60 s look-back, often from before the fault; a window found fault-free was counted as testing the present for 30 s after it arrived | a fault-free window counts as testing until 30 s after its own end; audits only consider windows later than the last test; ties go to the most recent window |

**Found by pilot round 3** (the same episodes; [`generated/pilot/round3/`](generated/pilot/round3/)). Correct outcomes per scheduler:

| Scheduler | bias (10) | timing (10) | load (20) | unmodelled reported as no fit (10) | clean episodes with an alarm (20) | mean bytes |
|---|---|---|---|---|---|---|
| A | 10 | 0 | 19 | 2 | 1 | 0 |
| B | 9 | 3 | 13 | 3 | 1 | 184 938 |
| C | 10 | 0 | 20 | 6 | 1 | 63 836 |
| D | 10 | 1 | 19 | 2 | 1 | 31 856 |
| E | 10 | 7 | 18 | 5 | 1 | 40 089 |
| F | 10 | 7 | 19 | 5 | 1 | 36 246 |

The changes after round 2 removed six of the seven alarms on clean episodes and every "no modelled cause fits" outcome of A, C and D. B, which fetches every channel continuously in 5 s blocks, still ended "no modelled cause fits" on 7 of 40 fault episodes.

| Cause | Change |
|---|---|
| When fetched records detected a fault, the detection was stamped with the start of the fetched block rather than with the time the records arrived, so B's detections looked earlier than the onset | the detection time is the arrival time; the decision window still starts with the records that detected the fault |
| Every hypothesis has a constant size over the decision window. When the window starts with a block that straddles the onset, normal operation fits the part before it and no constant fault fits the whole | when the whole window gives "no modelled cause fits", the final decision tries change points every 2 s, in time order: the first one before which normal operation is not rejected and after which a modelled cause fits is reported, with the change point in the reason; otherwise "no fit" stands |
| The pilot did not run the ablations or the engine comparison on identical records | both are part of the pilot from round 4 on, so their effect sizes inform the pre-registration |

Round 4 is the last development round: the protocol is frozen after it, whatever it shows.

## 2. Development pilot, final round

Round 4: the 70 development episodes again (10 per kind: 20 clean, 10 bias, 10 timing error, 10 extra force, 10 uphill grade, 10 unmodelled meter gain error), every scheduler and ablation on the same records. Raw results: [`generated/pilot/round4/`](generated/pilot/round4/) and [`generated/pilot/dev_summary.md`](generated/pilot/dev_summary.md). Development evidence only: these episodes chose the protocol, so they cannot test it.

**Schedulers** (fault episodes: 10 bias, 10 timing, 20 extra force; the grade episodes count as extra force, since without the IMU grade and drag are one class):

| Scheduler | bias | timing | force | fault episodes correct | wrong | no fit | missed | unmodelled: no fit / wrongly attributed (of 10) | clean with an alarm (of 20) | mean bytes | median decision delay [s] |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A fixed low | 10 | 0 | 19 | 29 | 0 | 0 | 11 | 2 / 1 | 1 | 0 | 23.7 |
| B fixed high | 10 | 3 | 17 | 30 | 0 | 2 | 8 | 3 / 1 | 1 | 184 938 | 23.1 |
| C event capture | 10 | 0 | 20 | 30 | 0 | 0 | 10 | 6 / 0 | 1 | 63 836 | 29.1 |
| D random, budget matched to F | 10 | 1 | 19 | 30 | 0 | 0 | 10 | 2 / 1 | 1 | 31 922 | 24.1 |
| E information gain | 10 | 7 | 18 | 35 | 0 | 1 | 4 | 5 / 2 | 1 | 40 089 | 12.6 |
| F ambiguity-directed | 10 | 7 | 19 | 36 | 0 | 1 | 3 | 5 / 2 | 1 | 36 246 | 12.1 |
| F without ambiguity information | 9 | 8 | 17 | 34 | 0 | 3 | 3 | 7 / 0 | 1 | 56 107 | 39.3 |
| F without timing allowance | 10 | 0 | 18 | 28 | 0 | 8 | 4 | 5 / 2 | 1 | 37 611 | 11.3 |
| F with summary and frames counted twice | 10 | 7 | 19 | 36 | 0 | 1 | 3 | 5 / 2 | 1 | 36 047 | 12.1 |

Paired over the 40 fault episodes (bootstrap 95 % intervals): F − D +0.150 [+0.025, +0.300]; F − A +0.175 [+0.050, +0.325]; F − E +0.025 [0.000, +0.075]; F − F without ambiguity information +0.050 [−0.075, +0.175] at 20 997 fewer bytes [16 891, 25 094]; F − F without timing allowance +0.200 [+0.075, +0.325]; F − F with double counting 0.000.

**What round 4 says, before any final data:**

- **No wrong attribution on a fault episode, by any scheduler.** Risk among supported decisions was 0 everywhere, so "risk at matched coverage" cannot discriminate between schedulers on these data; coverage carries the comparison.
- **The summary alone diagnoses bias and extra force.** A, with no requested record, was correct on 10 of 10 bias and 19 of 20 force episodes. Requested records add the timing error and speed.
- **Directed choice beats undirected choice at the same budget** (F against D), on 40 development episodes.
- **The ambiguity-directed rule and information gain perform alike** (F against E: one discordant episode).
- **The ambiguity information saves bytes rather than correct diagnoses**: without it, F fetched 55 % more and decided 27 s later, with 2 fewer correct.
- **The timing allowance is what makes timing errors diagnosable**: without it, F diagnosed no timing error and 8 fault episodes ended "no modelled cause fits".
- **Treating dependent sources as independent changed nothing measurable here**, because frames replace the summary for the same time before the ablation can double-count much.
- **An unmodelled meter gain error is attributed to a modelled cause in 2 of 10 episodes** (a bias, a timing error) by A, D, E and F; that is the main abstention failure.
- **One clean episode raised a cleared alarm** under every scheduler (the summary monitor).

**Engines on identical records** (45 to 70 s of each episode, after every onset):

| Engine | records | clean: no alarm (of 20) | bias correct (of 10) | timing correct (of 10) | force correct (of 20) | unmodelled reported as no fit (of 10) |
|---|---|---|---|---|---|---|
| Reference set-valued diagnosis | full-rate frames | 20 | 10 | 9 | 20 | 9 |
| Multiple-hypothesis baseline | full-rate frames | 20 | 10 | 9 | 19 | 0 (cannot report it) |
| Aligned residual monitor | full-rate frames | 20 | 4 | 4 | 16 | 6 |
| Reference set-valued diagnosis | summary | 20 | 10 | 0 | 19 | 1 |
| Multiple-hypothesis baseline | summary | 19 | 10 | 0 | 19 | 0 |
| Aligned residual monitor | summary | 17 | 0 | 0 | 14 | 1 |
| R3v (frozen) | its own stream | 20 | 0 | 0 | 0 | 0 |
| CSIA2 (frozen) | its own stream | 20 | 0 | 0 | 0 | 0 |

The multiple-hypothesis baseline's prior for normal operation is calibrated on the calibration split (below); with equal priors it reported a fault on all 20 clean windows. R3v and CSIA2 have no hypothesis for a timing error or an extra force, and did not flag the bias at these sizes.

**One change after round 4, to a baseline only.** With equal prior probabilities, the multiple-hypothesis baseline cannot prefer normal operation on a steady window, where a timing offset has no signature and both explain the records equally well. Its prior for normal operation is now calibrated on the calibration split by the rule used for the reference diagnosis (the smallest prior that makes normal operation the most probable hypothesis on every fault-free calibration window, with the odds raised by 1.1): 0.93 on full-rate frames, 0.76 on the summary. Only the engine comparison was rerun; no scheduler or engine logic changed.

## 3. Final evaluation

Pending: generated once, after the pre-registration commit.
