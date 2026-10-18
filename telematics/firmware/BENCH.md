# Telematics firmware on the NUCLEO-U575ZI-Q: build, flash, connect, bench test

**Status: built and host-tested, never run on hardware.** The images link (`tests/telematics/test_firmware_target.py`), and the portable code passes its unit tests and the host data-path tests (`tests/telematics/test_firmware_host.py`). No connection below has been made, measured or bench-verified. Nothing in this procedure touches the vehicle's motor controller or its high-voltage side, and the board is powered only from the ST-LINK USB port.

## 1. What the images do

| Image | Contents | First milestone step |
|---|---|---|
| `tm_u575.elf` / `.bin` / `.hex` | Wheel edges on TIM2 (1 µs capture, 64-bit time across timer overflow) -> per-channel records every 50 ms (a heartbeat when there is no edge) -> bounded log queue (256 records) -> STLG blocks -> 4 KiB slots in internal flash bank 2 (256 slots, 1 MB). It probes I2C1 at start for an LSM6DSOX or ISM330DHCX (0x6A or 0x6B) and a TMP117 (0x48) and logs them if they answer. A status line on the UART every second; reset cause and boot count in every session header. | wheel pulse -> timestamped record -> bounded queue -> persistent log |
| `tm_u575_can.elf` | The same plus FDCAN1 in bus-monitoring mode (receives every frame, sends nothing, not even the acknowledge). Frames are logged raw (STLG CAN2); the pit decodes them with the adapter the log names, here the semmc simulation fixture. Needs the LSE-locked clock: without the LSE it reports `CAN: off` and logs no frames. | controller receive adapter (bench fixture) |

Host side: `tools/telematics_import.py` reads a dump of the log region, splits it into sessions, imports them into the pit database and plots speed and distance per channel.

## 2. Build

```
# portable library, unit tests and host simulator (no hardware, no cross compiler)
cmake -S telematics/firmware -B build-telematics -G Ninja
cmake --build build-telematics && ctest --test-dir build-telematics --output-on-failure

# target images (arm-none-eabi-gcc 13.2 in CI, Ubuntu 24.04 package gcc-arm-none-eabi)
cmake -S telematics/firmware -B build-u575 -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel \
      -DCMAKE_TOOLCHAIN_FILE=$PWD/telematics/firmware/cmake/arm-none-eabi-cortex-m33.cmake -DTM_TARGET_U575=ON
cmake --build build-u575
sha256sum build-u575/tm_u575*.elf build-u575/tm_u575*.bin
```

Artifacts: `build-u575/tm_u575.{elf,bin,hex,map}` and `build-u575/tm_u575_can.{elf,bin,hex,map}`; CI uploads them as `telematics-u575-images`. The revision string printed at start is `git describe --always --dirty`: a revision ending in `-dirty` is not acceptable for a recorded bench test.

## 3. Flash and read back (commands not executed here)

Either tool, through the board's on-board ST-LINK (USB connector CN1):

```
# STM32CubeProgrammer CLI
STM32_Programmer_CLI -c port=SWD -w build-u575/tm_u575.bin 0x08000000 -v -rst
STM32_Programmer_CLI -c port=SWD -r 0x08100000 0x100000 dump.bin          # the log region (bank 2)

# OpenOCD 0.12 or later (target/stm32u5x.cfg)
openocd -f interface/stlink.cfg -f target/stm32u5x.cfg -c "program build-u575/tm_u575.elf verify reset exit"
openocd -f interface/stlink.cfg -f target/stm32u5x.cfg -c "init; reset halt; dump_image dump.bin 0x08100000 0x100000; resume; exit"
```

Write only the image at 0x08000000. **Do not mass-erase**: that also erases the log in bank 2. To clear the log on purpose, send `ERASE YES` on the UART. Without a programmer, `DUMP` on the UART prints the used slots as hex (acquisition pauses while it runs); capture it to a file.

```
python3 tools/telematics_import.py dump.bin --db bench.sqlite --out build/bench_import \
        --wheel-circumference 1.500 --wheel-ppr 1 --source "bench: signal generator, 1 pulse per 'revolution'"
python3 tools/telematics_import.py --uart-capture capture.txt --db bench.sqlite --out build/bench_import
```

## 4. Connection table

