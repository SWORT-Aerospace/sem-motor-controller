# Reference diagnosis, actions and schedulers: specification

The mathematics behind `research/bea/relations.py`, `diagnosis.py`, `episode.py` and `schedulers.py`. The relationships, signatures and nuisance terms are those of [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) section 1; this document adds what the diagnosis does with measured records. Thresholds marked "calibrated" are set on the calibration split by [`../research/run_pilot.py`](run_pilot.py) and frozen in the pre-registration.

## 1. From records to signals

**Full-rate records.**

- **Slots.** Each controller frame goes to its 10 ms controller cycle: slot = round((t_rx − t_ref) / period). Receipt jitter is far below the period. A cycle with no record (a lost frame) is filled by linear interpolation. Neighbouring records are never averaged, so the measurement noise stays independent between samples.
- **Drive or coast.** The command trace decides whether the gates are on. Near each of its transitions, the 100 Hz q current places the change to the cycle. Elsewhere the trace alone decides, because the gates can be on at zero torque.
- **Speed.** Rotor speed while driving; while coasting, wheel speed from the count windows, each stamped when it closes and taken at its centre.
- **Power model.** The model power P_model comes from the nominal loss map, driven by the measured iq, rotor speed and voltage.

**Summary records.** These are the 2 Hz snapshots: iq, speed and voltage at the message time, the mean battery power since the previous message, and the latest wheel window. A message is usable only if the previous message has the next sequence number and was in the same mode: a mean that straddles a drive/coast change is not used. The model power is averaged over the same interval as the measured mean (the mean of its values at the two snapshots).

**Intervals never bridge gaps.** A relationship built on an interval (R2, R4, and R1 and R3 near mode changes) needs a sample at the interval's end. Where messages are missing, or where fetched frames replaced the summary, the interval is dropped. Wheel windows are paired by their actual spacing: 0.1 s apart in full-rate records, 0.5 s apart in the summary (one window per message).

## 2. Residuals and the fit

Each relationship gives a block, with four parts:

- the measured residual r (measured quantity minus nominal model);
- the signature columns C (one per parameter);
- the timing term s(δ) = P_model(t − δ) − P_model(t) for R1, and I_model(t − δ) for R3;
- the covariance Σ.

**Covariance.**

- R1, R3 and R5: white noise per sample, plus an alignment variance at the samples where the measured signal has a corner. Linear interpolation cannot place a slope change inside a sample interval: the error is at most about a quarter of the second difference. Second differences within three noise levels are treated as noise.
- R2: the banded covariance of differenced rotor speeds.
- R4: the banded covariance of the second difference of quantised wheel distance.
- **Calibrated scale factors.** Each relationship's standard deviations are multiplied by a factor per evidence source (full-rate frames or the summary), set on the calibration split: the square root of the median of its share of the normal-operation fit statistic per sample. The factors are listed in `generated/pilot/calibration.json`. On the summary, the power and coast-current models overstate the noise by a factor of about 2.5 (their values are means of five frames); the other factors are within about 6 % of 1.

**Timing offset.** Under an offset δ, the bus meter reports its whole quantity late, the loss terms included. So the R1 columns are evaluated at t − δ, C(δ). In R3, a coast sample offset by δ can carry the current of the drive that preceded it, together with that drive's loss terms. Samples of R1 and R3 are kept 0.5 s away from both ends of the window, so that t − δ stays inside it for every δ tested.

**Fit of hypothesis h.**

```
J_h = min over delta in D_h, x in B_h of  || L^-1 ( r - C(delta) x - s(delta) ) ||^2,     Sigma = L L^T
```

- B_h is the box of H0 with h's own parameter freed.
- D_h is the H0 timing bound, or ±0.5 s for HT.
- The search over δ is a 21-point grid, refined by golden section. When the timing term has no signature on the window (whitened norm below 0.05 at both ends of D_h), only δ = 0 is evaluated.
- The inner problem is bounded least squares (`bvls`, tested against enumeration).

## 3. Decision

z_h = (J_h − n) / √(2n), where n is the number of samples.

1. **Normal operation is rejected** when z_H0 > z_c, or when some fault hypothesis improves the fit by more than its margin: J_H0 − J_h > κ_h.
   - z_c is calibrated per evidence source: 1.1 times the largest per-episode maximum of z_H0 on fault-free calibration episodes, and at least 3.
   - κ_h is calibrated per hypothesis and per evidence source (summary or full-rate frames). It is 1.1 times the largest per-episode maximum of J_H0 − J_h on fault-free calibration episodes, and at least 10.83 (the χ²(1) 0.999 point).
   - The timing hypothesis gets a larger κ because searching δ over ±0.5 s gives it more freedom.
