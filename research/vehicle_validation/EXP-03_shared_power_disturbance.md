# EXP-03: shared power disturbance versus independent losses

Status: **NOT RUN** (physical). Simulated pre-check: PASS (`tools/run_vehicle_experiment.py --only EXP-03`).

## Claim and hypothesis

*Claim.* When several sources lose admissible evidence together, the analysis reports the shared paths they have in
common and calls a common cause **SUPPORTED only with direct evidence of a disturbance on one of those paths** (a
power reset cause, a bus error status, a session that ended without its final record, counted log drops). Without such
evidence it stays AMBIGUOUS between a common cause and independent causes. Simultaneity alone is never a common cause.

*Hypothesis.* A dip on the unit's supply produces a reset cause and an incomplete session, which the analysis finds;
two unrelated losses at the same time produce neither, and a source that kept working exonerates the paths it shares.

## What is compared

Family C (`host/assurance/verdicts.common_cause`): onsets of lost admissible evidence within 1 s of each other from two
or more sources; their shared paths from the schema (`telematics/schema/telemetry_schema.yaml`, `sources.depends_on`
and `shared_paths`); exoneration by any source on the same path that delivered fresh admissible evidence in the second
after the event; direct disturbance evidence from the log (BOOT reset cause, TEMP status, COUNTERS2 drop counters, a
missing final counters record).

## Independent ground truth

* **Supply disturbance:** a programmable bench supply (or a supply with a series switch) feeding the unit, its output
  recorded by an oscilloscope on the unit's input and on its 3.3 V rail, with the scope's time base and trigger written
  down. The dip depth and length are set, not inferred.
* **Independent losses:** the operator's record of what was disconnected and when (a wheel sensor plug pulled, the
  GNSS antenna covered), with a stopwatch or a video clock.

## Setup and procedure

*Bench only* until T-VEH-PWR is closed; this protocol never disturbs the vehicle's supply.

1. Unit on the bench supply; signal generator on wheel_0; IMU and one TMP117 on I2C1.
2. Supply dips of increasing depth and length until the unit resets (brown-out); five repetitions at the reset
   threshold and five just above it (no reset). Each dip's scope trace is kept.
3. Independent losses: pull the wheel_0 sensor plug and cover the GNSS antenna (when GNSS exists on the target) within
   the same second, without touching the supply. Five repetitions.
4. Import every session and run the evidence review.

## Expected signature (from the simulated pre-check)

| Case | Signature |
|---|---|
| unit power cut (0.5 s, brown-out reset) | one SUPPORTED shared-path event on `unit:recorder` at the cut: the session ended without a final counters record and the next session's reset cause is a power reset |
| GNSS outage and wheel disconnect together | one AMBIGUOUS event: no shared path remains a candidate (the paths are exonerated by sources that kept working, for example the battery monitor and the IMU) |

## Supports, falsifies, inapplicable

* **Supports:** every reset dip gives a SUPPORTED event on the unit's supply or recorder path with the reset cause in
  its basis; every dip without a reset that still drops evidence gives an event with the drop counters or an AMBIGUOUS
  verdict; every independent-loss run gives AMBIGUOUS, never SUPPORTED.
* **Falsifies:** a SUPPORTED common cause in an independent-loss run; a reset dip with no reported event; an event whose
  basis cites a disturbance on a path the affected sources do not share.
* **Inapplicable:** a dip so short that no source lost evidence (nothing to explain); a run in which the scope did not
  trigger (no ground truth).

## Data to record

Log, database, review, scope traces, the operator's timeline, the run sheet. Known gap: the schema's power tree is the
bench's (USB); the vehicle supply's paths are added when its DC-DC and protection are chosen (T-VEH-PWR,
[`docs/HARDWARE_OPEN_ITEMS.md`](../../docs/HARDWARE_OPEN_ITEMS.md)).
