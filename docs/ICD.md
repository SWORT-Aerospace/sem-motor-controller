# Interface control document v2.0

**Authoritative** for the interfaces of the telematics unit: with the vehicle's motor controller (receive only), with its own sensors, its local log, its uplink to the pit and the pit's import. Part B keeps the interfaces of the deferred controller development and of the `semmc` simulation fixture, unchanged in substance from v1.0 (v0.6); they bind nothing in the telematics delivery. Supersedes v1.0 (this file's history) and `docs/archive/INTERFACE_CONTROL.md`.

Owners: telematics engineer (Part A); the controller team owns its controller's interface, which Part A records once they answer [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md); controls and hardware leads (Part B). UNKNOWN values stay null until measured or stated by their owner (`docs/INPUT_SHEET.md`).

# Part A. Telematics unit (current)

## A.1 Nodes and responsibilities

| Node | Hardware | Responsibilities | Must never |
|---|---|---|---|
| Motor controller | the controller team's product; model UNKNOWN | its own drive, protection, precharge, driver controls; whatever it broadcasts on CAN | depend on the telematics unit for anything |
| Telematics unit | NUCLEO-U575ZI-Q for development (`telematics/firmware/`); a product board later | receive and timestamp the controller's broadcast; capture its own sensors; local log; live summary to the pit | transmit on the vehicle bus: no torque request, arming, mode selection, fault reset, configuration change, or part in protection or precharge |
| Pit | laptop | MQTT broker, validation and SQLite storage, log import, analysis, shadow-mode monitors | send anything to the car |

The deployed node (`host/telematics/node.py` as the host model, `telematics/firmware/` on the target) has no transmit path; tests check both (`tests/telematics/test_wheel_node_pit.py`, `tests/telematics/test_firmware_target.py`). The earlier supervised node is a research simulation only (`host/telemetry_adapter/legacy_node.py`, Part B).

## A.2 Vehicle CAN interface (receive only)

| Item | Value | Status |
|---|---|---|
| Role of the unit | listener; FDCAN1 in bus-monitoring mode (no frame, no acknowledge, no error frame); transceiver transmitter disabled in hardware (silent pin) | firmware implemented, not run on hardware |
| Physical layer, bit rate, frame format, identifiers | as the controller team states them | **UNKNOWN**: [`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md) section 2 |
| Messages and signals | from their DBC or protocol document, decoded by `DbcAdapter` with a unit-checked mapping | **UNKNOWN** until their answer |
| Bus load added by the unit | zero frames | by design |
| Termination | none added unless the controller team asks | the breakout's terminator switched off |
| Electrical noninterference | not proven by receive-only firmware; the checks E1 to E6 of `telematics/firmware/BENCH.md` section 7 | to be run before any connection |
| Test fixture | `semmc` (Part B), our own message set, used only to exercise the adapter path in simulation and on the bench | not an agreed interface |

## A.3 Measurements and adapters

Every received or sensed value becomes a measurement (`host/telematics/measurement.py`): `record_id` (local), `source`, `signal` and `unit` from the registry (`host/telematics/signals.py`), `value` or null, `t_rx_us`, `t_sample_us` (null when the source gives no sample time; never invented), `t_unc_us`, `source_seq` (the source's own counter, or null), `validity` (`valid`, `unverified`, `invalid`, `out_of_range`, `decode_error`, `no_evidence`), `provenance`, and `upper` for a bounded unknown. A missing value is null with its reason, never zero.

| Adapter | Use | Sequence | Sample time | Validity |
|---|---|---|---|---|
| `SimFixtureAdapter` (`semmc-sim-fixture`) | simulation and bench fixture | byte 1 of every semmc frame | none in the protocol: receive time, uncertainty one broadcast period (ASSUMED) | CRC-8 per frame; `ctrl_validity` flags fresh within 0.3 s, else `unverified` |
| `DbcAdapter` | the controller team's definitions | a counter signal named in the mapping, else none | only if the mapping names a time signal | sentinel raw values and flag signals named in the mapping; units checked against the DBC at load |

The log keeps the raw frames (STLG `CAN2`), so the pit can decode them again with a corrected adapter; the adapter's identity is in the log metadata (`controller_adapter`).

## A.4 Time

| Domain | Clock | Use |
|---|---|---|
| telematics | TIM2, 1 MHz, extended to 64 bits across overflow (`tm_time.h`); MSIS locked to the LSE when it starts, else untrimmed MSI (the log metadata says which) | every receive and capture time |
| source | whatever a source states (none for the controller's broadcast in the fixture) | `t_sample_us` when given and mapped |
| utc | GNSS PPS edges timestamped in the telematics clock | pit interpolation between edges (`pps`), extrapolation (`holdover`), `none` before two edges |

## A.5 The unit's own inputs

Pins, levels and the connection table: `telematics/firmware/BENCH.md` section 4 (not bench-verified). Wheel edges are captured on falling edges with a 2 µs input filter; one record per channel every 50 ms, a heartbeat when there was no edge. No edge is no evidence, never 0 m/s; a channel silent while another moves is suspect (stuck active, or stuck inactive / disconnected), as `docs/ENERGY_METHODS.md` 0.2 describes. COUNTERS2 ids 24 and 25 count suspect episodes; the status line shows each channel's state (N M S A I). IMU (LSM6DSOX or ISM330DHCX) and up to four TMP117 (addresses 0x48 to 0x4B, one TEMP channel each) on I2C1 when they answer at start; GNSS with PPS and the battery-side monitor are on the host model only so far; 1-Wire probes have no driver (an option in the BOM, in no total).

## A.6 Local log (STLG v1)

`host/telematics/stlg.py` is the reference; the firmware writes the same format (`telematics/firmware/src/tm_stlg.c`).
* Header `STLG | u16 1 | u32 meta length | metadata JSON | CRC-32`. Metadata: `run_id` (unit and boot: one session per boot; `<uid>-NOR-B<boot>` for a session on the NOR, which counts its own boots, so the two storages never give the same run id), `storage`, `unit_id`, `boot`, `reset` (cause and flags), clock source, format, `controller_adapter`, `transmits`, sensors (wheel circumference and pulses per revolution or null, channel names), firmware revision, kind (simulation, bench or vehicle).
* Block `BK | u32 seq | u64 base_us | u16 n | CRC-32 | records`, at most 4076 bytes of records; the base lies up to 1 s before the first record so slightly older records still fit.
* Records `u8 type | u8 len | u32 dt_us | body`. Types: 1 CAN, 2 PPS, 3 GNSS, 4 IMU, 5 WHEEL (counts per window, legacy), 6 COUNTERS (legacy), 7 EVENT, 8 TEMP, **9 WHEEL_EDGES** (channel, flags, edges, span, cumulative edges, record counter, lost edges), **10 COUNTERS2** (id/value pairs), **11 CAN2** (29-bit and FD capable), **12 BOOT** (boot count, reset flags and cause), **13 BATT** (battery-side monitor). Readers keep unknown types as raw bytes.
* On the target the log region is a W25Q NOR on SPI1 when one of 1 to 16 MiB answers its JEDEC id at start (the whole part: 4096 slots of 4 KiB for 16 MiB), else internal flash bank 2 (1 MB, 256 slots): a header slot per session followed by block slots, never wrapped; a slot interrupted by a power loss fails its CRC and is counted; `ERASE YES` on the console clears the region (a chip erase on the NOR). `DUMP <first> <last>` prints a slot range with the session header before it. `tools/telematics_import.py` splits a dump, whole or ranged, into sessions.
* EVENT code 2 marks the switch to sparse logging (A.7).

## A.7 Queues, storage and loss reporting

| Item | Value | Status |
|---|---|---|
| Log queue | 256 records on the target, 512 in the host model; a full queue drops the new record and counts it | implemented |
| Storage | W25Q128JV NOR (16 MiB) on the bench and in configuration A, internal flash 1 MB as the fallback; durations per record mix in `docs/generated/telematics_storage.md` (NOR: 138 min of the bench mix, 26.7 min of the fixture vehicle's at full rate); microSD is an option without a driver | implemented (NOR host-tested on a bus model; not on hardware) |
| Storage reserve | once only min(32 slots, 1/8 of the storage) are free: sparse logging, one `WHEEL_EDGES` record per channel and the counters every 10 s, blocks flushed every 300 s; CAN, IMU and TEMP records counted in `log_thinned` and not written; an `EVENT` code 2 marks the switch | implemented |
| Full storage | the block is not written, its records are counted (`log_dropped_storage`), acquisition continues | implemented |
| Counters | COUNTERS2 every second and in every live message: frames received, decoded, ignored, unknown, invalid, companion frames seen, records logged, queue drops and high water, storage drops, blocks written, stall events, write errors, wheel records and lost edges, wheel suspect episodes (ids 24 stuck active, 25 stuck inactive or disconnected), records thinned in sparse logging (id 26), CAN ring overruns, uplink sent, dropped and backlog high water, uptime | implemented |
| Restart | a new session with `BOOT` (count, cause); the import reports the gap and that records after the last counters record of the previous session are unaccounted | implemented |

## A.8 Live uplink

* Topic `sem/car/telemetry`, MQTT 3.1.1, QoS 1, 2 Hz. Schema **`sem.telemetry.v4`**: `run_id`, `boot`, `seq`, `t_local_ms`, `utc`, `utc_q`, `utc_err_s`, `adapter` (`id`, `fixture`, `silent_ms`), `registry` (the signal registry's identifier: units and ranges), `m` (per signal `[value, q, age_ms, source seq, time reference ("s" sample, "r" receive), upper]`, q one of the validities above or `stale` or `missing`; the value is null unless q is `valid` or `unverified`; values rounded to 6 significant digits), `counters`, `replayed`.
* The pit rejects a v4 message with a `sup` or `ctrl` block (the receive-only node has neither), an unknown registry, a unit or range outside the registry, a value with a q that is not valid, or an age beyond the signal's staleness limit. It still accepts `sem.telemetry.v1` to `v3` from the legacy simulations and older runs.
* While the link is down the unit keeps the newest 30 messages, drops the oldest and counts them; the backlog is sent oldest first with `replayed = true`; the log does not depend on the link.
* Transport, persistence and the meaning of a broker acknowledgement: unchanged from v1.0 (`docs/MQTT_SETUP.md`; host implementation `host/telematics/mqtt_link.py`, `host/pit/mqtt_ingest.py`). The link is monitoring only: no inbound message reaches the vehicle bus.
* Measured size in the demonstration: about 2.1 KB per message (`docs/generated/telematics_demo/summary.json`), 15 MB per running hour at 2 Hz; 1 Hz or fewer signals halves it.

## A.9 Pit import and database

`host/pit/ingest.py`: tables `runs`, `live`, `rejected`, `rx`, `records`, `signals` (names the shadow replay reads), `measurements` (every measurement with its fields, keyed by `(run_id, record_id)` where the import's record id comes from the record's place in the log), `imports`. A second import of the same log adds nothing. Energy from valid aligned V x I at the controller input and at the battery, with missing intervals: `host/pit/energy.py`, `docs/ENERGY_METHODS.md` 0.1.

## A.10 Power

On the bench the unit is powered from USB only. On the vehicle it is to be powered from the propulsion battery (48 V nominal, 10 Ah as the vehicle team reports it) through its own fuse, TVS, reverse protection and an isolated DC-DC, downstream of the joulemeter, so that its consumption counts in the official result; **this connection is blocked** until the battery's maximum voltage is known and a TVS and DC-DC pair passes the clamp rule (`docs/TELEMATICS_BOM.md`, Vehicle supply; T-VEH-PWR). It takes no supply from the controller's connector. The emergency stop removes its power; the log loses at most the queued records and the open block, which the import reports.

# Part B. Deferred controller development and the semmc simulation fixture

The sections below are the v1.0 interfaces of our own controller design and of the `semmc` protocol. They describe the deferred controller development and the simulation fixture; nothing in Part A depends on them, and the vehicle's actual controller does not use them.

### B.1 Node responsibilities

| Node | Hardware | Responsibilities | Must never |
|---|---|---|---|
| Motor controller | STM32G474 candidate (`hardware/kicad`) | PWM, commutation, current loop, protection, state machine, arbitration of every torque source, energy at the controller input | depend on CAN, the supervisor, logging or LTE for manual driving or for any protection |
| Telematics unit | STM32U575 (telematics proposal v0.1, 14/10/2026); **allocation not frozen** (section 12) | receive timestamps, local log, GNSS/PPS, IMU, wheel halls, supervisor task (proposed), live uplink | let logging, storage or LTE delay the supervisor task; arm, select a mode or reset faults |
| Supervisor (task) | proposed on the telematics unit | ECO torque request and envelope at 50 Hz (PROV), from fresh controller telemetry only (`host/telemetry_adapter/supervisor.py`) | request propulsion from a stale, duplicated or invalid speed |
| Driver controls | wired to the controller | arming, mode (manual / ECO), cancel, brake, dead-man, fault reset | be overridden by any message |
| Vehicle hardware | vehicle | e-stop and safety loop (HW_PERMIT), fuse, battery isolation | n/a |
| Pit | laptop | MQTT broker, validation and ingestion into SQLite, offline log import, monitoring and CSIA replay in shadow mode | send any command to the car while it is not stopped and disarmed |

Motor control stays local to the controller. CSIA and the R3v monitor run in the pit, or on logged data as replay; their outputs are never an input to the controller (`docs/csia/EVALUATION_RESULTS_v2.md`, ADR-0008).

### B.2 CAN

| Item | Value | Status |
|---|---|---|
| Physical | ISO 11898-2 high-speed CAN; TJA1051T/3-class transceiver | candidate; bus UNKNOWN |
| Frame | classic CAN, 11-bit identifier, DLC 8 (valid on CAN 2.0B and CAN FD buses) | frozen (protocol 1.x) |
| Identifiers | one block of 64: `supervision.can_id_base + 0x00 … 0x3F` (multiple of 0x40); protocol numbering 0x300–0x33F; the CRC data ID uses the protocol number, not the bus identifier | numbering frozen; **block allocation: vehicle team** |
| Bit rate, sample point | 500 kbit/s assumed in analyses | **UNKNOWN** (telematics proposal: CAN 2.0B, rate not stated) |
| Load | controller 394 frames/s, supervisor 72 frames/s; 12.6 % of a 500 kbit/s bus; worst-case response time of every message below its period (`docs/generated/bus_load.md`) | estimate; other traffic UNKNOWN |
| Termination, topology | 120 Ω at both ends (telematics proposal); the controller draft has a split-termination network (populate if the controller is a bus end) | position UNKNOWN |

### B.3 Encoding

* **Byte and bit order:** Intel, LSB first; multi-byte fields little-endian.
* **Byte 0:** CRC-8/SAE-J1850 (poly 0x1D, init 0xFF, xorout 0xFF) over the 16-bit data ID `(major << 11) | protocol_id`, little-endian, then bytes 1–7. Check value of "123456789": 0x4B. A frame from another major version fails the CRC.
* **Byte 1:** sequence counter, u8 per message, wraps.
* **Scaling:** physical = raw × scale + offset, per field (`docs/generated/can_messages.md`).
* **Invalid values:** NaN encodes as the field's `invalid` raw sentinel; a field without a sentinel refuses to encode NaN. Decoders map the sentinel to NaN and flag raw values outside the declared range. A torque request carrying the sentinel or an out-of-range value makes the supervisor input INVALID (ECO exits); it is never read as zero torque. Measurements the controller does not have (before the first slow step, or flagged) are sent as NaN, never as 0.
* **Versioning:** protocol 1.1 (spec hash `16ff00853dfda3ce`). Minor versions are additive: 1.1 added `ctrl_energy_quality` (0x323); every 1.0 message is unchanged. `sup_hello` carries the companion's major/minor; `ctrl_session` and `ctrl_identity` carry the controller's. A major mismatch is rejected (`rx_proto_mismatch`).

### B.4 Sequence, session, freshness and reconnection (controller side, `mc_freshness.c`, `mc_core.c`)

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

### B.5 Driver controls and protection boundaries

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
| Precharge bypass | FET gate pulled down (bypass open at power-up and in reset); rule for closing it: V_DC ≥ `power.precharge_complete_fraction` x V_BAT (VBUS_SENSE vs INA228) within `power.precharge_timeout_s`, else a fault; a link that falls back after closing is a fault | no inrush at power-up | the pull-down yes; the sequencing is implemented (`firmware/src/io/mc_precharge.c`, `mc_startup.c` with the battery-current cross-check, host tests) and linked into the target image, but never closes there until a verified INA228 description and its I2C transport exist |

Every row of this table is checked on the exported netlist by `tools/hw_consistency.py` (PR1–PR7). Electrical levels of the driver inputs, contact types and the safety-loop voltage are UNKNOWN (input sheet).

### B.6 Status, trace and fault messages (controller → bus)

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

### B.7 STM32U575 allocation: what must be verified before it is frozen

| Item | Required | How to verify |
|---|---|---|
| Supervisor task | 50 Hz with bounded jitter while logging, SD writes and the modem are active | timestamp the task on a GPIO; logic-analyser capture during a flash stall and LTE transfer |
| CAN receive | 466 frames/s without overrun | FDCAN RX FIFO overrun counter at the full controller rate |
| Flash bandwidth | ≥ 9.35 KiB/s sustained plus erase time, without blocking the task | write benchmark with sector erases |
| RAM | log queue (512 records ≈ 10 KiB), uplink queue, GNSS and IMU buffers | linker map |
| Clock | PPS capture with a timer input; drift of the unit's oscillator | capture against GNSS PPS for 10 min |
If any item fails, the supervisor moves to another computer or ECO is not offered (manual only); the controller is unaffected.

### B.8 Host demonstration (HOST SIMULATION)

`tools/run_host_demo.py` runs: synthetic driver and plant → controller core (C) → CAN → telematics node (timestamps, supervisor, bounded queue, STLG log, GNSS/PPS, IMU, halls) → controller arbitration → simulated motor → LTE/MQTT with outage → pit validation and SQLite → offline import → pit-side CSIA replay and shadow replay. Ten checks with their evidence: `docs/generated/host_demo/summary.md`. It validates no hardware.
