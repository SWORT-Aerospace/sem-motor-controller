# Telematics firmware: embedded port plan (not implemented)

**No telematics firmware exists.** The host model (`host/telematics/`) fixes the behaviour; this page lists what the STM32U575 firmware needs to reproduce it, and the bench checks that would show it does. The STM32U575 allocation is not frozen (`ICD.md` 12). Development starts on a NUCLEO-U575ZI-Q with an external CAN transceiver (`TELEMETRY_CANDIDATES.md`).

## 1. Drivers

| Function | STM32U575 peripheral (candidate) | Notes | Host counterpart |
|---|---|---|---|
| CAN receive and transmit | FDCAN1 (the only instance, RM0456) + external transceiver | hardware filters on the controller's 64-identifier block; RX FIFO serviced by interrupt; timestamp each frame from a free-running 1 µs timer | `TelematicsNode.on_can` |
| PPS capture | timer input-capture channel | the same timebase as CAN timestamps | `on_pps`, `UtcEstimator` |
| Wheel pulses | timer input capture, one channel per wheel | count edges per 100 ms window (PROV); a continuous Hall switch (`TELEMETRY_CANDIDATES.md`) | `Sensors`, STLG `WHEEL` |
| GNSS | UART with DMA (UBX binary protocol) | default 38400 baud (UBX-19014285 p. 15), raise after boot | STLG `GNSS` |
| IMU | SPI with DMA, data-ready interrupt captured on the timebase | self-test at boot; offset calibration at rest | STLG `IMU` |
| LTE modem | UART with RTS/CTS and DMA, through a 1.8 V level translator | AT-command MQTT client (AT+CMQTT*, A76XX AT manual V1.12 ch. 18); non-blocking state machine; power-key and reset GPIOs | `MqttLink` |
| Local log | OCTOSPI NOR flash (8 MB in the proposal), or microSD | 4 KiB blocks with header, sequence and CRC-32 (STLG v1); erase ahead of the writer | `stlg.Writer` |
| Slow temperatures | 1-Wire on a UART in half-duplex, or GPIO | 12-bit conversion up to 750 ms: start, then read later | proposed |
| Steering angle (optional) | I2C (AS5600 at fixed address 0x36) | | proposed |
| Supply monitoring | ADC on the input rail | brown-out warning before the log loses power | proposed |
| Watchdogs | IWDG + a task-level watchdog for the supervisor | | `supervisor_overruns` counter |
| RTC | LSE 32.768 kHz | wall time between PPS fixes is not trusted for UTC | |

## 2. Scheduling

Priorities follow `host/telematics/node.py`, highest first. No task may wait on a lower one.

1. **CAN RX interrupt:** timestamp, hand the frame to the supervisor's input, enqueue a log record; never waits for the log or the modem.
2. **Supervisor task, 50 Hz (PROV):** fixed-period task; output frames go to CAN first, then the log. Deadline: done within its period; a miss is counted (`supervisor_overruns`).
3. **Sensor tasks:** PPS, wheel windows, GNSS parsing, IMU reads; each fills its own bounded buffer.
4. **Log writer:** moves queued records into flash blocks at a bounded rate; a flash stall fills the queue and drops are counted, never hidden.
5. **Uplink, 2 Hz:** builds the summary, hands it to the modem state machine when connected, else to the bounded backlog.

LTE, MQTT and the modem never block the supervisor or the log: all modem I/O is DMA plus a state machine polled from the lowest-priority task.

## 3. Buffers (host values, PROV)

| Buffer | Host size | Overflow | Counter |
|---|---|---|---|
| Log queue | 512 records | drop the new record | `log_dropped_queue`, `queue_high_water` |
| Flash | 8 MB: 14.6 min at the host demo's 9.35 KiB/s | stop logging | `log_dropped_storage` |
| Uplink backlog | 30 messages (15 s at 2 Hz) | drop the oldest | `uplink_dropped` |
| Client buffer of unacknowledged MQTT messages | 10 messages | refuse; the message stays in the backlog | link statistics |

The flash size against an attempt's length is an open decision (`INPUT_SHEET.md` item 9).

## 4. Bench acceptance checks

Each check reproduces on the bench a property the host already tests. Pass criteria marked PROV until the hazard and latency analysis sets them.

| # | Check | Method | Pass | Host reference |
|---|---|---|---|---|
| E1 | Supervisor timing under load | GPIO toggle per task cycle; logic analyser during a flash stall and an LTE transfer | 50 Hz, jitter within 1 ms (PROV), no overrun | `control_unaffected_by_logging_and_lte` |
| E2 | CAN receive without loss | replay the controller's frames at the full protocol rate (466 frames/s with the supervisor's) during a flash stall | every frame logged or counted as dropped; RX FIFO never overflows | `log_drops_counted_not_hidden` |
| E3 | PPS capture | capture against the GNSS PPS for 10 min | timebase drift and capture jitter recorded; holdover error within the 50 ppm bound | `utc_alignment_with_quality` |
| E4 | Log integrity after power loss | 100 abrupt supply cuts during writing | the import reads every closed block; at most the open block lost | STLG reader tests |
| E5 | Uplink outage and reconnect with the real modem and SIM | remove the antenna or block the network for 20 s, then restore | bounded backlog, drops counted, every sequence number accounted for at the pit, replayed messages flagged | `run_mqtt_demo.py` checks |
| E6 | Pit restart | stop the pit service for 10 s | no loss: the broker queues for the persistent session | `pit_restart_without_loss` |
| E7 | Modem supply | current probe on VBAT during 2G/LTE transmission | voltage stays within 3.4-4.2 V at peak current (A7672X Hardware Design V1.04 p. 26) | n/a |
| E8 | Unit consumption | average and peak input power over a simulated attempt | recorded as an energy term for the analysis | `ENERGY_METHODS.md` |
| E9 | Emergency-stop power cut | cut the supply as the e-stop would | log intact up to the last closed block; modem reconnects after power-up (about 8 s to UART-ready) | `ICD.md` 9 |

## 5. Open items before the port starts

* The telematics board files (`bk4000tg_kicad.zip`, `telemetry.pdf`) to fix pins and parts.
* The STM32U575 datasheet (DS13737) to confirm electrical and temperature limits.
* The vehicle CAN bus parameters (`INPUT_SHEET.md` item 5) and the controller's identifier block.
* The battery arrangement: no accessory battery on the telematics board (Article 57b).