Sources for the pins: ST's NUCLEO-U575ZI-Q board support package v1.2.3, Zephyr's `nucleo_u575zi_q` board files and ST's open pin data (STM32CubeMX-DB 6.0.180), which agree; the board's user manual UM2861 and the data sheet DS13737 have not been read (blocked from this environment). Every row is **unverified on the board**.

| Signal | MCU pin | Function | Nucleo position | Connect to | Levels and notes |
|---|---|---|---|---|---|
| wheel_0 | PA3 | TIM2_CH4, AF1 | Arduino A0 (CN9) | Hall switch output (open collector) | 3.3 V logic. Internal pull-up on; fit an external 4.7 kOhm to 3.3 V for a long lead. A 5 V or 12 V sensor supply must not reach the pin: per-pin 5 V tolerance is not in the sources read (check DS13737). Counts falling edges. |
| wheel_1 | PA2 | TIM2_CH3, AF1 | Arduino A1 (CN9) | second Hall switch | as wheel_0 |
| wheel_2 | PA0 | TIM2_CH1, AF1 | Zio connector, position to confirm in UM2861 | third Hall switch | as wheel_0 |
| UART TX | PA9 | USART1_TX, AF7 | ST-LINK virtual COM port (USB) | nothing: through CN1 | 115200 8N1 (114286 actual, -0.8 %) |
| UART RX | PA10 | USART1_RX, AF7 | ST-LINK virtual COM port | nothing | commands `STATUS`, `DUMP`, `ERASE YES`, `HELP` |
| CAN RX | PD0 | FDCAN1_RX, AF9 | Zio connector, to confirm | transceiver RXD | `tm_u575_can` only. 3.3 V transceiver with VIO = 3.3 V (TJA1051T/3 or SN65HVD230 class) |
| CAN TX | PD1 | FDCAN1_TX, AF9 | Zio connector, to confirm | transceiver TXD | held recessive by bus-monitoring mode; for a hardware guarantee use the transceiver's silent pin (TJA1051T/3 S high) or leave TXD tied high (section 6) |
| SPI1 SCK / MISO / MOSI | PA5 / PA6 / PA7 | SPI1, AF5 | Arduino D13 / D12 / D11 | W25Q128JV breakout | not used by these images yet (driver and its host tests exist: `src/tm_w25q.c`) |
| SPI1 CS | PD14 | GPIO | Arduino D10 | W25Q128JV /CS | idle high |
| I2C1 SCL / SDA | PB8 / PB9 | I2C1, AF4, open drain | Arduino D15 / D14 | IMU and TMP117 breakouts | external pull-ups (on most breakouts); 3.3 V only |
| LD1 green | PC7 | GPIO | on board | | toggles every second (status line) |
| LD2 blue | PB7 | GPIO | on board | | on while a slot is being programmed |
| GND | | | any GND pin | sensor ground, transceiver ground | one ground reference (section 6) |

Pins left alone because the board uses them (open pin data `.ioc`): PA11/PA12 USB, PA15 UCPD1_CC1, PB3 SWO, PB5 UCPD. Port G (PG2 to PG15) needs VDDIO2 enabled and is not used.

## 5. Bench procedure (to be run; nothing recorded yet)

Equipment: the NUCLEO-U575ZI-Q, a USB cable, a function generator with a 0-3.3 V square output (or a Hall switch and a magnet on a slow rotor), a serial terminal, STM32CubeProgrammer or OpenOCD. For the CAN step: a USB-CAN adapter in normal mode (it acknowledges the frames), a 3.3 V CAN transceiver breakout and two 120 Ohm terminations.

