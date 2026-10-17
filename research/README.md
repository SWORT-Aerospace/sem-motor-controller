# Research: budgeted evidence acquisition for timing-aware diagnosis

A research extension of the telemetry project, kept apart from the vehicle work. It asks whether a pit-side diagnostic can tell a battery-current measurement bias, a timing error between the electrical and motor records, and a larger opposing load apart, using the records the telemetry chain already keeps plus a few bounded requests for more. It must also say when it cannot.

**Status.** Host simulation only. Nothing here runs on the vehicle, sends anything to it, or changes propulsion, braking, protection thresholds or control-loop timing. No result comes from hardware. The CSIA core used for comparison is licensed for evaluation only ([`PROTOCOL.md`](PROTOCOL.md) section 3).

## Documents

| Document | Contents |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | Research question, hypotheses, baseline at the start, electrical measurement boundary, decision gates, data separation, comparisons, reporting |
| [`PRIOR_ART.md`](PRIOR_ART.md) | Prior work with the access level of each source, the baselines it implies and the claims it rules out |
| [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) | Gate 1: which hypotheses the available evidence can separate, under which conditions, and with which additional records |
| [`generated/identifiability.md`](generated/identifiability.md) | Generated numbers behind the identifiability analysis |

## Steps

| Step | Result | Status |
|---|---|---|
| 1. Baseline and measurement boundary | [`PROTOCOL.md`](PROTOCOL.md) sections 3 and 4 | done |
| 2. Prior art | [`PRIOR_ART.md`](PRIOR_ART.md); most named sources could be read only as summaries | done, with access gaps listed |
| 3. Identifiability (gate 1) | [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) | done |
| 4. Causal evaluation harness | | not started |
| 5. Diagnostic reference, actions, schedulers, baselines | | not started |
| 6. Development pilot, pre-registration, final evaluation | | not started |
| 7. Embedded recorder interface, demonstration, physical validation plan | | not started |

## Layout and commands

```
research/
  bea/records.py           measurement records with their timing kept explicit
  bea/identifiability.py   signature model, bounded least squares, separation distances
  run_identifiability.py   writes generated/identifiability.{json,md}
  generated/               generated results (do not edit)
tests/research/            tests of the above
```

```sh
python3 -m pytest -q tests/research               # about a minute
python3 research/run_identifiability.py           # rewrites generated/ (several minutes)
python3 research/run_identifiability.py --check   # recomputes and compares with the committed results
```

The code uses only numpy and the repository's own vehicle and powertrain models (`models/vehicle/`).
