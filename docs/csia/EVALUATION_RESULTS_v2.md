# CSIA v2 evaluation: results and decision (synthetic, shadow mode)

**Status: SYNTHETIC EVIDENCE ONLY.** CSIA stays in shadow mode (ADR-0008); `restriction_permitted()` stays False. Protocol: [`EVALUATION_PROTOCOL_v2.md`](EVALUATION_PROTOCOL_v2.md). Pre-registered results: [`../generated/csia_v2_evaluation_synthetic.md`](../generated/csia_v2_evaluation_synthetic.md) (and `.json`). v1 results ([`EVALUATION_RESULTS.md`](EVALUATION_RESULTS.md)) are unchanged.

## 1. What was run

* Freeze: commit `b44e781` recorded the hashes of 12 files, the E6 model and every threshold in `V2_FREEZE.json` before any evaluation seed was generated. `--eval` verified the hashes at run time: no mismatch. No frozen file changed after the freeze (`tests/fault_injection/test_csia_v2_freeze.py`).
* Evaluation set, run once: 94 untouched scenarios (24 fault-free of 300 s, seeds 6000–6023; 14 fault kinds × 5 of 240 s, seeds 7000–7069), 5.78 h outside fault windows. Command: `python3 tools/run_csia_evaluation_v2.py --eval`, 191 s on a 4-core x86-64 host.

## 2. Results (evaluation set)

| monitor | FA episodes / h | false attributions / h | coverage | correctly attributed | misattributed | median latency s | median eligible-evidence latency s |
|---|---|---|---|---|---|---|---|
| B1 range / freshness | 36.2 | 36.2 | 7 % | 5 / 70 | 16 | 0.4 | 0.3 |
| R3 calibrated residuals + gates (detection only) | 1.0 | 0 | 80 % | – | 0 | 2.7 | 1.1 |
| **R3v** R3 + majority vote | **1.0** | **0** | 80 % | 34 / 70 | **0** | 2.7 | 1.1 |
| CSIA1 frozen v1 adapter | 35.7 | 32.9 | 80 % | 49 / 70 | 16 | 3.2 | 1.5 |
| CSIA2 v2 adapter | 1.0 | 0 | 80 % | **48 / 70** | 4 | 2.7 | 1.1 |
| TRUST2 TrustCore threshold | 53.5 | 56.5 | 84 % | 38 / 70 | 22 | 9.1 | 8.4 |
| B1 + CSIA2 | 37.2 | 36.2 | 87 % | 53 / 70 | 19 | 1.2 | 1.1 |

All monitors pass through the same 3-tick node-level debounce.

## 3. Findings

1. **The v2 power balance removes the v1 false alarms.** With the same attribution logic, CSIA1 had 35.7 false-alarm episodes per hour (193 of them on dc_meter/phase_current), CSIA2 has 1.0, the same as R3v. Coverage is unchanged (80 %). This supports the two corrections (time alignment, copper-loss term) on data neither was tuned on, within the limitation that the generator's loss structure matches the model's (protocol section 8).
2. **The adapter's attribution increment is not supported by the pre-registered rule.** CSIA2 attributes 14 more faults than the majority vote (48 against 34) but names a wrong cause in 4 more scenarios (4 against 0); the rule allows at most 1 more. **R3v is the recommended monitor.** CSIA2's wrong causes: front-left wheel dropout blamed on the IMU or the right wheel (2 of 5) and intermittent front-left wheel blamed on the IMU (2 of 5). R3v reports those as unattributed disagreements instead (median ambiguity 0.56 against 0.04).
3. **TrustCore beliefs are not a usable detector here** (53.5 FA/h, 22 misattributions). Its contribution is not supported.
4. **B1 is needed for dropped samples and is noisy on GNSS.** Rotor-sample dropout was never eligible for any relationship in 3 of 5 scenarios; only the freshness channel sees it, which is why B1 + CSIA2 has the highest coverage (87 %). B1's 209 GNSS episodes come from its range check on degraded fixes at low speed (also seen in v1); it needs a quality gate before it is shown to anyone.
5. **Observability limits.** Rotor faults are observable only while the freewheel transmits torque: stuck rotor detected in 3 of 5 (median 61 % of the window unobservable), rotor scale error in 1 of 5, none attributed.
6. **Runtime and memory (host CPython figures, not target figures).** 0.20 ms per tick for R3v, 0.36 ms for CSIA2; peak traced memory 340–500 KiB. The R3 figure (720 KiB) is higher than R3v's although the code is the same: the first residual monitor measured pays one-time allocations. CSIA runs pit-side or as replay shadow; no target-processor figure exists.

## 4. Decision and consequences

* Pit-side analysis uses **R3v** (calibrated residuals, the adapter's gates, majority-vote attribution, 3-tick persistence) plus B1's freshness channel, with B1's GNSS range check gated on fix quality before display. Unattributed disagreements are shown as such.
* The CSIA2 adapter stays in the repository as a shadow research component: its corroboration logic attributes more faults but its wrong-cause rate is not acceptable for a display that people act on.
* The E6 model must be refitted on bench data of the real motor and controller (R, switching and fixed losses) before any residual result is trusted on the vehicle.
* Candidate changes for a v3 (none applied; each needs a new freeze and a new untouched set): endpoint corroboration that excludes nodes with recent failures (the intermittent-wheel misattributions), a B1 GNSS quality gate, a rotor observability study.
* The vehicle gate (`VALIDATION_PLAN.md` section 6: ≥ 10 h of in-vehicle shadow data) is unaffected.
