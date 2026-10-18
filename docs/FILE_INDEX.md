# File index

Every file in the repository, by folder, with its role. Generated files and test fixtures are marked or grouped; build outputs (`build/`, `.deps/`, `.venv/`) are not part of the tree. The documents in `docs/` are listed with their status in [`README.md`](README.md) (current guides, verification results, research, historical records). Each folder has its own guide: [`telematics/firmware/`](../telematics/firmware/README.md), [`config/`](../config/README.md), [`firmware/`](../firmware/README.md), [`protocol/`](../protocol/README.md), [`host/`](../host/README.md), [`models/`](../models/README.md), [`hardware/`](../hardware/README.md), [`tools/`](../tools/README.md), [`tests/`](../tests/README.md).

Which suite each file belongs to (telematics, reference, deferred controller): [`generated/scope.md`](generated/scope.md).

Contents: [Repository root](#repository-root) · [telematics/](#telematics) · [config/](#config) · [firmware/](#firmware) · [protocol/](#protocol) · [host/](#host) · [models/](#models) · [hardware/](#hardware-hardware) · [tools/](#tools-tools) · [tests/](#tests)

## Repository root

| File | Role in the system |
|---|---|
| `README.md` | Front page: the telematics unit and its boundary with the controller, status, commands, bill of materials, connection guide, critical path |
| `CONTRIBUTING.md` | Team workflow: picking up work, branches and pull requests, who reviews what, rules for engineering data, hardware safety, documentation |
| `requirements.txt` | Pinned Python packages for every tool and test |
| `.gitignore` | Keeps build outputs, the fetched CSIA core, Python caches and the `.venv/` of the quick start out of git |
| `.github/workflows/ci.yml` | CI on GitHub-hosted runners: the `telematics` job (no controller build: telematics and reference suites with a broker, firmware unit tests, target images, the demonstration), the `controller` job (the deferred controller suite, its C build, legacy demonstrations, cross-compile, studies) and the `erc` job (KiCad 8 ERC) |
| `third_party/csia-trust-layer.lock` | Pinned commit and licence record of the CSIA core that `tools/fetch_csia.py` fetches into `.deps/`; frozen (listed in `docs/csia/V2_FREEZE.json`) |
| `conftest.py`, `pytest.ini` | Test configuration; see the tests section |
| `docs/` | Every document, with its status: [`docs/README.md`](README.md); records of earlier releases are in `docs/archive/` |


## telematics/

The telematics unit's firmware for the NUCLEO-U575ZI-Q ([`../telematics/firmware/README.md`](../telematics/firmware/README.md)). Built for the target and unit-tested on a computer; **never flashed, no connection bench-verified**. Build outputs (`build-telematics/`, `build-u575/`) are not part of the tree.

### telematics/firmware/

| File | Role in the system |
|---|---|
| `telematics/firmware/README.md` | Layout, commands, and the rules the firmware keeps (bounded interrupts and loops, no transmit path, counted losses) |
| `telematics/firmware/BENCH.md` | Build and flash commands, the connection table (unverified), bench steps B1 to B12 and electrical checks E1 to E6 before any vehicle bus |
| `telematics/firmware/CMakeLists.txt` | Host build (portable library under sanitizers, `tm_tests`, `tm_hostsim`) and, with `TM_TARGET_U575=ON`, the `tm_u575` and `tm_u575_can` images (`.elf`, `.bin`, `.hex`, map) |
| `telematics/firmware/cmake/arm-none-eabi-cortex-m33.cmake` | Cross toolchain file for the Cortex-M33 (single-precision hardware floating point) |

### telematics/firmware/include/ and src/ (portable, no hardware access)

| File | Role in the system |
|---|---|
| `telematics/firmware/include/tm_config.h` | Build-time sizes and periods: wheel channels, queue and CAN ring lengths, slot size, record and counter periods |
| `telematics/firmware/include/tm_time.h` | 64-bit time from a 32-bit timer with overflow, for interrupt and main-loop readers |
| `telematics/firmware/include/tm_le.h` | Little-endian field writers for record bodies |
| `telematics/firmware/include/tm_crc32.h`, `telematics/firmware/src/tm_crc32.c` | CRC-32 (the one STLG uses) |
| `telematics/firmware/include/tm_wheel.h`, `telematics/firmware/src/tm_wheel.c` | Wheel edge accumulator: edges, span and cumulative total per record, line level, overrun, heartbeat; the `WHEEL_EDGES` body |
| `telematics/firmware/include/tm_queue.h`, `telematics/firmware/src/tm_queue.c` | Bounded log queue with drop counter and high-water mark; single-producer ring for received CAN frames |
| `telematics/firmware/include/tm_stlg.h`, `telematics/firmware/src/tm_stlg.c` | STLG v1 header, block and record encoding, byte-for-byte as `host/telematics/stlg.py` |
| `telematics/firmware/include/tm_flashlog.h`, `telematics/firmware/src/tm_flashlog.c` | Slot-based log on any erasable storage behind a small interface: session header, blocks, resume after restart, full-storage handling, non-blocking erase and program steps |
| `telematics/firmware/include/tm_reset.h`, `telematics/firmware/src/tm_reset.c` | Reset cause from the reset flags and the `BOOT` record |
| `telematics/firmware/include/tm_counters.h` | Counter identifiers of the `COUNTERS2` record (must match `COUNTER2_IDS` in `host/telematics/stlg.py`) |
| `telematics/firmware/include/tm_app.h`, `telematics/firmware/src/tm_app.c` | The application: platform interface, frame and wheel records, counters, queue to blocks to storage, status line, flush and erase requests |
| `telematics/firmware/include/tm_bus.h` | Bus interface (write, read, write-then-read) shared by the I2C and SPI drivers and their test doubles |
| `telematics/firmware/include/tm_imu.h`, `telematics/firmware/src/tm_imu.c` | LSM6DSOX or ISM330DHCX IMU and TMP117 temperature drivers over the bus interface |
| `telematics/firmware/include/tm_w25q.h`, `telematics/firmware/src/tm_w25q.c` | W25Q SPI NOR driver as a storage back end for `tm_flashlog` (not wired into the images) |

### telematics/firmware/platform/host/ and tests/

| File | Role in the system |
|---|---|
| `telematics/firmware/platform/host/tm_fakeflash.h`, `telematics/firmware/platform/host/tm_fakeflash.c` | RAM model of the flash for host tests: erase sets 0xFF, programming a unit that is not erased is an error, operations take simulated time, a stall window keeps the device busy |
| `telematics/firmware/platform/host/tm_hostsim.c` | Host simulator: the firmware's own application code with a simulated clock, line levels and RAM flash, driven by a script on standard input (edges, overruns, frames, storage stalls, restarts, flush); not the target (interrupt and flash timing are not modelled); used by `tests/telematics/test_firmware_host.py` |
| `telematics/firmware/tests/test_tm.c` | Unit tests of the portable code: CRC-32, time extension, wheel records, queue, STLG blocks, reset causes, flash log, application |
| `telematics/firmware/tests/test_drivers.c` | Unit tests of the W25Q, IMU and TMP117 drivers against bus doubles |

### telematics/firmware/platform/u575/ (target only)

| File | Role in the system |
|---|---|
| `telematics/firmware/platform/u575/startup_stm32u575.c` | Vector table from ST's interrupt list, reset handler, fault handlers |
| `telematics/firmware/platform/u575/stm32u575zi_flash.ld` | Memory map: code in bank 1, the log region in bank 2 (1 MiB), RAM with a no-init section |
| `telematics/firmware/platform/u575/system_u575.c` | Clock: MSIS 4 MHz, LSE and MSI PLL mode when the LSE starts; PLL1 for the CAN kernel clock |
| `telematics/firmware/platform/u575/board_u575.c`, `telematics/firmware/platform/u575/board_u575.h` | Pins, TIM2 capture on three channels, LEDs, IWDG, reset flags |
| `telematics/firmware/platform/u575/drivers_u575.h` | Interfaces of the target drivers |
| `telematics/firmware/platform/u575/flash_u575.c` | Internal flash bank 2: page erase and quad-word programming as non-blocking steps; ECC error handling |
| `telematics/firmware/platform/u575/uart_u575.c` | USART1 console through the ST-LINK |
| `telematics/firmware/platform/u575/can_u575.c` | FDCAN1 receive in bus-monitoring mode (sends nothing), frames to the ring with receive time (the `tm_u575_can` image only) |
| `telematics/firmware/platform/u575/spi_u575.c` | SPI1 master with bounded waits |
| `telematics/firmware/platform/u575/i2c_u575.c` | I2C1 master with bounded waits |
| `telematics/firmware/platform/u575/main_u575.c` | Start-up, the TIM2 capture interrupt, the main loop, sensors, status line and console commands |
| `telematics/firmware/platform/u575/vendor/PROVENANCE.md` | Source, commit, SHA-256 and licence of each vendored header; the references the register code follows |
| `telematics/firmware/platform/u575/vendor/cmsis_core/Include/*.h`, `telematics/firmware/platform/u575/vendor/cmsis_core/LICENSE.md` | Arm CMSIS-Core 5.9.0 headers, unchanged |
| `telematics/firmware/platform/u575/vendor/cmsis_device_u5/Include/*.h`, `telematics/firmware/platform/u575/vendor/cmsis_device_u5/LICENSE.md` | ST cmsis-device-u5 v1.4.3 headers, unchanged |


## config/

Paths are relative to the repository root. The calibration blobs encoded from these files (`<build>/cal/synthetic.bin`, `<build>/cal/unconfigured.bin`) are build outputs, not part of the tree.

### config/

| File | Role in the system |
|---|---|
| `config/README.md` | Developer documentation for the configuration: registry fields, schema, synthetic and unconfigured files, generator and validator commands, generated files, and how a measured value enters. |
| `config/parameters.yaml` | Parameter registry, the single source of truth for every configuration parameter: blob identifier, kind, plausibility bounds, and whether it is required for a simulation or a hardware build. |
| `config/vehicle.schema.json` | Generated by `tools/gen_config.py` from `parameters.yaml` (do not edit): JSON Schema of the structure of `vehicle.*.yaml`, with every key required, nulls allowed and conventions fixed. |
| `config/vehicle.synthetic.yaml` | Synthetic configuration for host simulation, tests and models; every value is a placeholder, valid for `--mode sim` and invalid for `--mode hw`. |
| `config/vehicle.unconfigured.yaml` | Real-vehicle configuration, null until each value is measured or verified; fails `--mode hw` by design (93 issues at present) and records the team-reported battery values only in `battery.notes`. |

## firmware/

Paths are relative to the repository root. Build outputs (`<build>/cal/*.bin`, the `semmc_core` library, host executables and test binaries) are produced in the CMake build directory and are not part of the tree.

### firmware/

| File | Role in the system |
|---|---|
| `firmware/CMakeLists.txt` | Builds the portable `semmc_core` library (core sources plus the generated protocol codec), the host tools and the C tests; encodes the calibration blobs with `tools/config_tool.py` and registers the 8 ctest entries. Refuses a hardware build (`SEMMC_HARDWARE_BUILD=ON`) at configure time, after validating the vehicle configuration in hardware mode. |
| `firmware/README.md` | Developer documentation for the firmware: what the core does, state machine, interfaces, dependencies, build and test commands, generated files and limitations. |

### firmware/cmake/

| File | Role in the system |
|---|---|
| `firmware/cmake/arm-none-eabi-cortex-m4f.cmake` | Toolchain file for the Cortex-M4F (STM32G4 class) portability compile of `semmc_core` with `SEMMC_PORTABLE_ONLY=ON`; proves the core has no host dependencies and gives its code size, but produces no firmware image. |

### firmware/include/semmc/

| File | Role in the system |
|---|---|
| `firmware/include/semmc/mc_core.h` | Public API of the controller core: init, slow step, fast step, transport-neutral message RX/TX, link state, and the CAN binding functions; defines the slow and fast input structs, the slow-to-fast handoff and the `mc_core_t` state. |
| `firmware/include/semmc/mc_types.h` | Shared types: 64-bit microsecond time, per-signal validity flags (`MC_VAL_*`) with `mc_valid`/`mc_usable`, build kind (host simulation or hardware), sign conventions and small float helpers. |
| `firmware/include/semmc/mc_state_machine.h` | States, owners, transition ids (`MC_T_*`), command reason bits (`MC_R_*`), wired driver inputs, supervisor input and arbiter structs, and the invariants I1 to I9 that the tests check. |
| `firmware/include/semmc/mc_control.h` | Motor-control primitives and their conventions: PI controller, Clarke/Park transforms, measured versus reconstructed phase currents, voltage and current limits, SVPWM, FOC loop and Hall decoder interfaces. |
| `firmware/include/semmc/mc_freshness.h` | Freshness, sequencing and time-domain rules for received data (new-sample definition, ordering floor, lag tolerance with re-anchoring, wraparound), result codes and the 32-to-64-bit time extension. |
| `firmware/include/semmc/mc_protection.h` | Software fault list (`mc_fault_t`), derate reasons, protection inputs and state, and timing constants (undervoltage debounce, derate recovery and hold, stall detection). |
| `firmware/include/semmc/mc_io.h` | Measurement scaling and plausibility for the board's inputs: NTC conversion with open/short detection, two-track pedal with range and agreement checks, phase-current and bus-voltage scaling, boot offset self-test, low-side sampling window, driver-enable path check. |
| `firmware/include/semmc/mc_precharge.h` | Precharge sequencing: states, completion and timeout rules, failure detection after the bypass closes, what is not detected. |
| `firmware/include/semmc/mc_startup.h` | Power-stage start-up sequence for this board: precharge with the battery-current cross-check, gate-driver wake after the bypass closes, offsets with the driver awake, arm permission, fault attempts and lockout. |
| `firmware/include/semmc/mc_drv835x.h` | DRV8353 driver logic with every device constant in a verified description: wake, configure, read back, clear on request, status supervision. |
| `firmware/include/semmc/mc_ina228.h` | INA228 driver logic with every device constant in a verified description: reset, identity, configure and read back, conversion polling, sample age and validity. |
| `firmware/include/semmc/mc_periph_timing.h` | Register timing values computed from clock frequencies: FDCAN nominal bit timing, TIM1 centre-aligned ARR, dead-time generator encoding. |
| `firmware/include/semmc/mc_config.h` | Calibration blob format v1, validator rule codes shared with `tools/config_tool.py`, raw configuration and typed parameter structs (`mc_params_t`), and the physical-output gate. |
| `firmware/include/semmc/mc_crc.h` | CRC-8/SAE-J1850 (with data-ID seeding) and CRC-32 interfaces; CRC-32 protects the calibration blob. |
| `firmware/include/semmc/mc_csia_shadow.h` | Controller-side CSIA advisory tracker interface, shadow mode only; `mc_csia_may_restrict()` is the single future gate and returns false in v0.1. |
| `firmware/include/semmc/mc_params_generated.h` | GENERATED by `tools/gen_config.py` from `config/parameters.yaml` (do not edit): blob parameter ids, enumerations and the per-parameter kind, required-flag and range table used by the C validator. |

### firmware/src/core/

| File | Role in the system |
|---|---|
| `firmware/src/core/mc_core.c` | Wires all subsystems for one motor: supervisor session and tags, frame decoding and freshness, energy integration with gap accounting, protection, state machine and arbiter in the slow step, Hall/current/FOC in the fast step, and scheduling and encoding of the 12 controller messages. |

### firmware/src/state_machine/

| File | Role in the system |
|---|---|
| `firmware/src/state_machine/mc_state_machine.c` | Operating state machine (BOOT to FAULT_LATCHED, transitions T1 to T18): edge detection on wired controls, throttle latch, torque ownership, fault latching and reset. |
| `firmware/src/state_machine/mc_arbiter.c` | Torque arbitration through layers L0 to L4 (hardware shutdown, immediate inhibits, local hard ceilings, supervisory envelope, owner request with slew); outputs accepted torque, `iq_ref`, PWM enable and reason bits. |

### firmware/src/telemetry/

| File | Role in the system |
|---|---|
| `firmware/src/telemetry/mc_freshness.c` | Freshness trackers that decide whether a received frame renews validity; rejects duplicates, reordered frames, cached samples and delayed or jumped source times; provides `mc_time_extend`. |

### firmware/src/control/

| File | Role in the system |
|---|---|
| `firmware/src/control/mc_foc.c` | One FOC current-loop update: dq currents, d-priority PI with decoupling feed-forward, voltage limit, inverse Park and SVPWM duties; inhibits outputs on invalid inputs or time step. |
| `firmware/src/control/mc_pi.c` | PI controller with conditional-integration anti-windup and time-step rejection, plus the `mc_slew` rate limiter and angle wrap used by the arbiter and Hall code. |
| `firmware/src/control/mc_transforms.c` | Clarke and Park transforms, resolution of measured versus KCL-reconstructed phase currents, voltage and current vector limits, and min-max SVPWM. |
| `firmware/src/control/mc_hall.c` | Hall-sensor sector decoding, period-based speed, intra-sector angle interpolation and Hall fault detection (persistent illegal codes or sector skips). |

### firmware/src/protection/

| File | Role in the system |
|---|---|
| `firmware/src/protection/mc_protection.c` | Software fault detection and latching (bus voltage, temperatures, speed, Hall, current sense, throttle, stall, mirrored hardware trips), derating with immediate drop and slow recovery, fault reset and speed-taper factor. |

### firmware/src/calibration/

| File | Role in the system |
|---|---|
| `firmware/src/calibration/mc_config.c` | Boot-time calibration blob parser, configuration validator with rule codes shared with the Python tool, derivation of typed parameters, and the only gate for physical power-stage output. |
| `firmware/src/calibration/mc_crc.c` | CRC-8/SAE-J1850 and CRC-32 (zlib) implementations; CRC-32 checks the calibration blob (CAN payload CRCs are computed by the generated codec). |

### firmware/src/transport/

| File | Role in the system |
|---|---|
| `firmware/src/transport/mc_can_binding.c` | CAN binding of the transport-neutral core: maps protocol numbers 0x300 to 0x33F onto the calibrated 11-bit identifier block (`supervision.can_id_base`), counts foreign identifiers and forwards bus-off reports. |

### firmware/src/io/

| File | Role in the system |
|---|---|
| `firmware/src/io/mc_io.c` | Implementation of `mc_io.h` (portable; host-tested by `firmware/tests/test_io.c`). |
| `firmware/src/io/mc_precharge.c` | Implementation of `mc_precharge.h`. |
| `firmware/src/io/mc_periph_timing.c` | Implementation of `mc_periph_timing.h`. |
| `firmware/src/io/mc_startup.c` | Implementation of `mc_startup.h` (host-tested by `firmware/tests/test_drivers.c`). |
| `firmware/src/io/mc_drv835x.c` | Implementation of `mc_drv835x.h`. |
| `firmware/src/io/mc_ina228.c` | Implementation of `mc_ina228.h`. |

### firmware/src/csia_adapter/

| File | Role in the system |
|---|---|
| `firmware/src/csia_adapter/mc_csia_shadow.c` | Shadow-mode tracker for `csia_advisory` frames: freshness kept separate from content, restricting-mode claims counted, never changes a torque command. |

### firmware/platform/host/

| File | Role in the system |
|---|---|
| `firmware/platform/host/host_main.c` | Host-only `semmc_host` executable: closed-loop simulation, log replay and interactive lockstep co-simulation with the Python supervisor; writes a CSV trace and the transmitted CAN frames. |
| `firmware/platform/host/sim_plant.c` | Host-only synthetic plant (dq PMSM with averaged inverter, vehicle road load, battery, thermal models, noisy sensors, fault injection) used by the host tools and tests; not a validated model. |
| `firmware/platform/host/sim_plant.h` | Interface, scope and stated limitations of the simulated plant, its constants, fault-injection settings and sensor outputs. |
| `firmware/platform/host/contract_report_main.c` | Host-only `semmc_contract_report`: runs control-contract scenarios A1 to A6 (arbiter) and B1 to B4 (core through CAN and plant) and checks each update against an independent oracle; used by `tools/control_contract_report.py`. |
| `firmware/platform/host/cfgcheck_main.c` | Host-only `semmc_cfgcheck`: runs the C configuration validator on a blob and prints rule codes, so `tests/integration/test_config_parity.py` can compare them with the Python validator. |

### firmware/platform/stm32g4/

| File | Role in the system |
|---|---|
| `firmware/platform/stm32g4/README.md` | The STM32G474 target firmware: build, status table (compiled / checked / emulated / bench-tested), structure, interrupts, safety behaviour, open items. |
| `firmware/platform/stm32g4/FLASHING.md` | Writing the image and the calibration blob, boot report, reading `g_bench` with `tools/bench_read.py`. |
| `firmware/platform/stm32g4/stm32g474xe_flash.ld` | Linker script: flash, SRAM and CCM regions from ST's template; last 4 KB of flash reserved for the calibration blob; reset-surviving `.noinit`. |
| `firmware/platform/stm32g4/src/*.c`, `firmware/platform/stm32g4/src/*.h` | Target drivers and start-up, one pair per function (listed in the platform README's structure table); `board_pins_generated.h` is written by `tools/gen_board_pins.py`. |
| `firmware/platform/stm32g4/timing/*` | Emulation-only harness and its memory layout for `tools/emulate_core_timing.py`; not a flashable image. |
| `firmware/platform/stm32g4/vendor/*` | ST's CMSIS device header for the STM32G474 and the CMSIS-Core headers, copied unchanged with their licences; sources and commits in `vendor/PROVENANCE.md`. |

### firmware/tests/

| File | Role in the system |
|---|---|
| `firmware/tests/test_control.c` | Unit tests of transforms, current resolution, PI anti-windup and time-step handling, voltage and current limits, SVPWM, Hall decoding and slew. |
| `firmware/tests/test_freshness.c` | Unit tests of the freshness rules: duplicates, repeated samples, reordering, wraparound, source reboot, clock domain, resync, delayed-sample re-anchoring, creeping delay and time extension. |
| `firmware/tests/test_config.c` | Tests of CRC check values, blob parsing and corruption rejection, synthetic versus hardware validation, and one mutation per validator rule. |
| `firmware/tests/test_state_machine.c` | Tests of state machine invariants and arbiter behaviour, including the control-contract cases (hard ceiling clamps on the same update, bounded envelope ramp). |
| `firmware/tests/test_protocol.c` | Tests of the generated codec: golden vectors, malformed and wrong-ID frames, NaN and saturation handling, and the 64-number identifier block. |
| `firmware/tests/test_core.c` | Closed-loop tests of the core with the generated codec and simulated plant: FOC tracking, ECO handshake and loss, bus-off, reboot, limits sets, reconstructed phase, overcurrent, telemetry validity, energy gaps and CAN block relocation. |
| `firmware/tests/test_core_preemption.c` | The current interrupt preempting the slow step, emulated with `ld --wrap`: an overcurrent raised between the slow step's read and clear is kept and latches. |
| `firmware/tests/test_io.c` | `src/io`: NTC, pedal, ADC scaling and offsets, sampling window, enable path, precharge sequences, CAN bit timing, TIM1 ARR and dead time. |
| `firmware/tests/test_drivers.c` | INA228 and DRV8353 driver logic against simulated devices with invented test register maps (bus errors, identity, read-back, ageing, fault clearing), and the start-up sequence (order, stale or disagreeing measurements, timeouts, disconnect, attempts and lockout). |
| `firmware/tests/test_core_properties.c` | Randomised property test (P1 to P8) with an adversarial supervisor, random driver and reboots through the real CAN binding; arguments `[n_seeds [seconds [base_seed]]]`, run by ctest at 6 x 12 s and 24 x 12 s. |
| `firmware/tests/mc_test.h` | Minimal dependency-free test harness (`CHECK`, `CHECK_NEAR`, `CHECK_EQ_INT`, `RUN`, summary line). |
| `firmware/tests/test_support.h` | Shared test helpers that load the build-time calibration blobs and derive the synthetic parameters. |

## protocol/

Paths are relative to the repository root. `protocol/protocol.yaml` is the only hand-edited specification; everything listed as generated is rewritten by the generators and must not be edited. `docs/generated/can_messages.md` is also written by `tools/gen_protocol.py` and is indexed under `docs/`.

### protocol/

| File | Role in the system |
|---|---|
| `protocol/README.md` | Developer documentation for the semmc CAN protocol: message set, frame layout, CRC and sequence rules, codec interfaces, generated files, the spec-hash and version rule, and how to change a message safely. |
| `protocol/protocol.yaml` | Single source of the CAN contract (version 1.1): 16 messages with 11-bit identifiers in the 0x300 to 0x33F block, sender, period and field layout with scaling and invalid sentinels, plus the inputs of the 19 golden vectors. Any edit, including a comment, changes the spec hash and requires regeneration. |
| `protocol/__init__.py` | Empty package marker so `protocol.generated.semmc_protocol` can be imported. |

### protocol/generated/

| File | Role in the system |
|---|---|
| `protocol/generated/__init__.py` | Empty package marker (maintained, not generated). |
| `protocol/generated/semmc_protocol.h`, `protocol/generated/semmc_protocol.c`, `protocol/generated/semmc_protocol.py`, `protocol/generated/semmc_golden_vectors.c` | C codec compiled into the controller core, the Python codec used by host software, tools and tests (same arithmetic, identical bytes), and the C golden-vector self-check linked into `test_protocol`. Generated by `tools/gen_protocol.py` from `protocol/protocol.yaml`; do not edit. |
| `protocol/generated/semmc_base0x300.dbc` | DBC description of the 16 messages at identifier base 0x300 for other teams' CAN tools, cross-checked with cantools. Generated by `tools/gen_dbc.py` from `protocol/protocol.yaml`; do not edit. |

### protocol/golden_vectors/

| File | Role in the system |
|---|---|
| `protocol/golden_vectors/vectors.json` | Expected bytes, saturation and invalid flags and decoded values of the 19 golden vectors, read by the Python round-trip test. Generated by `tools/gen_protocol.py` from `protocol/protocol.yaml`; do not edit. |

## host/

Paths are relative to the repository root. `__init__.py` files and `__pycache__/` are not listed. No source file in `host/` is generated; the run outputs of the demonstrations (`run.stlg`, `pit.sqlite`, reports) are written under each tool's `--out` directory, outside the tree.

### host/

| File | Role in the system |
|---|---|
| `host/README.md` | Developer documentation for the Python host side: contents, important files with inputs and outputs, data flow from controller frames to the shadow replay report, dependencies, run and test commands, frozen files and limitations. |

### host/telematics/

| File | Role in the system |
|---|---|
| `host/telematics/node.py` | Host model of the receive-only telematics unit: timestamps controller frames and decodes them through an adapter, logs every frame and sensor sample through a bounded queue, keeps the latest measurement per signal, and sends the 2 Hz `sem.telemetry.v4` summary with a bounded, flagged backlog; also the in-process link `SimLink`. No transmit path. |
| `host/telematics/measurement.py` | The measurement record (source, signal, unit, receive and sample time, uncertainty, source sequence, validity, provenance) and the latest-value table behind the live summary. |
| `host/telematics/signals.py` | Signal registry: identity, unit, origin, role, range and staleness limit of every reported quantity; its identifier names it in live messages. |
| `host/telematics/controller_adapter.py` | Controller adapters: the semmc simulation fixture (CRC, sequence, validity flags), a DBC adapter with a unit-checked mapping, and a null adapter. |
| `host/telematics/wheel.py` | Wheel speed and distance from edge timing, with standstill only on positive evidence and lower bounds after lost edges; the reference for the firmware's records. |
| `host/telematics/sim_vehicle.py` | Simulated vehicle and external controller for the demonstration: broadcast frames, wheel edges, GNSS, IMU, temperatures, battery monitor, with injectable faults. |
| `host/telematics/stlg.py` | Reference implementation of the STLG v1 local log format (metadata header, 4 KiB CRC-checked blocks, record types 1 to 13), with a non-blocking writer and a reader that counts corrupt blocks, gaps and truncation. |
| `host/telematics/clocks.py` | Clock-domain models of the simulation (controller time, drifting telematics clock, GNSS PPS edges) and the estimator that maps telematics time to UTC with quality `pps`, `holdover` or `none`. |
| `host/telematics/sensors.py` | Synthetic wheel Hall (counts per window), GNSS and IMU sensors of the legacy supervised demonstrations, with injectable wheel dropouts and GNSS outages. |
| `host/telematics/mqtt_link.py` | Drop-in uplink over a real MQTT broker (paho-mqtt, QoS 1, bounded client buffer) that records hand-over and broker acknowledgement per sequence number. |

### host/pit/

| File | Role in the system |
|---|---|
| `host/pit/ingest.py` | Pit validation and storage into one SQLite file: checks every live message (`sem.telemetry.v1` to `v4`) and records each receipt with its outcome, and imports STLG logs with PPS-derived UTC, measurements through the logged adapter, and an accounting of every record; every key is idempotent. |
| `host/pit/mqtt_ingest.py` | Pit ingestion service process: MQTT subscriber with a persistent session that validates and commits each message through `ingest.py` before acknowledging it, and logs connection events. |
| `host/pit/shadow_replay.py` | Shadow replay of the frozen B1, R3v and CSIA2 monitors over one stored run, with run classification, input coverage, attribution episodes and insufficient-evidence notes; writes `report.md`, `report.json`, `timeline.csv` and has no command path. |
| `host/pit/csia_replay.py` | Rebuilds the monitors' input samples from a run's decoded signals (shared with the shadow replay) and replays the frozen v1 CSIA adapter with host timing figures. |
| `host/pit/energy.py` | Energy from valid, aligned V x I at the controller input and at the battery, with missing intervals, their causes and a bound; distance from wheel edges; the earlier energy per distance from the controller's counter; used by `tools/run_pit_replay.py` and the demonstration. |

### host/telemetry_adapter/

| File | Role in the system |
|---|---|
| `host/telemetry_adapter/legacy_node.py` | The v0.6 supervised telematics node (ECO supervisor before logging, `sem.telemetry.v3`): a legacy research simulation, run only by the legacy demonstrations with `--legacy-supervised`. |
| `host/telemetry_adapter/supervisor.py` | The supervisor: session handshake, periodic bounds and torque requests encoded with the generated codec, rejection of stale, repeated or invalid speed, re-handshake after a controller reboot, and two test policies (speed hold, pulse-and-coast). |
| `host/telemetry_adapter/cosim.py` | Lockstep co-simulation driver for the C host executable `semmc_host --interactive`: sends events and supervisor frames, steps the controller and reads back its frames and state. |
| `host/telemetry_adapter/e2e.py` | End-to-end synthetic scenario runner (supervisor, both codecs, C core, simulated plant) used by the end-to-end, fault-injection and CSIA shadow tests and the policy comparison. |

### host/csia_adapter/

All files below are frozen: their SHA-256 hashes are listed in `docs/csia/V2_FREEZE.json` and checked by `tests/fault_injection/test_csia_v2_freeze.py`.

| File | Role in the system |
|---|---|
| `host/csia_adapter/adapter.py` | Frozen v1 CSIA vehicle adapter: wraps the pinned TrustCore with vehicle sensor relationships and reports freshness, evidence, observability, trust and attribution in shadow mode only. |
| `host/csia_adapter/adapter_v2.py` | Frozen v2 adapter (CSIA2): v1 with a time-aligned power balance and copper, switching and fixed loss model, plus the least-squares calibration of that model. |
| `host/csia_adapter/baselines.py` | Frozen comparison monitors: B1 range, NaN and freshness checks, and B2 fixed-threshold residuals. |
| `host/csia_adapter/synthetic.py` | Frozen synthetic development scenario generator (seed 7) and the synthetic adapter parameters. |
| `host/csia_adapter/eval_set.py` | Frozen v1 held-out scenario generator (unseen seeds, randomised drive profiles and faults). |
| `host/csia_adapter/eval_set_v2.py` | Frozen v2 scenario generator with temperature-dependent copper loss and speed-hold segments; separate development and evaluation seed sets. |
| `host/csia_adapter/evaluation.py` | Frozen v1 evaluation harness: monitor variants, threshold calibration on development data and per-scenario metrics. |
| `host/csia_adapter/evaluation_v2.py` | Frozen v2 evaluation harness with one shared 3-tick persistence filter; defines R3v (calibrated residuals with majority-vote attribution), CSIA2 and the other v2 monitors. |

### host/logger/

| File | Role in the system |
|---|---|
| `host/logger/semmc_log.py` | semmc-log v1 text event format: builds scenario logs for the C host executable and decodes the controller's transmitted frames with the generated Python codec. |

### host/replay/

| File | Role in the system |
|---|---|
| `host/replay/replay.py` | Command-line replay of a recorded semmc-log through the C core without the simulated plant by default, tabulating requested against accepted torque with decoded reasons. |

### host/vcu_bridge/

| File | Role in the system |
|---|---|
| `host/vcu_bridge/semmc_socketcan.py` | Optional Linux SocketCAN bridge (proposal, not run on any vehicle): filters and translates the semmc identifier block, decodes classic frames and sends supervisor frames. |

## models/

Paths are relative to the repository root. Every parameter set in this directory is SYNTHETIC. Nothing here is generated; the reports produced from these models live in `docs/generated/`, `docs/figures/` and `hardware/calculations/` and are indexed there.

### models/

| File | Role in the system |
|---|---|
| `models/README.md` | Developer documentation for the energy and powertrain models: force terms and sign conventions, power map, inverter losses, DP optimiser and strategies, how to run them, outputs and limitations. |
| `models/__init__.py` | Empty package marker so the tools and tests can import `models.*`. |

### models/vehicle/

| File | Role in the system |
|---|---|
| `models/vehicle/__init__.py` | Empty package marker. |
| `models/vehicle/longitudinal.py` | Longitudinal vehicle model: `VehicleParams` with effective mass and the gear-ratio convention (motor speed / wheel speed), `resistive_force` (rolling, aerodynamic, grade, cornering, drivetrain and coupled-motor drag), `tractive_force` and `motor_torque_for_force`, and the coast-down tools `fit_coastdown` (road-load coefficients with an identifiability verdict) and `simulate_coastdown`. Holds `SYNTHETIC_VEHICLE`. |
| `models/vehicle/powertrain.py` | Battery-terminal power maps: `SyntheticPhysicsMap` (motor copper, iron and friction loss, inverter loss, auxiliary load per mode) and `MeasuredLossMap` (bilinear interpolation of a measured loss CSV, no extrapolation), each declaring which losses it includes; `check_no_double_counting`. Holds the synthetic motor, MOSFET and gate-driver parameters. |

### models/inverter/

| File | Role in the system |
|---|---|
| `models/inverter/__init__.py` | Empty package marker. |
| `models/inverter/losses.py` | First-order calculations for a two-level three-phase MOSFET inverter: conduction, switching, output-capacitance, gate-drive, dead-time and reverse-recovery losses, DC-link ripple, precharge, junction temperature, shunt sizing and fuse checks. Used by the power map and by `tools/run_electrical_calcs.py` and `tools/hardware_calcs.py`. |

### models/optimization/

| File | Role in the system |
|---|---|
| `models/optimization/__init__.py` | Empty package marker. |
| `models/optimization/track.py` | Track description for the optimiser and simulator: per-lap grade and curvature segments, stops and corner speed limits; `synthetic_track()` (1.5 km lap, 4 laps) and its flat variant. |
| `models/optimization/dp.py` | Offline spatial dynamic-programming optimiser: minimum battery-terminal energy for a finish-time target with coast, propulsion and driver braking as separate actuators; reports infeasibility with a reason; exports the bounded controller schedule and the driver braking guidance as CSV. |
| `models/optimization/strategies.py` | Common time-domain simulator for all strategies (torque bound, slew and acceleration limit, driver braking model with brake override, violation counting, energy reconciliation) and the controllers it runs: constant speed, pulse-and-coast, DP schedule follower, baseline braking cues and bounded pace correction. |

## Hardware (`hardware/`)

### `hardware/`

| File | Role in the system |
|---|---|
| `hardware/README.md` | Entry point to the hardware: the telematics BOM, then the deferred motor-controller draft (sheets, important files, what is confirmed and unresolved, checks, generated files, limitations). |
| `hardware/telematics/bom.yaml` | Telematics bill of materials, configurations A and B: every line with quantity, price range, dated source and decision; `tools/telematics_bom.py` renders `docs/TELEMATICS_BOM.md`. |

### `hardware/bom/`

| File | Role in the system |
|---|---|
| `hardware/bom/README.md` | Explains the BOM files and their status; nothing is order-ready or purchased. |
| `hardware/bom/pricing.yaml` | Hand-maintained price evidence per draft BOM line (evidence class, source, retrieval date, availability, alternates) plus project items, equipment, spares and revision allowance; input to `tools/price_bom.py`. |
| `hardware/bom/procurement.yaml` | Hand-maintained single source of the project procurement lines (motor controller, telemetry, shared wiring, development equipment, recurring connectivity); estimated lines reference `docs/generated/budget.json`; `tools/gen_procurement.py` turns it into the README budget table and `docs/PROCUREMENT.md`. |
| `hardware/bom/BOM_candidates.csv` | The v0.1 conditional BOM, superseded by the draft and priced BOMs and kept as a record. |
| `hardware/bom/BOM_draft.csv`, `hardware/bom/BOM_priced.csv` | Draft BOM grouped from the schematic data, and the same lines with price ranges, evidence and availability. Generated by `tools/gen_kicad_schematic.py` (draft) and `tools/price_bom.py` (priced); do not edit. |

### `hardware/acceptance/`

| File | Role in the system |
|---|---|
| `hardware/acceptance/procedures.yaml` | Hand-maintained source of the physical acceptance stages S0 to S10: steps, units, limits with their sources (or the reason a limit is pending), stop conditions, equipment and evidence; `tools/acceptance.py` renders `docs/BENCH_ACCEPTANCE.md` and checks returned records against it. |
| `hardware/acceptance/BENCH_PACKAGE.md` | What goes to the bench: the three firmware images and the stages that use each, why the PWM bench image cannot drive a gate (netlist checks BP1 to BP5), equipment by stage, connector pin tables. Generated by `tools/bench_package.py --doc`. |

### `hardware/footprints/`

| File | Role in the system |
|---|---|
| `hardware/footprints/assignments.yaml` | Hand-maintained footprint disposition for every BOM line: footprint and package where decided, otherwise the rating, data sheet, connector or pinout it waits for. Read by the schematic generator and the BOM pricing. |
| `hardware/footprints/library_pins.yaml` | SHA-256 of each KiCad 8.0.9 footprint file the assignment uses. |
| `hardware/footprints/FOOTPRINT_CHECK.md` | Counts per disposition and per-line results of the footprint checks, with each footprint's land-pattern source. Generated by `tools/check_footprints.py`; do not edit. |
| `hardware/kicad/ERC_RECORD.yaml` | The CI KiCad 8.0.9 ERC result (run, artifact, counts) for one SHA-256 of the schematic inputs; valid only while that hash matches. Written by `tools/erc_record.py`. |
| `hardware/kicad/fp-lib-table` | Project footprint library table for the libraries the assignment uses, resolved through `${KICAD8_FOOTPRINT_DIR}`. Generated by `tools/check_footprints.py`. |

### `hardware/calculations/`

| File | Role in the system |
|---|---|
| `hardware/calculations/README.md` | Describes the electrical calculations and where each one is produced. |
| `hardware/calculations/ov_trip_inputs.yaml` | Inputs of the over-voltage trip worst case: network resistors and tolerances, device and supply bounds with their data-sheet sources (null until read), pass-criteria limits. |
| `hardware/calculations/ov_trip_worst_case.md` | Over-voltage comparator trip and release: nominal, resistor-only and full worst case, criteria, power-up and loading notes. Generated by `tools/ov_trip_worst_case.py`; do not edit. |
| `hardware/calculations/current_sense_error_budget.md`, `hardware/calculations/power_stage_envelope.md` | Phase-current error budget and MOSFET loss and thermal envelope over the unknown motor current and bus voltage. Generated by `tools/hardware_calcs.py`; do not edit. |

### `hardware/interfaces/`

| File | Role in the system |
|---|---|
| `hardware/interfaces/README.md` | Points to the candidate pin maps, the electrical I/O list and the CAN message table. |
| `hardware/interfaces/pin_allocation_STM32G474VBCETx.csv`, `hardware/interfaces/pin_allocation_STM32G474MBCETx.csv`, `hardware/interfaces/pin_allocation_STM32G474RBCETx.csv` | Candidate MCU pin allocations for LQFP100 (used by the schematic and the consistency check), LQFP80 and LQFP64 (incomplete). Generated by `tools/pin_allocation.py` from ST's open pin database; do not edit. |
| `hardware/interfaces/st_open_pin_data/*` | Two files of ST's `STM32_open_pin_data` (pins and signals of the STM32G474V, alternate-function numbers of the G47x GPIO) with ST's BSD-3 licence; read by `tools/gen_board_pins.py`. |

### `hardware/kicad/`

| File | Role in the system |
|---|---|
| `hardware/kicad/semmc.kicad_sch`, `hardware/kicad/01_power_input.kicad_sch` to `hardware/kicad/12_aux_rails.kicad_sch`, `hardware/kicad/semmc.kicad_sym`, `hardware/kicad/semmc.kicad_pro`, `hardware/kicad/sym-lib-table`, `hardware/kicad/semmc.net` | The draft schematic (root and 12 hierarchical sheets), project symbols, project file, symbol-library table and the netlist KiCad exports from it. Generated by `tools/gen_kicad_schematic.py` (the netlist by its `--check` step); do not edit. |
| `hardware/kicad/CONNECTIVITY_CHECK.md`, `hardware/kicad/PIN_TYPE_CHECK.md` | Reports of the netlist-versus-intent connectivity check and of the pin-type rule check on the exported netlist. Generated by `tools/gen_kicad_schematic.py --check` and `tools/pin_type_check.py`; do not edit. |
| `hardware/kicad/ERC_REPORT.rpt`, `hardware/kicad/ERC_REPORT.json` | KiCad ERC reports, not committed (CI keeps them as the `erc-report` artifact). Generated by `tools/run_kicad_erc.sh` with KiCad 8 or newer; do not edit. |
| `hardware/kicad/semmc_schematic_DRAFT.pdf` | PDF export of the draft schematic for reading without KiCad; no tool writes it, so it is re-exported by hand and can lag the sheets. |

### `hardware/layout/`

| File | Role in the system |
|---|---|
| `hardware/layout/PRE_LAYOUT.md` | What must be fixed before PCB layout (outline, mounting, connectors, current paths, thermal approach, copper, assembly), the constraints the circuit already fixes, layout readiness per sheet and the release gate. |

### `hardware/protection/`

| File | Role in the system |
|---|---|
| `hardware/protection/SHUTDOWN_TRUTH_TABLE.md` | How each protective input reaches the gate outputs (hardware or firmware path, latching, reset, latency), what still stops the motor if one path fails, and the requirements this places on part selection. |

### `hardware/review/`

| File | Role in the system |
|---|---|
| `hardware/review/CONSISTENCY_CHECK.md` | PASS, FAIL or OPEN results of the cross-artefact check of the draft (protection topology, pins, BOM coverage, timing against configuration, power rails). Generated by `tools/hw_consistency.py`; do not edit. |
| `hardware/review/REVIEW_CHECKLIST.md` | The human design-review checklist (stage 0 gate) to be completed before any fabrication. |
| `hardware/review/DESIGN_REVIEW.md` | Design review of the schematic against primary component documentation, topic by topic (gate driver, MOSFETs, DC link, current sensing, protection, precharge, supply, CAN, clock, debug), with every KiCad ERC warning reviewed individually. |

### `hardware/schematic_plan/`

| File | Role in the system |
|---|---|
| `hardware/schematic_plan/SCHEMATIC_PLAN.md` | The v0.1 schematic sheet plan, superseded by the generated KiCad draft and kept as a record. |

### `hardware/selection/`

| File | Role in the system |
|---|---|
| `hardware/selection/COMPONENT_SELECTION.md` | Candidate or UNRESOLVED status of each hardware function with reasons, alternates and what blocks a selection freeze. |
| `hardware/selection/DATASHEET_REGISTER.md` | Register of the primary datasheets still to be read and the values each must supply before any layout. |
| `hardware/selection/PINOUT_VERIFICATION.md` | Evidence level of every IC's pin numbers, reset states, current-sense topology and the schematic checks performed. |

### `hardware/timing/`

| File | Role in the system |
|---|---|
| `hardware/timing/timing_budget.md`, `hardware/timing/timing_budget.json` | MCU timing allocation and current-sampling window budget (PWM, dead time, ADC window, break routing, startup states, interrupt budget). Generated by `tools/timing_budget.py`; do not edit. |
| `hardware/timing/clock_tree_alternatives.md`, `hardware/timing/clock_tree_alternatives.json` | STM32G474 clock-tree alternatives and CAN bit timing per candidate bus; selects no crystal. Generated by `tools/clock_tree.py`; do not edit. |

## Tools (`tools/`)

### `tools/`

| File | Role in the system |
|---|---|
| `tools/README.md` | Every tool by purpose with inputs, outputs and commands; what CI and `verify_all.py` run; which tools write tracked files. |
| `tools/__init__.py` | Makes `tools` a Python package so tests and other tools can import its modules. |
| `tools/gen_config.py` | Generates the configuration JSON schema and the C parameter table from `config/parameters.yaml`; `--check` reports stale files. |
| `tools/config_registry.py` | Library module that loads the parameter registry, the single source for the schema, the C table and the validators. |
| `tools/config_tool.py` | Validates a vehicle configuration for simulation or hardware mode and encodes the calibration blob; the same rules run in the firmware. |
| `tools/gen_protocol.py` | Generates the C and Python CAN codecs, golden vectors and the CAN message table from `protocol/protocol.yaml`; `--check` reports stale files. |
| `tools/gen_dbc.py` | Generates the DBC description of the protocol for other teams' CAN tools, optionally relocated to another identifier block; `--check` for the default file. |
| `tools/gen_procurement.py` | Generates `docs/PROCUREMENT.md` (the v0.6 combined table) from `hardware/bom/procurement.yaml` and `docs/generated/budget.json`, refusing undated prices, unresolved estimate references and unevidenced orders. |
| `tools/check_links.py` | Checks relative links, anchors and (in current documents) backtick file paths in every tracked Markdown file. |
| `tools/fetch_csia.py` | Fetches the pinned CSIA core into `.deps/` and verifies its commit; nothing of it is copied into the repository. |
| `tools/mqtt_broker.py` | Library module that starts, kills and restarts a local loopback Mosquitto broker for the tests and the MQTT demonstration. |
| `tools/run_telematics_demo.py` | The independent receive-only demonstration: simulated controller and sensors, local log, real MQTT broker (or in-process), SQLite, speed, power, energy and data quality, with controller silence, invalid frames, missing signals, a storage stall, a broker outage and a restart; nine checks. |
| `tools/telematics_import.py` | Imports a log read from the board (raw dump or console `DUMP`), splits it into sessions, writes them into the pit database and plots speed and distance. |
| `tools/telematics_bom.py` | Renders the telematics BOM and its totals from `hardware/telematics/bom.yaml`; `--check` reports a stale file. |
| `tools/scope.py` | Renders `docs/scope.yaml` (module and test-suite classification) as `docs/generated/scope.md`; `--check` reports stale or unclassified files. |
| `tools/run_host_demo.py` | End-to-end host demonstration of the controller core, telematics node model, local log, simulated uplink, pit storage, offline import and pit-side replays, with pass/fail checks. |
| `tools/run_mqtt_demo.py` | The telemetry chain through a real local Mosquitto broker and a separate pit ingestion process, including broker and pit crashes, with pass/fail checks. |
| `tools/run_pit_replay.py` | Advisory shadow replay of the R3v and CSIA2 monitors over one run stored in a pit database; reads the database and writes a report only. |
| `tools/control_contract_report.py` | Before/after report of the control-contract correction on the synthetic configuration; fails on any contract violation. |
| `tools/make_replay_sample.py` | Generates the synthetic recorded log used by the host replay test, learning the session tag from the controller. |
| `tools/run_optimization.py` | Synthetic energy-strategy study (DP plan and strategy comparison) writing the optimisation results, schedules and figure; `--quick` for CI-sized grids. |
| `tools/run_policy_comparison.py` | Compares speed hold with pulse-and-coast through the controller core and the host plant, in energy per metre. |
| `tools/run_electrical_calcs.py` | Synthetic parameterised electrical calculations and sensitivity study showing which missing measurements dominate component selection. |
| `tools/run_csia_study.py` | Compares the CSIA adapter with simple checks and fixed-threshold residuals on the synthetic development set. |
| `tools/run_csia_evaluation.py` | Frozen CSIA v1 held-out evaluation and ablation, guarded by the development-set freeze manifest. |
| `tools/run_csia_evaluation_v2.py` | CSIA v2 evaluation by the pre-registered protocol: development runs, freeze, and a single run on the untouched evaluation set. |
| `tools/run_csia_posthoc.py` | Exploratory post-hoc analysis of debounce variants after the v1 evaluation, without touching frozen files or results. |
| `tools/telematics_budget.py` | Logging capacity, LTE data volume and auxiliary power budget of the combined controller and telematics design. |
| `tools/wheel_sensor_check.py` | Checks whether a sampled or a continuous Hall switch can see every wheel magnet over a labelled geometry grid; `--check` reports a stale result. |
| `tools/coastdown_sensitivity.py` | Shows how grade, wind and speed noise bias a coast-down fit on the synthetic vehicle; `--check` reports a stale result. |
| `tools/bus_load.py` | CAN bus-load and worst-case response-time estimate, printed to standard output and used by the tests. |
| `tools/can_bit_timing.py` | FDCAN bit timing for the reference project's CAN FD bus, superseded by `tools/clock_tree.py` and kept for its record. |
| `tools/verify_all.py` | Runs every reproducible check in one command and writes a verification record, including the tracked files the run changed. |
| `tools/gen_kicad_schematic.py` | Holds the motor-controller circuit as Python data and generates the KiCad draft schematic and draft BOM; `--check` adds the netlist connectivity comparison. |
| `tools/run_kicad_erc.sh` | Runs KiCad's electrical rules check on the draft schematic (KiCad 8 or newer) and writes the ERC report. |
| `tools/erc_summary.py` | Summarises the KiCad ERC JSON report and, with `--fail-on-errors`, fails on any ERC error (used by CI). |
| `tools/pin_type_check.py` | Applies a subset of ERC pin-type rules to the netlist KiCad exported and writes `hardware/kicad/PIN_TYPE_CHECK.md`. |
| `tools/hw_consistency.py` | Cross-checks the exported netlist, pin allocation, BOM, platform notes, timing budget and configuration, with PASS, FAIL or OPEN per item. |
| `tools/price_bom.py` | Prices the draft BOM as low-high ranges and computes the budget scenarios and the feasibility statement. |
| `tools/timing_budget.py` | Computes the STM32G474 timing allocation and current-sampling window budget from the configuration and tagged constants. |
| `tools/clock_tree.py` | Enumerates STM32G474 clock trees and CAN bit timings for candidate crystals and buses, citing ST source limits. |
| `tools/hardware_calcs.py` | Computes the current-sense error budget and the power-stage loss and thermal envelope for the draft hardware. |
| `tools/pin_allocation.py` | Allocates the controller's functions to STM32G474 pins from ST's open pin database and writes the candidate pin maps. |
| `tools/gen_board_pins.py` | Writes `firmware/platform/stm32g4/src/board_pins_generated.h` and `docs/generated/pin_af_verification.md` from the pin map, checking every pin, position and alternate function against ST's pin database; `--check` in CI. |
| `tools/emulate_core_timing.py` | Runs the core's ARM build in an instruction-level emulator and reports instruction counts of the fast and slow steps (`docs/generated/core_timing_emulated.md`). |
| `tools/bench_read.py` | Reads `g_bench` from a running board through OpenOCD and writes a JSON record for the acceptance procedures. |
| `tools/fetch_kicad_symbols.py` | Downloads the 17 KiCad 8.0.9 symbol libraries the schematic uses into `build/kicad-symbols-8.0.9/`, checking each file's SHA-256. |
| `tools/acceptance.py` | Renders `docs/BENCH_ACCEPTANCE.md` from `hardware/acceptance/procedures.yaml`, writes blank result records for a stage and checks returned records (limits, stop conditions, blocked steps, evidence files, signatures). |
| `tools/ov_trip_worst_case.py` | Writes `hardware/calculations/ov_trip_worst_case.md` from `ov_trip_inputs.yaml`: nominal, resistor-only and full worst-case trip and release of the over-voltage comparator; `--check` fails when stale. |
| `tools/bench_package.py` | Writes `hardware/acceptance/BENCH_PACKAGE.md` (images and their stages, the gate-disable checks, equipment, connector pin tables) and builds the bench package folder with images, procedures, per-stage templates, scripts, checks and a SHA-256 manifest; CI uploads it. |
| `tools/erc_record.py` | Hashes the schematic inputs (sheets, project symbols, library tables, pinned library hashes), records a CI KiCad ERC result against that hash in `hardware/kicad/ERC_RECORD.yaml`, and checks a fresh CI report against the record; the release gate's G5 uses it. |
| `tools/check_footprints.py` | Fetches the pinned KiCad 8.0.9 footprints the assignment uses, checks every BOM line's disposition and every assigned footprint against its symbol (pin-to-pad, courtyard, fabrication outline, filters, polarity), writes `hardware/footprints/FOOTPRINT_CHECK.md` and `hardware/kicad/fp-lib-table`; `--check` fails on a failed check or stale output. |
| `tools/check_datasheets.py` | Renders `docs/reference/datasheets/README.md` from `manifest.yaml`, records the SHA-256 and size of received PDFs, and fails `--check` when the page is stale or a recorded file changed. |
| `tools/blockers.py` | Renders `docs/BLOCKERS.md` from `docs/blockers.yaml` and refuses an incomplete entry; `--check` reports a stale document. |
| `tools/release_gate.py` | Evaluates the fabrication release gate and writes `docs/generated/release_gate.md`; builds the release package only when every condition passes. |

### `tools/mqtt/`

| File | Role in the system |
|---|---|
| `tools/mqtt/compose.yaml` | Container definition of a local pit broker (eclipse-mosquitto 2.0.18, pinned) for manual work; not used by the tests. |
| `tools/mqtt/mosquitto.conf` | Loopback-only, unauthenticated Mosquitto configuration with persistence, used by the container and by a manual `mosquitto -c` run. |

## tests/

Paths are relative to the repository root. Every test runs on a host against synthetic models, plant and parameters; none runs on hardware. The C unit tests are in `firmware/tests/` (indexed there) and run with ctest.

### Repository root (test configuration)

| File | Role in the system |
|---|---|
| `conftest.py` | Marks every test with its suite from `docs/scope.yaml` (telematics, reference, controller) and refuses controller fixtures outside the controller suite; puts the repository root on `sys.path` and provides the session fixtures `build_dir`, `host_exe`, `cfgcheck_exe` and `synthetic_blob`; configures the C host build on demand in `SEMMC_BUILD_DIR` (default `build/`) and runs an incremental build once per session. |
| `pytest.ini` | Sets `tests/` as the pytest test path and `-q` as the default verbosity. |

### tests/

| File | Role in the system |
|---|---|
| `tests/README.md` | Developer documentation for the test suite: organisation, what each file checks, fixtures and the on-demand C build, environment variables, external tools and skip-or-fail behaviour, commands, side effects and limitations. |

### tests/integration/

| File | Role in the system |
|---|---|
| `tests/integration/test_protocol_python.py` | Python CAN codec against golden vectors, a bitwise CRC reference and hand-calculated frames; wrong-major and malformed frames; generator freshness (`gen_protocol.py`, `gen_config.py`); bus-load budget. |
| `tests/integration/test_dbc.py` | The committed DBC is current and decodes every golden vector like the project codec under an independent parser (cantools), at block bases 0x300 and 0x500. |
| `tests/integration/test_config_parity.py` | Python and C configuration validators report identical rule codes for the synthetic configuration and 37 mutations in both modes; a hardware CMake configure refuses the unconfigured and synthetic configurations. |
| `tests/integration/test_end_to_end.py` | Lockstep co-simulation through both codecs, the C core and the plant: handshake, ECO engagement on the driver edge, speed hold within bounds, supervisor-loss timeout, command trace and energy agreement. |
| `tests/integration/test_host_demo.py` | Host demonstration checks, plus the STLG log (including the temperature record and its import), telematics node queues and backlog, UTC estimator and pit validation and de-duplication. |
| `tests/integration/test_acceptance.py` | The acceptance and blocker documents are current, every limit has a source or a pending reason, references resolve, and the record checker rejects wrong verdicts, invented limits, blocked steps and missing evidence. |
| `tests/integration/test_mqtt_pipeline.py` | Pit validation (schemas v1, v2 and v3), database migration, node wheel speed and temperatures, receipt recording and bounded backlog without a broker; with Mosquitto, session persistence across a broker crash, acknowledgement versus delivery, and the MQTT demonstration. |
| `tests/integration/test_shadow_replay.py` | Pit-side shadow replay: data class from run metadata, insufficient-evidence reporting, missing-run exit code, configuration notes in the report, and no command path in the replay and pit-energy modules. |
| `tests/integration/test_pit_energy.py` | Pit energy per distance: formulas, the root README worked example against independent arithmetic and the vehicle model, run summaries that report missing data, wheel-channel cross-check and the replay tool's energy output. |
| `tests/integration/test_supervisor.py` | The supervisor gives zero torque on stale, duplicated or invalid controller speed and bounded torque on fresh speed; pulse-and-coast hysteresis. |
| `tests/integration/test_vcu_bridge.py` | The proposed SocketCAN bridge: identifier filter, classic-frame packing and decoding, rejection of CAN FD, extended and corrupted frames, relocated identifier block. |
| `tests/integration/test_target_firmware.py` | Builds the STM32G474 image and checks the vector table against ST's interrupt list, the memory layout, no double precision on the current-interrupt path, fault handlers reaching the safe state, the emulated instruction-count regression guard, memory barriers in the fast/slow handoff, the bench-reader layout and the separately marked bench PWM and timing-marker images. |
| `tests/integration/test_math_spec.py` | Recomputes every numerical example of `docs/MATH_SPEC.md` with the implementing code. |
| `tests/integration/test_docs.py` | Documentation links and backtick paths resolve, generated check documents are current, no em dash or assistant branding in current documents, root README scope statements. |

### tests/telematics/

| File | Role in the system |
|---|---|
| `tests/telematics/test_measurement_and_adapters.py` | Measurement rules (a value cannot hide missing data; sentinels, ranges and flags classified; missing and stale reported as null), the semmc fixture adapter (sequence from the protocol, no invented sample time, sentinels, CRC errors, companion frames), the DBC adapter (same result as the fixture on the same frames, refuses a unit mismatch). |
| `tests/telematics/test_wheel_node_pit.py` | Wheel speed over complete edge intervals, a lost record losing no distance and an overrun making it a lower bound, no evidence against standstill; the node has no transmit path, logs raw frames and reports missing values as null; v4 validation at the pit; idempotent import and energy with missing intervals. |
| `tests/telematics/test_telematics_demo.py` | The demonstration's checks in-process and through a real broker; outputs, both energy boundaries, no non-valid value stored as a number, no supervisor block in any live message. |
| `tests/telematics/test_firmware_host.py` | Builds the firmware on the host and runs its unit tests; counter and record identifiers equal to the Python reference; wheel records byte for byte; a flash image imported with speed, distance, restart and accounting; full storage counted; the console dump format. |
| `tests/telematics/test_firmware_target.py` | Builds both target images and checks the vector table against ST's interrupt list, the layout (log bank left free, no controller code), and that the sources have no transmit path. |
| `tests/telematics/test_telematics_bom.py` | Telematics BOM: totals are sums of their own lines, unknown prices stay unknown and are listed, no controller part and every line has a source, the page is current and keeps the battery as reported. |
| `tests/telematics/test_energy_and_shadow_scope.py` | Shadow relationships without their inputs disabled and reported; a vehicle report ignores simulator fields; energy boundaries stated; frozen CSIA evaluation files unchanged and the R3v result kept. |

### tests/fault_injection/

| File | Role in the system |
|---|---|
| `tests/fault_injection/test_fault_injection.py` | 21 injected-fault and abnormal-input scenarios through the C core and synthetic plant (hardware faults, sensor loss, derating, driver overrides, invalid start-up, reboots, bus-off, reordered, malformed and NaN supervisor frames). |
| `tests/fault_injection/test_csia_adapter.py` | CSIA vehicle adapter in shadow mode: pinned core, no nuisance suspects, correct fault attribution, ambiguity without corroboration, freshness apart from trust, and no effect of hostile advisories on controller commands. |
| `tests/fault_injection/test_csia_freeze.py` | Frozen CSIA v1 files match `docs/csia/DEV_SET_FREEZE.json`; the evaluation set is deterministic and disjoint from development. |
| `tests/fault_injection/test_csia_v2_freeze.py` | Frozen CSIA v2 files match `docs/csia/V2_FREEZE.json`; v2 development and evaluation seeds are disjoint from each other and from v1. |

### tests/simulation/

| File | Role in the system |
|---|---|
| `tests/simulation/test_models.py` | Tests of `models/`: force signs, coast-down identifiability, inverter loss rules, measured-map limits, DP feasibility and export, and the strategy simulator's braking, limits and energy reconciliation. |
| `tests/simulation/test_replay.py` | Replays the recorded synthetic log through `semmc_host` and checks state transitions, duplicate and reordered frames, stale gap, NaN request, derating and brake override. |
| `tests/simulation/replay_sample.semmc.log` | Synthetic "recorded" log (driver inputs, measurements, supervisor CAN frames) used by the replay test. Generated by `tools/make_replay_sample.py`; do not edit. |

### tests/hardware/

| File | Role in the system |
|---|---|
| `tests/hardware/test_hw_consistency.py` | Protection-topology and cross-artefact checks on the committed KiCad netlist, with mutation tests that break one protection path at a time. |
| `tests/hardware/test_hardware_tools.py` | Schematic connectivity (needs `kicad-cli`, else skipped), pin allocation of current sensing and break inputs, timing budget and BOM pricing coverage; rewrites the files those tools generate. |
| `tests/hardware/test_clock_and_telematics.py` | Clock-tree feasibility and PLL ranges, dead-time code, controller and supervisor frame rates and log flash fill time. |
| `tests/hardware/test_procurement.py` | Project procurement file: validation, generated tables current, estimates reproduce the priced BOM without double counting, no unsupported status, no zero totals for unknown costs. |
| `tests/hardware/test_wheel_sensor_check.py` | Wheel-magnet detection arithmetic against hand calculations and the quoted datasheet sampling periods. |
| `tests/hardware/test_datasheets.py` | The document manifest is current and ordered, a received file is pinned by its hash, and no revision is guessed. |
| `tests/hardware/test_release_gate.py` | The committed release-gate report is current and names every condition, and a failing gate builds no package. |
