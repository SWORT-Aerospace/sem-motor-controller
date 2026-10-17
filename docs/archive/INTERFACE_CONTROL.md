# Interface control document v0.1 (amended v0.3): SUPERSEDED

> **Superseded by [`ICD.md`](../ICD.md) v1.0 (v0.4).** Kept as the record of v0.1 to v0.3. Changed since: protocol 1.1 (`ctrl_energy_quality`), session tags distinct across session resets, the freshness lag rule, the telematics log and uplink sections.

> **v0.3 amendment (ADR-0012).** The vehicle bus is **UNKNOWN**. The CHUDS/CAN FD values that v0.2 wrote into this table were observed in a **reference project** (Cornell), not on our vehicle. The telematics proposal for our vehicle (v0.1, 14/10/2026) shows **CAN 2.0B**. The message set, framing, integrity and sequence rules below are unchanged (frozen v1). The bus parameters are now selected per vehicle: see `docs/archive/VEHICLE_INTERFACE_MATRIX.md`.

## 1. CAN bus

| Item | Value | Status |
|---|---|---|
| Physical | ISO 11898-2 high-speed CAN; TJA1051T/3-class transceiver (FD-capable, also valid on a classic CAN 2.0B bus) | candidate; bus UNKNOWN |
| Identifiers | 11-bit, one block of 64: `can_id_base … can_id_base + 0x3F`, where `supervision.can_id_base` is a calibration value (multiple of 0x40, rule 40). The protocol's own numbering is 0x300–0x33F (protocol default, used by the synthetic config). The CRC data id uses the protocol number, not the bus identifier. | message numbers frozen v1; **bus allocation pending (vehicle team)** |
| Frame format | classic CAN, 11-bit, DLC 8 (valid on CAN 2.0B and on CAN FD buses) | frozen v1 |
| Controller CAN mode | **depends on the vehicle bus.** Classic CAN 2.0B bus (telematics proposal): classic mode. A CAN FD bus (reference project only): FD operation enabled for reception with a matching data-phase timing; semmc still transmits classic frames only. Clock and timing options: `hardware/timing/clock_tree_alternatives.md` | **UNKNOWN until the bus is confirmed** |
| Nominal bit rate | not stated by the telematics proposal; 500 kbit/s used in host analyses (`SEMMC_NOMINAL_BITRATE`, protocol header) | **UNKNOWN** |
| Byte/bit order | Intel (LSB-first), little-endian multi-byte | frozen v1 |
| Integrity | CRC-8/SAE-J1850 over the 16-bit Data ID `(major<<11)|id` and bytes 1–7; check value `"123456789"` → 0x4B | frozen v1 |
| Sequence | byte 1, u8 per message, wraps | frozen v1 |
| Messages | `docs/generated/can_messages.md` (generated) | frozen v1 |
| Codecs | `protocol/generated/semmc_protocol.{h,c,py}`; golden vectors `protocol/golden_vectors/vectors.json` | generated, tested in C and Python |
| Bus load | semmc frames 12.3 % at 500 kbit/s; the 13.7 % total adds a reference-project (CHUDS) load case, not our bus; `docs/generated/bus_load.md` | estimate; our bus's other traffic unknown |
| Termination / stub lengths / connector | telematics proposal: 120 Ω at both ends, CANH/CANL/GND | **UNFROZEN** (harness unknown) |
| Exchange format for other teams | `protocol/generated/semmc_base0x300.dbc` (generated; `tools/gen_dbc.py --base …` for another block), cross-checked against the golden vectors | generated, tested |

### 1.1 Saturation and invalid values
Encoders clamp physical values to `[min, max]` and report saturation. NaN encodes as the field's `invalid` sentinel; if the field has no sentinel, the encoder refuses to emit a frame. Decoders map the sentinel to NaN and flag raw values outside the declared range. The controller treats an invalid or out-of-range torque request as **supervisor INVALID** (ECO exits), never as "zero torque".

