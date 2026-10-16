# CAN messages - semmc protocol v1.1 (GENERATED, spec hash `3365b84b45a16c63`)

Generated from `protocol/protocol.yaml` by `tools/gen_protocol.py`; do not edit.

Every frame: 8 bytes, 11-bit id, byte 0 = CRC-8/SAE-J1850 over [DataID LE16] + bytes 1..7, byte 1 = sequence (u8). Bits are Intel/LSB-first. physical = raw x scale + offset.

| id | message | sender | period | DataID |
|---|---|---|---|---|
| 0x300 | `ctrl_fault` | controller | 1000 ms + on change | 0x0B00 |
| 0x308 | `sup_torque_req` | companion | 20 ms (PROVISIONAL) | 0x0B08 |
| 0x309 | `sup_limits` | companion | 100 ms | 0x0B09 |
| 0x30A | `sup_hello` | companion | 500 ms | 0x0B0A |
| 0x310 | `ctrl_status` | controller | 20 ms | 0x0B10 |
| 0x311 | `ctrl_cmd_trace` | controller | 20 ms | 0x0B11 |
| 0x312 | `driver_controls` | controller | 20 ms | 0x0B12 |
| 0x313 | `ctrl_session` | controller | 500 ms + on change | 0x0B13 |
| 0x318 | `ctrl_motion` | controller | 10 ms | 0x0B18 |
| 0x319 | `ctrl_currents` | controller | 10 ms | 0x0B19 |
| 0x320 | `ctrl_energy` | controller | 100 ms | 0x0B20 |
| 0x321 | `ctrl_thermal` | controller | 100 ms | 0x0B21 |
| 0x322 | `ctrl_validity` | controller | 100 ms | 0x0B22 |
| 0x323 | `ctrl_energy_quality` | controller | 100 ms | 0x0B23 |
| 0x328 | `csia_advisory` | companion | 100 ms | 0x0B28 |
| 0x330 | `ctrl_identity` | controller | 1000 ms | 0x0B30 |

## `ctrl_fault` (0x300)

Latched faults, first fault since reset and last MCU reset reason.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| latched | 16..39 | raw | - | - | - | - | - | - |
| first_fault | 40..47 | raw | - | - | - | - | - | - |
| reset_reason | 48..55 | raw | - | - | - | - | - | - |
| fault_count | 56..63 | raw | - | - | - | - | - | - |

## `sup_torque_req` (0x308)

Supervisory torque request (motor shaft). PROVISIONAL 50 Hz / 100 ms timeout, simulation only, pending hazard and latency analysis.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| session_tag | 16..23 | raw | - | - | - | - | - | - |
| limits_ref | 24..27 | raw | - | - | - | - | - | - |
| coast_request | 28..28 | bool | - | - | - | - | - | - |
| reserved | 29..31 | raw | - | - | - | - | - | - |
| torque_Nm | 32..47 (signed) | scaled | 0.002 | 0 | -65.534 | 65.534 | N*m | -32768 |
| src_time_ms | 48..63 | raw | - | - | - | - | - | - |

## `sup_limits` (0x309)

Supervisor-declared bounds; can only tighten controller limits.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| session_tag | 16..23 | raw | - | - | - | - | - | - |
| limits_seq | 24..31 | raw | - | - | - | - | - | - |
| max_torque_Nm | 32..47 | scaled | 0.002 | 0 | 0 | 131.07 | N*m | - |
| max_batt_power_W | 48..63 | scaled | 1.0 | 0 | 0 | 65535 | W | - |

## `sup_hello` (0x30A)

Companion session announcement / handshake. Cannot arm or select a mode.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| proto_major | 16..19 | raw | - | - | - | - | - | - |
| proto_minor | 20..23 | raw | - | - | - | - | - | - |
| role | 24..31 | raw | - | - | - | - | - | - |
| companion_session | 32..63 | raw | - | - | - | - | - | - |

## `ctrl_status` (0x310)

