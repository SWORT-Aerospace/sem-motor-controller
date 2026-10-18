# Current state of the telematics repository (2026-10-18)

Inventory taken before the evidence-platform work, at `295a815` on `eng/v0.7-telematics` (SWORT-Aerospace/sem-motor-controller#6, base `eng/v0.6-vehicle-package`, CI green on all three jobs). It is the starting map: what exists, how far each part has been shown to work, and what does not belong to telematics. Evidence labels: **SIMULATED** (host model only), **HOST-TESTED** (the real code runs on a computer under test), **BENCH-TESTED**, **HIL-TESTED**, **VEHICLE-TESTED**. Nothing in this repository is bench-, HIL- or vehicle-tested.

Scope: telematics only. The motor controller belongs to another team. The unit receives, logs, validates, cross-checks, displays and transmits; it never commands propulsion ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)).

## Architecture as found

```
sensors (Hall wheels on TIM2, IMU and TMP117 on I2C1)   controller CAN broadcast (FDCAN1, bus monitoring)
                \                                         /
          NUCLEO-U575ZI-Q firmware (telematics/firmware): timestamp, bounded queue, STLG records
                                     |
              local log: W25Q NOR (SPI1) or internal flash bank 2; console status and DUMP
                                     |
         (host model only) live summary sem.telemetry.v4 over MQTT  ---->  pit ingest (host/pit)
                                     |                                          |
          tools/telematics_import.py (dump -> STLG sessions)  ---------->  SQLite (runs, records,
                                                                            measurements, live, rx)
                                                                                |
                                         speed, distance, energy (host/pit/energy.py), shadow monitors
                                         R3v and CSIA2 (host/pit/shadow_replay.py), plots
```

Boundaries: CAN in (receive only, bus-monitoring mode, no transmit code in the firmware); UART console (status lines, `DUMP`, `ERASE YES`); MQTT out, host model only (the target has no modem code); SQLite at the pit. Persistent storage: STLG v1 slots on the NOR or internal flash (`docs/ICD.md` A.6).

## IMPLEMENTED

| Item | Where | Evidence level |
|---|---|---|
| Measurement model: every value with source, signal, unit, receive time, sample time only when the source gives one, timestamp uncertainty, source sequence, validity (`valid`, `unverified`, `invalid`, `out_of_range`, `decode_error`, `no_evidence`), provenance; live summary adds `stale` and `missing`; missing never written as 0 | `host/telematics/measurement.py` | HOST-TESTED |
| Signal registry (unit, origin, role, plausible range, stale time) with a hash named in every live message | `host/telematics/signals.py` | HOST-TESTED |
| Controller receive adapters: semmc simulation fixture (CRC, sequence, validity flags) and DBC adapter (unit-checked mapping); no method produces a frame | `host/telematics/controller_adapter.py` | HOST-TESTED (fixture frames only) |
| Wheel capture and validity: 1 us capture, 64-bit time; no edge is no evidence, never 0; stuck active / stuck inactive or disconnected flagged against moving channels; the same integer rule in C and Python | `telematics/firmware/src/tm_wheel.c`, `host/telematics/wheel.py` | HOST-TESTED |
| Firmware application: bounded queue, STLG blocks with CRC, restart reasons, counters, sparse logging at the storage reserve | `telematics/firmware/src/` | HOST-TESTED (portable code, ASan/UBSan) |
| Target images for the NUCLEO-U575ZI-Q: TIM2 capture, IWDG, USART1 console, internal flash log, W25Q NOR on SPI1, I2C1 IMU and TMP117, FDCAN1 bus monitoring (`tm_u575_can`) | `telematics/firmware/platform/u575/` | built and linked; register sequences compared with ST's HAL; never run |
| Log import: whole or ranged dump, sessions, idempotent import, speed and distance plots, status-line overflow check | `tools/telematics_import.py`, `host/pit/ingest.py` | HOST-TESTED |
| Pit database: `runs`, `records`, `signals`, `measurements`, `live`, `rejected`, `rx`, `imports`; live-message validation with rejections kept | `host/pit/ingest.py`, `host/pit/mqtt_ingest.py` | HOST-TESTED |
| Energy at two boundaries from valid aligned V x I, missing intervals with causes | `host/pit/energy.py` | HOST-TESTED (simulated data) |
| Shadow monitors R3v and CSIA2 on pit data, relationships disabled when inputs are missing; frozen v2 evaluation unchanged | `host/pit/shadow_replay.py`, `host/csia_adapter/` | SIMULATED |
| Independent demonstration through a real Mosquitto broker, 9 checks (receive only, missing never zero, accounting, outage, restart, re-ingest) | `tools/run_telematics_demo.py` | SIMULATED inputs, HOST-TESTED pipeline |
| Bench package: images with SHA-256 manifest, procedure B0 to B12 and E1 to E6, parts, connections, console capture tool, blank results form | `tools/telematics_bench.py`, `telematics/bench/bench.yaml` | procedure written; not run |
| Telematics BOM with the vehicle supply blocked until V_bat,max is known | `hardware/telematics/bom.yaml`, `tools/telematics_bom.py` | document; nothing ordered |

