# Telematics firmware: status by function (v0.7)

What the NUCLEO-U575ZI-Q firmware ([`../telematics/firmware/`](../telematics/firmware/README.md)) implements, what exists only in the host model (`host/telematics/`), and the checks that would show each on the bench. **Nothing has been flashed or run on a board**; "on the target" means written for the STM32U575, compiled and linked, with the portable part unit-tested on a computer. Host simulation is not embedded firmware, and the host tests do not show that the firmware runs on the board. Bench procedure and connection table: [`../telematics/firmware/BENCH.md`](../telematics/firmware/BENCH.md).

The firmware sends nothing to the motor controller and has no supervisor ([`decisions/ADR-0013-telematics-scope.md`](decisions/ADR-0013-telematics-scope.md)).

## 1. Functions

| Function | Peripheral, pins (from ST's board files, not bench-checked) | Status | Code | Host counterpart | Bench step |
|---|---|---|---|---|---|
| Clock and timebase | MSIS 4 MHz; LSE 32.768 kHz trims the MSI (PLL mode) when it starts; TIM2 at 1 MHz, extended to 64 bits across its 32-bit overflow | on the target | `platform/u575/system_u575.c`, `board_u575.c`, `include/tm_time.h` | `host/telematics/clocks.py` | B1, B4, B7 |
| Wheel pulses | TIM2 CH4 PA3, CH3 PA2, CH1 PA0; falling edge, input filter; one `WHEEL_EDGES` record per channel every 50 ms (edges, span, cumulative total, line level, overrun) | on the target | `src/tm_wheel.c`, `TIM2_IRQHandler` in `main_u575.c` | `host/telematics/wheel.py` (speed and distance are computed at the pit) | B3 to B7 |
| Log queue | 256 records; full: the new record is dropped and counted; high-water mark | on the target | `src/tm_queue.c` | `TelematicsNode` log queue | B9 |
| Local log | STLG v1 on a W25Q NOR on SPI1 when one answers its JEDEC id at start (all of the part: 4096 slots of 4 KiB for 16 MiB; run id prefix `<uid>-NOR`), else internal flash bank 2 (0x08100000, 256 slots); one session per boot: header slot, then blocks with sequence and CRC-32; a partly filled block written after 2 s; once only the reserve (32 slots, at most 1/8) is left, sparse logging: wheel and counters every 10 s, flush every 300 s, the rest counted in `log_thinned` | on the target | `src/tm_stlg.c`, `src/tm_flashlog.c`, `src/tm_w25q.c`, `platform/u575/flash_u575.c`, `spi_u575.c` | `host/telematics/stlg.py` (byte-for-byte equal); the W25Q bus model `platform/host/tm_fakew25q.c` (busy, write enable, page wrap, ignored commands); durations in [`generated/telematics_storage.md`](generated/telematics_storage.md) | B4, B7 to B10 |
| Restart reasons and counters | reset flags to a `BOOT` record; named counters (`COUNTERS2`) every second: drops, high-water marks, stalls, lost edges, CAN overruns, uptime | on the target | `src/tm_reset.c`, `src/tm_app.c` | `host/telematics/node.py` | B2, B8 |
| Watchdog | IWDG, about 2 s | on the target | `board_u575.c` | | not yet tested |
| Console | USART1 PA9/PA10 through the ST-LINK; status line every second (time, timer overflow count, edges, wheel states, storage, log mode, time left); `STATUS`, `DUMP`, `DUMP <first> <last>`, `ERASE YES`, `HELP` | on the target | `uart_u575.c`, `main_u575.c` | `tools/telematics_import.py` reads the dump and checks the status lines (`--status-capture`); `tools/uart_capture.py` records the console | B1, B4, B7 |
| CAN receive | FDCAN1 PD0/PD1 in bus-monitoring mode (sends nothing, not even the acknowledge bit); 500 kbit/s; frames to a 128-frame ring, then `CAN2` records with receive time; only in the `tm_u575_can` image, and only when the LSE starts (the CAN clock needs it) | on the target | `platform/u575/can_u575.c` | `host/telematics/controller_adapter.py` decodes at the pit (semmc fixture, DBC) | B11 |
| IMU and temperature | I2C1 PB8/PB9, about 100 kHz, bounded waits; LSM6DSOX or ISM330DHCX at 100 Hz (`IMU`), TMP117 at 1 Hz (`TEMP`) | on the target | `i2c_u575.c`, `src/tm_imu.c` | `TelematicsNode.on_sensor` in `host/telematics/node.py`; simulated by `sim_vehicle.py` | B12 |
| GNSS with PPS capture | a UART and a timer capture channel (not allocated) | **host only** | | `host/telematics/node.py` `on_pps`, `on_sensor("gnss")`; `clocks.py` | none yet |
| Battery-side monitor | not chosen | **host only** | | `host/telematics/sim_vehicle.py`, STLG `BATT` | none yet |
| LTE modem and live uplink | UART with flow control through a 1.8 V translator (configuration B) | **host only** | | `host/telematics/node.py` (`sem.telemetry.v4`), `mqtt_link.py` | U1 to U5 |

## 2. Scheduling (no supervisor)

The firmware is one interrupt-driven capture path and a cooperative main loop; nothing waits on a lower-priority task.

1. **TIM2 interrupt (priority 1):** reads the capture registers, extends the time to 64 bits, adds the edge to the channel's accumulator. No logging, no flash, no printing.
2. **FDCAN1 interrupt (priority 2, CAN image):** copies the frame with its receive time into the 128-frame ring; a full ring counts an overrun.
3. **Main loop:** moves frames from the ring to the log queue; every 50 ms takes each wheel channel's record (capture masked for the copy only); every second the counters; then at most 64 queued records into the open block; then one bounded flash step; then the sensors on I2C, the status line and the console.
4. **Flash:** each page erase and quad-word program (internal flash), or each sector erase and 256-byte page program (NOR, after a blank check that skips erasing a blank sector), is started and then polled from the main loop, so nothing waits on it. The code runs from bank 1 while the log is written in bank 2 (the dual-bank read-while-write behaviour, to be confirmed in RM0456). While an erase runs, records wait in the queue and are counted if it fills.
5. **Later, lowest priority:** the modem state machine (configuration B). The modem never blocks acquisition or the log.

Bounded waits: an I2C wait gives up after about 20 ms (a stuck bus), an SPI transfer after about 4 ms per byte; a slow device delays the main loop but not the capture interrupt. A main loop that falls behind takes the next wheel record at once instead of catching up.

## 3. Buffers and what happens when they fill

| Buffer | Size on the target | Full | Counter |
|---|---|---|---|
| CAN ring | 128 frames | new frame dropped | `can_rx_overrun` |
| Log queue | 256 records | new record dropped | `log_dropped_queue`, `queue_high_water` |
| Log storage | NOR: 4096 slots of 4 KiB (16 MiB); internal flash: 256 slots (1 MiB) | at the reserve: sparse logging (an `EVENT` record, code 2); full: logging stops, acquisition continues | `log_thinned`, `log_dropped_storage` |
| Wheel accumulator | edges between records | an overrun marks the record; the cumulative total keeps distance | `wheel_edges_lost` |
| Uplink backlog (host model) | 30 messages | oldest dropped | `uplink_dropped` |

Recording durations per record mix and storage, measured with the firmware's own code on the host model: [`generated/telematics_storage.md`](generated/telematics_storage.md). The 16 MiB NOR holds 138 min of the bench mix (wheel only) and 26.7 min of the fixture vehicle's (394 controller frames/s, IMU, three TMP117) at full rate, then sparse logging; internal flash alone holds 7.6 and 1.5 min. In the host model, a NOR whose every sector needs erasing writes about 9 KB/s at worst, below the fixture vehicle's 10.4 KB/s; the blank check avoids the erases on a fresh or erased part. Storage for a whole attempt at the vehicle's rate is open (T-STORAGE in [`BLOCKERS.md`](BLOCKERS.md#t-storage)).

## 4. Uplink checks for configuration B (U1 to U5)

Each reproduces on the bench a property the host demonstration checks. Pass criteria are provisional until the hardware is chosen.

| # | Check | Method | Pass | Host reference |
|---|---|---|---|---|
| U1 | Network outage and reconnect with the real modem and SIM | remove the antenna or block the network for 20 s, then restore | bounded backlog, drops counted, every sequence number accounted for at the pit, replayed messages flagged; acquisition and the log unaffected | `acquisition_continues_through_uplink_outage` |
| U2 | Pit restart | stop the pit service for 10 s | no loss: the broker queues for the persistent session | `pit_restart_without_loss` (`tools/run_mqtt_demo.py`) |
| U3 | Modem supply | current probe on VBAT during transmission | voltage stays within 3.4 to 4.2 V at peak current (A7672X Hardware Design V1.04 p. 26) | none |
| U4 | Unit consumption | average and peak input power over a simulated attempt | recorded as an energy term | [`ENERGY_METHODS.md`](ENERGY_METHODS.md) 2.2 |
| U5 | Supply cut | cut the supply as the emergency stop would | log intact up to the last closed block; modem reconnects after power-up | B8 |

## 5. Open items

* The STM32U575 manuals (RM0456, DS13737, ES0499, UM2861): pin levels, LSE fitting, solder-bridge defaults, PLL limits, flash timings, the I2C timing formula, and the register behaviour listed in [`U575_REGISTER_CHECK.md`](U575_REGISTER_CHECK.md) section 3 (T-U5-DOCS). The code itself has been compared with ST's HAL and corrected where it differed (same page, section 1).
* Storage for an attempt (T-STORAGE); GNSS and PPS on the target (T-GNSS); the modem (T-MODEM).
* The controller's bus parameters and frames (T-CTRL-IF; [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md)).
