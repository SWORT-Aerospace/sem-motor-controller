# CSIA held-out evaluation: results and conclusions (synthetic, shadow mode)

**Status: SYNTHETIC EVIDENCE ONLY. No vehicle-validation claim.** CSIA remains in shadow mode (ADR-0008). Protocol: [`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md). Pre-registered results: [`../generated/csia_evaluation_synthetic.md`](../generated/csia_evaluation_synthetic.md). Exploratory post-hoc analysis: [`../generated/csia_posthoc_synthetic.md`](../generated/csia_posthoc_synthetic.md).

## 1. What was run
* **Freeze.** The adapter, the development generator, the baselines and the harness were hash-frozen in commit `46ef5d8` *before* the held-out set was run. The harness checked the hashes at run time: no violation.
* **Held-out set.** 94 unseen scenarios: 24 fault-free and 70 with one fault each, across 14 fault kinds, 6 of which (by kind or variant) were absent from development. This gives 5.80 h of operation outside fault windows.
* **Monitors.** Each was run once: B1, the V0–V3v ablation, the frozen CSIA adapter, TrustCore thresholding, and B1+CSIA.

## 2. Pre-registered results (held-out set)

| monitor | false-alarm episodes / h | false attributions / h | missed / 70 | correctly attributed | misattributed | median detection latency s |
|---|---|---|---|---|---|---|
| B1 range/freshness | 144.2 | 144.2 | 63 | 7 | 17 | 0.1 |
| V0 naive residuals, no gates | 380.4 | 0 | 45 | – | – | 1.5 |
| V1 naive + gates | 7.2 | 0 | 22 | – | – | 7.4 |
| V2 calibrated, no gates | 379.7 | 0 | 45 | – | – | 5.9 |
| V3 calibrated + gates | **0** (95 % upper 0.52) | 0 | 18 | – | – | 6.0 |
| V3v + majority vote | **0** (95 % upper 0.52) | 0 | 18 | 35 | **0** | 6.0 |
| **CSIA adapter (frozen)** | **19.7** | 2.4 | 16 | **48** | 9 | 4.2 |
| TrustCore threshold | 73.5 | 96.7 | 15 | 39 | 17 | 5.3 |
| B1 + CSIA | 163.8 | 146.6 | 11 | 53 | 23 | 1.0 |

## 3. Findings
1. **Gating carries most of the benefit.** Adding the regime gates (slip, freewheel, yaw, GNSS quality, slew) cut false alarms from ~380/h to 7/h with naive residuals, and to 0/h with calibrated residuals. The calibrated residual design alone, without gates, did not help (V2 ≈ V0).
2. **The frozen CSIA adapter does not generalise cleanly to the held-out conditions.** It raised 19.7 false-alarm episodes per hour, mostly on the power-balance relationship (53 of 114 episodes) and on GNSS pairs. It also misattributed 9 faults: current drift was blamed on the rotor in 4 of 5 cases, intermittent wheel dropout on the IMU in 3 of 5.
3. **The difference from V3v is the debounce, not the attribution logic** (post-hoc, exploratory). With the same 3-tick debounce, CSIA had 0 false alarms, 47 correct attributions and 6 misattributions. Without it, V3v reproduced CSIA's 114 false-alarm episodes exactly. CSIA's corroboration and auxiliary-input logic therefore buys about 12 extra correct attributions at the cost of about 6 misattributions relative to a plain majority vote.
4. **The TrustCore belief output is not a usable detector here.** Thresholding the beliefs on the development data produced 73 false alarms per hour and 17 misattributions on held-out data.
5. **Observability limits are real and reported.** No relationship-based method detected rotor scale errors of 3–12 % or dropped rotor samples; the rotor is observable only while driving through the freewheel (median 65 % of a stuck-rotor fault window was unobservable). DC-meter gain errors of 10–45 % were detected in 1 of 5 cases, because the power-balance uncertainty (8 % + 4 W) is wide. Dropped rotor samples are caught by the freshness channel (B1), which is why B1+CSIA has the fewest misses.
6. **B1 alone is noisy on GNSS.** Its range check flags negative GNSS speeds when the fix is degraded at low speed.

## 4. Consequences
* The ADR-0008 evidence gate is **not** met and cannot be met with synthetic data. CSIA stays in shadow mode, and `restriction_permitted()` stays False.
* For the paper, the defensible claim is narrow: regime gating plus calibrated residuals removes the nuisance alarms of a naive residual monitor. CSIA-style corroborated attribution attributes more faults than a majority vote, but with a misattribution cost that has to be fixed and re-measured on a **new** held-out set. Persistence filtering is required.
* Candidate changes for the next development iteration (none applied):
  * persistence filtering on adapter output;
  * a power-balance variance model that covers hills, standing starts and stops;
  * auxiliary-input handling in E6, so that current drift is not blamed on the rotor;
  * a rotor-scale observability study.
  * Each needs a new freeze and a new held-out set.

## 5. Which component produced which output (v0.3 note; nothing re-run, nothing re-tuned)
The held-out numbers in §2 are the frozen, pre-registered results. They are unchanged. Finding 3 (the debounce) is **post-hoc and exploratory**; it was found after the pre-registered run and is not a pre-registered result.

| Output that was scored | Produced by | What the evidence shows about that component |
|---|---|---|
| residual value per relationship | **residual design** (naive vs calibrated: yaw, centreline, time alignment, losses, grade) | without gates, calibration changed nothing (V0 380.4/h vs V2 379.7/h) |
| which relationships are evaluated in a tick | **validity gates** (slip, freewheel, yaw, GNSS quality, slew) | the largest effect: 380 → 7.2/h (naive) and 380 → 0/h (calibrated) |
| alarm persistence | **debounce** in the monitor wrapper (3 ticks in V0–V3v; none in the frozen CSIA adapter path) | post-hoc: accounts for the whole false-alarm difference between V3v and the adapter |
| attribution (suspect / ambiguous) | **corroboration logic** of the adapter (`corroborated`, `recently_failed`, the auxiliary-input rule), compared with a plain majority vote (V3v) | adapter 48 correct / 9 misattributed; majority vote 35 / 0; post-hoc with the same debounce 47 / 6 |
| trust (Beta belief per node) | **TrustCore** (pinned `csia-trust-layer`) | used only by the "TrustCore threshold" monitor: 73.5 false alarms/h, 17 misattributions. The adapter's detection and attribution outputs do **not** use the belief. |

**No improvement in this table is attributed to TrustCore.** No ablation has shown that TrustCore contributes to the adapter's detection or attribution, and the only TrustCore-based detector tested was the worst monitor. Any future claim of a TrustCore contribution needs an ablation that switches the belief in and out of an output that actually uses it.

## 6. Plan for the next evaluation (NOT run, NOT tuned in v0.3)
1. Develop the next detector version on the **development** set only (candidate changes in §4).
2. Freeze, with hashes recorded in a commit before any new held-out data exists:
   * the detector code;
   * the scoring procedure: debounce and persistence handling, the outage scoring rule, episode definitions, eligibility windows;
   * the monitor list, including an ablation that switches each component (residual design, gates, debounce, corroboration, TrustCore belief where used) in and out.
3. Commit a hash of the new held-out seed list and the generator parameters before generating the data. The set must use new seeds and new magnitudes, onsets and conditions, not the v0.2 held-out set (now partly seen through §3's post-hoc analysis).
4. Run once and report every pre-registered metric, including failures. Anything examined after the run is labelled post-hoc.
5. No vehicle claim from synthetic data. Vehicle data collection starts only after a sensor set and logging exist (`docs/COMBINED_ARCHITECTURE.md`); CSIA stays in shadow mode.