## PARTIAL

| Item | What exists | What is missing |
|---|---|---|
| Canonical telemetry contract | registry (unit, range, stale time) and ICD prose | per-field physical and transport source, encoding, scaling, expected rate, timestamp source, startup, stale, invalid and missing semantics, lineage, measured or derived, in one machine-readable file |
| Evidence states | validity per measurement, `stale`/`missing` in the live summary | one explicit state model across the pipeline (VALID, STALE, MISSING, INVALID, UNSUPPORTED, UNKNOWN and the qualifiers) with reasons; `unsupported` (a signal this configuration cannot provide) is reported as `missing` |
| Timing and freshness | receive time, sample time when given, uncertainty, source sequence, age in the live summary; STLG block sequence gaps | per-source inter-arrival, jitter, dropped-sample estimate from the sequence, duplicate and reorder detection, wraparound, on the receive path and at the pit |
| Receive-only boundary | firmware: no transmit registers referenced, bus-monitoring mode; node: no frame-producing method; demonstration check | `host/vcu_bridge/semmc_socketcan.py` has a `send()` that can put any semmc frame, including `sup_torque_req`, on a real CAN socket (reference scope, untested); no test proves that no production module can reach a transmit or encode path |
| CAN noninterference | E1 to E6 written; receive-only image | host tests for flood, malformed frames, bus load from the unit (zero frames) and processing bounds |
| Lineage | provenance string per measurement | which raw sources and shared dependencies (power, bus, clock) a derived value or conclusion depends on |
| Cross-domain checks | CSIA relationships E1 to E7 inside the frozen shadow adapter (simulation-tuned) | a vehicle evidence interface with declared operating contexts, admissibility, verdicts and receipts, separate from the frozen research code |
| Pit queries | `series`, energy gaps, wheel distance | time-aligned signals, missing and stale intervals, event windows as reusable queries; evidence-state rows |
| Advisory energy | Wh, Wh/km at two boundaries | rolling efficiency, remaining-energy estimate; recommendations stay advisory |

## PLACEHOLDER

* Vehicle context (STARTUP, STOPPED, CRUISE, ...): not modelled.
* Evidence receipts ("why did the system say this"): not produced.
* `research/`: no vehicle validation protocols (the earlier research directory holds untracked caches only).
* `docs/HARDWARE_OPEN_ITEMS.md`: does not exist; the items are spread over BLOCKERS, BOM and BENCH.

## UNVERIFIED

