# Contributing

How the team works in this repository. Commands and tools are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## 1. Picking up work

1. Choose the next open step on the critical path ([README section 6](README.md#6-next-steps-critical-path), in full in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)) and put your name in its "Person responsible" column in your first pull request.
2. Start from the folder guide for that kind of task ([`docs/README.md`](docs/README.md) lists them). Each folder has a `README.md` describing its files, inputs, outputs and tests. The suite a file belongs to (telematics, reference, deferred controller) is in [`docs/scope.yaml`](docs/scope.yaml).
3. If the task needs information from the controller team (signals, connector, bit rate), check [`docs/CONTROLLER_INTERFACE_REQUEST.md`](docs/CONTROLLER_INTERFACE_REQUEST.md); for vehicle facts (battery, wheels, mounting), [`docs/INPUT_SHEET.md`](docs/INPUT_SHEET.md).

## 2. Branches and pull requests

* Work on a branch named after the task (for example `tm/wheel-capture` or `pit/energy-report`); `main` changes only through reviewed pull requests.
* Keep a pull request to one topic. Say in its description what changed, why, how it was tested, and what it does not cover.
* GitHub Actions must be green on the pull request before it is merged (the `telematics` job never builds the controller; the `controller` job keeps the deferred work tested). A change is "fixed" only when that run has passed.

## 3. Who reviews what

| Area | Reviewer (role, from [`docs/ICD.md`](docs/ICD.md)) |
|---|---|
| Telematics firmware, log format, live summary, controller adapters (`telematics/`, `host/telematics/`, `docs/TELEMETRY_*`, `docs/ICD.md`) | telematics engineer |
| The interface with the controller team ([`docs/CONTROLLER_INTERFACE_REQUEST.md`](docs/CONTROLLER_INTERFACE_REQUEST.md)) | telematics engineer and the controller team |
| Telematics parts and budget (`hardware/telematics/`) | telematics engineer, team lead |
| Deferred controller development (`firmware/`, `hardware/`, the semmc fixture in `protocol/`) | controls lead, hardware lead |
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

* Nothing is ordered without a dated quote replacing the snapshot in [`hardware/telematics/bom.yaml`](hardware/telematics/bom.yaml) and the team lead's agreement.
* The telematics unit is connected to the vehicle's CAN bus only after the controller team agrees and the electrical checks of [`telematics/firmware/BENCH.md`](telematics/firmware/BENCH.md) section 7 have passed; it stays receive-only.
* No board is energised before the design review ([`hardware/review/REVIEW_CHECKLIST.md`](hardware/review/REVIEW_CHECKLIST.md)) is signed. Energised tests follow the staged bring-up checklist and are carried out by qualified members under the lab's safety procedure, never alone.
* The telematics unit never sends to the controller: no torque request, arming, fault reset or configuration change, and no part in protection or precharge. A change that adds a transmit path to the deployed node or firmware is not accepted (tests check it).

## 6. Writing documentation

* Say whether something runs on the host, is proposed, or has been tested on hardware.
* Units are SI unless stated; give the units of every number.
* Current documents contain no em dashes (a test checks this). Superseded documents are moved to [`docs/archive/`](docs/archive/) and listed in [`docs/README.md`](docs/README.md), not rewritten.
