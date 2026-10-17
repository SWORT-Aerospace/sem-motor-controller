# Contributing

How the team works in this repository. Commands and tools are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## 1. Picking up work

1. Choose an open task in [README section H](README.md#h-priorities) and put your name in its "Person responsible" column in your first pull request.
2. Start from the folder guide listed for that kind of task in [README section G](README.md#g-where-to-work). Each folder has a `README.md` describing its files, inputs, outputs and tests.
3. If the task needs information from the vehicle (battery, motor, connectors, CAN bus), check [`docs/INPUT_SHEET.md`](docs/INPUT_SHEET.md) first: most hardware work is blocked on those inputs.

## 2. Branches and pull requests

* Work on a branch named after the task (for example `hw/battery-ratings` or `fw/stm32g4-adc`); `main` changes only through reviewed pull requests.
* Keep a pull request to one topic. Say in its description what changed, why, how it was tested, and what it does not cover.
* GitHub Actions must be green on the pull request before it is merged. A change is "fixed" only when that run has passed.

## 3. Who reviews what

| Area | Reviewer (role, from [`docs/ICD.md`](docs/ICD.md)) |
|---|---|
| Controller behaviour, state machine, limits, CAN protocol (`firmware/`, `protocol/`) | controls lead |
| Schematic, part selection, BOM and pricing (`hardware/`, `tools/gen_kicad_schematic.py`) | hardware lead |
| Telemetry unit, log format, live summary (`host/telematics/`, `docs/TELEMETRY_*`) | telematics engineer |
| Pit database and analysis (`host/pit/`) | pit software |
| Vehicle harness, safety loop, battery isolation | vehicle team |

A change to an interface between two of these areas needs both owners' approval and follows [`docs/INTEGRATION_GUIDE.md`](docs/INTEGRATION_GUIDE.md) section 6.

## 4. Rules for engineering data

* **Every value has a source.** A datasheet value carries the document, revision and page; a measurement carries the date, setup and instrument; a team decision carries who decided. Enter vehicle values in `config/` and the input sheet, not in code.
* **Unknown stays unknown.** Use `null` in configuration and TBD in tables. Never enter zero or a guess to make something run; the synthetic configuration exists for simulation only and must never be copied into a vehicle configuration.
* **Generated files are not edited by hand.** Edit the source (the YAML file or the generator) and regenerate ([`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) section 3).
* **Decisions are written down.** A choice that others depend on gets an entry in [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md): requirement, evidence, choice, implementation, test.
* **The CSIA evaluation files are frozen.** Files listed in `docs/csia/V2_FREEZE.json` are checked by hash; a change needs a new freeze and a new evaluation set.

## 5. Hardware and safety

* Nothing is ordered without a dated quote in [`hardware/bom/procurement.yaml`](hardware/bom/procurement.yaml) and the team lead's agreement.
* No board is energised before the design review ([`hardware/review/REVIEW_CHECKLIST.md`](hardware/review/REVIEW_CHECKLIST.md)) is signed. Energised tests follow the staged bring-up checklist and are carried out by qualified members under the lab's safety procedure, never alone.
* The motor controller's protection and the driver's wired controls must work without CAN, the telemetry unit, LTE or the pit. A change that makes them depend on any of these is not accepted.

## 6. Writing documentation

* Say whether something runs on the host, is proposed, or has been tested on hardware.
* Units are SI unless stated; give the units of every number.
* Current documents contain no em dashes (a test checks this). Superseded documents are moved to [`docs/archive/`](docs/archive/) and listed in [`docs/README.md`](docs/README.md), not rewritten.
