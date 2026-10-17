# Flashing the STM32G474 board

Two separate things are written to flash: the firmware image (from address 0x08000000) and, later, the
calibration blob (the last 4 KB, from 0x0807F000). The image never contains a calibration, and the
firmware never writes one. Do this only at bench stage 2 or later of
[docs/BENCH_ACCEPTANCE.md](../../../docs/BENCH_ACCEPTANCE.md): logic supply from a current-limited bench
supply, no battery, no motor.

## Equipment

- An ST-LINK (ST-LINK/V3, or the one on a Nucleo board with its jumpers set for an external target)
  connected to the board's debug header J802: SWDIO (PA13), SWCLK (PA14), NRST, GND, and the 3V3 sense
  line. A 3.3 V USB-serial adapter on J802's UART pins (PC4 TX, PC5 RX) for the boot report.
- OpenOCD 0.12 or later (`interface/stlink.cfg`, `target/stm32g4x.cfg`), or STM32CubeProgrammer.

## 1. Build and record the image

```sh
cmake -S firmware -B build-g4 -G Ninja -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi-cortex-m4f.cmake \
      -DSEMMC_TARGET_STM32G474=ON -DSEMMC_SANITIZE=OFF -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build build-g4
sha256sum build-g4/semmc_stm32g474.elf
```

Record the commit and the SHA-256 in the bench log. The boot report prints the revision; a revision ending
in `-modified` was built from a tree with uncommitted changes and is not acceptable for a recorded test.

## 2. Write the image

```sh
openocd -f interface/stlink.cfg -f target/stm32g4x.cfg \
        -c "program build-g4/semmc_stm32g474.elf verify reset exit"
```

or `STM32_Programmer_CLI -c port=SWD mode=UR -w build-g4/semmc_stm32g474.bin 0x08000000 -v -rst`.

## 3. Check the boot report

At 115200 8N1 the board prints, after each reset:

```
semmc stm32g474 <revision>
clock: 160 MHz from HSI16 (no crystal: CAN off)
event log (oldest first): t_ms code a b
...
calibration: none in flash (0x0807F000)
pwm: sampling only (no valid calibration), outputs off
current offsets: not accepted (calibration missing or out of tolerance)
can: off
gate driver: not configured in this revision: DRV_ENABLE stays low
battery meter: not read in this revision: precharge bypass stays open
```

That is the expected report for this revision without a calibration. Event code 0x0001 is a boot (`a` =
reset-cause bits from RCC_CSR >> 24, `b` = boot count); the codes are listed in
`src/event_log.h`.

## 4. Read the bench values

With OpenOCD running (`openocd -f interface/stlink.cfg -f target/stm32g4x.cfg`):

```sh
python3 tools/bench_read.py --elf build-g4/semmc_stm32g474.elf --samples 10 --period 0.5 --json bench.json
```

This reads `g_bench` through the debug port while the core keeps running: state, platform faults, raw ADC
averages (the zero-current offsets with the driver disabled), pedal track fractions, PWM settings and the
worst-case fast-step and slow-step times. Do not halt the core while the power stage could be energised:
whether the TIM1 outputs are disabled while the core is halted is to be confirmed in RM0440 (this revision
never enables the gate driver, so at bench stages 2 and 3 halting is safe).

## 5. Write a calibration (only when one exists)

A calibration blob exists only for a vehicle configuration that passes hardware validation; the encoder
refuses anything else:

```sh
python3 tools/config_tool.py validate config/vehicle.<car>.yaml --mode hw
python3 tools/config_tool.py blob config/vehicle.<car>.yaml --mode hw -o cal_hw.bin
openocd -f interface/stlink.cfg -f target/stm32g4x.cfg \
        -c "init" -c "reset halt" -c "flash erase_address 0x0807F000 0x1000" \
        -c "flash write_image cal_hw.bin 0x0807F000 bin" -c "verify_image cal_hw.bin 0x0807F000 bin" \
        -c "reset run" -c "exit"
```

The firmware still refuses physical output unless the blob's provenance is `bench_measured` and it permits
output; a synthetic blob written here is rejected at boot. To remove a calibration, erase the same 4 KB.
