# Research: budgeted evidence acquisition for timing-aware diagnosis

A research extension of the telemetry project, kept apart from the vehicle work. It asks whether a pit-side diagnostic can tell a battery-current measurement bias, a timing error between the electrical and motor records, and a larger opposing load apart, using the records the telemetry chain already keeps plus a few bounded requests for more. It must also say when it cannot.

**Status.** Host simulation only. Nothing here runs on the vehicle, sends anything to it, or changes propulsion, braking, protection thresholds or control-loop timing. No result comes from hardware. The CSIA core used for comparison is licensed for evaluation only ([`PROTOCOL.md`](PROTOCOL.md) section 3).

## Documents

| Document | Contents |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | Research question, hypotheses, baseline at the start, electrical measurement boundary, decision gates, data separation, comparisons, reporting |
| [`PRIOR_ART.md`](PRIOR_ART.md) | Prior work with the access level of each source, the baselines it implies and the claims it rules out |
| [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) | Gate 1: which hypotheses the available evidence can separate, under which conditions, and with which additional records |
| [`HARNESS.md`](HARNESS.md) | The causal evaluation harness: what is simulated, every assumption, the causality checks |
| [`DIAGNOSIS.md`](DIAGNOSIS.md) | The reference diagnosis, the actions and their costs, schedulers A to F |
| [`RECORDER.md`](RECORDER.md) | The proposed telemetry-unit recorder: interface, versioned wire format, tests, host timing |
| [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md) | The experiments that would test the assumptions, the equipment, and the next physical action |

## Steps

| Step | Result | Status |
|---|---|---|
| 1. Baseline and measurement boundary | [`PROTOCOL.md`](PROTOCOL.md) sections 3 and 4 | done |
| 2. Prior art | [`PRIOR_ART.md`](PRIOR_ART.md); most named sources could be read only as summaries | done, with access gaps listed |
| 3. Identifiability (gate 1) | [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) | done; passed conditionally |
| 4. Causal evaluation harness | [`HARNESS.md`](HARNESS.md) | done |
| 5. Diagnosis, actions, schedulers, baselines | [`DIAGNOSIS.md`](DIAGNOSIS.md) | done |
| 6. Development pilot, pre-registration, final evaluation | see the results section below | in progress |
| 7. Recorder interface, demonstration, physical validation plan | [`RECORDER.md`](RECORDER.md), [`PHYSICAL_VALIDATION.md`](PHYSICAL_VALIDATION.md) | in progress |

## Layout and commands

```
research/
  bea/records.py          measurement records with their timing kept explicit
  bea/relations.py        relationships, signatures, nuisance, hypotheses, bounded least squares, fit
  bea/identifiability.py  separation distances on synthetic truth (gate 1)
  bea/harness.py          truth plant, sensors, transport and clocks, faults, vehicle log, pit access
  bea/diagnosis.py        reference set-valued diagnosis from received records
  bea/episode.py          one scheduler and one engine on one episode, in simulated time
  bea/schedulers.py       actions and schedulers A to F (and the ablation of F)
  bea/baselines.py        aligned residual monitor, multiple-hypothesis baseline, frozen R3v and CSIA2
  bea/scoring.py          evaluator-only comparison with the labels
  recorder/               portable C recorder for the telemetry unit, with host tests
  run_identifiability.py  gate 1 tables
  run_pilot.py            calibration and development pilot
  run_final.py            the pre-registered final evaluation (run once)
  run_demo.py             three-episode demonstration
  generated/              generated results (do not edit)
tests/research/           tests of all of the above
```

```sh
python3 -m pytest -q tests/research                        # a few minutes
python3 research/run_identifiability.py --check            # recomputes gate 1 and compares (several minutes)
python3 research/run_demo.py                               # the demonstration
```

The code uses only numpy, the repository's vehicle and powertrain models (`models/vehicle/`) and, for the comparison, the frozen CSIA adapters (`host/csia_adapter/`, unchanged).
