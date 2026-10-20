# Tools

Scripts that generate code and documents from the repository's source files, check that the generated files are current, run the host simulations and studies, and check the draft hardware. None of them touches hardware: every result comes from the host computer, from synthetic models or from the draft design files.

Run every command from the repository root, inside the virtual environment created from `requirements.txt` (see [`README.md`](../README.md), "Getting started"). Many tools need the C host build first (`cmake -S firmware -B build -G Ninja && cmake --build build`), which also writes the calibration blobs in `build/cal/`.

Abbreviations used below:
* **CI**: continuous integration, the GitHub Actions workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
* **CAN**: Controller Area Network, the vehicle bus. **DBC**: the common file format that describes CAN messages for other tools.
* **MQTT**: the publish/subscribe protocol of the telemetry uplink; Mosquitto is the broker used here.
* **CSIA**: the experimental sensor-consistency diagnostics, run pit-side or in replay shadow mode only. **R3v**: the calibrated-residual monitor with majority-vote attribution that was retained after the v2 evaluation; **CSIA2**: the experimental v2 CSIA adapter.
* **KiCad**: the open-source electronics design suite (`kicad-cli` is its command-line tool). **ERC**: electrical rules check. **BOM**: bill of materials. **MCU**: microcontroller unit.
* **DP**: dynamic programming (the energy-strategy optimiser). **STLG**: the vehicle's local block log format.

**Scope (v0.7).** The telematics tools are `run_telematics_demo.py`, `telematics_import.py`, `telematics_bom.py`, `telematics_bench.py`, `telematics_storage.py`, `uart_capture.py`, `scope.py`, `run_pit_replay.py`, `mqtt_broker.py`, `check_links.py` and the shared analyses `bus_load.py`, `can_bit_timing.py`, `wheel_sensor_check.py`; none needs the controller build. The others serve the reference models or the deferred controller development ([`../docs/scope.yaml`](../docs/scope.yaml)); `run_host_demo.py` and `run_mqtt_demo.py` are the LEGACY supervised simulations and run only with `--legacy-supervised`.

| Tool | What it does | Writes |
|---|---|---|
| [`run_telematics_demo.py`](run_telematics_demo.py) | End-to-end demonstration of the receive-only telematics node against a simulated external controller and sensors: real Mosquitto broker (or `--in-process`), controller silence, invalid frames, a missing signal, a storage stall, a broker outage, a restart; 9 checks | `build/telematics_demo/`; with `--samples`, `docs/generated/telematics_demo/` |
| [`telematics_import.py`](telematics_import.py) | A flash or UART dump (whole or a slot range) of the firmware's log region -> sessions -> STLG files -> pit import -> speed and distance plots; `--status-capture`: the console's status lines checked across the timer overflow, with the slot range to dump | the output directory and the database given; `status.csv`, `status.json` |
| [`telematics_bom.py`](telematics_bom.py) | Totals of the bench and configurations A and B from `hardware/telematics/bom.yaml`; refuses a bench part without its firmware driver and an unblocked vehicle supply without the pack's maximum voltage; `--check` in CI | `docs/TELEMATICS_BOM.md`, `docs/generated/telematics_bom.json` |
| [`telematics_bench.py`](telematics_bench.py) | `render [--check]`: `telematics/firmware/BENCH.md` and `BENCH_MINIMAL.md` from `telematics/bench/bench.yaml`, checked against the firmware sources, the BOM, the chain's checks and the measured durations; `package --images build-u575 --out build/telematics_bench [--rebuild]`: the bench package (images, SHA-256 manifest, procedure, connections, parts, blank results form); `package --minimal ... --host-build build-telematics`: the minimal bench package (one image, its six connection rows, parts and equipment, the document checks due before flashing with the PDFs to provide, blank form for M0 to M4, a SIMULATED rehearsal) | `telematics/firmware/BENCH.md`, `BENCH_MINIMAL.md`; `build/telematics_bench/`, `build/telematics_bench_minimal/` (CI artifacts `telematics-bench-package`, `telematics-bench-minimal`) |
| [`uart_capture.py`](uart_capture.py) | Console capture on the bench: serial terminal that writes every byte received to a file; `--send`, `--until`, `--duration` | the capture file |
| [`telematics_storage.py`](telematics_storage.py) | Recording durations of the log per record mix on internal flash and the NOR, measured with the firmware's code in the host simulator; `--check` in CI | `docs/generated/telematics_storage.md`, `.json` |
| [`scope.py`](scope.py) | Every tracked file's suite from `docs/scope.yaml`; `--check` in CI fails on an unclassified file | `docs/generated/scope.md` |

## 1. Tools by purpose

### 1.1 Generators

