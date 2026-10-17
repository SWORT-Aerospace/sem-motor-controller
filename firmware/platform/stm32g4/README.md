# STM32G474 target firmware

The controller firmware for the board drawn in `hardware/kicad`: startup code, linker script, clock, PWM,
ADC, CAN, watchdogs, the calibration store and the interrupt structure around the portable core
(`firmware/src`). It builds into a linked image, `semmc_stm32g474.elf` / `.bin` / `.hex`.

It has not been run on a board. Everything below that says "verified" was checked against ST's published
sources or by the tests named; nothing was measured on hardware.

## Build

```sh
cmake -S firmware -B build-g4 -G Ninja \
      -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi-cortex-m4f.cmake \
      -DSEMMC_TARGET_STM32G474=ON -DSEMMC_SANITIZE=OFF -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build build-g4
```

Needs `gcc-arm-none-eabi` and `libnewlib-arm-none-eabi` (Ubuntu 24.04: GCC 13.2.1), CMake and Ninja.
Outputs in `build-g4/`: `semmc_stm32g474.elf`, `.bin`, `.hex`, `.map`, and `semmc_core_timing.elf` (the
emulation harness below, not flashable). CI builds the image on every push and uploads it as the artifact
`semmc-stm32g474-image`.

Options: `-DSEMMC_HSE_HZ=16000000` once the board's 16 MHz crystal is confirmed (without it the image runs
from the internal RC and keeps CAN off); `-DSEMMC_HARDWARE_BUILD=ON -DSEMMC_VEHICLE_CONFIG=<yaml>` also
encodes the hardware calibration blob `cal_hw.bin`, and refuses at configure time unless that file is
hardware-valid. Flashing: [FLASHING.md](FLASHING.md).

## Status

| Item | Compiled and linked | Checked without hardware | Bench-tested | Notes |
|---|---|---|---|---|
| Vector table, reset handler, fault handlers | yes | vector positions against ST's `IRQn_Type`; every fault handler reaches `board_force_safe` (test_target_firmware.py) | no | fault handlers stop kicking the watchdogs |
| Linker script, memory map | yes | sections inside flash/RAM; calibration area outside the image (test_target_firmware.py) | no | sizes from ST's template linker file |
| Clock 160 MHz (HSI16 or 16 MHz HSE) | yes | sequence follows ST's HAL; PLL limits not checked against DS12288 | no | the crystal is not selected |
| Pin configuration | yes | every pin, position and AF against ST's pin database, 45 functions, 0 errors (`docs/generated/pin_af_verification.md`) | no | electrical limits not checked |
| TIM1 PWM, dead time, break inputs | yes | ARR and dead-time encodings by host test (test_io.c) | no | gate-driver input polarity assumed active high |
| ADC currents (injected) and slow signals (DMA) | yes | no | no | ADC clock and sampling times are assumptions |
| Fast step in the ADC interrupt | yes | no double-precision routine reachable from it (test_target_firmware.py); core instruction count in an emulator (below) | no | |
| Slow step at 1 kHz, CAN polling, watchdog kicks | yes | no | no | |
| FDCAN classic CAN, filter, bus-off recovery | yes | bit timing by host test (test_io.c) | no | off without crystal and bit rate |
| IWDG + external watchdog toggle | yes | no | no | IWDG timeout depends on LSI tolerance (unread) |
| Calibration store (read only) | yes | blob format shared with the host tests | no | |
| Event log across resets | yes | no | no | |
| Sensor scaling, pedal plausibility, precharge sequencing, enable-path check | yes | host tests (test_io.c) | no | portable code in `firmware/src/io` |
| DRV8353 SPI configuration | **no** | - | - | datasheet not read; DRV_ENABLE is never set |
| INA228 battery meter | **no** | - | - | register map not verified; battery voltage missing, precharge never closes |
| Motor operation | **inhibited** | - | - | needs both items above and a bench-measured calibration |

Emulated timing (`docs/generated/core_timing_emulated.md`, `tools/emulate_core_timing.py`): with current
control active the core's fast step executes about 1020 instructions on Cortex-M4F, a lower bound of 6.4 us
at 160 MHz against the 25 us half period at 20 kHz. This is an instruction count in an emulator, not a
measurement: wait states, pipeline effects and the platform's own interrupt code are not included. The
board measurement is `g_bench.fast_max_cycles`.

## Structure

