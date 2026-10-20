# EXP-03: shared power disturbance versus independent losses

Status: **NOT RUN** (physical). Simulated pre-check: PASS (`tools/run_vehicle_experiment.py --only EXP-03`).

## Claim and hypothesis

*Claim.* When several sources lose admissible evidence together, the analysis reports the shared paths they have in
common and calls a common cause **SUPPORTED only with direct evidence of a disturbance on one of those paths** (a
power reset cause, a bus error status, a session that ended without its final record, counted log drops). Without such
evidence it stays AMBIGUOUS between a common cause and independent causes. Simultaneity alone is never a common cause.

*Hypothesis.* A dip on the unit's supply produces a reset cause and an incomplete session, which the analysis finds;
two unrelated losses at the same time produce neither. A source that kept working excludes only a *complete* loss of
the paths it shares: a partial fault, differing reset thresholds, buffering or a disturbance briefer than a sample
period can affect sources on one path differently, so a partial or brief disturbance stays a candidate unless direct
evidence decides.

## What is compared

Family C (`host/assurance/verdicts.common_cause`): onsets of lost admissible evidence from two or more sources,
grouped within 1 s of the first onset of an event (a chain of onsets each close to the last does not merge widely
separated losses into one "simultaneous" event); their shared paths from the schema
(`telematics/schema/telemetry_schema.yaml`, `sources.depends_on` and `shared_paths`, each path with the errors it can
carry in common); direct disturbance evidence from the log (BOOT reset cause, TEMP status, COUNTERS2 drop counters, a
missing final counters record). Each shared path is judged under two fault models
(`verdicts.FAULT_MODELS`):

* *complete loss:* every source through the path loses its evidence for the event. A source outside the event that
  delivered admissible evidence continuously from one window before the event to one window after it (no break
  longer than twice its expected period) contradicts this model for its paths, and the receipt names that source.
* *partial or brief disturbance:* some sources on the path affected and not others. Nothing in the loss pattern
  excludes it; it stays a candidate.

A source that broke off or recovered within that span excludes nothing.

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
| GNSS outage and wheel disconnect together | one AMBIGUOUS event: complete loss of the shared paths (`ground:unit_ground`, `power:unit_supply`, `unit:recorder`) excluded by sources that kept delivering throughout (the battery monitor, the IMU, the temperatures); a partial or brief disturbance of those paths and independent causes kept as candidates |

## Supports, falsifies, inapplicable

* **Supports:** every reset dip gives a SUPPORTED event on the unit's supply or recorder path with the reset cause in
  its basis; every dip without a reset that still drops evidence gives an event with the drop counters, or an
  AMBIGUOUS verdict that keeps the partial disturbance of the supply path among its candidates; every independent-loss
  run gives AMBIGUOUS, never SUPPORTED.
* **Falsifies:** a SUPPORTED common cause in an independent-loss run; a reset dip with no reported event; an event whose
  basis cites a disturbance on a path the affected sources do not share; a partial disturbance excluded because one
  source kept working; a loss excluded on the evidence of a source that itself broke off or recovered.
* **Inapplicable:** a dip so short that no source lost evidence (nothing to explain); a run in which the scope did not
  trigger (no ground truth).

## Data to record

Log, database, review, scope traces, the operator's timeline, the run sheet. Known gap: the schema's power tree is the
bench's (USB); the vehicle supply's paths are added when its DC-DC and protection are chosen (T-VEH-PWR,
[`docs/HARDWARE_OPEN_ITEMS.md`](../../docs/HARDWARE_OPEN_ITEMS.md)).
