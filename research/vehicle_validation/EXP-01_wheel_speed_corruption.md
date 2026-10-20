# EXP-01: wheel-speed corruption versus a real slowdown

Status: **NOT RUN** (physical). Simulated pre-check: PASS for its three variants, wheel corruption, shared scaling
error and real slowdown (`tools/run_vehicle_experiment.py --only EXP-01`). The first physical step is the bench stage
below, after the minimal bench ([`telematics/firmware/BENCH_MINIMAL.md`](../../telematics/firmware/BENCH_MINIMAL.md)).

## Claim and hypothesis

*Claim.* When one wheel's speed evidence is wrong (a wrong circumference or pulses per revolution, a lost or extra
magnet, edges lost on that channel), the analysis reports a disagreement and a **conditional localization to that
wheel's evidence path**: conditional on the stated assumption that its two witnesses share no timing or value error,
with every dependency they do share listed, and naming neither a fault nor a cause. When both wheels carry the same
scaling error, it does **not** localize the disagreement to the correct GNSS path. When the vehicle really slows down,
it reports **no inconsistency** at all.

*Hypothesis.* A corrupted wheel path disagrees with two witnesses from sensors distinct from it (GNSS speed and the
other wheel on a straight) while those two agree; a real slowdown moves every speed source together. Distinct sensors
are not independent against every fault: two witnesses that agree because they share an error (both wheels through
one circumference parameter, or one acquisition path's timing) make the correct third measurement the odd one out, so
the analysis keeps the shared error as a candidate, first when the witnesses share a parameter.

## Relations and contexts

| Relation | Claim | Valid context | Tolerance (PROVISIONAL) |
|---|---|---|---|
| B1:<ch> | wheel speed agrees with GNSS speed | CRUISE | max(5 %, 0.3 m/s) + GNSS speed accuracy |
| B3:l-r | left and right wheel agree on a straight | CRUISE, \|yaw rate\| <= 0.05 rad/s | max(5 %, 0.2 m/s) |
| B2:<ch> | motor speed through the drivetrain agrees with the wheel | CRUISE, LAUNCH; not while a freewheel may overrun | max(5 %, 0.3 m/s); needs gear ratio, circumference, freewheel |
| localization (conditional) | the subject disagrees with two mutually agreeing witnesses from distinct sensors; the assumptions (no common timing or value error of the witnesses through each path they share) are listed | as its relations | none of its own |

## Independent ground truth

* **Distance:** a tape-measured straight of at least 100 m with marked start and end (or surveyed markers), crossed at
  steady speed; the true average speed from two light gates (or a video with a visible clock) at the markers. This
  does not pass through the unit's Hall inputs or its GNSS.
* **Circumference:** a roll-out of the wheel under load (ten turns on the floor, measured), recorded with its
  uncertainty. The value the import uses is written on the run sheet.
* **Which path was corrupted:** the operator's record of what was done (below), never inferred from the result.

The GNSS used as a witness is not ground truth here: it is under test as a witness. If a reference GNSS (RTK) is
available it is ground truth only if its antenna and receiver are separate from the unit's.

## Setup and procedure

*Bench (first, after the minimal bench M0 to M4).* Two signal generators on wheel_0 and wheel_1 at a known ratio (for example 40 Hz and 34 Hz,
15 % apart), the third channel idle. B3 must report INCONSISTENT for the pair; with no GNSS on the target (T-GNSS)
there is no third witness, so localization must **not** occur. Then both generators at the same rate: B3 CONSISTENT.

*Vehicle (after the bench stage, when T-VEH-PWR and T-GNSS are closed).* Runs on the measured straight, each in both
directions:

1. Nominal: correct circumference and magnets. Expect no inconsistency.
2. Corruption by parameter: import the same log a second time with one wheel's circumference set 15 % low
   (`tools/telematics_import.py --wheel-circumference`). No physical change. Expect B1 and B3 INCONSISTENT for that
   wheel and a conditional localization to its evidence path.
   2b. Shared scaling: import it a third time with the circumference 15 % low for both wheels. Expect B1 INCONSISTENT
   for both wheels, B3 CONSISTENT, no localization to a wheel, and a conclusion about GNSS that says the evidence does
   not separate a shared circumference error from an error on the GNSS path, the shared circumference first among its
   candidates.
3. Corruption by hardware, if the vehicle team agrees: one extra magnet on one wheel (a 1/ppr rate error). Same
   expectation as 2.
4. Real slowdown: the driver coasts or brakes from cruise to about 60 % of cruise speed and holds it. Expect no
   inconsistency and no localization.

## Expected signature (from the simulated pre-check)

| Case | Signature |
|---|---|
| corruption | B1:<ch> and B3 INCONSISTENT for most of the steady part; B1 of the other wheel CONSISTENT; a conditional localization AMBIGUOUS on `wheel.<ch>.speed` only, its assumptions listed; candidates name the circumference, magnets, wiring, slip |
| shared scaling error (both wheels' circumference 15 % low) | B1 INCONSISTENT for both wheels, B3 CONSISTENT; no localization to a wheel; the conclusion about `gnss.speed` states that the evidence does not separate a common value error of the two wheels through `wheel.circumference_m` from an error on the GNSS path, and lists the shared circumference first |
| real slowdown | no relation INCONSISTENT; B1 evaluated (CONSISTENT) at the lower speed, not left inapplicable throughout |

## Supports, falsifies, inapplicable

* **Supports** the claim: every corruption run gives a conditional localization to the corrupted wheel only, every
  shared-scaling import keeps the shared circumference ahead of GNSS, and every slowdown run has no inconsistency, in
  both directions, with the ground-truth speed within the tolerances' assumptions.
* **Falsifies** it: a localization to a wheel that was not corrupted; a localization to GNSS that does not name the
  shared circumference first when both wheels were scaled; no inconsistency for a 15 % corruption in CRUISE; any
  inconsistency in a slowdown run whose ground truth shows all sensors consistent; any statement that names a fault
  or calls a cause established.
* **Inapplicable:** no CRUISE context in the run (too short, cornering, GNSS without a fix); a light-gate failure; a
  run where the driver could not hold speed. Recorded as INAPPLICABLE with the reason.

## Data to record

The unit's log (dump), the pit database after import, the evidence review (`tools/run_evidence_review.py` with the
parameters and their sources), the ground-truth times and distances, the circumference used, photos of the magnets,
and the run sheet. Boundary: the unit only listens; nothing in this protocol is sent to the motor controller.
