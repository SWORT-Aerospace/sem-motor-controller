# EXP-04: timing degradation

Status: **NOT RUN** (physical). Simulated pre-check: PASS with one limitation (`tools/run_vehicle_experiment.py --only
EXP-04`).

## Claim and hypothesis

*Claim.* When controller frames arrive late, in bursts or after a stall, the stream timing records it and the values
whose sample time is no longer bounded become TIMING_UNCERTAIN for relations with a tighter tolerance: the result is
INSUFFICIENT_EVIDENCE, **never a false INCONSISTENT**.

*Hypothesis.* From the receive side, a stall shows as a late frame followed by a burst; its frames may have waited
since the last in-time frame (`timing.StreamTiming`, `Arrival.wait_bound_us`), and the pit widens their timestamp
bound by that much.

## What is compared

Per stream: late arrivals (more than 2 periods), bursts (less than a quarter period), wait-bounded frames, sequence
gaps, duplicates, reordering, ambiguous silences, jitter (`source_timing` table). Per relation: the inputs' timestamp
bounds against the relation's tolerance (250 ms; 600 ms for B4; 2 s for the thermal relation) and their mutual
alignment.

## Independent ground truth

* **Bench:** a CAN test generator (a USB-CAN adapter on an isolated bench bus with its own termination, never the
  vehicle bus) replaying a recorded or fixture broadcast with programmed stalls and delays. Its own transmit log with
  timestamps is the ground truth; a logic analyser on CAN_H/CAN_L gives the time each frame was on the wire.
* **Vehicle:** none. Delays are not injected on the vehicle: nothing in this system transmits on the vehicle bus, and
  the controller belongs to another team.

## Setup and procedure (bench only)

1. NUCLEO-U575ZI-Q with the receive-only CAN image (FDCAN1 in bus-monitoring mode), the transceiver, the isolated bench
   bus and the generator. Electrical checks E1 to E6 of `telematics/firmware/BENCH.md` first.
2. Nominal replay: expect no late arrival, burst or wait-bounded frame beyond the generator's own jitter.
3. Stalls of 0.2, 0.6 and 2 s (frames held and released together): expect one late arrival and a burst per stall,
   wait-bounded frames, and INSUFFICIENT_EVIDENCE for relations needing those values around the release.
4. A constant added delay of 0.3 s for 10 s: expect a late arrival at the start and a burst at the end; during the
   plateau the frames look regular (the limitation below).
5. Sequence faults (the generator skips, repeats and swaps counters): gaps, duplicates and reordering counted.

## Expected signature (from the simulated pre-check)

| Case | Signature |
|---|---|
| stall 0.6 s | `can:ctrl_motion`: 1 late arrival, about 60 burst frames, all wait-bounded; A1 and B2 INSUFFICIENT_EVIDENCE around the release; no INCONSISTENT |
| constant 0.3 s delay | 1 late arrival and a burst at the end; no INCONSISTENT at steady speed |
| limitation | during the plateau B2 is evaluated as CONSISTENT with values 0.3 s old (simulated data, whose assumed timestamp bounds are accepted): a constant latency is not observable from the receive side |

## Supports, falsifies, inapplicable

* **Supports:** every injected stall appears in the stream timing within one period of the generator's log and makes
  the affected values TIMING_UNCERTAIN; no stall or delay produces an INCONSISTENT verdict at steady state.
* **Falsifies:** an INCONSISTENT verdict caused by a stall or delay alone; a stall longer than two periods not seen as
  late; a burst frame treated as fresh by a relation with a tolerance below its wait bound.
* **Inapplicable:** a generator log without timestamps; a run in which the unit's own log dropped frames
  (`can_not_logged` or `log_dropped_queue` above zero): then the loss, not the timing, is under test.

## The limitation, and what would remove it

A constant added latency cannot be seen from the receive side: every frame arrives on time relative to the previous
one. A producer timestamp (the controller's own time in its frames) does not bound it by itself: it also needs a
stated relation between the controller's clock and the unit's (offset and drift, for example from a shared time
reference) with an uncertainty bound. A documented bound on the controller's sample-to-transmit delay would also do.
Without either, the sample age is unknown: on measured data the pit then marks the value TIMING_UNCERTAIN ("sample age
unknown") instead of using it, and only simulated data may carry an assumed bound. This is a request to the controller team
([`docs/CONTROLLER_INTERFACE_REQUEST.md`](../../docs/CONTROLLER_INTERFACE_REQUEST.md)), not something this unit can
add by transmitting.

## Data to record

Log, database, review, the generator's transmit log, the logic-analyser capture, the run sheet.
