# Minimal bench: handoff to the physical team

One wheel input through the whole chain: a signal generator on PA3, TIM2 capture, the log in internal flash, a
power cycle, the console DUMP, the decoder, the database, the review, a receipt and a speed and distance plot. The
detailed procedure is `BENCH_MINIMAL.md` inside the package below, and
[`../firmware/BENCH_MINIMAL.md`](../firmware/BENCH_MINIMAL.md) in the repository.

**Bench only, on USB power.** Nothing connects to the vehicle, its battery or the controller's bus. The unit has no
propulsion authority. **Nothing here has been run on a board yet.**

## 1. What to flash

| Item | Value |
|---|---|
| Commit | `b734667dd2f325d906fc2b891509ad13057aa81a` on `eng/v0.7-telematics` (SWORT-Aerospace/sem-motor-controller#6, not merged) |
| CI artifact | `telematics-bench-minimal`, artifact ID 12156850299, from the **push** run [39181623624](https://github.com/SWORT-Aerospace/sem-motor-controller/actions/runs/39181623624) (zip SHA-256 `ccc71bf52cd53179727e3da866d1cd8f5a7f334f0c6d7f205a4efcbfe986974c`). Do not use the pull-request run's artifact: it is built from a merge commit and carries a different revision and hash |
| Firmware | `images/tm_u575.bin`, 20,464 bytes, SHA-256 `5c244a88cb3ddbc896ff7540c28005a77651d948d5c382af748027d0a2f4f53d` (the same hash as a local build of `b734667`) |
| Also in the package | `tm_u575.elf` `6d73a6a5ef9c60b92fbaa9fb8dc11ab24dc5aa91053037455d2d5656ba1c1a87`, `tm_u575.hex` `dbf30125337457504c45a323f308450c3ef2680003d866e2ae52a85229c2610f`, `MANIFEST.json` (every file's hash), the blank `RESULTS_FORM.md` and `results.yaml`, `tools/uart_capture.py` |
| Revision in the banner | `b734667dd2f3` |

## 2. Gate before flashing: document checks DC01 to DC10 (open)

These ten checks must each be answered from RM0456, DS13737, ES0499 or UM2861, with the document's revision and
page, before M1. Do not flash while any is open or any answer contradicts the firmware line it names. They are open
because the four PDFs could not be obtained here. Commit them to `docs/reference/datasheets/` and the software side
completes [`DOCUMENT_CHECKS_RECORD.md`](DOCUMENT_CHECKS_RECORD.md). If you answer them yourselves, use the same table
on the results form.

The Winbond checks (DC11 to DC15) do not apply here: they come before external NOR use (full bench B0 and B7). Leave
Arduino D10 to D13 (SPI1) unconnected: with nothing answering there, the firmware logs to internal flash.

## 3. Hardware and equipment

| Item | Note |
|---|---|
| NUCLEO-U575ZI-Q | the board |
| USB data cable, PC to the ST-LINK port | connector type per UM2861 (DC01) |
| 2 male jumper wires | generator to A0 and GND |
| Signal generator | 100.000 Hz square, 0 to 3.3 V, high-impedance load setting, with its frequency accuracy |
| Oscilloscope | the generator's levels before connecting |
| Multimeter | continuity of the two wires |
| PC | STM32CubeProgrammer CLI or OpenOCD; Python 3 with `requirements.txt`; the repository at `b734667` |

## 4. Connections

| Row | Signal | MCU pin | NUCLEO position | Connect to | Checked against |
|---|---|---|---|---|---|
| `usb` | power, programming, console | PA9/PA10 (USART1) | ST-LINK USB port | PC | firmware line (CI); ST board support package v1.2.3 agrees |
| `leds` | LD1 green, LD2 blue | PC7, PB7 | on board | nothing | firmware line (CI); ST board support package v1.2.3 agrees |
| `wheel_0` | TIM2_CH4, AF1 | PA3 | Arduino A0 | generator output | firmware line (CI); A0 position from Zephyr's board description only |
| `wheel_1` | TIM2_CH3 | PA2 | Arduino A1 | nothing (open) | firmware line (CI) |
| `wheel_2` | TIM2_CH1 | PA0 | not needed | nothing (open) | firmware line (CI) |
| `gen_gnd` | ground | | any GND | generator ground | |

No row has been checked against UM2861 (DC01) or on a board. Record each position found and its continuity on the
results form.

## 5. Steps, expected results, stop conditions

| Step | Do | Expected | Stop if |
|---|---|---|---|
| M0 | Unpowered. Gate of section 2. `sha256sum images/tm_u575.bin`. Generator output off; set 100.000 Hz, low 0 V, high 3.3 V, high-Z; enable into nothing, check on the scope, disable. Wire A0 and GND. Continuity. | hash equal; low -0.1 to 0.1 V, high 3.0 to 3.3 V, 100.0 Hz; both wires continuous | a check is open or contradicts the firmware; the hash differs; the scope ever shows above 3.3 V or below -0.1 V |
| M1 | Generator off. USB in. `STM32_Programmer_CLI -c port=SWD -w images/tm_u575.bin 0x08000000 -v -rst`. `python3 tools/uart_capture.py /dev/ttyACM0 capture_M1.txt`. Do not halt the core with a debugger (2 s watchdog). | banner `telematics tm_u575 b734667dd2f3 boot=1`; `log: internal flash bank 2 (0x08100000, 1 MiB, 256 slots): no W25Q NOR of 1 to 16 MiB answered, slot 0 of 256`; `CAN: off (not in this image)`; `IMU: none, TMP117: none`; a `chip: rev` line; one status line per second with `wheel=NNN edges=0/0/0`; LD1 toggling | the flash verify fails; the revision differs or ends in `-dirty`; the log line names a W25Q NOR or says the internal log is refused; `boot=` rises without a reset press; no banner; a part gets hot. If the first start shows a slot other than 0 or `PAUSED`, type `ERASE YES` once and record it; stop if it persists |
| M2 | After 5 status lines, generator on for 60 s by the status line's `t=`, then off. Keep capturing until LD2 has stayed off for 5 s. | `edges=` of wheel_0 up 100 per line, plus or minus 1; `wheel=MII` within about 1 s; `lost=0`; `wheel=SNN` after the stop | the board restarts (a new banner). A wrong edge rate or `lost` above 0 is a result, not a stop: record it and continue |
| M3 | Generator off. Unplug USB for 10 s, plug back. `python3 tools/uart_capture.py /dev/ttyACM0 capture_M3.txt`, type `DUMP`, wait for `DUMP END`. | `boot=2`, a power-on or brown-out reset cause, `slot n of 256` with n above 0; `DUMP BEGIN 256`, one `S` line per used slot, `DUMP END` | slot 0 after the power cycle (the log did not persist: do not erase, return the files). Never `ERASE YES` or a mass erase after M2 |
| M4 | `python3 tools/run_bench_chain.py --uart-capture capture_M3.txt --pulse-hz 100 --circumference 0.1 --ppr 1 --boot 1 --out bench/M_chain`, then `python3 tools/pit_query.py --db bench/M_chain/pit.sqlite gaps --run <run_id> --signal wheel.wheel_0.speed` | `BENCH CHAIN ... (BENCH): PASS`: median speed within 0.2 % of 10.00 m/s, no speed of 0, distance about 600 m equal to the edge total x 0.1 m, receipts complete with "assumed timestamp bounds not accepted", the plot written | a check fails: do not rerun with other arguments; return everything. M4 can also be run from the returned captures |

## 6. Files to return

Commit them under `telematics/bench/results/<YYYY-MM-DD>_minimal/`, unedited:

| File | Content |
|---|---|
| `capture_M1.txt` | raw console capture from flashing to the end of M2 |
| `capture_M3.txt` | raw console capture after the power cycle, with the whole DUMP: this is the raw log |
| `dump.bin` | only if the log was read with the programmer instead (`STM32_Programmer_CLI -c port=SWD -r 0x08100000 0x100000 dump.bin`) |
| `RESULTS_FORM.md`, `results.yaml` | filled, with names and dates, including the document checks and the connection positions found |
| `setup_*.jpg` | the board with both wires visible; the generator's display; the scope screen with the M0 levels |
| `instruments.txt` | generator model, waveform, frequency, high and low levels, load setting, stated accuracy; scope model, probe attenuation, V/div, time/div, coupling, trigger; multimeter model; PC OS, programmer and ST-LINK firmware versions; terminal or `uart_capture.py` |
| `MANIFEST.json` | the one from the artifact flashed |
| `bench/M_chain/` | if M4 was run: `chain.json`, `chain.md`, the plot, `pit.sqlite` and the gaps listing |

## 7. Next action

The next action belongs to the physical team, with the four ST documents committed (or answered on the form) before
M1. Nothing further on the software side is planned until the files of section 6 come back.
