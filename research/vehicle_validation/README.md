# Vehicle validation protocols (telematics evidence platform)

These protocols say how the telematics unit's evidence analysis will be tested on the bench and on the vehicle,
what independent ground truth each test needs, and what result would support, falsify or not apply to each claim.
**No protocol here has been run physically. No result in this folder is a bench or vehicle result.**

The analysis under test is host software: evidence states (`host/telematics/evidence.py`), stream timing
(`timing.py`), lineage (`lineage.py`), vehicle context (`context.py`), the cross-domain witness relations
(`host/assurance/witnesses.py`), advisory conclusions and receipts (`verdicts.py`, `review.py`). The motor controller
belongs to another team and stays receive-only from this system: no protocol commands propulsion, changes a
controller setting or puts a frame on the vehicle bus.

| Protocol | Question | Relations | Simulated pre-check | Physical status |
|---|---|---|---|---|
| [EXP-01](EXP-01_wheel_speed_corruption.md) | Can the evidence tell a corrupted wheel-speed path from a real slowdown? | B1, B2, B3, localization | PASS (SIMULATED) | NOT RUN |
| [EXP-02](EXP-02_motor_effort_response.md) | Is electrical effort followed by the expected mechanical response, and can a real load be told from an IMU error? | A1, B4 | PASS (SIMULATED), one limitation | NOT RUN |
| [EXP-03](EXP-03_shared_power_disturbance.md) | Is a simultaneous loss of evidence a shared-path event or independent causes? | family C (common cause) | PASS (SIMULATED) | NOT RUN |
| [EXP-04](EXP-04_timing_degradation.md) | Does degraded timing make values TIMING_UNCERTAIN instead of producing false inconsistencies? | timing, all relations | PASS (SIMULATED), one limitation | NOT RUN |

## How each protocol is written

1. **Claim and hypothesis.** One sentence each, in terms of the relations and verdicts the software produces.
2. **Independent ground truth.** A measurement that does not pass through the unit's own sensors or through the
   witness being tested (a light gate, a tape-measured distance, an oscilloscope on a rail, a test generator's own
   log). If the ground truth shares a path with the evidence, the protocol says so and treats it as a caveat.
3. **Setup and procedure,** bench first. A vehicle stage only after the bench stage, with the vehicle team operating
   the vehicle and the unit powered as T-VEH-PWR allows (today: not at all on the vehicle).
4. **Expected signature,** taken from the simulated pre-check, and the window in which it should appear.
5. **Supports / falsifies / inapplicable.** Stated before the run. A run outside the protocol's conditions is
   inapplicable, not a pass.
6. **Run sheet.** [`RUN_SHEET.md`](RUN_SHEET.md), filled in during the run, kept with the log and the database in
   [`records/`](records/README.md) (its `README.md` says what goes there).

## Simulated pre-check

    python3 tools/run_vehicle_experiment.py --out build/vehicle_experiments

runs every protocol's variants on simulated drives in which the disturbance is known exactly (host simulation:
`host/telematics/sim_session.py`), through the same chain the vehicle data will take (log, import, evidence, review),
and checks each protocol's signature and falsifier. Its result is labelled SIMULATED. It shows that the host analysis
separates the cases the protocol needs; it does not show that the vehicle, its sensors or the firmware behave that
way. `tests/telematics/test_evidence_pipeline.py` runs it in CI.

Two rows are marked `limitation`: they pass when a known blind spot is reproduced (A1 cannot see an IMU offset at
cruise power; a constant CAN latency is not observable from the receive side, and a producer timestamp bounds it only with a stated clock relation and uncertainty bound). They are properties to fix, by
the interface or by another relation, not successes.

## Negative results

A run that falsifies a claim is kept: its run sheet, log, database and review stay in the record with the verdict
`FALSIFIED`, and the claim's label in [`docs/claims.yaml`](../../docs/claims.yaml) does not rise. Changing a tolerance,
a context threshold or a relation after seeing a result is a new protocol version with its reason, run again on new
data; the earlier result is not overwritten. A protocol that cannot be run as written (missing equipment, an
inapplicable context) is recorded as `INAPPLICABLE` with the reason, not as a pass.

## Claim labels

SIMULATED, HOST-TESTED, BENCH-TESTED, HIL-TESTED, VEHICLE-TESTED ([`docs/CLAIMS.md`](../../docs/CLAIMS.md)). A claim
rises to BENCH-TESTED or above only with a filled run sheet in `records/` that the claims check can find. Today every
claim from these protocols is SIMULATED.