Each generator has a `--check` form that compares the committed files with what it would write and exits 1 when they differ, without writing anything.

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `gen_config.py` | Generates the configuration JSON schema and the C parameter table from the parameter registry | `config/parameters.yaml` (read through `config_registry.py`) | `config/vehicle.schema.json`, `firmware/include/semmc/mc_params_generated.h` | `python3 tools/gen_config.py`; check: `python3 tools/gen_config.py --check` |
| `gen_protocol.py` | Generates the C and Python CAN codecs, the golden test vectors and the message table, with identical arithmetic in both languages | `protocol/protocol.yaml` | `protocol/generated/semmc_protocol.h`, `.c`, `.py`, `protocol/generated/semmc_golden_vectors.c`, `protocol/golden_vectors/vectors.json`, `docs/generated/can_messages.md` | `python3 tools/gen_protocol.py`; check: `python3 tools/gen_protocol.py --check` |
| `gen_dbc.py` | Generates a DBC file of the protocol for other teams' CAN tools; `--base` moves the 64-identifier block (a multiple of 0x40) | `protocol/protocol.yaml` (through `gen_protocol.py`) | `protocol/generated/semmc_base0x300.dbc` by default; `protocol/generated/semmc_base0x<BASE>.dbc` for another base, or the path given with `-o` | `python3 tools/gen_dbc.py [--base 0x300] [-o PATH]`; check (default file): `python3 tools/gen_dbc.py --check` |
| `gen_procurement.py` | Generates the project procurement tables (nine categories: controller, telemetry, shared wiring and power, fabrication and assembly, shipping and tax, spares and revision, development equipment, recurring connectivity, contingency) with per-category subtotals, and evaluates the builds of `procurement.yaml` (controller only, plus local logging, full scope) against $500 and $1,000; it refuses a build that leaves out a controller line. Estimated lines take their range from `docs/generated/budget.json`, so `price_bom.py` must run first after a pricing change. Refuses the source file (exit 2) when a price has no dated source, an estimate reference does not resolve, Ordered or Received has no order evidence, or a status is unknown | `hardware/bom/procurement.yaml`, `docs/generated/budget.json`, `hardware/bom/pricing.yaml` | the budget table between the `procurement-table` markers in `README.md`, and `docs/PROCUREMENT.md` | `python3 tools/gen_procurement.py`; check: `python3 tools/gen_procurement.py --check` |
| `gen_board_pins.py` | Writes the target firmware's pin header from the schematic's pin map, checking every pin's LQFP100 position, that ST lists the signal on that pin, and the alternate-function number, against ST's pin database | `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`, `hardware/interfaces/st_open_pin_data/` | `firmware/platform/stm32g4/src/board_pins_generated.h`, `docs/generated/pin_af_verification.md` | `python3 tools/gen_board_pins.py`; check: `--check` |
| `ov_trip_worst_case.py` | Trip and release of the over-voltage comparator at every corner of the resistor, reference, comparator and supply bounds; reports the full worst case only when every bound is known | `hardware/calculations/ov_trip_inputs.yaml` | `hardware/calculations/ov_trip_worst_case.md` | `python3 tools/ov_trip_worst_case.py`; check: `--check` |
| `bench_package.py` | Bench package: the committed page and, from built images, the folder for one board | `hardware/acceptance/procedures.yaml`, the netlist and consistency checks, `build-g4/` images | `hardware/acceptance/BENCH_PACKAGE.md`; `build/bench_package/` (CI artifact `bench-package`) | `python3 tools/bench_package.py --doc`; `--images build-g4 --board <serial> --out build/bench_package`; check: `--doc --check` |
| `erc_record.py` | Ties a CI KiCad ERC result to the SHA-256 of the schematic inputs it checked, so the release gate accepts it only for that exact schematic | the schematic sheets and library tables, the pinned library hashes, a CI ERC report or its counts | `hardware/kicad/ERC_RECORD.yaml` | `python3 tools/erc_record.py hash`; `record --run URL ...`; CI ERC job: `check --report hardware/kicad/ERC_REPORT.json` |
| `check_footprints.py` | Footprint disposition per BOM line and checks of each assigned footprint against its symbol, with the KiCad 8.0.9 footprint files pinned by SHA-256 | `hardware/footprints/assignments.yaml`, `library_pins.yaml`, `hardware/bom/BOM_draft.csv`, the schematic sheets, `build/kicad-footprints-8.0.9/` | `hardware/footprints/FOOTPRINT_CHECK.md`, `hardware/kicad/fp-lib-table` | `python3 tools/check_footprints.py --fetch` then `python3 tools/check_footprints.py`; check: `--check` |
| `check_datasheets.py` | Renders the primary-document download list and records received PDFs (SHA-256, size); the reviewer types the revision. `--check` fails on a stale page or a changed file | `docs/reference/datasheets/manifest.yaml`, PDFs in that folder | `docs/reference/datasheets/README.md`; with `--record`, the manifest | `python3 tools/check_datasheets.py`; check: `--check` |
| `blockers.py` | Renders the blocker-to-evidence register and refuses an incomplete entry (an open entry without its input or closure criterion, a closed one without evidence) | `docs/blockers.yaml` | `docs/BLOCKERS.md` | `python3 tools/blockers.py`; check: `--check` |
| `acceptance.py render` | Renders the physical acceptance procedures; `template` and `check` are in section 1.6 | `hardware/acceptance/procedures.yaml`, `docs/blockers.yaml` | `docs/BENCH_ACCEPTANCE.md` | `python3 tools/acceptance.py render`; check: `render --check` |

### 1.2 Validators

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `config_tool.py` | Validates a vehicle configuration for simulation (`sim`) or hardware (`hw`) mode and encodes the calibration blob. Exit 0 valid, 1 invalid, 2 usage or file error. The same rules run in `firmware/src/calibration/mc_config.c` | a configuration YAML file; `config/vehicle.schema.json` | `validate`: a printout only; `blob`: the binary blob at `-o` (the C build writes `build/cal/synthetic.bin` and `build/cal/unconfigured.bin` this way) | `python3 tools/config_tool.py validate config/vehicle.synthetic.yaml --mode sim`; `python3 tools/config_tool.py blob config/vehicle.synthetic.yaml --mode sim -o build/cal.bin` |
| `telematics_schema.py` | Checks the canonical telemetry schema (`telematics/schema/telemetry_schema.yaml`) against the protocol, the controller adapter, the firmware's record types and the registry hash, and renders `docs/TELEMETRY_SCHEMA.md` | the schema, `protocol/protocol.yaml`, `host/telematics/` | `docs/TELEMETRY_SCHEMA.md`; with `--check` a printout, exit 1 on a failed check or a stale page | `python3 tools/telematics_schema.py --check` |
| `claims.py` | Checks the claims register `docs/claims.yaml` (labels SIMULATED to VEHICLE-TESTED against existing tests, files and run records) and scans the telematics docs for sentences that claim validation or readiness; renders `docs/CLAIMS.md` | `docs/claims.yaml`, tracked Markdown | `docs/CLAIMS.md`; with `--check` a printout, exit 1 on a failed check or a stale page | `python3 tools/claims.py --check` |
| `check_links.py` | Checks that relative links and `#anchors` in every git-tracked Markdown file resolve, and that file paths in backticks exist in the documents listed in its `CURRENT` set. External links are not fetched | tracked `*.md` files (`git ls-files`) | a printout; exit 1 on any broken link | `python3 tools/check_links.py` |