* Every pin, level and connection of the NUCLEO-U575ZI-Q table (BENCH.md section 4); the PD0/PD1 positions.
* All register-level behaviour of the U575 code against RM0456, DS13737, ES0499 (compared with ST's HAL only; st.com unreachable from this environment so far).
* The W25Q128JV command set, pinout and timings (data sheet not read).
* The semmc protocol on any real bus (it is our simulation fixture; the controller team has not accepted it).
* Every stale threshold for controller signals (assumes the fixture's broadcast periods).
* GNSS, modem, battery-side monitor: host models only.

## BLOCKED

| Item | Blocked by |
|---|---|
| Real controller frames, rates, timestamps, validity | the controller team's answer (T-CTRL-IF) |
| Vehicle supply (DC-DC, TVS, fuse) and any vehicle power connection | V_bat,max (B-BAT-V, T-VEH-PWR) |
| Real wheel speed (circumference, pulses per revolution, Hall part) | drivetrain inputs (B-DRIVETRAIN) |
| Any bench result | a bench session with the package (T-BENCH1) |
| Register behaviour per the reference manual | RM0456, DS13737, ES0499 (T-U5-DOCS) |

## OUT OF SCOPE (inherited from PR #5, controller authority)

These remain in the repository as deferred controller development or simulation fixtures. None is part of the telematics delivery, none is imported by it, and the scope file marks each (`docs/scope.yaml`).

| Item | Why it is out of scope |
|---|---|
| `firmware/` (STM32G474 controller core, PWM, protection) | it is a motor controller: propulsion authority |
| `hardware/` except `hardware/telematics/` (power stage, gate driver, KiCad) | the controller's hardware |
| `host/telemetry_adapter/` (ECO supervisor, legacy supervised node, co-simulation) | issues torque requests in simulation; legacy mode only (`--legacy-supervised`) |
| semmc messages `sup_torque_req`, `sup_limits`, `sup_hello`, `csia_advisory` | messages to the controller in the old design; the production adapter only decodes controller broadcasts and ignores these |
| `host/vcu_bridge/semmc_socketcan.py` `send()` | was a real-bus transmit path for those messages; **removed**: the bridge now returns a receive-only socket |
| `tools/run_host_demo.py`, `tools/run_mqtt_demo.py` | legacy supervised simulations, refuse to run without `--legacy-supervised` |
| `docs/CONTROL_CONTRACT.md`, `ARCHITECTURE_FREEZE.md`, `BENCH_ACCEPTANCE.md`, `HARDWARE_ARCHITECTURE.md` | the controller's design record |

## After the evidence-platform change

The sections above are the audit made before any edit. What the change added, and its label
([`CLAIMS.md`](CLAIMS.md)): nothing below is above HOST-TESTED; nothing was run on a board or the vehicle.

| Area | Now | Where | Label |
|---|---|---|---|
| Receive-only boundary | the SocketCAN bridge's `send()` removed; an import-graph and AST scan of every production telematics file (with a planted negative control), adapter fuzzing, firmware CAN driver and FDCAN monitoring-mode checks | `tests/telematics/test_receive_only_boundary.py` | HOST-TESTED |
| Telemetry schema | one contract per signal; the registry is built from it; checked against protocol, adapter and firmware records; registry hash unchanged | `telematics/schema/telemetry_schema.yaml`, [`TELEMETRY_SCHEMA.md`](TELEMETRY_SCHEMA.md) | HOST-TESTED |
| Evidence states, timing, lineage, context | nine states; per-stream timing with a wait bound after stalls; raw sources and shared paths; context from admissible evidence | `host/telematics/evidence.py`, `timing.py`, `lineage.py`, `context.py` | HOST-TESTED |
| Pit evidence store | `evidence` rows per measurement with the raw record (`evidence_records` view), `source_timing`, `receipts`, `receipt_snapshots`; queries and a command line | `host/pit/ingest.py`, `queries.py`, `tools/pit_query.py` | HOST-TESTED |
| Cross-domain witnesses and verdicts | relations A1, A2, B1 to B4, D1, common cause; SUPPORTED, AMBIGUOUS, UNSUPPORTED with receipts; no fault labels | `host/assurance/` | HOST-TESTED |
| CAN noninterference, receive side | the log queue keeps a reserve for the unit's own records; frames beyond it counted (`can_not_logged`, COUNTERS2 id 27); flood test in C and Python | `telematics/firmware/src/tm_app.c`, `tests/telematics/test_evidence_pipeline.py` | HOST-TESTED |
| Bench chain | pulse to capture to log to decoder to database to query, against a known pulse train; the same tool reads a board's log | `tools/run_bench_chain.py`, bench step B4 | HOST-TESTED (host build); bench: not run |
| Advisory energy | rolling Wh/km, energy by speed band, nominal remaining energy, cruise-band suggestion; advisory only | `host/pit/advisory.py` | HOST-TESTED |
| CSIA shadow boundary | only VALID evidence in, no invented inputs, trust numbers withheld | `host/assurance/csia_boundary.py` | HOST-TESTED |
| Vehicle-validation protocols | EXP-01 to EXP-04 with ground truth, falsifiers and a run sheet; simulated pre-check passes | `research/vehicle_validation/`, `tools/run_vehicle_experiment.py` | SIMULATED; physical: not run |
| Hardware open items | pack configuration, TVS, DC-DC, temperature sensors, CAN format, Hall electrical data, storage, U575 registers | [`HARDWARE_OPEN_ITEMS.md`](HARDWARE_OPEN_ITEMS.md) | open |
| CI | separate jobs: static checks, schema validation, firmware build, host tools, unit tests, integration tests; HARDWARE_REQUIRED tests never run in CI | `.github/workflows/ci.yml`, `conftest.py` | |

Still open and unchanged by this work: every item under UNVERIFIED and BLOCKED above. The register-level check against
ST's manuals (T-U5-DOCS) could not be done: www.st.com was refused by this environment's network policy.
