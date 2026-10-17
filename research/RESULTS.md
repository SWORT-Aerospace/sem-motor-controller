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

## 2. Development pilot, final round

Pending: round 3 of the development pilot, with the changes above, is the last before the pre-registration.

## 3. Final evaluation

Pending: generated once, after the pre-registration commit.
