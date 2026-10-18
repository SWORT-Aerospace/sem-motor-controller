# Python test suite (`tests/`)

The pytest suite for everything in the repository that runs on a host computer: the CAN (Controller Area Network) codecs and the DBC file (the common CAN database format read by other teams' tools), the C controller core through its host build, the telemetry chain (telematics node model, local log, MQTT, pit ingestion), the energy models, the experimental CSIA sensor-consistency diagnostic, the hardware draft's consistency checks and the documentation. MQTT (Message Queuing Telemetry Transport) is the publish and subscribe protocol of the uplink to the pit.

**Scope:** every test runs on a host against synthetic models, a synthetic plant and synthetic parameters. None is a hardware test in the sense of running on or measuring a built board; nothing has been built or energised. The C unit and property tests are not here: they live in [../firmware/tests/](../firmware/tests/) and run with `ctest` (section 6).

## 1. What the directory contains

```
tests/
  integration/       cross-module checks: codecs and DBC, C/Python configuration parity, end-to-end co-simulation,
                     host demonstration, MQTT pipeline, pit shadow replay, pit energy per distance, supervisor,
                     CAN bridge, MATH_SPEC, documentation
  fault_injection/   injected faults through the C core and the simulated plant; CSIA adapter behaviour and freeze manifests
  simulation/        tests of models/ (vehicle, inverter, DP optimiser, strategy simulator) and host replay of a recorded log
  hardware/          consistency of the hardware draft: netlist protection paths, pin allocation, timing budget, BOM pricing,
                     project procurement, clock tree, wheel-sensor arithmetic
```

The test configuration sits at the repository root: [../conftest.py](../conftest.py) (fixtures and the on-demand C build) and [../pytest.ini](../pytest.ini) (`testpaths = tests`, `addopts = -q`). There is no `__init__.py` in `tests/`; the root `conftest.py` puts the repository root on `sys.path` so that `models`, `protocol`, `host` and `tools` import as packages.

## 2. Who works here

Everyone who changes code: a change to firmware, protocol, host software, models, tools, hardware data or a current document is not finished until the tests that cover it pass. The continuous-integration workflow [../.github/workflows/ci.yml](../.github/workflows/ci.yml) runs `python -m pytest -rs` with `SEMMC_REQUIRE_MQTT=1` on every push and pull request, after installing KiCad (the open-source schematic and printed-circuit-board design suite) and the Mosquitto MQTT broker.

## 3. Important files

| File | What it does in the system | Inputs | Outputs |
|---|---|---|---|
| [../conftest.py](../conftest.py) | Puts the repository root on `sys.path` and provides the session fixtures `build_dir`, `host_exe`, `cfgcheck_exe` and `synthetic_blob`. The first test that needs one configures the C host build if `semmc_host` is missing and then runs an incremental `cmake --build`. | `SEMMC_BUILD_DIR`; `firmware/` sources; cmake, a C compiler, Ninja if present | a built `semmc_host`, `semmc_cfgcheck` and `cal/synthetic.bin` in the build directory |
| [../pytest.ini](../pytest.ini) | Sets `tests/` as the test path and `-q` as the default verbosity. | none | none |
| [integration/test_protocol_python.py](integration/test_protocol_python.py) | Checks the Python CAN codec: CRC-8 (cyclic redundancy check) value against an independent bitwise implementation, every golden vector round trip, byte-by-byte hand calculations from `protocol.yaml` (two `sup_torque_req` frames, one `ctrl_energy_quality` frame), negative values and sequence wrap, rejection of another major version and of malformed frames. Also requires `tools/gen_protocol.py --check` and `tools/gen_config.py --check` to pass and bus load to stay under 30 % with every worst-case response time below its period. | `protocol/generated/semmc_protocol.py`, `protocol/golden_vectors/vectors.json`, `tools/bus_load.py` | assertions only |
| [integration/test_dbc.py](integration/test_dbc.py) | Requires the committed DBC to be current and decodes every golden vector with an independent DBC parser (cantools) at block bases 0x300 and 0x500, within half a scaling step of the project codec; rejects an unaligned base. | `protocol/protocol.yaml`, `tools/gen_dbc.py`, cantools (the file is skipped if cantools is not installed) | assertions only |
| [integration/test_config_parity.py](integration/test_config_parity.py) | Encodes the synthetic vehicle configuration unchanged and with 37 single-value mutations and requires the Python validator and the C validator (`semmc_cfgcheck`) to report identical rule codes in simulation and hardware modes; checks that the unconfigured configuration fails, that a hardware CMake configure refuses the unconfigured (`MISSING_REQUIRED`) and synthetic (`PROVENANCE`) configurations, schema rejection of typos, and float32 rounding. | `config/*.yaml`, `tools/config_tool.py`, C build (`cfgcheck_exe`), cmake | temporary blobs and CMake trees in pytest's temporary directory |
| [integration/test_end_to_end.py](integration/test_end_to_end.py) | Runs the lockstep co-simulation (supervisor, Python encode, C core, plant, C encode, Python decode). Checks that every controller frame decodes, ECO assist (the supervised eco mode) engages only after the driver's mode-switch edge, speed is held at 6 m/s within 0.5 m/s with accepted torque inside the limit, loss of the supervisor returns to READY within the timeout with zero torque, requested and accepted torque are logged with reason bits, and controller and plant energy agree within 2 %. | `host/telemetry_adapter/e2e.py`, C build, `config/vehicle.synthetic.yaml` | `<build>/e2e/` |
| [integration/test_host_demo.py](integration/test_host_demo.py) | Runs the host demonstration (120 s of simulated time) once and requires every demonstration check to pass and the known CSIA power-balance mismatch to be reported. Unit-tests the STLG block log (the project's on-vehicle log format: round trip, corrupt block counted and skipped, truncated tail reported, full storage drops and counts), the telematics node (a flash stall drops records without blocking reception; the uplink backlog is bounded and replays are flagged), the UTC (coordinated universal time) estimator (quality, holdover bound, no value before the first PPS edges, the pulse-per-second output of the satellite receiver) and pit validation and de-duplication. | `tools/run_host_demo.py`, `host/telematics/`, `host/pit/ingest.py`, C build, pinned CSIA core | pytest temporary directory |
| [integration/test_mqtt_pipeline.py](integration/test_mqtt_pipeline.py) | Without a broker: live-message validation (types, consistency, schema v2 wheel speed and v3 temperatures with v1 and v2 still accepted), migration of an old pit database, the node's wheel-speed formula with staleness and unknown configuration reported as null, the node's temperatures (stale, invalid and NaN readings reported as null), recording of every receipt with its outcome, and the bounded uplink backlog. With a Mosquitto broker: a persistent session survives a killed broker; a broker that loses its state acknowledges messages the pit never receives; the 60 s MQTT demonstration passes all checks and accounts for every message. | `host/pit/`, `host/telematics/`, `tools/mqtt_broker.py`, `tools/run_mqtt_demo.py`, Mosquitto, C build and CSIA core for the demonstration | broker, database and demonstration files in pytest's temporary directory |
| [integration/test_shadow_replay.py](integration/test_shadow_replay.py) | Checks the pit-side shadow replay: the data class follows the run metadata (synthetic or measured), a measured run with missing signals reports insufficient evidence and no score, the command-line tool reports a missing run with exit code 2 and writes configuration notes into its report (vehicle configuration changed since the run, counting window missing from the run metadata), and the replay and pit-energy modules import nothing that could send a command (no MQTT, socket, CAN or serial imports and no telematics, bridge or co-simulation modules). | `host/pit/shadow_replay.py`, `host/pit/csia_replay.py`, `host/pit/energy.py`, `tools/run_pit_replay.py`, pinned CSIA core | report and timeline in pytest's temporary directory |
| [integration/test_pit_energy.py](integration/test_pit_energy.py) | Checks the pit's energy-per-distance calculation: the wheel-speed, watt-hour, Wh/km and nominal pack-energy formulas; the worked example in the root README against independent arithmetic and against `resistive_force`, `motor_torque_for_force` and `tractive_force` of the vehicle model; a run summary that reports energy gaps, missing wheel windows and an unknown window instead of filling them in; the cross-check between two wheel channels; and the energy file written by `tools/run_pit_replay.py`. | `host/pit/energy.py`, `host/pit/ingest.py`, `models/vehicle/longitudinal.py`, the root `README.md`, `tools/run_pit_replay.py`, pinned CSIA core (last test) | database and replay output in pytest's temporary directory |
| [integration/test_supervisor.py](integration/test_supervisor.py) | Checks that the supervisor requests bounded propulsion only from fresh controller speed: a stale speed (200 ms without a new sample) and repeated identical frames give zero torque with reason `telemetry_stale`; an invalid speed (NaN, not a number) gives zero torque and a coast request with reason `telemetry_invalid`, never zero or the last value; checks the pulse-and-coast hysteresis. | `host/telemetry_adapter/supervisor.py`, the Python codec | assertions only |
| [integration/test_vcu_bridge.py](integration/test_vcu_bridge.py) | Checks the proposed Linux SocketCAN bridge for a vehicle control unit (VCU): the 0x300 to 0x33F filter, classic-frame packing and decoding, rejection of CAN FD (flexible data-rate) and extended-identifier frames, CRC failure reported without values, translation of a relocated block (base 0x500) and rejection of an unaligned base. No CAN interface is needed. | `host/vcu_bridge/semmc_socketcan.py`, the Python codec | assertions only |
| [integration/test_math_spec.py](integration/test_math_spec.py) | Recomputes every numerical example in `docs/MATH_SPEC.md` (vehicle dynamics, motor and inverter, the transition of the dynamic-programming (DP) optimiser, CSIA power balance, telematics and protocol figures) with the implementing code, so a model change fails until the document is updated. | `models/`, `host/csia_adapter/adapter_v2.py`, `host/telematics/clocks.py`, the Python codec, `tools/bus_load.py` | assertions only |
| [integration/test_target_firmware.py](integration/test_target_firmware.py) | Builds the STM32G474 image and checks it without hardware: the vector table against ST's interrupt list, the memory layout and the reserved calibration area, no double-precision routine reachable from the current interrupt, every fault handler reaching the safe state, the fast step in an instruction-level emulator within half a PWM period (instruction counts), the bench reader's layout and the separate bench PWM image | `firmware/platform/stm32g4/`, `tools/emulate_core_timing.py`, `tools/bench_read.py`, arm-none-eabi-gcc, unicorn | the image in pytest's temporary directory |
| [integration/test_acceptance.py](integration/test_acceptance.py) | The acceptance and blocker documents are current; every procedure limit has a source or a pending reason and every configuration reference exists; the record checker accepts a complete record and rejects a wrong verdict, a pass against a pending limit, a step run after a failed stop limit, a missing evidence file, a missing witness and a step blocked by an open register entry | `tools/acceptance.py`, `tools/blockers.py`, `hardware/acceptance/procedures.yaml`, `docs/blockers.yaml` | records in pytest's temporary directory |
| [integration/test_docs.py](integration/test_docs.py) | Requires every Markdown link in tracked files to resolve (`tools/check_links.py`, with backtick paths checked in the current documents), checks the heading-slug rule, requires the generated wheel-sensor, procurement and coast-down documents to be current, forbids em dashes and assistant branding in the current documents, checks that the root README keeps its scope statements (host, proposed and physically tested kept apart; three diagrams; no budget fit claimed), and checks that `docs/FILE_INDEX.md` or `docs/README.md` (directly, by a glob, by a sibling file, or through a folder guide) covers every tracked file. | tracked Markdown files (`git ls-files`), `tools/check_links.py` and three generators | assertions only |
| [fault_injection/test_fault_injection.py](fault_injection/test_fault_injection.py) | 21 scenarios through the C core and the synthetic plant: gate-driver fault, hardware overcurrent, disconnected and stuck Hall sensors (stall detection), low-speed crawl not a stall, two missing phase currents, a biased current visible in the KCL (Kirchhoff current-law) residual, thermal derate then trip, lost temperature sensor derates, bus-voltage NaN, hill climb not a fault, brake override, invalid start-up, synthetic calibration on a hardware build, fault recovery without resume, cached supervisor sample, supervisor and controller reboots, bus-off, reordered, malformed and NaN supervisor frames. | `semmc_host`, `cal/synthetic.bin`, `host/logger/semmc_log.py`, `host/telemetry_adapter/e2e.py`, the Python codec | logs, CSV and frame files in pytest's temporary directory |
| [fault_injection/test_csia_adapter.py](fault_injection/test_csia_adapter.py) | Checks the CSIA vehicle adapter in shadow mode on synthetic scenarios: the pinned core (0.8.0) is used and restriction is not permitted, normal events raise no suspects, degraded GNSS (satellite navigation) is gated, six fault classes are attributed within their latency and never misattributed, uncorroborated disagreement stays ambiguous, freshness is reported apart from trust, a repeated sample does not renew, a reconstructed phase is not KCL evidence, a residual-threshold baseline raises nuisance alarms the adapter does not, and hostile advisory frames leave controller commands identical. | `host/csia_adapter/`, pinned CSIA core, C build (last test), the Python codec | co-simulation files in pytest's temporary directory |
| [fault_injection/test_csia_freeze.py](fault_injection/test_csia_freeze.py) | Requires the frozen CSIA v1 development and evaluation files to match the SHA-256 manifest `docs/csia/DEV_SET_FREEZE.json`, and the evaluation set to be deterministic, disjoint from the development seed and of the frozen size (24 nominal, 70 faulted). | `docs/csia/DEV_SET_FREEZE.json`, `host/csia_adapter/eval_set.py` | assertions only |
| [fault_injection/test_csia_v2_freeze.py](fault_injection/test_csia_v2_freeze.py) | Same for CSIA v2: files match `docs/csia/V2_FREEZE.json`, and the v2 development and evaluation seeds are disjoint from each other and from v1. | `docs/csia/V2_FREEZE.json`, `host/csia_adapter/eval_set_v2.py` | assertions only |
| [simulation/test_models.py](simulation/test_models.py) | Tests `models/`: force signs for grade, headwind, tailwind, cornering and coupled motor drag; coast-down identifiability on a wide speed range and its refusal on a narrow one; the synchronous-MOSFET conduction rule and the DC-link ripple formula against a switching simulation; loss trends; precharge and shunt figures; the measured loss map's refusal to extrapolate or double-count; DP feasibility, time-energy trade-off, mandatory stops, infeasible targets, bounded export, braking exported as driver guidance and never as coast; torque-only infeasibility on a descent into a corner; the simulator's absence of hidden braking, driver-model execution, late-driver overspeed, acceleration limit with energy reconciliation, motor friction power and bounded pace correction. | `models/` | schedule and guidance CSV files in pytest's temporary directory |
| [simulation/test_replay.py](simulation/test_replay.py) | Replays the recorded synthetic log through `semmc_host` and checks the state sequence, that duplicated and reordered supervisor frames have no effect, that a stale gap ends ECO and needs a new driver edge, that a NaN request ends ECO, that voltage sag and heat derate rather than fault, and that the brake zeroes torque. | `replay_sample.semmc.log`, `host/replay/replay.py`, C build | `<build>/replay_test/` |
| [simulation/replay_sample.semmc.log](simulation/replay_sample.semmc.log) | Fixture: a synthetic "recorded" log (driver inputs, measurements and supervisor CAN frames with their CRC bytes) for the replay test. Generated by `tools/make_replay_sample.py`; do not edit. | `tools/make_replay_sample.py`, which runs `semmc_host` once to learn the session tag | input of `simulation/test_replay.py` |
| [hardware/test_hw_consistency.py](hardware/test_hw_consistency.py) | Runs the protection-topology and cross-artefact checks of `tools/hw_consistency.py` on the committed KiCad netlist, and breaks one protection path at a time in a copy (missing enable pull-down, nFAULT off the break input, the microcontroller driving the gate-driver enable directly) to show each break is caught. | `hardware/kicad/semmc.net`, `tools/hw_consistency.py` | mutated netlists in pytest's temporary directory |
| [hardware/test_hardware_tools.py](hardware/test_hardware_tools.py) | Checks schematic connectivity against the intended nets (needs `kicad-cli`, skipped without it), phase-current sensing on three analogue-to-digital converters and two PWM (pulse-width modulation) break inputs in the pin allocation, two valid current-sampling phases and at least 200 ns dead time in the timing budget, and that every BOM (bill of materials) line has a price with an evidence class. | `tools/gen_kicad_schematic.py`, `tools/timing_budget.py`, `tools/price_bom.py`, `hardware/` data, `kicad-cli` | rewrites tracked files (section 4) |
| [hardware/test_clock_and_telematics.py](hardware/test_clock_and_telematics.py) | Regression checks of the clock-tree and telematics-budget calculations: an 8 MHz crystal reaches CAN FD 500 kbit/s / 2 Mbit/s at 80 % sample points with a 160 MHz CPU, every candidate tree has a feasible classic timing, phase-locked-loop settings stay in their published ranges, the dead-time code at 170 MHz, controller 394 and supervisor 72 frames/s and the log flash fill time (16 to 18 min). | `tools/clock_tree.py`, `tools/telematics_budget.py` | assertions only |
| [hardware/test_procurement.py](hardware/test_procurement.py) | Checks the project procurement file and the tables generated from it: the file validates and the root README table and `docs/PROCUREMENT.md` are current; the requested lines and categories are present; the motor-controller estimates reproduce the priced BOM (bill of materials) figures in `docs/generated/budget.json` without counting a line twice, and the README numbers follow that file; nothing is marked selected, ordered or received; a quote needs a dated source and cannot be mixed with an estimate reference; totals never count assembly or optional parts; unknown costs print TBD, never zero, and no fit within the budget is claimed. | `hardware/bom/procurement.yaml`, `hardware/bom/pricing.yaml`, `docs/generated/budget.json`, `tools/gen_procurement.py`, the root `README.md`, `docs/PROCUREMENT.md` | assertions only |
| [hardware/test_datasheets.py](hardware/test_datasheets.py) | The primary-document manifest renders current, lists the gate driver, battery meter and MCU first, and pins a received file by its hash without guessing its revision | `tools/check_datasheets.py` | files in pytest's temporary directory |
| [hardware/test_release_gate.py](hardware/test_release_gate.py) | The committed release-gate report is current and names conditions G1 to G7, and a failing gate builds no package | `tools/release_gate.py` | a package directory in pytest's temporary directory (only if the gate passed) |
| [hardware/test_wheel_sensor_check.py](hardware/test_wheel_sensor_check.py) | Checks the wheel-magnet detection arithmetic of `tools/wheel_sensor_check.py` against hand calculations and the datasheet sampling periods it quotes. | `tools/wheel_sensor_check.py` | assertions only |

### 3.1 The on-demand C build (`conftest.py`)

Tests that drive the C core ask for one of the session fixtures:

| Fixture | Value |
|---|---|
| `build_dir` | `SEMMC_BUILD_DIR`, default `<repository>/build`. If `<build>/semmc_host` does not exist, runs `cmake -S firmware -B <build>` (with `-G Ninja` when `ninja` is on `PATH`); then always runs `cmake --build <build>` once per session |
| `host_exe` | `<build>/semmc_host` (controller core + simulated plant, driven by log files) |
| `cfgcheck_exe` | `<build>/semmc_cfgcheck` (C configuration validator) |
| `synthetic_blob` | `<build>/cal/synthetic.bin` (synthetic calibration blob encoded by `tools/config_tool.py` during the build) |

A clean checkout therefore needs no manual build before `pytest`, only cmake and a C compiler. A failing configure or build stops the tests that need it with an error. The build uses the CMake defaults, including address and undefined-behaviour sanitizers (`SEMMC_SANITIZE=ON`).

### 3.2 Environment variables

| Variable | Effect |
|---|---|
| `SEMMC_BUILD_DIR` | build directory used by the fixtures; default `<repository>/build` |
| `SEMMC_MOSQUITTO` | path of the Mosquitto broker binary; otherwise `mosquitto` on `PATH`, then `/usr/sbin/mosquitto` (`tools/mqtt_broker.py`) |
| `SEMMC_REQUIRE_MQTT` | `1` turns a missing broker into a failure instead of a skip (set in CI) |
| `SEMMC_CSIA_PATH` | location of the CSIA core instead of `.deps/csia-trust-layer` (`host/csia_adapter/adapter.py`) |

### 3.3 External tools and what happens without them

| Missing | Affected tests | Result |
|---|---|---|
| Mosquitto broker | the four broker tests in `test_mqtt_pipeline.py` (two broker tests, two MQTT demonstration tests) | skipped with "no mosquitto binary ..."; with `SEMMC_REQUIRE_MQTT=1` they error at fixture setup. The tests of that file that need no broker always run |
| `kicad-cli` (KiCad) | `test_schematic_connectivity_matches_intent` in `test_hardware_tools.py` | skipped with "kicad-cli not installed" |
| cantools | `test_dbc.py` | whole file skipped (`pytest.importorskip`) |
| arm-none-eabi-gcc | `test_target_firmware.py` | skipped with the reason; with `SEMMC_REQUIRE_ARM=1` (set in CI) a failure |
| unicorn | `test_emulated_fast_step_fits_half_a_pwm_period` | skipped (`pytest.importorskip`) |
| pinned CSIA core (`python3 tools/fetch_csia.py`) | `test_csia_adapter.py`, `test_host_demo.py`, the tests of `test_shadow_replay.py` and `test_pit_energy.py` that run the pit replay (two and one), the MQTT demonstration tests | **fail** with `ImportError: pinned CSIA core not found`; they are not skipped |
| cmake or a C compiler | every test that uses `build_dir`, `host_exe`, `cfgcheck_exe` or `synthetic_blob`, and the hardware-configure tests of `test_config_parity.py` | error or fail |

## 4. Inputs and outputs of the directory

**Inputs:** the code and data under test (`firmware/` through the host build, `protocol/`, `host/`, `models/`, `tools/`, `config/`, `hardware/`, the current documents in `docs/`), the fixture log in `simulation/`, the pinned CSIA core in `.deps/`, the external programs of section 3.3 and the environment variables of section 3.2.

**Outputs:** the pytest report (pass, fail, skip with reason). Temporary files go to pytest's temporary directories, except `<build>/e2e/` (end-to-end test) and `<build>/replay_test/` (replay test) in the build directory.

**Side effect on tracked files:** the tests in `tests/hardware/` regenerate committed files: `tools/timing_budget.py` rewrites `hardware/timing/timing_budget.json` and `.md`; `tools/price_bom.py` rewrites `hardware/bom/BOM_priced.csv`, `docs/BUDGET.md` and `docs/generated/budget.json`; with `kicad-cli` present, `tools/gen_kicad_schematic.py --check` rewrites, in `hardware/kicad/`, the schematic sheets, symbol library, library table, project file, `semmc.net` and `CONNECTIVITY_CHECK.md`, and also `hardware/bom/BOM_draft.csv`. On a current tree the content is unchanged. A difference shown by `git status` after a run means the committed files were stale, or, for `semmc.net`, that a different KiCad version exported it (the file records the exporting tool's version).

## 5. Dependencies on other directories

* Python packages from [../requirements.txt](../requirements.txt): pytest, NumPy, PyYAML, jsonschema (schema validation in `tools/config_tool.py`), cantools (DBC test), paho-mqtt (MQTT client), kiutils (schematic generator). matplotlib is only used by study tools that no test runs.
* C toolchain for the host build: cmake, a C11 compiler, Ninja optional.
* The CSIA core, fetched once with `python3 tools/fetch_csia.py` into `.deps/csia-trust-layer` (pinned in `third_party/csia-trust-layer.lock`).
* Code under test: [../firmware/](../firmware/README.md), [../protocol/](../protocol/README.md), [../models/](../models/README.md), [../host/](../host/), [../tools/](../tools/README.md), [../config/](../config/), [../hardware/](../hardware/README.md), and the documents checked by `test_docs.py` and `test_math_spec.py`.

## 6. How to run

From the repository root, inside the virtual environment created from `requirements.txt`:

```sh
python3 tools/fetch_csia.py                       # once: pinned CSIA core into .deps/
python3 -m pytest -rs                             # whole suite; -rs prints the reason for every skip
python3 -m pytest tests/simulation                # one directory
python3 -m pytest tests/integration/test_dbc.py   # one file
python3 -m pytest tests/simulation/test_models.py::test_force_signs_and_wind                          # one test
python3 -m pytest "tests/integration/test_protocol_python.py::test_golden_vector_roundtrip[15-ctrl_energy_quality]"   # one parametrised case
python3 -m pytest tests/simulation -k coastdown   # tests whose name contains "coastdown"
python3 -m pytest --collect-only tests            # list every test identifier without running
```

`pytest.ini` already passes `-q`; adding another `-q` also hides the final summary line.

Separate build directory, and the MQTT tests with a broker that is not on `PATH`:

```sh
SEMMC_BUILD_DIR=/tmp/semmc-build python3 -m pytest tests/fault_injection
SEMMC_MOSQUITTO=/path/to/mosquitto SEMMC_REQUIRE_MQTT=1 python3 -m pytest -rs tests/integration/test_mqtt_pipeline.py
```

Broker installation: [../docs/MQTT_SETUP.md](../docs/MQTT_SETUP.md). On an x86-64 host with a warm build directory the whole suite took about 1.5 minutes, of which the MQTT file with a broker took about 30 s (it waits in real time, up to 10 s per step).

C unit and property tests (in [../firmware/tests/](../firmware/tests/), not part of pytest):

```sh
cmake -S firmware -B build -G Ninja && cmake --build build
ctest --test-dir build --output-on-failure        # all 8 registered C tests
ctest --test-dir build -R test_protocol           # one C test by name
```

[../tools/verify_all.py](../tools/verify_all.py) runs the generators' checks, ctest, pytest and the studies in one command and writes a verification record.

## 7. Generated files and fixtures

| File | Generated by | Regenerate with |
|---|---|---|
| `tests/simulation/replay_sample.semmc.log` | `tools/make_replay_sample.py` (learns the session tag from the controller's `ctrl_session` reply in a first pass) | `python3 tools/make_replay_sample.py`, needed when the controller's session-tag derivation, a `sup_*` message or the protocol major version changes. The tool uses `build/semmc_host` and `build/cal/synthetic.bin` in the default build directory (it ignores `SEMMC_BUILD_DIR`), so build there first |

Everything else in `tests/` is edited by hand. The golden vectors the protocol tests read are generated in `protocol/` ([../protocol/README.md](../protocol/README.md) section 7).

## 8. Current limitations

* All tests are host-only and use synthetic plants and parameters; they show software behaviour, not hardware behaviour. The `hardware/` tests check the internal consistency of a draft design, not a built board.
* A missing CSIA core makes several tests fail instead of skip (section 3.3).
* The `hardware/` tests rewrite tracked files as a side effect (section 4).
* Many expected values are tied to the synthetic parameters and to figures quoted in documents (for example the bus load of 12.6 % and the 394 and 72 frames/s), so changing a parameter means updating the document and the test together.
* `test_docs.py` link-checks only files listed by `git ls-files`: a new Markdown file is not checked until it is added to git, and the test needs the git metadata of the checkout.
* The MQTT broker tests depend on wall-clock timing against a local broker and can be slower or less stable on a loaded machine.
