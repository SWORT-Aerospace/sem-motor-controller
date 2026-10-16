# Interface control document v1.0

**Authoritative** for every interface between the motor controller, the telematics unit, the driver controls, the pit and the vehicle. Supersedes `docs/INTERFACE_CONTROL.md` (v0.1, amended v0.3), which is kept as a record. Generated tables that this document points to are part of it: `docs/generated/can_messages.md` (message layouts), `protocol/generated/semmc_base0x300.dbc`, `docs/generated/bus_load.md`.

Owners: controls lead (protocol, controller behaviour, this document); telematics engineer (telematics firmware, log, uplink); vehicle team (harness, connectors, driver controls, bus allocation). A change to any **frozen** item needs a protocol version change and the owners' agreement. Values marked PROV are provisional and simulation-only; UNKNOWN values stay null until measured or decided (`docs/INPUT_SHEET.md`).

## 1. Node responsibilities

| Node | Hardware | Responsibilities | Must never |
|---|---|---|---|
| Motor controller | STM32G474 candidate (`hardware/kicad`) | PWM, commutation, current loop, protection, state machine, arbitration of every torque source, energy at the controller input | depend on CAN, the supervisor, logging or LTE for manual driving or for any protection |
| Telematics unit | STM32U575 (telematics proposal v0.1, 14/10/2026); **allocation not frozen** (section 12) | receive timestamps, local log, GNSS/PPS, IMU, wheel halls, supervisor task (proposed), live uplink | let logging, storage or LTE delay the supervisor task; arm, select a mode or reset faults |
| Supervisor (task) | proposed on the telematics unit | ECO torque request and envelope at 50 Hz (PROV), from fresh controller telemetry only (`host/telemetry_adapter/supervisor.py`) | request propulsion from a stale, duplicated or invalid speed |
| Driver controls | wired to the controller | arming, mode (manual / ECO), cancel, brake, dead-man, fault reset | be overridden by any message |
| Vehicle hardware | vehicle | e-stop and safety loop (HW_PERMIT), fuse, battery isolation | n/a |
| Pit | laptop | MQTT broker, validation and ingestion into SQLite, offline log import, monitoring and CSIA replay in shadow mode | send any command to the car while it is not stopped and disarmed |

Motor control stays local to the controller. CSIA and the R3v monitor run in the pit, or on logged data as replay; their outputs are never an input to the controller (`docs/csia/EVALUATION_RESULTS_v2.md`, ADR-0008).

## 2. CAN

| Item | Value | Status |
|---|---|---|
| Physical | ISO 11898-2 high-speed CAN; TJA1051T/3-class transceiver | candidate; bus UNKNOWN |
| Frame | classic CAN, 11-bit identifier, DLC 8 (valid on CAN 2.0B and CAN FD buses) | frozen (protocol 1.x) |
| Identifiers | one block of 64: `supervision.can_id_base + 0x00 … 0x3F` (multiple of 0x40); protocol numbering 0x300–0x33F; the CRC data ID uses the protocol number, not the bus identifier | numbering frozen; **block allocation: vehicle team** |
| Bit rate, sample point | 500 kbit/s assumed in analyses | **UNKNOWN** (telematics proposal: CAN 2.0B, rate not stated) |
| Load | controller 394 frames/s, supervisor 72 frames/s; 12.6 % of a 500 kbit/s bus; worst-case response time of every message below its period (`docs/generated/bus_load.md`) | estimate; other traffic UNKNOWN |
| Termination, topology | 120 Ω at both ends (telematics proposal); the controller draft has a split-termination network (populate if the controller is a bus end) | position UNKNOWN |

## 3. Encoding

* **Byte and bit order:** Intel, LSB first; multi-byte fields little-endian.
* **Byte 0:** CRC-8/SAE-J1850 (poly 0x1D, init 0xFF, xorout 0xFF) over the 16-bit data ID `(major << 11) | protocol_id`, little-endian, then bytes 1–7. Check value of "123456789": 0x4B. A frame from another major version fails the CRC.
* **Byte 1:** sequence counter, u8 per message, wraps.
* **Scaling:** physical = raw × scale + offset, per field (`docs/generated/can_messages.md`).
* **Invalid values:** NaN encodes as the field's `invalid` raw sentinel; a field without a sentinel refuses to encode NaN. Decoders map the sentinel to NaN and flag raw values outside the declared range. A torque request carrying the sentinel or an out-of-range value makes the supervisor input INVALID (ECO exits); it is never read as zero torque. Measurements the controller does not have (before the first slow step, or flagged) are sent as NaN, never as 0.
* **Versioning:** protocol 1.1 (spec hash `16ff00853dfda3ce`). Minor versions are additive: 1.1 added `ctrl_energy_quality` (0x323); every 1.0 message is unchanged. `sup_hello` carries the companion's major/minor; `ctrl_session` and `ctrl_identity` carry the controller's. A major mismatch is rejected (`rx_proto_mismatch`).

