# telematics/firmware: the telematics unit's firmware (NUCLEO-U575ZI-Q)

The firmware of the telematics delivery: it listens and records, and transmits nothing on the vehicle bus.
**Built and host-tested; never run on hardware.** The first milestone it implements is wheel pulse ->
timestamped record -> bounded queue -> persistent log -> host import -> plotted speed and distance; the
controller receive fixture (FDCAN1 in bus-monitoring mode) is the second image.

Nothing here depends on the controller firmware in `../../firmware/` (deferred controller development).

## Layout

| Path | Contents |
|---|---|
| `include/`, `src/` | Portable C11, no register access, built for the host (tests) and the target: `tm_wheel` (edge accumulation, the same rules as `host/telematics/wheel.py`), `tm_time` (64-bit time across timer overflow), `tm_queue` (bounded log queue, CAN receive ring), `tm_stlg` (STLG headers and blocks, `host/telematics/stlg.py` format), `tm_flashlog` (slot storage, at most one storage operation per call), `tm_reset` (restart cause), `tm_app` (the application), `tm_w25q` (W25Q SPI NOR of 1 to 16 MiB on the SPI transport, the log storage when it answers), `tm_imu` (LSM6DSOX/ISM330DHCX and TMP117 on the I2C transport), `tm_bus.h` (bounded SPI and I2C transport interfaces) |
| `platform/host/` | RAM flash model, the W25Q bus model `tm_fakew25q` and the host simulator `tm_hostsim` (the portable application driven by a script, on internal flash or the NOR model; writes a storage image) |
| `platform/u575/` | Startup and vector table, linker script, clocks and LSE/MSI PLL mode, TIM2 capture, watchdog, USART1, internal flash bank 2, FDCAN1 bus monitoring, SPI1 (the NOR), I2C1, `main_u575.c` (storage selection, console, sensor polling); vendored CMSIS headers with their provenance |
| `tests/` | C unit tests (`tm_tests`, under ASan and UBSan): CRC, timer extension, accumulator, queue, blocks, flash log on the RAM model (erase before write, power loss mid-slot, write errors, full storage), drivers on simulated devices |
| `BENCH_MINIMAL.md` | Generated from `../bench/bench.yaml` (section `minimal`): the first bench, one wheel input through the whole chain to a plot, with the document checks due before flashing |
| `BENCH.md` | Generated from `../bench/bench.yaml` by `tools/telematics_bench.py`: build and package commands, parts, the connection table, the bench procedure B0 to B12 and the electrical checks before any vehicle bus |

## Commands

```
cmake -S telematics/firmware -B build-telematics -G Ninja && cmake --build build-telematics
ctest --test-dir build-telematics --output-on-failure
cmake -S telematics/firmware -B build-u575 -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel \
      -DCMAKE_TOOLCHAIN_FILE=$PWD/telematics/firmware/cmake/arm-none-eabi-cortex-m33.cmake -DTM_TARGET_U575=ON
cmake --build build-u575
python3 -m pytest tests/telematics/test_firmware_host.py tests/telematics/test_firmware_target.py
```

## Rules this code keeps

* Interrupts are short and constant-time: the capture interrupt adds one edge to an accumulator; the CAN
  interrupt copies frames from the hardware FIFO into a ring. Everything else runs in the main loop.
* Nothing waits: a full queue drops and counts, a busy storage device returns at once, every bus transfer
  has a bound.
* Every loss is visible: queue high water and drops, storage drops and write errors, lost wheel edges
  (capture overrun), lost wheel records (sequence gaps), CAN ring overruns, restart reason and boot count.
* A source timestamp is never invented: wheel edges carry the capture time, CAN frames their receive time.
