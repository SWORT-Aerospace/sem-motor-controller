# Minimal bench: handoff to the physical team

One wheel input through the whole chain: a signal generator on PA3, TIM2 capture, the log in internal flash, a
power cycle, the console DUMP, the decoder, the database, the review, a receipt and a speed and distance plot. The
detailed procedure is `BENCH_MINIMAL.md` inside the package below, and
[`../firmware/BENCH_MINIMAL.md`](../firmware/BENCH_MINIMAL.md) in the repository.

**Bench only, on USB power.** Nothing connects to the vehicle, its battery or the controller's bus. The unit has no
propulsion authority. **Nothing here has been run on a board yet.**

**Decision (2026-10-19): do not start M1 yet.** The gate of section 2 is not met. Eight pre-flash checks need the
STM32U575 data sheet DS13737 or the reference manual RM0456, which have not been provided. M0's unpowered part can be
prepared meanwhile.

## 1. What to flash

| Item | Value |
|---|---|
| Commit | `ca74302` on `eng/v0.7-telematics` (SWORT-Aerospace/sem-motor-controller#6, not merged) |
| CI artifact | `telematics-bench-minimal`, artifact ID 12160820013, from the **push** run [39191847887](https://github.com/SWORT-Aerospace/sem-motor-controller/actions/runs/39191847887) (zip SHA-256 `bb60bf8c546669644c92972070d6316310876305b5ff6c4b30046a1f3e3ebc74`). Do not use the pull-request run's artifact (run 39191851097, artifact 12160316716): it is built from a merge commit and carries a different revision and hash |
| Firmware | `images/tm_u575.bin`, 20,576 bytes, SHA-256 `1a758fbea520b05ff68b2cba50a0d9502d492f5f25dfb815cd769cc932f48e12` (the same hash in CI and in a local fresh-clone build) |
| Also in the package | `tm_u575.elf` `e06f38d0a4639a1814660e4ae1cd9d270d8a95c82bbfaef01cfea9fe1dc1ad00`, `tm_u575.hex` `77d24508ed102cee629462d5212fbfdc1259c14c698062132843a84433bd3583`, `MANIFEST.json`, the blank `RESULTS_FORM.md` and `results.yaml`, `tools/uart_capture.py` |
| Revision in the banner | `ca7430256449` |
| Superseded | `b734667` (artifact 12156850299): do not flash. It leaves the LSE drive unset, which ES0499 forbids on revision X, and aborts I2C transfers on a spurious bus error |
| Later commits | add the vehicle image (`tm_u575_vehicle`: GNSS and PPS) and the live summary. They change the bytes of `tm_u575` (an unused record hook in the application, the metadata's UTC field formatted from a parameter) but not what it does or prints, so a build of a later commit has a different hash. The minimal bench flashes `ca74302`'s artifact above; a new candidate, with new hashes here, is made only when the bench needs a firmware change |

## 2. Gate before flashing

| Check | Document | Status |
|---|---|---|
| DC01 board: positions, console routing, power, crystal, connector | UM2861 Rev 10 | complete (documentary) |
| DC10 errata for the silicon revisions | ES0499 Rev 12 | complete for the minimal image; 2.2.27 (MSI PLL unlock) has no workaround in the firmware |
| DC02 PA3 input limits; DC03 alternate-function numbers; DC09 flash times and LSI range | DS13737 | **open** |
| DC04 clocks; DC05 TIM2 capture; DC06 flash programming; DC07 flash ECC; DC08 option bytes | RM0456 | **open** |

Answers, pages and affected code: [`DOCUMENT_CHECKS_RECORD.md`](DOCUMENT_CHECKS_RECORD.md). Commit DS13737 and RM0456
to `docs/reference/datasheets/` (`st-ds13737-stm32u575.pdf`, `st-rm0456-stm32u5.pdf`); the open checks are then
answered from them. M1 may start only when every check is answered and none contradicts the firmware line it names.
The Winbond checks (DC11 to DC15) do not apply here: they come before external NOR use. Leave Arduino D10 to D13
(SPI1, CN7 pins 10 to 16) unconnected.

## 3. Hardware and equipment

| Item | Note |
|---|---|
| NUCLEO-U575ZI-Q | the board; read its sticker in M0 |
| USB data cable, Type-A or Type-C to **Micro-B** | the ST-LINK connector CN1 is Micro-B (UM2861 section 3.1, Table 6); the board's Type-C connector is not used |
| 2 male jumper wires | generator to A0 and GND |
| Signal generator | 100.000 Hz square, 0 to 3.3 V, high-impedance load setting, with its frequency accuracy |
| Oscilloscope | the generator's levels before connecting |
| Multimeter | continuity of the two wires |
| PC | STM32CubeProgrammer CLI (SWD at 8 MHz or less, UM2861 Table 22) or OpenOCD; Python 3 with `requirements.txt`; the repository at `ca74302` |

## 4. Connections

| Row | Signal | MCU pin | Position (UM2861 Rev 10) | Connect to | Firmware line |
|---|---|---|---|---|---|
| `usb` | power, programming, console | PA9/PA10 (USART1) | CN1, USB Micro-B (Table 6, p. 14); USART1 to the ST-LINK virtual COM port with SB32, SB34 ON (Table 10, p. 29) | PC | `uart_u575.c:17` |
| `leds` | LD1 green, LD2 blue | PC7, PB7 | on board (section 7.5, p. 25) | nothing | `board_u575.c` `board_led` |
| `wheel_0` | TIM2_CH4, AF1 | PA3 | A0, CN9 pin 1 (Table 17, p. 35) | generator output | `board_u575.c:161`, `:173` |
| `wheel_1` | TIM2_CH3 | PA2 | A1, CN9 pin 3; also CN10 pin 13 by default (Table 20, p. 39) | nothing (open) | same |
| `wheel_2` | TIM2_CH1 | PA0 | CN10 pin 29 (Table 18, p. 35) | nothing (open) | same |
| `gen_gnd` | ground | | GND, CN9 pin 12 or 23 (Table 17) | generator ground | |

Default jumpers (Table 4, p. 7): JP1 OFF, JP2 ON, JP4 [1-2] (VDD 3.3 V), JP5 ON, JP6 [1-2] (5 V from the ST-LINK).
These are the documents. Whether this board matches is recorded in M0: position found, continuity, jumpers and
sticker.

## 5. Steps, expected results, stop conditions

| Step | Do | Expected | Stop if |
|---|---|---|---|
| M0 | Unpowered. Gate of section 2. `sha256sum images/tm_u575.bin`. Read the sticker: product identification and main board revision. Check the jumpers. Generator output off; set 100.000 Hz, low 0 V, high 3.3 V, high-Z; enable into nothing, check on the scope, disable. Wire A0 and GND. Continuity. | hash equal; sticker NUU575ZIQ$AT1 to $AT4 with MB1549-U575ZIQ-C02, C03 or C05; jumpers as section 4; low -0.1 to 0.1 V, high 3.0 to 3.3 V, 100.0 Hz; both wires continuous | a check is open or contradicts the firmware; the hash differs; the sticker is not one of those; a jumper differs from its default (record, do not move it); the scope ever shows above 3.3 V or below -0.1 V |
| M1 | Generator off. USB in. `STM32_Programmer_CLI -c port=SWD freq=8000 -w images/tm_u575.bin 0x08000000 -v -rst`. `python3 tools/uart_capture.py /dev/ttyACM0 capture_M1.txt`. Do not halt the core with a debugger (2 s watchdog). **Never press the blue user button B1**: PC13 transitions disturb the LSE on this package (ES0499 2.2.1). | LD5 on; banner `telematics tm_u575 ca7430256449 boot=1`; `clock: ... PLL mode on the LSE (LSE accuracy)`; `log: internal flash bank 2 (0x08100000, 1 MiB, 256 slots): no W25Q NOR of 1 to 16 MiB answered, slot 0 of 256`; `CAN: off (not in this image)`; `IMU: none, TMP117: none`; `chip: rev 0x2001` for $AT1 or $AT2, `0x3001` for $AT3, `0x3007` for $AT4; one status line per second with `wheel=NNN edges=0/0/0`; LD1 toggling | the flash verify fails; the revision differs or ends in `-dirty`; the chip revision does not match the sticker; the log line names a W25Q NOR or says the internal log is refused; `boot=` rises without a reset press; no banner; LD5 off; a part gets hot. If the clock line says the LSE did not start, record it and continue: M4's speed check may then fail. If the first start shows a slot other than 0 or `PAUSED`, type `ERASE YES` once and record it; stop if it persists |
| M2 | After 5 status lines, generator on for 60 s by the status line's `t=`, then off. Keep capturing until LD2 has stayed off for 5 s. | `edges=` of wheel_0 up 100 per line, plus or minus 1; `wheel=MII` within about 1 s; `lost=0`; `wheel=SNN` after the stop | the board restarts (a new banner). A wrong edge rate or `lost` above 0 is a result, not a stop: record it and continue |
| M3 | Generator off. Unplug USB for **at least 10 s** (ES0499 2.2.9: below 100 mV for more than 200 ms), plug back. `python3 tools/uart_capture.py /dev/ttyACM0 capture_M3.txt`, type `DUMP`, wait for `DUMP END`. | `boot=2`, a power-on or brown-out reset cause, `slot n of 256` with n above 0; `DUMP BEGIN 256`, one `S` line per used slot, `DUMP END` | slot 0 after the power cycle (the log did not persist: do not erase, return the files). Never `ERASE YES` or a mass erase after M2 |
| M4 | `python3 tools/run_bench_chain.py --uart-capture capture_M3.txt --pulse-hz 100 --circumference 0.1 --ppr 1 --boot 1 --out bench/M_chain`, then `python3 tools/pit_query.py --db bench/M_chain/pit.sqlite gaps --run <run_id> --signal wheel.wheel_0.speed` | `BENCH CHAIN ... (BENCH): PASS`: median speed within 0.2 % of 10.00 m/s, no speed of 0, distance about 600 m equal to the edge total x 0.1 m, receipts complete with "assumed timestamp bounds not accepted", the plot written | a check fails: do not rerun with other arguments; return everything. M4 can also be run from the returned captures |

## 6. Files to return

Commit them under `telematics/bench/results/<YYYY-MM-DD>_minimal/`, unedited:

| File | Content |
|---|---|
| `capture_M1.txt` | raw console capture from flashing to the end of M2 |
| `capture_M3.txt` | raw console capture after the power cycle, with the whole DUMP: this is the raw log |
| `dump.bin` | only if the log was read with the programmer instead (`STM32_Programmer_CLI -c port=SWD freq=8000 -r 0x08100000 0x100000 dump.bin`) |
| `RESULTS_FORM.md`, `results.yaml` | filled, with names and dates, including the document checks, the sticker, the jumpers and the connection positions found |
| `setup_*.jpg` | the sticker; the jumpers; the board with both wires visible; the generator's display; the scope screen with the M0 levels |
| `instruments.txt` | generator model, waveform, frequency, high and low levels, load setting, stated accuracy; scope model, probe attenuation, V/div, time/div, coupling, trigger; multimeter model; PC OS, programmer and ST-LINK firmware versions; terminal or `uart_capture.py` |
| `MANIFEST.json` | the one from the artifact flashed |
| `bench/M_chain/` | if M4 was run: `chain.json`, `chain.md`, the plot, `pit.sqlite` and the gaps listing |

## 7. Next action

1. DS13737 and RM0456 committed, so the software side can answer DC02 to DC09 (and fix any discrepancy, which would
   make a new candidate and update section 1).
2. Then the physical team runs M0 to M4 with the artifact of section 1 and returns the files of section 6.