## 4. Timestamps and clock domains

| Domain | Clock | Where it appears |
|---|---|---|
| controller | free-running µs timer, extended to 64 bits (`mc_time_extend`) | controller-internal; controller frames carry no timestamp, only the sequence counter |
| telematics | the unit's monotonic clock | receive time of every frame and sensor sample in the log; `src_time_ms` (u16, wraps every 65.5 s) of supervisor frames |
| utc | GNSS: PPS edges timestamped in the telematics clock | log records `PPS`; the pit maps telematics time to UTC by interpolation between edges, extrapolation marked `holdover`, `none` before two edges |

No node assumes the clocks agree. The controller checks supervisor timing against its own clock (section 5). UTC quality is carried with every UTC value. In the host demonstration the PPS-derived UTC error was 0.72 µs with PPS and 7.4 µs after 15 s of holdover (`docs/generated/host_demo/summary.md`); the hardware figure is to be measured.

## 5. Sequence, session, freshness and reconnection (controller side, `mc_freshness.c`, `mc_core.c`)

```
companion                                            controller
  sup_hello{major, minor, role 1, session S}  --->   (2 Hz until tagged)
                                              <---   ctrl_session{tag T, echo S}
  sup_limits{tag T, limits_seq L, bounds}     --->   newest set committed; previous set kept
  sup_torque_req{tag T, limits_ref L & 0xF, torque, coast, src_time_ms} --->
                                                     session established when both carry T
driver: mode switch OFF -> ON (wired)          --->   ECO_ASSIST only if the supervisor input is OK
```

* **Tag:** non-zero, `1 + (offset(boot_id) + n) mod 255` where n counts tags issued since boot and survives session resets: any 255 consecutive sessions of one boot get distinct tags. A frame with another tag is rejected (`rx_tag_mismatch`).
* **Session resets** (all tracker state cleared, tag 0 until the next hello): companion restart (new S), CAN bus-off, controller reboot (new boot_id, visible in `ctrl_status`).
* **New sample:** a frame renews freshness only if it is not an exact re-delivery of the last frame seen, its sequence is newer than every frame seen within the freshness window (ordering floor), its source time advanced, and its lag is within tolerance:
  `lag = lag_prev + local advance − source advance − 2 % of local advance`; reject if lag > 100 ms (PROV); a fresher sample becomes the reference; a sample fresher by more than 100 ms is held as a candidate and a second consistent sample re-anchors (`docs/MATH_SPEC.md` 3.8).
* **Validity windows (PROV):** request 100 ms, limits 500 ms, hello 3 s. After 30 s without a new sample the source time is ambiguous and the first frame is accepted only as a RESYNC.
* **Reconnection never resumes assist by itself:** ECO exits on any loss of the supervisor input, session reset or bus-off, and re-entry needs a new driver mode-switch edge after the session is re-established.
* **Limits sets:** a new `limits_seq` makes a new newest set and keeps the previous one; re-sending the same `limits_seq` refreshes in place; the companion changes `limits_seq` whenever the content changes. The bound applied is `min(newest, referenced)`.
* Verified by `firmware/tests/test_freshness.c`, `test_core.c` and the property test `test_core_properties.c` (properties P1–P8; soaks of 100 × 30 s and 300 × 30 s simulated driving with 0 failures). Host simulation only.

## 6. Driver controls and protection boundaries

| Signal | Path | Effect | Independent of firmware |
|---|---|---|---|
| Arm switch | wired, controller | OFF→ON edge with throttle released arms; OFF disarms | no |
| Mode switch | wired | OFF→ON edge enters ECO when the supervisor input is OK | no |
| Brake, ECO cancel | wired | torque 0 on the same update, ECO exits | no |
| Dead-man | wired, controller input and safety loop | torque 0; loop open → HW_PERMIT low | yes (HW_PERMIT) |
| E-stop | vehicle safety loop → optocoupler → HW_PERMIT | gate driver disabled in hardware | yes |
| Gate-driver ENABLE | `MCU_DRV_EN AND HW_PERMIT` (74LVC1G08), pull-downs on both and on the output | firmware alone cannot enable the bridge | yes |
| Gate-driver fault | nFAULT (VDS over-current, UVLO) → TIM1_BKIN | PWM outputs off in the timer hardware | yes |
| Bus over-voltage | comparator → TIM1_BKIN2 | PWM outputs off in the timer hardware | yes |
| Watchdog | MAX6369 WDO → HW_PERMIT (diode) and NRST | driver disabled and MCU reset | yes |
| Precharge bypass | FET gate pulled down (bypass open at power-up and in reset); rule for closing it: V_DC ≥ 0.95 V_BAT (VBUS_SENSE vs INA228) | no inrush at power-up | the pull-down yes; the closing logic belongs to the STM32G4 platform layer, **not implemented** |