| Step | Do | Expect | Record |
|---|---|---|---|
| B1 | Build, flash `tm_u575.bin`, open the terminal | banner: revision, `boot=1 reset=...`, clock line (`PLL mode on the LSE` if the LSE started), `log: slot 0 of 256`, then a status line every second; LD1 toggling | revision, banner text, whether the LSE started |
| B2 | Press reset (black button) twice | `boot=2`, `boot=3`; reset cause `PIN` | the three causes |
| B3 | 100.0 Hz square wave into wheel_0 (PA3) for 60 s, then stop | `edges=` rising by 100 per second; after stopping it holds | generator frequency (its own accuracy), edge counts |
| B4 | `DUMP` (or read bank 2 with the programmer), import with `--wheel-circumference 1.0 --wheel-ppr 1` | 100.0 edges/s gives 100.0 m/s in the import's speed (1 m per edge); the measured value minus 100 shows the timebase error (LSE-trimmed: expect ppm level; untrimmed MSI: up to the MSI accuracy in DS13737); distance = edges; after the stop: `no_evidence`, never 0 | speed error, distance, plot |
| B5 | 1 Hz, 10 Hz, 1 kHz, 5 kHz into wheel_0, each 20 s | edge counts exact at every rate; no `lost=` | the rate at which `lost` first appears, if any |
| B6 | Pull the wheel_0 lead off while running, then hold the line low with a jumper for 5 s | lead off (line high, pull-up): `no_evidence` with a falling upper bound; held low after edges: `0 m/s` with "standstill: line held active" | the import's validity per interval |
| B7 | Run 75 min with 1 kHz (32-bit timer overflow at 71.6 min) | no jump in the edge times across the overflow: speed stays 1000 m/s at 1 m per edge | speed around 71.6 min |
| B8 | Power-cycle the board during a log write (pull USB while LD2 is on), reconnect, import | the session continues as a new boot; at most one corrupt block counted; no other loss before the last counters record | import report |
| B9 | Fill the log (run long or flash a build with a smaller region), keep running | `slots=256/256`, `drop_st` rising, acquisition still running | counters |
| B10 | `ERASE YES` | erase, restart, `log: slot 0 of 256` | |
| B11 | `tm_u575_can.bin`; transceiver on PD0/PD1 with its silent pin strapped (section 6, E1); bus with both terminations; first only a USB-CAN adapter sending 8-byte frames at 500 kbit/s, then a second node (another adapter) that acknowledges | adapter alone: its frames are not acknowledged (acknowledge errors at the adapter), so the board sends nothing, not even the acknowledge bit; with the second node: `CAN: on (bus monitoring ...)`, `can=` counts every frame, no frame from the board appears on the bus | frame counts on every node, error counters, scope trace of the board's TXD (stays high) |
| B12 | IMU and TMP117 breakouts on I2C1 | banner names them; IMU records at about 100 Hz, temperature at 1 Hz in the import | IMU axes vs board orientation, temperature vs a reference thermometer |

Step B11 shows protocol-level receive-only behaviour; it does not show electrical noninterference with the vehicle bus (section 6).

## 6. Electrical checks before connecting to any vehicle bus (separate from the firmware)

Receive-only firmware does not by itself prove that the unit cannot disturb the bus. Before the unit goes near the controller team's bus (docs/CONTROLLER_INTERFACE_REQUEST.md, section 5):

| Check | Method | Pass |
|---|---|---|
| E1 transmitter disabled in hardware | transceiver silent/standby pin strapped (TJA1051T/3 S = high, or SN65HVD230 Rs to a level that disables the driver) and the MCU TXD pin not able to override it; or TXD tied to VIO through a resistor with the MCU pin not connected | with the board running and powered off, the CANH-CANL differential stays recessive (< 0.5 V) on a scope while a frame generator floods the bus |
| E2 unpowered behaviour | unit unpowered, bus active | no change in the bus's error counters or waveform; the transceiver's unpowered leakage within its data sheet figure |
| E3 termination | measure CANH-CANL resistance with the bus unpowered, with and without the unit | the unit adds no termination (its breakout's 120 Ohm removed or switched off) unless the interface agreement says otherwise; about 60 Ohm total for a bus terminated at both ends |
| E4 bus loading | the unit's input capacitance and stub length | stub within the bus's limit agreed with the controller team |
| E5 ground | the unit's ground reference to the controller's | one ground connection at the agreed point; no ground loop through the USB host during a vehicle test (use a battery-powered laptop or an isolated USB) |
| E6 supply | the unit's own supply from the 48 V pack through its DC-DC (docs/TELEMATICS_BOM.md) | the unit cannot back-feed the bus or the controller's logic supply |

## 7. What is not covered yet

GNSS with PPS capture, the SPI NOR log (driver ready, not wired into these images), the LTE modem, the live uplink from the target (the host model is `host/telematics/node.py`), a watchdog test, interrupt latency and the flash write throughput on the real part. Each is a later step in docs/TELEMETRY_EMBEDDED_PORT.md.