### 1.3 Studies

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `run_optimization.py` | Synthetic energy-strategy study: DP plan with propulsion, coast and driver braking, compared with other strategies on one forward simulator | `models/optimization/`, `models/vehicle/` (synthetic vehicle, motor, inverter and track) | `docs/generated/optimization_synthetic.md`, `.json`, `docs/generated/dp_schedule_synthetic.csv`, `dp_driver_guidance_synthetic.csv`, `dp_schedule_torque_only_flat_synthetic.csv`, `docs/figures/dp_plan_synthetic.png` | full: `python3 tools/run_optimization.py`; coarse grids (CI): `python3 tools/run_optimization.py --quick`, which writes the same files into `build/optimization_quick/` instead |
| `run_policy_comparison.py` | Speed hold against pulse-and-coast, each run as the supervisor of the controller core and the host plant; energy per metre over the steady part of the run | the C host build in `build/`, `config/vehicle.synthetic.yaml` | `docs/generated/policy_comparison_host.md`; per-policy runs in `build/policy_cmp/` | `python3 tools/run_policy_comparison.py --duration 300` (default 200 s; the committed result used 300) |
| `run_electrical_calcs.py` | Parameterised electrical calculations and sensitivity study with synthetic operating points; candidate MOSFET figures are search-snippet values, marked UNVERIFIED | `models/inverter/losses.py`, candidate values in the script | `docs/generated/electrical_calcs_synthetic.md`, `docs/figures/electrical_sensitivity_synthetic.png` | `python3 tools/run_electrical_calcs.py` |
| `run_csia_study.py` | CSIA adapter against simple checks and fixed-threshold residuals on the synthetic development set | `host/csia_adapter/` | `docs/generated/csia_comparison_synthetic.md` | `python3 tools/run_csia_study.py` |
| `run_csia_evaluation.py` | CSIA v1 held-out evaluation and ablation. Refuses to run (exit 2) if a frozen file differs from the freeze manifest | `docs/csia/DEV_SET_FREEZE.json`, `host/csia_adapter/` | `docs/generated/csia_evaluation_synthetic.md`, `.json`; `--smoke` writes `docs/generated/csia_evaluation_smoke.md`, `.json` instead (not tracked); `--write-manifest` rewrites the manifest (freeze step only) | `python3 tools/run_csia_evaluation.py [--smoke] [--jobs N]` |
| `run_csia_evaluation_v2.py` | CSIA v2 evaluation by the pre-registered protocol (`docs/csia/EVALUATION_PROTOCOL_v2.md`): development runs, freeze, and a single run on the untouched evaluation set. `--eval` refuses if a frozen file changed or the results already exist | `docs/csia/V2_FREEZE.json`, `host/csia_adapter/` | `--dev`: `docs/generated/csia_v2_development_synthetic.md`, `.json`; `--freeze`: `docs/csia/V2_FREEZE.json`; `--eval`: `docs/generated/csia_v2_evaluation_synthetic.md`, `.json` | `python3 tools/run_csia_evaluation_v2.py --dev` (also `--freeze`, `--eval`; `--jobs N`) |
| `run_csia_posthoc.py` | Exploratory analysis added after the v1 evaluation (debounce variants); changes no frozen file and no pre-registered result | `docs/generated/csia_evaluation_synthetic.json`, `host/csia_adapter/` | `docs/generated/csia_posthoc_synthetic.md`, `.json` | `python3 tools/run_csia_posthoc.py [--jobs N]` |
| `telematics_budget.py` | Logging capacity, LTE data volume and auxiliary power of the combined controller and telematics design | the generated Python codec (`protocol/generated/semmc_protocol.py`); telematics-proposal values and assumptions tagged in the script | `docs/generated/telematics_budget.md`, `.json` | `python3 tools/telematics_budget.py` |
| `wheel_sensor_check.py` | Whether a sampled (DRV5032) or continuous (DRV5023-Q1) Hall switch sees every wheel magnet, over a labelled geometry grid (not the vehicle's) | datasheet timing values written in the script | `docs/generated/wheel_sensor_check.md` | `python3 tools/wheel_sensor_check.py`; check: `python3 tools/wheel_sensor_check.py --check` |
| `coastdown_sensitivity.py` | How grade, wind and speed noise bias a coast-down fit on the synthetic vehicle | `models/vehicle/longitudinal.py` | `docs/generated/coastdown_sensitivity.md` | `python3 tools/coastdown_sensitivity.py`; check: `python3 tools/coastdown_sensitivity.py --check` |
| `bus_load.py` | CAN bus load and worst-case response time at the protocol's nominal bit rate, including a reference-project load case (the vehicle bus's other traffic is unknown) | `protocol/protocol.yaml` | a Markdown table on standard output only | `python3 tools/bus_load.py` |
| `can_bit_timing.py` | FDCAN bit timing for the reference project's CAN FD bus; superseded by `clock_tree.py` and kept for its record | constants in the script | `docs/generated/can_bit_timing.md` | `python3 tools/can_bit_timing.py` |