Operating state, owner, supervisor link and boot identity.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| state | 16..19 | raw | - | - | - | - | - | - |
| owner | 20..21 | raw | - | - | - | - | - | - |
| sup_link | 22..23 | raw | - | - | - | - | - | - |
| session_tag | 24..31 | raw | - | - | - | - | - | - |
| boot_id | 32..47 | raw | - | - | - | - | - | - |
| build_is_sim | 48..48 | bool | - | - | - | - | - | - |
| cal_provenance | 49..50 | raw | - | - | - | - | - | - |
| output_permitted | 51..51 | bool | - | - | - | - | - | - |
| pwm_enabled | 52..52 | bool | - | - | - | - | - | - |
| derating | 53..53 | bool | - | - | - | - | - | - |
| hw_trip | 54..54 | bool | - | - | - | - | - | - |
| reserved | 55..55 | raw | - | - | - | - | - | - |
| last_transition | 56..63 | raw | - | - | - | - | - | - |

## `ctrl_cmd_trace` (0x311)

Requested (owner) vs accepted torque and reason bits (MC_R_*).

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| requested_Nm | 16..31 (signed) | scaled | 0.002 | 0 | -65.534 | 65.534 | N*m | -32768 |
| accepted_Nm | 32..47 (signed) | scaled | 0.002 | 0 | -65.534 | 65.534 | N*m | -32768 |
| reason | 48..63 | raw | - | - | - | - | - | - |

## `driver_controls` (0x312)

Wired driver controls AS SEEN BY THE CONTROLLER (report only; never an input).

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| throttle | 16..31 | scaled | 0.0001 | 0 | 0 | 1 | 1 | 65535 |
| brake | 32..32 | bool | - | - | - | - | - | - |
| cancel | 33..33 | bool | - | - | - | - | - | - |
| mode_eco | 34..34 | bool | - | - | - | - | - | - |
| arm_switch | 35..35 | bool | - | - | - | - | - | - |
| estop_chain_ok | 36..36 | bool | - | - | - | - | - | - |
| driver_present | 37..37 | bool | - | - | - | - | - | - |
| fault_reset | 38..38 | bool | - | - | - | - | - | - |
| throttle_valid | 39..39 | bool | - | - | - | - | - | - |
| reserved | 40..63 | raw | - | - | - | - | - | - |

## `ctrl_session` (0x313)

Handshake reply - session tag assigned to the echoed companion session.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| session_tag | 16..23 | raw | - | - | - | - | - | - |
| companion_session_echo | 24..55 | raw | - | - | - | - | - | - |
| proto_major | 56..59 | raw | - | - | - | - | - | - |
| proto_minor | 60..63 | raw | - | - | - | - | - | - |

## `ctrl_motion` (0x318)

Rotor mechanical speed, measured q current, bus voltage.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| speed_mech_rad_s | 16..31 (signed) | scaled | 0.05 | 0 | -1638.35 | 1638.35 | rad/s | -32768 |
| iq_A | 32..47 (signed) | scaled | 0.01 | 0 | -327.67 | 327.67 | A | -32768 |
| vbus_V | 48..63 | scaled | 0.01 | 0 | 0 | 655.34 | V | 65535 |

## `ctrl_currents` (0x319)

d current, battery current (+ discharge), phase-measurement provenance, KCL residual.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| id_A | 16..31 (signed) | scaled | 0.01 | 0 | -327.67 | 327.67 | A | -32768 |
| ibatt_A | 32..47 (signed) | scaled | 0.01 | 0 | -327.67 | 327.67 | A | -32768 |
| measured_mask | 48..50 | raw | - | - | - | - | - | - |
| reconstructed_mask | 51..53 | raw | - | - | - | - | - | - |
| kcl_available | 54..54 | bool | - | - | - | - | - | - |
| reserved | 55..55 | raw | - | - | - | - | - | - |
| kcl_residual_A | 56..63 (signed) | scaled | 0.1 | 0 | -12.7 | 12.7 | A | -128 |

## `ctrl_energy` (0x320)