### 1.2 Session and ownership (handshake)
```
companion                               controller
  sup_hello{major,minor,role=1,session S} --->      (any time; 2 Hz until tagged)
                                       <--- ctrl_session{tag T, echo S}   (T derived from boot id; new per boot)
  sup_limits{tag T, limits_seq L, bounds} --->      committed atomically; previous set kept
  sup_torque_req{tag T, limits_ref L&0xF, torque, coast, src_time} --->
                                            established when both carry T
driver: eco switch OFF->ON edge (wired)   ---> ECO_ASSIST (only if supervisor OK)
```
* A controller reboot changes `boot_id` (in `ctrl_status`) and therefore the tag. Old-tag frames are rejected (`rx_tag_mismatch`), and the companion must re-handshake.
* A companion reboot (new `S`) ends the session; ECO exits and needs a new driver edge.
* Expiration: a request is valid for `supervision.timeout_s` after the last **new** sample. Limits are valid for `limits_timeout_s`.
* **Limits sets (v0.2 controller behaviour, wire format unchanged).** A new `limits_seq` makes a new newest set and keeps the previous one. Re-sending the same `limits_seq` refreshes the newest set in place. The companion must change `limits_seq` whenever the content changes. A request must reference a held set; the bound applied is `min(newest, referenced)`, so a tighter set applies on the next controller update even before a request references it (`docs/CONTROL_CONTRACT.md` §3).
* Provisional: 50 Hz / 100 ms, **simulation only**.

## 2. Calibration blob (controller non-volatile)
Format v1 (`firmware/include/semmc/mc_config.h`): `"SMCB"`, format version, schema version, provenance, cal id (≤ 15 ASCII), cal version, then (id, kind, f32) entries, then CRC-32. Unknown ids, duplicate ids, wrong kind, length errors or CRC errors reject the whole blob. Produced by `tools/config_tool.py blob`; on a hardware build the blob must pass `--mode hw`.

## 3. Wired driver and vehicle I/O (controller connector)

| Signal | Direction | Electrical (to be designed) | Firmware use |
|---|---|---|---|
| Throttle track A, track B | in, analog | ratiometric pedal; two independent tracks; open/short detection | `throttle`, `throttle_valid` (plausibility → fault `THROTTLE_IMPLAUSIBLE`) |
| Brake switch | in, digital | normally-closed preferred (fails safe) | immediate torque 0 |
| Eco cancel | in, digital | momentary | ECO → READY |
| Mode switch (manual / eco) | in, digital | latching | eco edge detection |
| Arm switch | in, digital | latching | OFF→ON edge required |
| Fault reset | in, digital | momentary | edge |
| E-stop chain sense | in, digital | sensed downstream of the isolation contacts | DISARMED when open |
| Dead-man sense | in, digital | from the dead-man switch (also in the hardware enable chain) | READY when released |
| Hall A/B/C + supply | in | protected inputs; supply and open-drain vs push-pull **unknown** | sector, speed, angle |
| Motor temperature | in, analog | sensor type **unknown** | derate / trip |
| Motor phases U/V/W | power out | n/a | n/a |
| Battery + / − (after the vehicle e-stop and fuse) | power in | precharge required | n/a |
| CAN H/L | bidirectional | n/a | §1 |
| Debug UART / SWD | bench only | not populated or disabled for competition | n/a |

## 4. Companion ↔ controller responsibilities
| Function | Owner |
|---|---|
| PWM, commutation, current loop, protection, state, arbitration | Controller |
| Logging, track matching, energy strategy, CSIA adapter | Companion |
| Arming, mode, fault reset | Driver (wired) |
| Emergency isolation, dead-man power cut | Vehicle hardware |

## 5. Log formats
* `semmc-log v1` (`host/logger/semmc_log.py`): `<t_us> <KIND> <payload>` with kinds IO, CAN, HW, MEAS, FAULT, BUSOFF, RESET, STEP, END. Time is the receiver's local monotonic time. Source time and clock domain travel in the payload.
* Host simulation CSV columns: see the header of `firmware/platform/host/host_main.c::main`.

## 6. Cellular and pit network (monitoring only)
The companion may publish telemetry over cellular. It must not accept any inbound command that results in a CAN write, and it has no API to arm, select modes or change limits remotely. Any future pit-to-car message (e.g. a strategy update between runs) must be applied only while the vehicle is DISARMED and confirmed locally. It is not part of v0.1.