### 1.4 Demonstrations and pit-side replay (host simulation)

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `run_host_demo.py` | End-to-end host demonstration: synthetic driver and plant, controller core, telematics node model with the STLG log, simulated LTE/MQTT uplink, pit validation into SQLite, offline log import, pit-side CSIA replay and the R3v/CSIA2 shadow replay. Prints one `DEMO` line per check; exit 1 if any fails | the C host build in `build/` (`semmc_host`, `cal/synthetic.bin`) | in `--out` (default `build/host_demo`): `run.stlg`, `controller.csv`, `controller_tx.log`, `pit.sqlite`, `summary.json`, `summary.md`, `csia_timeline.csv`, `pit_replay/`; `--samples DIR` also copies the summaries, `csia_timeline.csv` and `pit_replay_report.md` to DIR (the committed samples are in `docs/generated/host_demo/`) | `python3 tools/run_host_demo.py --out build/host_demo` |
| `run_mqtt_demo.py` | The same telemetry chain through a real local Mosquitto broker and a separate pit ingestion process, with broker and pit crashes. Prints one `MQTT` line per check; exit 1 if any fails, exit 2 if no Mosquitto binary is found | the C host build in `build/`; a Mosquitto binary ([`docs/MQTT_SETUP.md`](../docs/MQTT_SETUP.md)) | in `--out` (default `build/mqtt_demo`): the broker's files, the local log, `pit.sqlite`, `summary.json`, `summary.md`, `pit_replay/`; `--samples DIR` copies the summaries and `pit_replay_report.md` (committed samples: `docs/generated/mqtt_demo/`) | `python3 tools/run_mqtt_demo.py --out build/mqtt_demo [--duration 120] [--pace 2]` |
| `run_pit_replay.py` | Shadow replay of R3v and CSIA2 over one run stored in a pit database, as an advisory report. Reads the database only; it has no CAN, MQTT or controller interface. Exit 0 when a report was written, 2 when the run is not in the database | a pit SQLite file with the run's log imported (the demonstrations produce one); the vehicle configuration named in the run's metadata (or `--config`) | in `--out` (default `build/pit_replay`): `report.md`, `report.json`, `timeline.csv` | `python3 tools/run_pit_replay.py --db build/host_demo/pit.sqlite --run HOSTSIM-0001 --out build/pit_replay` |
| `run_evidence_review.py` | Shadow evidence review of one stored run: evidence per tick, vehicle context, cross-domain relations, conclusions SUPPORTED, AMBIGUOUS or UNSUPPORTED with receipts, common-cause events; parameters the log lacks are UNSUPPORTED unless given with `--param name=value` | a pit SQLite file with the run imported | `<run>_evidence_review.json` and `.md` in `--out`; tables `receipts` and `receipt_snapshots` | `python3 tools/run_evidence_review.py --db pit.sqlite --run <run_id> --out build/evidence_review [--pair wheel_l:wheel_r]` |
| `csia_disagreement_case.py` | The CSIA clean-run disagreement as a minimal reproducible case: the 550-tick run, the failing relationship and operating conditions, a constant-input case at two steady points, the classification, and the boundary's behaviour now; SIMULATED; frozen files untouched | the pinned CSIA core (`fetch_csia.py`) | `docs/generated/csia_clean_run_case.md` (`--check` in CI) | `python3 tools/csia_disagreement_case.py [--check]` |
| `run_firmware_vehicle_sim.py` | Firmware-in-the-loop drive (SIMULATED): the simulated vehicle drives the firmware's own C code (tm_app and tm_gnss in `tm_hostsim`), then the log goes through import, evidence review (`--pair wheel_l:wheel_r`) and the R3v/CSIA shadow replay; GNSS speed and UTC compared with the simulation; the firmware's live messages (tm_live) through the pit's validation and store, sequence numbers accounted for, every value compared with the pit's import of the log | the host firmware build (`build-telematics`, built if needed) | `flash.bin`, `live.txt`, `pit.sqlite`, `import/`, `evidence_review/`, `replay/`, `summary.json` in `--out` | `python3 tools/run_firmware_vehicle_sim.py --out build/firmware_vehicle_sim [--duration 140] [--gnss-outage 60:70] [--wheel-scale 0:90:110:1.05] [--link-outage 20:40]` |
| `run_vehicle_experiment.py` | Simulated pre-check of the vehicle-validation protocols EXP-01 to EXP-04 (`research/vehicle_validation/`): known disturbances through the whole chain; each protocol's signature, falsifier and known limitations checked; SIMULATED, never a vehicle result; exit 1 if a check fails | nothing (simulation) | `results.json`, `results.md` and one directory per variant (logs, database) in `--out` | `python3 tools/run_vehicle_experiment.py --out build/vehicle_experiments [--only EXP-01]` |
| `run_bench_chain.py` | The pulse-to-database chain against a known pulse train, checks C1 to C9 (through the shadow review, its receipts and the speed and distance plot): in the firmware's host build (default, SIMULATED), on a log read from the board with the generator's rate (BENCH only if the log says so; `--boot N` picks the session), or `--rehearse-minimal`: the minimal bench procedure on the host simulator, read back with the bench's own command | `build-telematics/tm_hostsim`, or `--dump`/`--uart-capture` with `--pulse-hz` | `chain.json`, `chain.md`, `pit.sqlite`, `import/*_speed_distance.png` in `--out` | `python3 tools/run_bench_chain.py --out build/bench_chain` |
| `pit_query.py` | Evidence queries on a pit database: `runs`, `aligned`, `gaps`, `events`, `window`, `prepost`; a value that was not admissible prints as its state | a pit SQLite file | text on standard output | `python3 tools/pit_query.py --db pit.sqlite gaps --run <run_id> --signal ctrl.dc_voltage` |
| `control_contract_report.py` | Before/after report of the control-contract correction on the synthetic configuration; exit 1 if the "after" run violates the contract anywhere | `build/semmc_contract_report`, `build/cal/synthetic.bin`, the frozen `docs/generated/control_contract_before.csv` | `docs/generated/control_contract_after.csv`, `docs/generated/control_contract_before_after.md` | `python3 tools/control_contract_report.py --build build` |
| `make_replay_sample.py` | Generates the synthetic "recorded" log used by the replay test; learns the session tag from the controller first. Re-run only when the session-tag derivation changes | `build/semmc_host`, `build/cal/synthetic.bin` | `tests/simulation/replay_sample.semmc.log` | `python3 tools/make_replay_sample.py` |

### 1.5 Verification

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `verify_all.py` | Runs every reproducible check (section 3) and writes a record of each command, exit code, expected outcome, duration and summary lines, then lists the tracked files whose content changed during the run. Exit 1 on any FAIL | the whole repository; gcc, cmake, ninja, the arm-none-eabi toolchain, `kicad-cli` and Mosquitto for full coverage | in `--out` (default `build/verify`): `logs/`, `verification.json`, `verification.md`; plus every file that the checks themselves rewrite (section 4) | quick: `python3 tools/verify_all.py --out build/verify`; full: `python3 tools/verify_all.py --out build/verify --full`; selected checks: `--only ID ...` |

The committed record of a full run is in `docs/generated/verification/`, and its context in [`docs/VERIFICATION_REPORT.md`](../docs/VERIFICATION_REPORT.md).

### 1.6 Hardware

These act on the draft motor-controller hardware in [`hardware/`](../hardware/); [`hardware/README.md`](../hardware/README.md) explains the design and the order in which to run them.