2. **Otherwise, the outcome is "consistent within the tested model".** If no fault of reference size could have separated on these records, the outcome is "insufficient evidence" instead. The reference sizes are 0.2 A, 0.1 s and 3 N, and the test is the noise-free separation of section 2 with bounded nuisance, at d ≥ 4. Hypotheses that could not be tested are listed in the reason.
3. **If normal operation is rejected,** the remaining set is the fault hypotheses with z_h ≤ z_c and J_h within 9 of the best fault fit:
   - an empty set: "no modelled hypothesis fits";
   - one hypothesis: "supported";
   - more than one: "fault detected, cause unresolved", with the set.

**Recorded with every diagnosis:** the window, the blocks used and their sample counts, J and z for every hypothesis, every estimate (offset and parameters), the timing bound, and the reason.

**Not claimed:** "consistent" does not mean healthy, and an empty set never means healthy.

## 4. Evidence assembly in an episode

**Detection.** A fault is detected by the summary monitor (the last 20 s of summaries, evaluated every second, two consecutive rejections). Fetched full-rate records can also detect it: each one is diagnosed on its own when it arrives. A fetched window found consistent marks as tested each hypothesis it could have shown (reference power at least 4), stamped with the window's end, not with its arrival time.

**Cleared alarms.** When the decision after an alarm is "consistent" or "insufficient", the alarm is cleared and counted, the monitor is re-armed and the episode continues.

**Decision window.** It starts at detection. Within it:

- fetched frame segments are used first (highest rate first, without overlaps);
- the summary covers the remaining time;
- the summary is never used for time covered by frames, because both measure the same quantities.

**Timing bound.** It is 0.1 s until clock metadata shows the receipt path to be tight (jitter between consecutive sequence numbers below 5 ms); then it is 5 ms.

## 5. Actions

Each action has a cost: bytes from [`HARNESS.md`](HARNESS.md) section 5, and latency from the round trip, transfer and capture time.

| Action | Records | What it can test |
|---|---|---|
| edge | 2 s of full-rate motion, current and command frames around a power edge seen in the summary | HT (and HB, HL weakly) |
| coast | a coast segment of frames at 1/10 rate, plus its wheel counts | HB through R3; HL through R4 |
| steady | a steady-driving segment of frames at 1/10 rate | HB and HL through R1 and R2 |
| imu | IMU records plus 1/10-rate frames (only when an IMU exists) | grade against drag (R5) |
| capture | the next 6 s of full-rate frames and wheel counts | whatever the next 6 s contains |
| clock metadata | receipt-path jitter and recorder counters | narrows the timing bound |
| wait | nothing | lets a coast or an edge occur |
| stop | nothing | reports the current decision, unresolved if it is |

The action set is finite and is rebuilt from the summary at each step. An increase of the acquisition rate is **not** an action: it would change the controller's frame schedule. Every action exports more of what is already acquired, or waits.

## 6. Schedulers

All six use the same engine, the same actions and a hard byte limit (200 kB per episode).

- **A (fixed low rate):** the summary only; decides 20 s after detection.
- **B (fixed high rate):** clock metadata, then every channel at full rate in 5 s blocks for the whole episode; decides 20 s after detection.
- **C (event capture):** on detection, clock metadata, the last 5 s and the next 20 s of every channel at full rate.
- **D (random bursts):** random actions at random times, until the byte budget matched to F's mean in the pilot is spent.
- **E (information gain):** maximises expected information gain per cost. For each candidate it predicts the noise-free separation d of each open pair on a proxy of the window rebuilt from the summary. It scores Σ w (1 − exp(−d²/8)) per (bytes + 2000 B/s × latency). It stops when the best score is negligible.
- **F (ambiguity-directed):**
  - **Open hypotheses.** After detection, the set the current decision retains (all faults if it has none). Before detection, the hypotheses the summary monitor cannot test (reference power below 4).
  - **Choice.** The candidate that separates the most open pairs (predicted d ≥ 4) per cost. Already-fetched windows are never repeated. Clock metadata comes first when a timing hypothesis is open.
  - **Stopping.** If nothing affordable separates a pair, F waits for a new coast or edge. Within 6 s of the deadline it stops and reports the open set.
  - **Audits.** Before detection, every 15 s, with at most 30 % of the byte budget: one window for each hypothesis not tested by a window ending in the last 30 s, at most two per audit, from the last 60 s of the log. Only windows later than the last window that tested the hypothesis are considered, since an earlier window cannot show a fault that began after it.
  - **Ties** between candidates of equal value and cost go to the most recent window (E and F).

**Bounded computation.** Each choice evaluates at most about eight candidates, each with at most three pairs.

**Not a guarantee.** The predicted separations are computed on a proxy rebuilt from 2 Hz snapshots. A power edge appears there as a 0.5 s ramp, so the prediction for timing is conservative. The predictions guide the choice and carry no formal guarantee.
