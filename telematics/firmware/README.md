# Telematics firmware (NUCLEO-U575ZI-Q)

Firmware for the telematics unit. It timestamps wheel pulses, reads the IMU and temperature sensors, receives the motor controller's CAN broadcast and the GNSS receiver's position solution and time pulse, and writes everything to an on-board log that is read out after each run. It listens and records only: it transmits nothing on the vehicle bus.

**Status: built and host-tested; never run on hardware.** The portable code passes its unit tests under AddressSanitizer and UndefinedBehaviorSanitizer and matches the Python reference byte for byte. The images build and link with reproducible hashes. The register-level code follows ST's HAL and has been checked against the board manual UM2861 Rev 10 and the errata ES0499 Rev 12; the checks that need the STM32U575 data sheet and reference manual are open ([`../bench/DOCUMENT_CHECKS_RECORD.md`](../bench/DOCUMENT_CHECKS_RECORD.md)).

Nothing here depends on the deferred motor-controller firmware in [`../../firmware/`](../../firmware/README.md).

## What it does

| Function | Implementation |
|---|---|
| Wheel speed | TIM2 input capture on PA3, PA2 and PA0 at 1 MHz, extended to 64 bits across the timer's overflow. One record per channel every 50 ms. No edges means unknown, never 0 m/s; a stuck or disconnected sensor is flagged against the wheels that are moving |
| On-board log | STLG v1 records in 4 KiB slots on a W25Q NOR flash (1 to 16 MiB) when one answers at start-up, otherwise in internal flash bank 2 (1 MiB). One session per boot, blocks with sequence numbers and CRC-32. Once only a reserve is left, sparse logging keeps the wheels and counters |
| Controller data | FDCAN1 in bus-monitoring mode: receive only, no acknowledge bit, no transmission. Frames go through a 128-frame ring into the log with their receive time |
| Sensors | ISM330DHCX or LSM6DSOX IMU at 100 Hz and up to four TMP117 temperature sensors at 1 Hz, on I2C1 |
| GNSS and time | NEO-M9N class receiver on USART2 (PD6 RX, PD5 TX, 38400 baud): UBX-NAV-PVT at 10 Hz becomes a `GNSS` record (ground speed, speed accuracy, satellites, fix). The PPS output on PA1 (TIM2_CH2) is captured at 1 MHz; each edge is labelled with the UTC second it marks from the next valid NAV-PVT and logged as a `PPS` record, which the pit uses to put the unit's clock on UTC. An edge that cannot be labelled is counted, not logged. The only bytes sent are a configuration message to the receiver's UART |
| Diagnostics | Restart cause and boot count, a counter for every drop or overrun (GNSS frames, checksum errors, receive overruns, PPS edges and unlabelled edges included), a status line every second on the USB console |
| Console | USART1 through the ST-LINK USB port: `STATUS`, `DUMP`, `DUMP <first> <last>`, `ERASE YES`, `HELP` |

Peripherals, pins and the bench step that checks each function: [`../../docs/TELEMETRY_EMBEDDED_PORT.md`](../../docs/TELEMETRY_EMBEDDED_PORT.md).

## Images

| Image | Contents | Used for |
|---|---|---|
| `tm_u575` | wheels, log, sensors, console | the minimal bench and bench steps B0 to B10, B12 |
| `tm_u575_can` | `tm_u575` plus CAN reception | bench step B11 and the electrical checks E1 to E5 |
| `tm_u575_vehicle` | `tm_u575_can` plus GNSS and PPS | the GNSS bench check (receiver wired to CN9 and CN10), then the vehicle |

The three images share the portable code. `tm_u575` and `tm_u575_can` contain no GNSS code (the build flags `TM_ENABLE_CAN` and `TM_ENABLE_GNSS` select the parts), so the minimal-bench image is unchanged by the vehicle image.

The image to flash on the minimal bench is the CI artifact named in [`../bench/HANDOFF_MINIMAL.md`](../bench/HANDOFF_MINIMAL.md), with its SHA-256. A local build of the same commit gives the same hash.

## Build and test

Requires CMake 3.28, Ninja, gcc 13 for the host build and `arm-none-eabi-gcc` 13.2 for the target. Run from the repository root.