| Tool | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `gen_kicad_schematic.py` | Holds the circuit as Python data and writes the hierarchical KiCad schematic and the draft BOM. `--check` first regenerates everything, then exports the netlist with `kicad-cli` and compares every intended net with KiCad's connectivity (exit 1 on a mismatch). Unlike the other `--check` forms, it writes files | its own design data; `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`; the pinned KiCad 8.0.9 symbol libraries (`build/kicad-symbols-8.0.9/`, from `fetch_kicad_symbols.py`; another directory through `KICAD8_SYMBOL_DIR`); `kiutils` | `hardware/kicad/*.kicad_sch`, `semmc.kicad_sym`, `semmc.kicad_pro`, `sym-lib-table`, `hardware/bom/BOM_draft.csv`; with `--check` also `hardware/kicad/semmc.net` and `CONNECTIVITY_CHECK.md` | `python3 tools/gen_kicad_schematic.py --check` |
| `fetch_kicad_symbols.py` | Downloads the 17 KiCad symbol libraries the schematic uses at tag 8.0.9 and rejects any file whose SHA-256 differs from the pinned one | the KiCad project's `kicad-symbols` repository | `build/kicad-symbols-8.0.9/` (ignored by git) | `python3 tools/fetch_kicad_symbols.py` |
| `run_kicad_erc.sh` | Runs KiCad's ERC on the draft schematic against the same pinned 8.0.9 libraries the generator used. Needs KiCad 8 or newer and exits 2 otherwise. When the user has no global symbol-library table, it installs KiCad's default one (into `~/.config/kicad/<major>.0/` unless `XDG_CONFIG_HOME` is set); it never overwrites an existing one | `hardware/kicad/semmc.kicad_sch` | `hardware/kicad/ERC_REPORT.rpt`, `ERC_REPORT.json` (not tracked) | `bash tools/run_kicad_erc.sh` |
| `erc_summary.py` | Summarises the ERC JSON report: counts by severity and type, then the violations (library-symbol issues in a shortened list). `--fail-on-errors` exits 1 on any error | `hardware/kicad/ERC_REPORT.json` | a printout; with `--md PATH`, a Markdown summary listing every violation | `python3 tools/erc_summary.py hardware/kicad/ERC_REPORT.json --fail-on-errors` |
| `pin_type_check.py` | Applies a subset of ERC pin-type rules to the netlist KiCad exported (not a KiCad ERC); always exits 0 | `hardware/kicad/semmc.net`, the sheets (for PWR_FLAG markers) | `hardware/kicad/PIN_TYPE_CHECK.md` | `python3 tools/pin_type_check.py` |
| `hw_consistency.py` | Cross-checks the exported netlist, pin allocation, BOM, platform notes, timing budget and configuration; each item is PASS, FAIL or OPEN; exit 1 on any FAIL | `hardware/kicad/semmc.net`, `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`, `hardware/bom/BOM_draft.csv`, `tools/gen_kicad_schematic.py`, `firmware/platform/stm32g4/README.md`, `config/vehicle.synthetic.yaml`, `tools/timing_budget.py` | `hardware/review/CONSISTENCY_CHECK.md` | `python3 tools/hw_consistency.py` |
| `price_bom.py` | Prices the draft BOM as low-high ranges and computes the budget scenarios and the feasibility statement from the high ends; stops if a line has no pricing rule | `hardware/bom/BOM_draft.csv`, `hardware/bom/pricing.yaml` | `hardware/bom/BOM_priced.csv`, `docs/BUDGET.md`, `docs/generated/budget.json` | `python3 tools/price_bom.py` |
| `timing_budget.py` | PWM, dead-time encoding, current-sampling window, break routing, startup pin states and interrupt budget for the STM32G474 | `config/vehicle.synthetic.yaml` and tagged constants in the script | `hardware/timing/timing_budget.md`, `.json` | `python3 tools/timing_budget.py` |
| `clock_tree.py` | Enumerates complete STM32G474 clock trees for candidate crystals and CPU frequencies and computes the CAN bit timing for four candidate buses; selects no crystal | limits from ST's HAL and CMSIS sources (cited by file and line), `config/vehicle.synthetic.yaml` | `hardware/timing/clock_tree_alternatives.md`, `.json` | `python3 tools/clock_tree.py` |
| `hardware_calcs.py` | Current-sense error budget and power-stage loss and thermal envelope over the unknown phase current and bus voltage | `models/inverter/losses.py`, snippet MOSFET values from `run_electrical_calcs.py` | `hardware/calculations/current_sense_error_budget.md`, `power_stage_envelope.md` | `python3 tools/hardware_calcs.py` |
| `pin_allocation.py` | Allocates the controller's functions to distinct pins for every STM32G474 package (signal availability and pin uniqueness only) | a local clone of ST's `STM32_open_pin_data` repository (the committed files used commit `7d1f1514ed5583ec5007ad91236b4e1d377295b1`) | `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv` (LQFP100), `..._MBCETx.csv` (LQFP80), `..._RBCETx.csv` (LQFP64), `docs/generated/pin_allocation.md` | `python3 tools/pin_allocation.py --db /path/to/STM32_open_pin_data --commit <sha>` |

| `release_gate.py` | Evaluates the fabrication release gate (BOM resolved, footprints and primary pin checks, datasheet register, PCB with a passing DRC, ERC, signed reviews, a hardware-valid configuration); builds the release package (sources, PDFs, Gerbers, drill, BOM, placement, notes, checksums, manifest) only when every condition passes. Exit 1 while it fails | the BOM files, the register, `hardware/kicad/`, the review checklists, `config/vehicle.*.yaml` | `docs/generated/release_gate.md`; with `--package DIR` and a passing gate, the package in DIR | `python3 tools/release_gate.py` |
| `acceptance.py template`, `check` | Writes a blank result record for one acceptance stage and board; checks a returned record: values against the sourced or configured limits, stop conditions, steps blocked by open register entries, evidence files, operator and witness | `hardware/acceptance/procedures.yaml`, `docs/blockers.yaml`, optionally a vehicle configuration | a YAML record; a printout and exit 1 on any error | `python3 tools/acceptance.py template --stage S3 --board SN001 --out bench/records/SN001/S3.yaml`; `python3 tools/acceptance.py check bench/records/SN001/S3.yaml` |
| `bench_read.py` | Reads the firmware's `g_bench` structure from a running board through OpenOCD and writes readings as JSON for the acceptance records | the flashed `.elf` (for the symbol address); an OpenOCD server | standard output; `--json PATH` | `python3 tools/bench_read.py --elf build-g4/semmc_stm32g474.elf --samples 10 --json reading.json` |
| `emulate_core_timing.py` | Runs the core's Cortex-M4F build in an instruction-level emulator (unicorn) and reports instruction counts of the fast and slow steps; counts, not timing on silicon | `build-g4/semmc_core_timing.elf`, a calibration blob | standard output; `--out PATH` | `python3 tools/emulate_core_timing.py --elf build-g4/semmc_core_timing.elf --blob build/cal/synthetic.bin --ms 300 --out docs/generated/core_timing_emulated.md` |

The procurement generator `gen_procurement.py` (section 1.1) also belongs to the hardware work: its source file is `hardware/bom/procurement.yaml`, and its estimated lines come from the output of `price_bom.py`.

### 1.7 Setup and shared modules

