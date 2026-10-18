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

Timing evidence, in three separate kinds:

* **Emulated instruction counts** (`docs/generated/core_timing_emulated.md`, `tools/emulate_core_timing.py`):
  with current control active the core's fast step executes about 1020 instructions. Exploratory only:
  without a validated processor model an instruction count is not a bound on time in either direction (IT
  folding, wait states, stalls); the platform's own interrupt code is not included.
* **On-target measurements**, prepared but not yet taken (no board): `g_bench.fast_isr_max_cycles` (the
  whole fast interrupt), `fast_margin_min_ticks` and `fast_late_writes` (the margin left before the counter
  peak after the last compare write, which is the actual deadline: `src/pwm.h`), `adc_wait_max_cycles` (skew
  between the phase-current conversions), `slow_max_cycles` (wall time of the slow step, including the fast
  interrupts that preempt it), `slow_overruns` and `stack_unused_min_bytes` (stack high-water mark from a
  painted stack). The `semmc_stm32g474_timing` image also drives the status-LED pin (PE14) high for the whole
  fast interrupt, for a scope. These give observed maxima under the tested conditions.
* **Worst-case execution time**: not established. It needs the Cortex-M4 instruction timings, the device's
  flash and bus timing, and an analysis of every path; observed maxima do not prove it.

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

## PWM, ADC and memory review

What the code does, what it was checked against, and what only the reference manual (RM0440), the data sheet
(DS12288) or the errata (ES0430) can confirm. None of those three has been read
([`../../../docs/reference/datasheets/README.md`](../../../docs/reference/datasheets/README.md)); ST's own HAL and
CMSIS sources are used for register encodings only.

| Item | Implementation | Checked against | Still to confirm |
|---|---|---|---|
| Clock tree | HSI16 or a 16 MHz crystal / M 4 x N 80 / R 2 = 160 MHz; AHB, APB1, APB2 undivided, so TIM1, TIM2 and TIM6 count at 160 MHz; 4 flash wait states, range-1 boost | ST HAL sequence and CMSIS field widths ([`../../../hardware/timing/clock_tree_alternatives.md`](../../../hardware/timing/clock_tree_alternatives.md)) | PLL input and VCO ranges (the HAL comments disagree; DS12288); wait states at 160 MHz (RM0440) |
| Timer events | centre-aligned mode 1, RCR = 0, ARR = 160 MHz / (2 f_pwm) (4000 at 20 kHz); update events at the peak and the valley; CCR preload loads at each update; one sampling trigger per period, at the valley | CMSIS fields; ARR encoding by `firmware/tests/test_io.c` | update-event and preload timing in centre-aligned mode (RM0440, TIM1) |
| ADC trigger, every instance | JEXTSEL = 8 (TIM1_TRGO2), rising edge, on ADC1, ADC2 and ADC3 | ST LL driver `stm32g4xx_ll_adc.h` at `stm32g4xx_hal_driver@a6001282` (SHA-256 `c76242a6b0786d4f`): `LL_ADC_INJ_TRIG_EXT_TIM1_TRGO2 = ADC_JSQR_JEXTSEL_3`, line 1412, with no instance restriction (the restricted triggers carry notes (1) and (2), lines 5382-5383) | RM0440 trigger table |
| ADC clock and sampling | HCLK / 4 = 40 MHz; injected currents 24.5 cycles, regular slow channels 247.5 cycles; conversion 12.5 cycles at 12 bits (0.925 us for a current sample) | CMSIS fields | maximum ADC clock and the sampling time needed for the 100 ohm / 470 pF filter's source impedance (DS12288); trigger-to-sampling latency (RM0440) |
| Simultaneous phase samples | three ADCs, same trigger and sampling time; the interrupt waits at most 2 us for ADC2 and ADC3 and records the wait (`g_bench.adc_wait_max_cycles`) | none | ADC3 also runs a continuous regular scan. ST's LL notes describe the injected group interrupting the regular group (lines 2149-2159), but not the delay this adds to the injected start (RM0440). If the measured wait is not a few cycles, the phases are not sampled together: move the slow channels to ADC4/ADC5 or trigger them away from the valley |
| Current-sense settling | a phase counts as measured only if its low side was on for at least dead time + `inverter.current_sense_settle_s` (`mc_lowside_sample_mask`) | host tests | amplifier settling (DRV8353 data sheet) |
| Dead time | DTG with CKD = 0, rounded up to the next programmable value (never below the configured one) | `test_io.c` against the encoding formula | DTG ranges and resolution (RM0440) |
| Break | BKIN = PE15 (DRV_NFAULT), BKIN2 = PC3 (BRK2_N), both active low, digital filter 4 samples; AOE = 0 (latched until software sets MOE); OSSI = OSSR = 1; BDTR in one write with LOCK level 1; system break on core lockup and flash double-ECC error | CMSIS fields | polarity and filter semantics, the AF1/AF2 enable bits, re-arming after a break (RM0440); TIM1 break errata (ES0430) |
| DMA and memory | `adc_slow` (DMA1 channel 1, DMAMUX request 37) in SRAM1 at 0x2000007C in the current map; CCM SRAM unused; each sample is one aligned 16-bit transfer, so the slow step reads whole samples, and channels of one scan are a few microseconds apart | linker map | DMA access to SRAM1 (RM0440 bus matrix) |
| Fast-step deadline | the last compare write must complete before the counter peak: T/2 minus the conversion (0.925 us) and the interrupt entry, about 24 us at 20 kHz; on the board `fast_margin_min_ticks` (ticks of 6.25 ns left at the peak) and `fast_late_writes` | derivation in [`src/pwm.h`](src/pwm.h) | trigger and interrupt latency with flash wait states (RM0440, Arm DDI 0439); measured margin on the board |