| File | Content |
|---|---|
| `stm32g474xe_flash.ld` | memory map; last 4 KB of flash reserved for the calibration blob |
| `src/startup_stm32g474.c` | vector table (generated from ST's interrupt list), reset and fault handlers |
| `src/system_clock.c` | FPU, VTOR, boost mode, flash latency, PLL, DWT cycle counter |
| `src/board.c`, `src/board_pins_generated.h` | pin setup from the verified pin map, input reading, `board_force_safe` |
| `src/pwm.c` | TIM1 PWM, break inputs, ADC trigger |
| `src/adc.c` | ADC1..3: injected currents, ADC3 regular scan with DMA |
| `src/can.c` | FDCAN1 classic CAN |
| `src/timebase.c`, `src/watchdog.c`, `src/calstore.c`, `src/event_log.c`, `src/uart.c` | time bases, watchdogs and reset cause, calibration area, reset-surviving log, debug UART |
| `src/main.c` | start-up order, fast and slow steps, inhibits, `g_bench` (debugger view) |
| `timing/` | emulation-only harness for instruction counts |
| `vendor/` | ST's CMSIS device header and CMSIS-Core, unchanged ([vendor/PROVENANCE.md](vendor/PROVENANCE.md)) |

## Interrupts and data flow

| Priority | Interrupt | Work |
|---|---|---|
| 0 | ADC1_2 (end of injected sequence) | phase currents and hall code, `mc_core_fast_step`, duties |
| 1 | TIM1_BRK_TIM15 | records which break input fired (the hardware already cleared the outputs) |
| 3 | TIM6_DAC (1 kHz) | inputs, pedal, temperatures, precharge, enable-path check, CAN receive, `mc_core_slow_step`, CAN transmit, LEDs, watchdogs |

The core's slow-to-fast command is double-buffered and published with one store
(`firmware/include/semmc/mc_core.h`); fast-step flags are cleared by the slow step only after it has
observed them (`firmware/tests/test_core_preemption.c`).

PWM timing: centre-aligned, high side centred on the counter peak, low side on the valley; currents sampled
one timer tick before the valley; duties written after the sample load at the next peak. When the outputs
come on, the main output enable is set one cycle after the first duties are written, so the first half
period never runs on stale compare values (at reset those would turn all three low sides on).

## Safety behaviour in this revision

- **Physical output** requires, all at once: a calibration that is hardware-valid, `bench_measured` and
  permits output (checked in the core); a configured gate driver (not implemented: DRV_ENABLE stays low);
  the precharge bypass closed with both voltages verified (the battery meter is not read: never); no break
  input active; HW_PERMIT high (safety loop and external watchdog, in hardware through the AND gate).
- **A synthetic calibration never runs**: the core refuses its provenance in a hardware build.
- **Without a calibration** the core latches CONFIG_INVALID. TIM1 still runs as a sampling clock with its
  outputs permanently off, so the zero-current ADC offsets can be read on the bench.
- **Faults**: TIM1 breaks on the driver's nFAULT, the overvoltage comparator, a core lockup and a flash
  double-ECC error, in hardware. CPU faults force all outputs off and wait for the watchdog.
- **Not covered by the MCU**: overcurrent other than what the gate driver's own monitoring reports (no
  separate comparator reaches the MCU; see the hardware design review, item H-OC).

## Vendor tooling (ADR-0009)

ST's X-CUBE-MCSDK is used as a reference only, not as generated control code, until the rules question on
evaluation-kit software (Art. 66a) is answered. Register sequences follow ST's HAL/LL sources
(`STMicroelectronics/stm32g4xx-hal-driver@a6001282`), cited in each driver.

## Open platform items

| Item | Needs |
|---|---|
| DRV8353 register settings (gate drive current, VDS trip, CSA gain, 6x PWM mode) and `GATE_DRIVER_CONFIGURED` | DRV8353 datasheet |
| INA228 driver (shunt calibration, VBUS and current registers) | INA228 datasheet |
| ADC clock and sampling times | DS12288, amplifier output impedance |
| IWDG timeout tolerance | DS12288 (LSI accuracy) |
| Crystal and `SEMMC_HSE_HZ` | board decision (16 MHz proposed) |
| Output behaviour while the core is halted by a debugger | RM0440 DBGMCU section (confirm the outputs are disabled when TIM1 is frozen) |
| Fast-step execution time | measurement on the board |