| File | What it does | Inputs | Outputs | Command |
|---|---|---|---|---|
| `fetch_csia.py` | Fetches the pinned CSIA core with git and verifies its commit; the CSIA code is not copied into this repository | `third_party/csia-trust-layer.lock` | `.deps/csia-trust-layer/` (ignored by git) | `python3 tools/fetch_csia.py` |
| `config_registry.py` | Library module: loads the parameter registry for `gen_config.py` and `config_tool.py` | `config/parameters.yaml` | none | imported, not run |
| `mqtt_broker.py` | Library module: starts, kills and restarts a local Mosquitto on a free loopback port for the tests and `run_mqtt_demo.py`. Finds the binary from `$SEMMC_MOSQUITTO`, then `mosquitto` on `PATH`, then `/usr/sbin/mosquitto` | a Mosquitto binary | a broker configuration and persistence files in the directory it is given | imported, not run |
| `mqtt/compose.yaml`, `mqtt/mosquitto.conf` | Container broker (eclipse-mosquitto 2.0.18) listening on 127.0.0.1:1883 with no authentication, for manual pit work; the tests and demonstrations do not use it | none | a running broker | `docker compose -f tools/mqtt/compose.yaml up` |
| `__init__.py` | Makes `tools` a Python package, so tests and tools can write `from tools import ...` | | | |

## 2. What CI runs

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on GitHub-hosted Ubuntu 24.04 runners with Python 3.13 (the suites are defined in [`../docs/scope.yaml`](../docs/scope.yaml)). None touches hardware; tests marked `hardware_required` never run there.