**Memory map** ([`stm32g474xe_flash.ld`](stm32g474xe_flash.ld)):

* Flash 512 KB from 0x08000000: image region 508 KB, calibration 4 KB at 0x0807F000 (read only by the firmware).
  0x0807F000 is a multiple of 4 KB, so the calibration occupies whole pages in either bank mode (4 KB pages
  single-bank, 2 KB dual-bank); the factory bank mode is to be read in RM0440. Sizes are from ST's linker
  template, to be confirmed in DS12288.
* SRAM 96 KB from 0x20000000 (SRAM1 80 KB, SRAM2 16 KB); the 32 KB CCM SRAM is unused. Stack at the top
  (0x20018000), at least 4 KB reserved at link time, painted at start-up and measured in the main loop
  (`g_bench.stack_unused_min_bytes`); no static stack-depth analysis has been done.
* This revision uses 49.8 KB of flash and 7.8 KB of RAM.
* **STM32G474VCT6 (256 KB flash).** The image itself would fit. The current linker layout places the
  calibration page at 0x0807F000, which a 256 KB part does not have, so that variant needs its own layout with
  the calibration at the end of its flash, and matching programming instructions. Its other differences from the
  xE variant (RAM, peripherals, errata) have not been checked (DS12288). It is not an approved alternate.

## Open platform items

| Item | Needs |
|---|---|
| DRV8353 register settings (gate drive current, VDS trip, CSA gain, 6x PWM mode) and `GATE_DRIVER_CONFIGURED` | DRV8353 datasheet |
| INA228 driver (shunt calibration, VBUS and current registers) | INA228 datasheet |
| ADC clock and sampling times | DS12288, amplifier output impedance |
| IWDG timeout tolerance | DS12288 (LSI accuracy) |
| Crystal and `SEMMC_HSE_HZ` | board decision (16 MHz proposed) |
| Output behaviour while the core is halted by a debugger | RM0440 DBGMCU section (confirm the outputs are disabled when TIM1 is frozen) |
| Fast-step execution time, deadline margin, phase-sample skew, stack depth | measurement on the board (the `g_bench` fields and the timing image above) |