Every row of this table is checked on the exported netlist by `tools/hw_consistency.py` (PR1–PR7). Electrical levels of the driver inputs, contact types and the safety-loop voltage are UNKNOWN (input sheet).

## 7. Status, trace and fault messages (controller → bus)

| Message | Period | Content |
|---|---|---|
| `ctrl_status` 0x310 | 20 ms | state, owner, supervisor link, session tag, boot id, build kind (sim/hardware), calibration provenance, output permitted, PWM enabled, derating, hardware trip, last transition |
| `ctrl_cmd_trace` 0x311 | 20 ms | requested and accepted torque, reason bits: NOT_ARMED, FAULT_INHIBIT, HW_TRIP, BRAKE_OVERRIDE, CANCEL_OVERRIDE, SUPERVISOR_INVALID, DRIVER_ABSENT, THROTTLE_LATCH, CLAMP_TORQUE, CLAMP_BATTERY, CLAMP_DERATE, CLAMP_SPEED, SLEW, SUPERVISOR_BOUND, REGEN_DISABLED, COAST |
| `ctrl_fault` 0x300 | 1 s and on change | latched fault bits (config invalid, self-test, hardware over-current, hardware over-voltage, gate driver, software over-current, bus over/under-voltage, FET and motor over-temperature, hall, current sense, bus-voltage sense, watchdog, over-speed, throttle implausible, control dt, rotor stall), first fault, reset reason, count |
| `ctrl_validity` 0x322 | 100 ms | per measurement a 4-bit field: 1 missing, 2 stale, 4 invalid (flagged, non-finite, out of range, integrity), 8 saturated |
| `ctrl_energy` 0x320 | 100 ms | energy at the controller input (bus shunt: power-stage input; logic rails are upstream and excluded), battery power |
| `ctrl_energy_quality` 0x323 | 100 ms | seconds integrated and seconds of gap (V or I invalid, or a step > 20 ms); energy is never interpolated across a gap |
| `ctrl_motion`, `ctrl_currents`, `ctrl_thermal` | 10 / 10 / 100 ms | speed, iq, vbus (NaN unless usable); id, battery current, measured/reconstructed phase masks, KCL residual and availability; temperatures and derate |
| `ctrl_identity` 0x330 | 1 s | protocol, firmware and calibration versions, calibration provenance, build kind, hardware revision |

## 8. Local log (telematics unit)

**STLG v1** (`host/telematics/stlg.py` is the reference implementation):
* header `STLG | version | metadata JSON | CRC-32`; metadata: `run_id`, `kind` (HOST SIMULATION or vehicle), format, clock domain, storage size, protocol major/minor/spec hash, calibration blob SHA-256 and provenance, vehicle configuration SHA-256, software commit and working-tree state, sensor configuration (wheel circumference, pulses per revolution, channel assignment) with its status;
* 4 KiB blocks `BK | block_seq | base_us | n | CRC-32 | records`; a power loss loses at most the block being written;
* records `type | len | dt_us | body`: CAN frame (every received and sent frame), PPS edge, GNSS fix, IMU sample, wheel window, counters, event.
The controller's calibration identity is logged twice: as the blob hash in the header and as `ctrl_identity` frames.

## 9. Storage, queues and drop reporting

| Item | Value | Status |
|---|---|---|
| Storage | QSPI flash 8 MB (telematics proposal); microSD optional | proposal |
| Rate | 9.35 KiB/s with every semmc frame and the unit's own sensors, uncompressed: 8 MB lasts 14.6 min (host demonstration); semmc frames alone: 16.9 min (`docs/generated/telematics_budget.md`) | estimate; a full run needs microSD, compression or decimation: **decision for the telematics engineer** |
| Log queue | 512 records; writer 4000 records/s (PROV) | to size on the target |
| Full queue | newest record dropped and counted (`log_dropped_queue`); receive and the supervisor are never blocked | implemented in the host model |
| Full storage | block not written, records counted (`log_dropped_storage`), `storage_full` set | implemented |
| Reporting | a `COUNTERS` record every second in the log; counters in every uplink message: rx_frames, log_records, log_dropped_queue, log_dropped_storage, uplink_sent, uplink_dropped, queue_high_water, supervisor_overruns | implemented |

