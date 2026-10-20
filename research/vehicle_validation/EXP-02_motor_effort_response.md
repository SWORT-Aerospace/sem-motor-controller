# EXP-02: motor effort versus mechanical response

Status: **NOT RUN** (physical). Simulated pre-check: PASS with one limitation (`tools/run_vehicle_experiment.py --only
EXP-02`).

## Claim and hypothesis

*Claim.* While propulsion power is applied and the vehicle moves, a deceleration stronger than coasting is reported as
an observed inconsistency of effort and response (A1), **without a fault label and without picking a cause**; the IMU
and wheel-acceleration relation (B4) then tells a real load (both agree on the deceleration) from an IMU error (they
disagree).

*Hypothesis.* A real extra load slows the vehicle in every speed source and in the IMU alike; an IMU offset appears
in the IMU only.

## Relations and contexts

| Relation | Claim | Valid context | Tolerance (PROVISIONAL) |
|---|---|---|---|
| A1 | electrical effort is accompanied by a mechanical response | moving above 1 m/s (LAUNCH, CRUISE, COAST, UNKNOWN), power >= 50 W | deceleration no stronger than the coast-down deceleration + 0.2 m/s^2; needs `vehicle.coast_decel_mps2` |
| B4 | the IMU mean agrees with the wheel-speed derivative over the same window | moving above 1 m/s | 0.3 m/s^2 + 0.5 m/s^2 for the unknown grade |
| A2 | an acceleration is accompanied by electrical effort | moving | above 0.3 m/s^2 with less than 50 W |

`vehicle.coast_decel_mps2` is a parameter, UNSUPPORTED until this protocol's coast-down stage gives it.

## Independent ground truth

* **Coast-down deceleration:** timed coast-down runs on a flat, measured straight, both directions, speed from light
  gates at known spacing (not from the unit). Gives `vehicle.coast_decel_mps2` with its spread.
* **Known extra load:** a drag applied by the vehicle team that does not touch the propulsion path, for example a
  towed weight on a measured slope or a pad pressed with a measured force (force gauge); the force and the times it
  was applied are written down. Whether such a load is acceptable is the vehicle team's decision.
* **Known IMU error:** the unit mounted on a wedge of known angle (inclinometer reading recorded): the longitudinal
  axis then reads g x sin(angle) extra. No change to the vehicle.
* **Electrical effort:** the controller's own V and I are the evidence under test; an independent meter (a clamp
  meter or the event's joulemeter) on the same leads gives a check of their scale.

## Setup and procedure

*Bench.* Not applicable to A1 (it needs motion); B4 can be checked with the unit on a tilting plate and a generator on a
wheel channel at a constant rate: B4 CONSISTENT flat, INCONSISTENT tilted by 7 degrees (1.2 m/s^2).

*Vehicle (after T-VEH-PWR, T-CTRL-IF and the coast-down stage).*

1. Coast-down stage: at least five runs each way; the parameter and its spread go on the run sheet.
2. Nominal cruise and accelerations: expect A1 and B4 CONSISTENT or INAPPLICABLE, never INCONSISTENT.
3. Known load at cruise power: expect A1 INCONSISTENT and B4 CONSISTENT in the load window.
4. Unit tilted on the wedge: expect B4 INCONSISTENT; A1 only if the cruise power is above the effort floor.

## Expected signature (from the simulated pre-check)

| Case | Signature |
|---|---|
| real drag (150 N, 5 s) | A1 INCONSISTENT throughout the drag; B4 CONSISTENT; A1's conclusion AMBIGUOUS with "higher load" and "IMU mounting or offset" among its candidates |
| IMU offset (1.2 m/s^2, 10 s) | B4 INCONSISTENT throughout; no inconsistency outside the window (2 s settling) |
| limitation | at the simulated cruise power (about 33 W, below the 50 W floor) A1 is INAPPLICABLE: only B4 sees the IMU offset |

## Supports, falsifies, inapplicable

* **Supports:** load runs give A1 INCONSISTENT with B4 CONSISTENT; tilt runs give B4 INCONSISTENT; nominal runs give
  neither; no statement names a fault.
* **Falsifies:** A1 INCONSISTENT in nominal runs whose ground truth shows no extra load; B4 INCONSISTENT under a real
  load with a level unit; a load run in which A1 stays CONSISTENT although the measured deceleration exceeds the
  coast-down value by more than the tolerance.
* **Inapplicable:** power below the effort floor; speed below 1 m/s; grade not known to be within the 0.5 m/s^2
  allowance (about 3 degrees); controller data not admissible (stale, unverified).

## Data to record

Log, database, evidence review with the coast-down parameter and its source, ground-truth times, forces and angles,
the run sheet. Boundary: the unit only listens; the load is applied by the vehicle team, never through the motor
controller.
