# Claims and the evidence for each

Every claim the study makes, with the evidence that supports or limits it. Labels:

- **[F]** fact about the repository or design;
- **[D]** derived by analysis;
- **[M]** measured in host simulation;
- **[P]** proposal;
- **[A]** assumption.

"Host simulation" means synthetic parameters and injected faults on the computer; no claim here is a vehicle or bench measurement.

## 1. Supported, in host simulation

| # | Claim | Evidence | Limits |
|---|---|---|---|
| 1 | A bias of the bus current, a timing error between the electrical and motor records, and an extra opposing force can be separated from each other and from normal operation as classes, each on the right operating condition: a bias on a coast or at low steady power, a timing error on a full-rate power transient, an extra force on steady driving or full-rate coast records [D] | [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) sections 2, 3 and 6; `tests/research/test_identifiability.py` | linear signatures with an exact time shift; Gaussian noise of assumed levels; synthetic plant |
| 2 | A timing error has no signature at steady power at any rate, and the 2 Hz summary shows one only rarely [D, M] | [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) P1, P4, gate item 5; final evaluation: 2 of 40 diagnosed from the summary | the "cannot" of the first version was too strong ([`RESULTS.md`](RESULTS.md) section 3.4) |
| 3 | Without the IMU, drag and grade are collinear at every rate; drag and headwind are not separable with any sensor in the design [D] | [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) P6, P7, cases D and E | the IMU's bias after mounting calibration is assumed, not measured |
| 4 | Choosing records by predicted separation diagnoses more fault episodes correctly than random requests from the same actions at the same budget [M] | final P1: +0.164 [+0.100, +0.229] on 140 fault episodes | one harness, one set of fault sizes, pure delays only |
| 5 | Requested records add correct diagnoses to the summary alone, mainly timing errors [M] | final S1: +0.186 [+0.121, +0.250]; A diagnosed 0 of 40 timing errors | the summary alone diagnosed all 40 biases and 54 of 60 force episodes |
| 6 | Directed requests match or beat fetching every channel continuously, at about a fifth of the bytes [M] | final S3: +0.157 [+0.093, +0.229]; 38 242 against 184 934 B | bytes are not modem energy (below) |
| 7 | The engine's ambiguity information saves about a third of the requested bytes and about 27 s of decision delay, without losing correct diagnoses of modelled faults [M] | final S5: −20 847 B [−23 161, −18 608]; correct +0.021 [−0.029, +0.071] | it costs abstention on unmodelled faults (claim 14) |
| 8 | The timing allowance is necessary to diagnose timing errors [M] | final S6: 22 of 40 against 0 of 40 | |
| 9 | Among supported decisions on modelled faults, no wrong cause was given [M] | final S9: 0 of 120, Wilson upper bound 0.031 | the simulated faults are those the engine models |
| 10 | On identical full-rate records, the reference set-valued diagnosis is far ahead of an aligned residual monitor [M] | final S15: +0.486 [+0.407, +0.571] | the monitor's thresholds were calibrated by one rule on 16 episodes |
| 11 | A portable recorder for the telemetry unit implements the requests the schedulers use (buffered windows, future capture, clock metadata) with bounded memory and rate-limited responses [F, M] | [`RECORDER.md`](RECORDER.md); 72 host checks under sanitizers; a Cortex-M4F compile check | host timings are measured maxima on the host, not a worst-case execution time; not run on the target |
| 12 | The research code is diagnostic only: it cannot reach CAN, MQTT, serial or sockets, or change propulsion, braking, protection thresholds or control-loop timing [F] | `tests/research/test_boundary.py`; no firmware or host module imports the research code (only the link check and `tools/verify_all.py` name its files) | |

## 2. Not supported, or not established

| # | Claim | Evidence | Status |
|---|---|---|---|
| 13 | The ambiguity-directed rule is better than information gain | final S2: 0.000 [−0.021, +0.021]; each was correct on 120 of 140, and they disagreed on 2 episodes, one each way | **not supported**: the benefit comes from directed acquisition, not from this rule in particular |
| 14 | The diagnosis abstains on faults it does not model | final S11, S12: F reported "no modelled cause fits" on 14 of 30 unmodelled faults and attributed 8 of 30 to a modelled cause | **not established**. On identical full-rate windows the reference abstained on 24 of 30; at episode level F stops early once one cause remains, and that early stop is where the attributions come from (without the ambiguity information: 1 of 30) |
| 15 | The reference diagnosis beats a calibrated multiple-hypothesis baseline on modelled faults | final S14: +0.021 [−0.007, +0.057] | **not established**; its distinct contribution is the explicit "no modelled cause fits" |
| 16 | Treating dependent sources as independent harms the diagnosis | final S8: +0.029 [0.000, +0.064] | small effect at the edge of the interval; descriptive only |
| 17 | The frozen R3v and CSIA2 detect these faults | final S16 and the engine table: they flagged none | **not supported** at these sizes; they have no timing or force hypothesis |
| 18 | The method is new | [`PRIOR_ART.md`](PRIOR_ART.md) section 4 | **not claimed**. Most named sources were read only as summaries; the narrowed applied claim of section 4.4 awaits the access gaps of section 4.6 |

## 3. Not tested

| # | Question | Why not | What would test it |
|---|---|---|---|
| 19 | Do the results hold on the vehicle or the bench? | no controller board, no telemetry firmware, no request path to the vehicle [F] | [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md): E2 on the stand-in rig first |
| 20 | Are timing errors of the sizes used (0.06 to 0.2 s) realistic, and are they delays? | the receipt-path and meter timing are assumed [A] | E2: 50 repetitions of a 2 A step |
| 21 | Lag and averaging timing errors, simultaneous faults, the IMU | outside the pre-registered evaluation | a further pre-registered run on the "robust" split |
| 22 | Fewer bytes means less modem energy | the modem's energy per byte, per connection and per idle period is not measured [A] | a modem power measurement under the request pattern |
| 23 | The research fits the vehicle budget | the development boards, the missing sensors and the bench equipment are not costed (TBD in [`../docs/PROCUREMENT.md`](../docs/PROCUREMENT.md)) | quotes for the lines of [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md) section 2 |
| 24 | Worst-case execution time of the recorder on the telemetry unit | not ported; host maxima only | E4 on the target, then a WCET argument |
| 25 | Distribution-free coverage or false-alarm guarantees | windows within an episode are dependent, and acquisition is adaptive | not claimed; would need per-episode calibration with the deployed policy |

## 4. Where each number comes from

- The final evaluation: [`generated/final/summary.md`](generated/final/summary.md), from pre-registration commit `9aefb99`, run once ([`PREREGISTRATION.md`](PREREGISTRATION.md)).
- The development pilot, which chose the protocol and is not evidence for it: [`RESULTS.md`](RESULTS.md) sections 1 and 2.
- The identifiability analysis: [`generated/identifiability.md`](generated/identifiability.md).
- The demonstration, three episodes through the frozen configuration: [`generated/demo/demo.md`](generated/demo/demo.md). Episode A, a timing error, was missed: the drive-on edge after the onset was too weak to test it, and the audit budget was used up before the sharp drive-off edge.