## 10. LTE / MQTT and offline import

* Topic `sem/car/telemetry`, JSON schema `sem.telemetry.v1`, 2 Hz (the proposal allows 1–5 Hz): `run_id`, `seq`, `t_local_ms`, `utc` with `utc_q` and `utc_err_s`, controller state and summary values (speed, iq, vbus, mean battery power, energy, energy integrated/gap seconds, accepted torque, reason), supervisor torque and reason, GNSS, counters, `replayed`. Unknown values are JSON null.
* While LTE is down the unit keeps the newest 30 messages (15 s), drops the oldest and counts them; on reconnection the backlog is sent oldest first with `replayed = true`.
* Pit ingestion validates every message (schema, types, states, ranges) and stores rejections with their reason; keys are idempotent: `(run_id, seq)` for live messages, `(run_id, block, index)` for log records, so replays and re-imports add no rows.
* Offline import reads the STLG file from flash, SD or USB into the same SQLite database, with telematics time and PPS-derived UTC and quality per record.
* **Transport (v1.1 of this section, v0.5).**
  * Car side: MQTT 3.1.1, QoS 1 (at least once). The unit hands a message to the client only while connected; the client holds at most 10 unacknowledged messages and resends them, DUP set, after reconnecting.
  * Pit side: a subscriber with a persistent session (clean session off, fixed client id) that re-subscribes on every connection. It records every receipt in `rx` with its outcome (stored, duplicate, rejected) and the DUP flag, and commits before acknowledging, so a crash causes a redelivery, never a loss.
  * The broker persists sessions and queued messages.
  * A broker acknowledgement is not delivery to the pit: a broker that loses its state can acknowledge messages no subscriber receives. Gaps are therefore reported by `seq`, and the local log stays the complete record.
  * Host implementation: `host/telematics/mqtt_link.py`, `host/pit/mqtt_ingest.py`, `tools/mqtt_broker.py`; setup `docs/MQTT_SETUP.md`.
* **Power and emergency stop.** The telematics unit is powered from the propulsion battery downstream of the joulemeter (2026 Articles 56d, 57b); its consumption is part of the official result. The emergency stop removes its power at once (Article 37e); the log loses at most its open block, and the modem needs about 8 s after power-up before its UART is ready (A7672X Hardware Design V1.04).
* The link is monitoring only: no inbound message leads to a CAN write; no remote arming, mode selection or limit change. A future pit-to-car message (for example a schedule between runs) may be applied only while the vehicle is stopped and DISARMED, and confirmed locally.

Host demonstrations of this chain: `python3 tools/run_host_demo.py --out build/host_demo` (simulated link, section 13) and `python3 tools/run_mqtt_demo.py --out build/mqtt_demo` (real local Mosquitto broker, `docs/generated/mqtt_demo/summary.md`).

## 11. Connectors

None is confirmed. The telematics proposal shows a CAN connector with CANH, CANL and GND and 120 Ω termination at both ends. The controller's connectors in the draft schematic (battery, phases, driver controls, halls, motor temperature, CAN, SWD) have UNRESOLVED part numbers and pinouts until the harness is decided (input sheet). This section is completed when the vehicle team confirms connector types and pinouts.

## 12. STM32U575 allocation: what must be verified before it is frozen

| Item | Required | How to verify |
|---|---|---|
| Supervisor task | 50 Hz with bounded jitter while logging, SD writes and the modem are active | timestamp the task on a GPIO; logic-analyser capture during a flash stall and LTE transfer |
| CAN receive | 466 frames/s without overrun | FDCAN RX FIFO overrun counter at the full controller rate |
| Flash bandwidth | ≥ 9.35 KiB/s sustained plus erase time, without blocking the task | write benchmark with sector erases |
| RAM | log queue (512 records ≈ 10 KiB), uplink queue, GNSS and IMU buffers | linker map |
| Clock | PPS capture with a timer input; drift of the unit's oscillator | capture against GNSS PPS for 10 min |
If any item fails, the supervisor moves to another computer or ECO is not offered (manual only); the controller is unaffected.

## 13. Host demonstration (HOST SIMULATION)

`tools/run_host_demo.py` runs: synthetic driver and plant → controller core (C) → CAN → telematics node (timestamps, supervisor, bounded queue, STLG log, GNSS/PPS, IMU, halls) → controller arbitration → simulated motor → LTE/MQTT with outage → pit validation and SQLite → offline import → pit-side CSIA replay. Nine checks with their evidence: `docs/generated/host_demo/summary.md`. It validates no hardware.