**Telematics jobs** (never the project's controller build):
* `static-checks`: `scope.py --check`, `gen_protocol.py --check`, `gen_dbc.py --check`, `telematics_bom.py --check`, `telematics_bench.py render --check`, `wheel_sensor_check.py --check`, `check_links.py`, `claims.py --check`, and that the Python sources compile.
* `schema-validation`: `telematics_schema.py --check` and the schema tests (`test_evidence_model.py -k schema`).
* `firmware-build` (the ARM toolchain): host build and `ctest` under sanitizers (`build-telematics`), `telematics_storage.py --check`, the NUCLEO-U575ZI-Q images (`build-u575`, uploaded as `telematics-u575-images`), the bench package (uploaded as `telematics-bench-package`).
* `host-tools` (Mosquitto): `fetch_csia.py`, `run_bench_chain.py` (host mode), `run_telematics_demo.py` through a real broker, `run_evidence_review.py` and `pit_query.py` on its database, `run_vehicle_experiment.py`, `csia_disagreement_case.py --check`; outputs uploaded as `telematics-host-tools`.
* `unit-tests`: `python -m pytest -rs -m "(telematics or reference) and not integration and not hardware_required"` with the controller build directory pointed at a path that must still not exist afterwards.
* `integration-tests` (Mosquitto, the ARM toolchain): `python -m pytest -rs -m "(telematics or reference) and integration and not hardware_required"` with `SEMMC_REQUIRE_MQTT=1`, `SEMMC_REQUIRE_ARM=1` and the same controller-build check.
* `telematics`: passes when all six pass (the check name branch rules may name).

**`controller` job** (the deferred controller development; KiCad 8 from `ppa:kicad/kicad-8.0-releases`, Mosquitto, the ARM toolchain), in this order:
1. `fetch_kicad_symbols.py`, `check_footprints.py --fetch`. Generated files are current: `gen_config.py`, `gen_protocol.py`, `gen_dbc.py`, `gen_procurement.py`, `gen_board_pins.py`, `blockers.py`, `check_datasheets.py`, `ov_trip_worst_case.py`, `check_footprints.py`, `bench_package.py --doc`, `acceptance.py render`, `wheel_sensor_check.py`, `coastdown_sensitivity.py` (each with `--check`), `check_links.py`.
2. `fetch_csia.py`; `config_tool.py validate config/vehicle.synthetic.yaml --mode sim` must pass and `config_tool.py validate config/vehicle.unconfigured.yaml --mode hw` must fail.
3. C build and `ctest` with sanitizers (the build runs `config_tool.py blob` to make the calibration blobs).
4. Schematic connectivity gate: `gen_kicad_schematic.py --check`, then `git diff --exit-code` over `hardware/kicad` and `hardware/bom/BOM_draft.csv` (the netlist and its report excluded), so committed schematic files and the draft BOM must equal the generator's output.
5. `python -m pytest -rs -m controller` with `SEMMC_REQUIRE_MQTT=1` and `SEMMC_REQUIRE_ARM=1`. Through the tests this also runs `gen_kicad_schematic.py --check`, `timing_budget.py`, `price_bom.py`, `run_pit_replay.py` (on an empty database), the checks of `hw_consistency.py` (in memory), and functions of `run_host_demo.py`, `run_mqtt_demo.py`, `mqtt_broker.py`, `config_tool.py`, `bus_load.py`, `clock_tree.py`, `telematics_budget.py` and `gen_procurement.py`.
6. Legacy supervised demonstrations: `run_host_demo.py --legacy-supervised --out build/host_demo`, `run_mqtt_demo.py --legacy-supervised --out build/mqtt_demo`, then `run_pit_replay.py --db build/host_demo/pit.sqlite --run HOSTSIM-0001 --out build/pit_replay`.
7. Cortex-M4F cross-compile of the portable core (size per module), the linked STM32G474 target image and the emulated instruction counts (`emulate_core_timing.py`), the bench package.
8. Quick synthetic studies: `run_optimization.py --quick`, `run_electrical_calcs.py`, `run_csia_study.py`.

**`erc` job** (KiCad 8 from `ppa:kicad/kicad-8.0-releases`; the recorded runs used KiCad 8.0.9): `fetch_kicad_symbols.py`, `bash tools/run_kicad_erc.sh`, upload of `hardware/kicad/ERC_REPORT.*` as the `erc-report` artifact (whatever the result), then `erc_summary.py hardware/kicad/ERC_REPORT.json --fail-on-errors`.

**Not run in CI as commands:** `pin_type_check.py`, `hw_consistency.py` (so `CONSISTENCY_CHECK.md` is not rewritten), `clock_tree.py`, `hardware_calcs.py`, `telematics_budget.py`, `pin_allocation.py`, `can_bit_timing.py`, `bus_load.py`, `control_contract_report.py`, `make_replay_sample.py`, `run_policy_comparison.py`, `run_csia_evaluation.py`, `run_csia_evaluation_v2.py`, `run_csia_posthoc.py`, `verify_all.py`, and the generators in their writing form.

**CI detects a stale committed output only for** `scope.py`, `telematics_schema.py`, `claims.py`, `telematics_bom.py`, `telematics_bench.py render`, `telematics_storage.py`, `csia_disagreement_case.py`, `gen_config.py`, `gen_protocol.py`, `gen_dbc.py`, `gen_procurement.py`, `gen_board_pins.py`, `blockers.py`, `acceptance.py render`, `wheel_sensor_check.py`, `coastdown_sensitivity.py` (their `--check` forms), `release_gate.py` (its report is compared by `tests/hardware/test_release_gate.py`) and `gen_kicad_schematic.py` (the `git diff` gate). For every other tool that writes tracked files (section 4), CI does not notice a stale file: re-run the tool and commit its outputs yourself.

## 3. What `verify_all.py` runs

The `CHECKS` list in `verify_all.py`, in order. Commands run from the repository root; `python3` stands for the interpreter that runs `verify_all.py`.

| Check id | Group | Command | Mode |
|---|---|---|---|
| `gen_config` | generation | `python3 tools/gen_config.py --check` | both |
| `gen_protocol` | generation | `python3 tools/gen_protocol.py --check` | both |
| `gen_dbc` | generation | `python3 tools/gen_dbc.py --check` | both |
| `fetch_csia` | dependencies | `python3 tools/fetch_csia.py` | both |
| `cfg_synthetic_sim` | configuration | `python3 tools/config_tool.py validate config/vehicle.synthetic.yaml --mode sim` | both |
| `cfg_unconfigured_hw` | configuration | `python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw` (must fail) | both |
| `c_configure`, `c_build`, `ctest` | firmware | `cmake -S firmware -B build -G Ninja`, `cmake --build build`, `ctest --test-dir build --output-on-failure -V` | both |
| `property_soak` | firmware | `build/test_core_properties 100 30` | full only |
| `arm_configure`, `arm_build`, `arm_size` | portability | Cortex-M4F configure and build into `build-arm`, `arm-none-eabi-size -t build-arm/libsemmc_core.a` | both |
| `pytest` | python | `python3 -m pytest -rs -p no:cacheprovider` | both |
| `replay` | host simulation | `python3 host/replay/replay.py tests/simulation/replay_sample.semmc.log --out build/replay` | both |
| `contract_report` | host simulation | `python3 tools/control_contract_report.py --build build` | both |
| `telematics_scope`, `telematics_bom`, `telematics_bench_doc` | generation | `python3 tools/scope.py --check`, `python3 tools/telematics_bom.py --check`, `python3 tools/telematics_bench.py render --check` | both |
| `tm_configure`, `tm_build`, `tm_ctest` | telematics firmware | `cmake -S telematics/firmware -B build-telematics -G Ninja`, `cmake --build build-telematics`, `ctest --test-dir build-telematics --output-on-failure -V` | both |
| `tm_u575_configure`, `tm_u575_build` | telematics firmware | configure and build the NUCLEO-U575ZI-Q images into `build-u575` (README section 2) | both |
| `tm_storage` | telematics firmware | `python3 tools/telematics_storage.py --check --build build-telematics` | both |
| `tm_bench_package` | telematics firmware | `python3 tools/telematics_bench.py package --images build-u575 --out build/telematics_bench --rebuild --allow-dirty` (a working tree with changes is marked not valid for a recorded run) | both |
| `telematics_demo` | telematics | `python3 tools/run_telematics_demo.py --out build/telematics_demo` | both |
| `host_demo` | host simulation | `python3 tools/run_host_demo.py --legacy-supervised --out build/host_demo` | both |
| `pit_replay` | host simulation | `python3 tools/run_pit_replay.py --db build/host_demo/pit.sqlite --run HOSTSIM-0001 --out build/pit_replay` (uses the database from `host_demo`) | both |
| `mqtt_demo` | host simulation | `python3 tools/run_mqtt_demo.py --legacy-supervised --out build/mqtt_demo` | both |
| `optimisation_quick` | studies | `python3 tools/run_optimization.py --quick` | quick only |
| `optimisation_full` | studies | `python3 tools/run_optimization.py` | full only |
| `electrical` | studies | `python3 tools/run_electrical_calcs.py` | both |
| `csia_dev_study` | studies | `python3 tools/run_csia_study.py` | both |
| `policy_comparison` | studies | `python3 tools/run_policy_comparison.py --duration 300` | full only |
| `csia_eval_v1_rerun` | studies | `python3 tools/run_csia_evaluation.py` | full only |
| `wheel_sensor_check` | hardware | `python3 tools/wheel_sensor_check.py --check` | both |
| `coastdown_sensitivity` | studies | `python3 tools/coastdown_sensitivity.py --check` | both |
| `procurement_tables` | hardware | `python3 tools/gen_procurement.py --check` | both |
| `doc_links` | documentation | `python3 tools/check_links.py` | both |
| `kicad_connectivity` | hardware | `python3 tools/gen_kicad_schematic.py --check` | both |
| `kicad_drift` | hardware | `git diff --exit-code --stat -- hardware/kicad hardware/bom/BOM_draft.csv ':!hardware/kicad/semmc.net'` | both |
| `pin_type_check` | hardware | `python3 tools/pin_type_check.py` | both |
| `hw_consistency` | hardware | `python3 tools/hw_consistency.py` | both |
| `kicad_erc` | hardware | `bash tools/run_kicad_erc.sh` | both |
| `timing_budget` | hardware | `python3 tools/timing_budget.py` | both |
| `clock_tree` | hardware | `python3 tools/clock_tree.py` | both |
| `hardware_calcs` | hardware | `python3 tools/hardware_calcs.py` | both |
| `price_bom` | hardware | `python3 tools/price_bom.py` | both |
| `telematics_budget` | integration | `python3 tools/telematics_budget.py` | both |

Quick mode (the default) runs 35 of the 39 checks; `--full` runs 38 (it replaces `optimisation_quick` with `optimisation_full` and adds the property soak, the policy comparison and the CSIA v1 re-run). An exit code of 2 from `kicad_erc` (KiCad older than 8) or `mqtt_demo` (no Mosquitto) is recorded as NOT AVAILABLE instead of FAIL. Not in the list: `erc_summary.py`, `pin_allocation.py`, `can_bit_timing.py`, `bus_load.py` (only through pytest), `make_replay_sample.py`, `run_csia_evaluation_v2.py` and `run_csia_posthoc.py`.

## 4. Which tools write tracked files

### 4.1 Tools that write tracked files

After changing a tool's inputs (or the tool), re-run it and commit its outputs in the same change.

| Tool | Tracked files it writes |
|---|---|
| `telematics_schema.py` | `docs/TELEMETRY_SCHEMA.md` |
| `claims.py` | `docs/CLAIMS.md` |
| `gen_config.py` | `config/vehicle.schema.json`, `firmware/include/semmc/mc_params_generated.h` |
| `gen_protocol.py` | `protocol/generated/semmc_protocol.h`, `.c`, `.py`, `semmc_golden_vectors.c`, `protocol/golden_vectors/vectors.json`, `docs/generated/can_messages.md` |
| `gen_dbc.py` | `protocol/generated/semmc_base0x300.dbc` (another `--base` writes a new file) |
| `gen_procurement.py` | `docs/PROCUREMENT.md` (v0.6 combined table; since v0.7 no README block) |
| `gen_kicad_schematic.py` | `hardware/kicad/*.kicad_sch`, `semmc.kicad_sym`, `semmc.kicad_pro`, `sym-lib-table`, `hardware/bom/BOM_draft.csv`; with `--check` also `hardware/kicad/semmc.net`, `CONNECTIVITY_CHECK.md` |
| `pin_type_check.py` | `hardware/kicad/PIN_TYPE_CHECK.md` |
| `hw_consistency.py` | `hardware/review/CONSISTENCY_CHECK.md` |
| `price_bom.py` | `hardware/bom/BOM_priced.csv`, `docs/BUDGET.md`, `docs/generated/budget.json` |
| `timing_budget.py` | `hardware/timing/timing_budget.md`, `.json` |
| `clock_tree.py` | `hardware/timing/clock_tree_alternatives.md`, `.json` |
| `hardware_calcs.py` | `hardware/calculations/current_sense_error_budget.md`, `power_stage_envelope.md` |
| `pin_allocation.py` | `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`, `..._MBCETx.csv`, `..._RBCETx.csv`, `docs/generated/pin_allocation.md` |
| `wheel_sensor_check.py` | `docs/generated/wheel_sensor_check.md` |
| `coastdown_sensitivity.py` | `docs/generated/coastdown_sensitivity.md` |
| `can_bit_timing.py` | `docs/generated/can_bit_timing.md` |
| `telematics_budget.py` | `docs/generated/telematics_budget.md`, `.json` |
| `run_optimization.py` | `docs/generated/optimization_synthetic.md`, `.json`, `dp_schedule_synthetic.csv`, `dp_driver_guidance_synthetic.csv`, `dp_schedule_torque_only_flat_synthetic.csv`, `docs/figures/dp_plan_synthetic.png` |
| `run_policy_comparison.py` | `docs/generated/policy_comparison_host.md` |
| `run_electrical_calcs.py` | `docs/generated/electrical_calcs_synthetic.md`, `docs/figures/electrical_sensitivity_synthetic.png` |
| `run_csia_study.py` | `docs/generated/csia_comparison_synthetic.md` |
| `run_csia_evaluation.py` | `docs/generated/csia_evaluation_synthetic.md`, `.json` (frozen result; `--write-manifest` writes `docs/csia/DEV_SET_FREEZE.json`) |
| `run_csia_evaluation_v2.py` | `docs/generated/csia_v2_development_synthetic.*` (`--dev`), `docs/csia/V2_FREEZE.json` (`--freeze`), `docs/generated/csia_v2_evaluation_synthetic.*` (`--eval`, once) |
| `run_csia_posthoc.py` | `docs/generated/csia_posthoc_synthetic.md`, `.json` |
| `control_contract_report.py` | `docs/generated/control_contract_after.csv`, `docs/generated/control_contract_before_after.md` |
| `make_replay_sample.py` | `tests/simulation/replay_sample.semmc.log` |
| `gen_board_pins.py` | `firmware/platform/stm32g4/src/board_pins_generated.h`, `docs/generated/pin_af_verification.md` |
| `blockers.py` | `docs/BLOCKERS.md` |
| `acceptance.py render` | `docs/BENCH_ACCEPTANCE.md` |
| `release_gate.py` | `docs/generated/release_gate.md` (and, only when the gate passes, the package directory given with `--package`) |
| `emulate_core_timing.py` | only with `--out docs/generated/core_timing_emulated.md` |
| `run_host_demo.py`, `run_mqtt_demo.py` | only with `--samples docs/generated/host_demo` or `--samples docs/generated/mqtt_demo` (the committed samples) |

### 4.2 Tools that write nothing tracked

| Tool | Where it writes |
|---|---|
| `run_host_demo.py` and `run_mqtt_demo.py` (without `--samples`), `run_pit_replay.py` | under `build/` by default (`--out`) |
| `verify_all.py` | its record under `build/verify` by default; but the checks it runs rewrite tracked files (see below) |
| `config_tool.py` | `validate` writes nothing; `blob` writes the path given with `-o` (`build/cal/` in the C build) |
| `fetch_csia.py` | `.deps/csia-trust-layer/`, ignored by git |
| `run_kicad_erc.sh` | `hardware/kicad/ERC_REPORT.rpt` and `.json`, not tracked (CI keeps them as an artifact) |
| `erc_summary.py`, `bus_load.py`, `check_links.py` | standard output only (`erc_summary.py --md PATH` writes PATH) |

### 4.3 Side effects to know about

* **`gen_kicad_schematic.py --check` is not read-only.** It regenerates every schematic file and the draft BOM before comparing; drift is detected by the `git diff` that follows it.
* **`run_optimization.py --quick` writes to `build/optimization_quick/`** (since v0.5), so CI and the quick mode of `verify_all.py` no longer overwrite the committed full-resolution results in `docs/generated/` and `docs/figures/`. Only the full run (no `--quick`) rewrites the committed files; `--out DIR` sends either run elsewhere.
* **A local `pytest` run rewrites tracked files:** the hardware tests run `timing_budget.py`, `price_bom.py` and (when `kicad-cli` is installed) `gen_kicad_schematic.py --check`.
* **`verify_all.py` rewrites tracked files** through the checks it runs (the hardware reports, the studies, the control-contract report) and lists every one that changed in its record. Check that list before committing anything.
* Some outputs carry run-dependent values (wall-clock times in the optimisation and CSIA results, the host tick time in the CSIA development study, delays in the demonstration summaries), so a re-run can change them without a change in the method.