```sh
# host build: unit tests under ASan and UBSan, and the host simulator
cmake -S telematics/firmware -B build-telematics -G Ninja && cmake --build build-telematics
ctest --test-dir build-telematics --output-on-failure

# target images: tm_u575.elf/.bin/.hex, tm_u575_can.* and tm_u575_vehicle.*
cmake -S telematics/firmware -B build-u575 -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel \
      -DCMAKE_TOOLCHAIN_FILE=$PWD/telematics/firmware/cmake/arm-none-eabi-cortex-m33.cmake -DTM_TARGET_U575=ON
cmake --build build-u575

# Python checks of the firmware sources and images
python3 -m pytest tests/telematics/test_firmware_host.py tests/telematics/test_firmware_target.py

# firmware-in-the-loop drive: the simulated vehicle drives this code, the log goes through the pit (SIMULATED)
python3 tools/run_firmware_vehicle_sim.py --out build/firmware_vehicle_sim --gnss-outage 60:70
```

## Flashing and reading the log

Follow the bench procedure, not these lines alone: [`BENCH_MINIMAL.md`](BENCH_MINIMAL.md) for the first bench, [`BENCH.md`](BENCH.md) for the full bench. Both are generated from [`../bench/bench.yaml`](../bench/bench.yaml) by `tools/telematics_bench.py`.

```sh
STM32_Programmer_CLI -c port=SWD freq=8000 -w tm_u575.bin 0x08000000 -v -rst   # SWD at 8 MHz or less
python3 tools/uart_capture.py /dev/ttyACM0 capture.txt                         # console; type DUMP to read the log
python3 tools/telematics_import.py --uart-capture capture.txt --db pit.sqlite --out build/bench_import
```

Do not halt the core with a debugger while it runs: the watchdog resets it after about 2 s.

## Source layout

| Path | Contents |
|---|---|
| `include/`, `src/` | Portable C11 with no register access, built for both the host and the target: wheel accumulation (`tm_wheel`, same rules as `host/telematics/wheel.py`), 64-bit time (`tm_time`), bounded queues (`tm_queue`), STLG format (`tm_stlg`, same as `host/telematics/stlg.py`), slot storage (`tm_flashlog`), restart cause (`tm_reset`), the application (`tm_app`), the W25Q NOR driver (`tm_w25q`), IMU and TMP117 (`tm_imu`), the GNSS parser and PPS labelling (`tm_gnss`), bounded SPI and I2C interfaces (`tm_bus.h`) |
| `platform/u575/` | Start-up and vector table, linker script, clocks, TIM2 capture, watchdog, USART1, internal flash, FDCAN1, SPI1, I2C1, USART2 for the GNSS receiver (`gnss_u575.c`), `main_u575.c`; vendored CMSIS headers with their provenance in `vendor/PROVENANCE.md` |
| `platform/host/` | RAM flash model, a W25Q bus model and the host simulator `tm_hostsim`, which runs the portable application and GNSS code from a script (edges, frames, sensor records, GNSS bytes, PPS edges) and writes a storage image |
| `tests/` | C unit tests (`tm_tests`): CRC, timer extension, accumulator, queues, blocks, the flash log on the RAM model (erase before write, power loss mid-slot, write errors, full storage), drivers on simulated devices, the GNSS parser and PPS labelling |
| `BENCH_MINIMAL.md`, `BENCH.md` | Generated bench procedures |

## Design rules

* **Short interrupts.** The capture interrupt adds one edge to an accumulator or takes the PPS time; the CAN interrupt copies frames from the hardware FIFO into a ring; the GNSS UART interrupt puts each byte and its arrival time in a ring. Everything else runs in the main loop.
* **Nothing waits.** A full queue drops and counts, a busy storage device returns at once, and every bus transfer has a time bound.
* **Every loss is visible.** Queue high-water marks and drops, storage drops and write errors, lost wheel edges, sequence gaps, CAN ring overruns, restart reason and boot count are all logged.
* **No invented timestamps.** Wheel edges and PPS edges carry their capture time, CAN frames and GNSS messages their receive time. A PPS edge is logged only with the UTC second it was matched to.
* **No transmit path.** The CAN driver configures bus-monitoring mode and references no transmit register; tests check this ([`../../tests/telematics/test_receive_only_boundary.py`](../../tests/telematics/test_receive_only_boundary.py)).