Battery-side energy since controller boot and instantaneous battery power.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| energy_J | 16..47 | scaled | 0.1 | 0 | 0 | 429496729.4 | J | 4294967295 |
| p_batt_W | 48..63 (signed) | scaled | 1.0 | 0 | -32767 | 32767 | W | -32768 |

## `ctrl_thermal` (0x321)

Temperatures and derating.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| t_fet_degC | 16..31 (signed) | scaled | 0.1 | 0 | -3276.7 | 3276.7 | degC | -32768 |
| t_motor_degC | 32..47 (signed) | scaled | 0.1 | 0 | -3276.7 | 3276.7 | degC | -32768 |
| derate | 48..55 | scaled | 0.004 | 0 | 0 | 1.0 | 1 | 255 |
| derate_reasons | 56..63 | raw | - | - | - | - | - | - |

## `ctrl_validity` (0x322)

Per-signal validity nibbles (bit0 missing, bit1 stale, bit2 invalid/nonfinite/ out-of-range/integrity, bit3 saturated).

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| v_speed | 16..19 | raw | - | - | - | - | - | - |
| v_ia | 20..23 | raw | - | - | - | - | - | - |
| v_ib | 24..27 | raw | - | - | - | - | - | - |
| v_ic | 28..31 | raw | - | - | - | - | - | - |
| v_vbus | 32..35 | raw | - | - | - | - | - | - |
| v_ibatt | 36..39 | raw | - | - | - | - | - | - |
| v_t_fet | 40..43 | raw | - | - | - | - | - | - |
| v_t_motor | 44..47 | raw | - | - | - | - | - | - |
| v_throttle | 48..51 | raw | - | - | - | - | - | - |
| v_sup_req | 52..55 | raw | - | - | - | - | - | - |
| v_sup_limits | 56..59 | raw | - | - | - | - | - | - |
| v_hall | 60..63 | raw | - | - | - | - | - | - |

## `ctrl_energy_quality` (0x323)

Completeness of ctrl_energy.energy_J. integrated_s is the time over which battery power was integrated; gap_s is the time NOT integrated because battery current or bus voltage was invalid, or because an update interval exceeded the integration limit. energy_J is complete only while gap_s is 0.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| integrated_s | 16..39 | scaled | 0.01 | 0 | 0 | 167772.14 | s | 16777215 |
| gap_s | 40..63 | scaled | 0.01 | 0 | 0 | 167772.14 | s | 16777215 |

## `csia_advisory` (0x328)

CSIA vehicle-adapter advisory. v0.1 = SHADOW ONLY: the controller logs and re-reports it but never changes a command because of it (ADR-0008).

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| trust | 16..23 | scaled | 0.004 | 0 | 0 | 1.0 | 1 | 255 |
| mode | 24..25 | raw | - | - | - | - | - | - |
| observability | 26..27 | raw | - | - | - | - | - | - |
| monitor_ok | 28..28 | bool | - | - | - | - | - | - |
| evidence_fresh | 29..29 | bool | - | - | - | - | - | - |
| reserved | 30..31 | raw | - | - | - | - | - | - |
| evidence_mask | 32..39 | raw | - | - | - | - | - | - |
| explanation | 40..47 | raw | - | - | - | - | - | - |
| src_time_ms | 48..63 | raw | - | - | - | - | - | - |

## `ctrl_identity` (0x330)

Protocol, firmware and calibration identity.

| field | bits | kind | scale | offset | min | max | unit | invalid raw |
|---|---|---|---|---|---|---|---|---|
| proto_major | 16..19 | raw | - | - | - | - | - | - |
| proto_minor | 20..23 | raw | - | - | - | - | - | - |
| fw_major | 24..31 | raw | - | - | - | - | - | - |
| fw_minor | 32..39 | raw | - | - | - | - | - | - |
| cal_version | 40..55 | raw | - | - | - | - | - | - |
| cal_provenance | 56..57 | raw | - | - | - | - | - | - |
| build_is_sim | 58..58 | bool | - | - | - | - | - | - |
| hw_rev | 59..63 | raw | - | - | - | - | - | - |
