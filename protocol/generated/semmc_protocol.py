"""GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit.

semmc CAN protocol v1.0, spec hash 193e498f6cb45df6.
"""
import math
import struct

PROTOCOL_MAJOR = 1
PROTOCOL_MINOR = 0
SPEC_HASH = "193e498f6cb45df6"

MESSAGES = {
 "ctrl_fault": {
  "id": 768,
  "data_id": 2816,
  "period_s": 1.0,
  "sender": "controller",
  "fields": [
   {
    "name": "latched",
    "start": 16,
    "width": 24,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 16777215
   },
   {
    "name": "first_fault",
    "start": 40,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "reset_reason",
    "start": 48,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "fault_count",
    "start": 56,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   }
  ]
 },
 "sup_torque_req": {
  "id": 776,
  "data_id": 2824,
  "period_s": 0.02,
  "sender": "companion",
  "fields": [
   {
    "name": "session_tag",
    "start": 16,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "limits_ref",
    "start": 24,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "coast_request",
    "start": 28,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "reserved",
    "start": 29,
    "width": 3,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 7
   },
   {
    "name": "torque_Nm",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.002,
    "offset": 0,
    "min": -65.534,
    "max": 65.534
   },
   {
    "name": "src_time_ms",
    "start": 48,
    "width": 16,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535
   }
  ]
 },
 "sup_limits": {
  "id": 777,
  "data_id": 2825,
  "period_s": 0.1,
  "sender": "companion",
  "fields": [
   {
    "name": "session_tag",
    "start": 16,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "limits_seq",
    "start": 24,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "max_torque_Nm",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535,
    "scale": 0.002,
    "offset": 0,
    "min": 0,
    "max": 131.07
   },
   {
    "name": "max_batt_power_W",
    "start": 48,
    "width": 16,
    "kind": "scaled",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535,
    "scale": 1.0,
    "offset": 0,
    "min": 0,
    "max": 65535
   }
  ]
 },
 "sup_hello": {
  "id": 778,
  "data_id": 2826,
  "period_s": 0.5,
  "sender": "companion",
  "fields": [
   {
    "name": "proto_major",
    "start": 16,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "proto_minor",
    "start": 20,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "role",
    "start": 24,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "companion_session",
    "start": 32,
    "width": 32,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 4294967295
   }
  ]
 },
 "ctrl_status": {
  "id": 784,
  "data_id": 2832,
  "period_s": 0.02,
  "sender": "controller",
  "fields": [
   {
    "name": "state",
    "start": 16,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "owner",
    "start": 20,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "sup_link",
    "start": 22,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "session_tag",
    "start": 24,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "boot_id",
    "start": 32,
    "width": 16,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535
   },
   {
    "name": "build_is_sim",
    "start": 48,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "cal_provenance",
    "start": 49,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "output_permitted",
    "start": 51,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "pwm_enabled",
    "start": 52,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "derating",
    "start": 53,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "hw_trip",
    "start": 54,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "reserved",
    "start": 55,
    "width": 1,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "last_transition",
    "start": 56,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   }
  ]
 },
 "ctrl_cmd_trace": {
  "id": 785,
  "data_id": 2833,
  "period_s": 0.02,
  "sender": "controller",
  "fields": [
   {
    "name": "requested_Nm",
    "start": 16,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.002,
    "offset": 0,
    "min": -65.534,
    "max": 65.534
   },
   {
    "name": "accepted_Nm",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.002,
    "offset": 0,
    "min": -65.534,
    "max": 65.534
   },
   {
    "name": "reason",
    "start": 48,
    "width": 16,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535
   }
  ]
 },
 "driver_controls": {
  "id": 786,
  "data_id": 2834,
  "period_s": 0.02,
  "sender": "controller",
  "fields": [
   {
    "name": "throttle",
    "start": 16,
    "width": 16,
    "kind": "scaled",
    "signed": False,
    "invalid": 65535,
    "raw_lo": 0,
    "raw_hi": 65534,
    "scale": 0.0001,
    "offset": 0,
    "min": 0,
    "max": 1
   },
   {
    "name": "brake",
    "start": 32,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "cancel",
    "start": 33,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "mode_eco",
    "start": 34,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "arm_switch",
    "start": 35,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "estop_chain_ok",
    "start": 36,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "driver_present",
    "start": 37,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "fault_reset",
    "start": 38,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "throttle_valid",
    "start": 39,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "reserved",
    "start": 40,
    "width": 24,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 16777215
   }
  ]
 },
 "ctrl_session": {
  "id": 787,
  "data_id": 2835,
  "period_s": 0.5,
  "sender": "controller",
  "fields": [
   {
    "name": "session_tag",
    "start": 16,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "companion_session_echo",
    "start": 24,
    "width": 32,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 4294967295
   },
   {
    "name": "proto_major",
    "start": 56,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "proto_minor",
    "start": 60,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   }
  ]
 },
 "ctrl_motion": {
  "id": 792,
  "data_id": 2840,
  "period_s": 0.01,
  "sender": "controller",
  "fields": [
   {
    "name": "speed_mech_rad_s",
    "start": 16,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.05,
    "offset": 0,
    "min": -1638.35,
    "max": 1638.35
   },
   {
    "name": "iq_A",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.01,
    "offset": 0,
    "min": -327.67,
    "max": 327.67
   },
   {
    "name": "vbus_V",
    "start": 48,
    "width": 16,
    "kind": "scaled",
    "signed": False,
    "invalid": 65535,
    "raw_lo": 0,
    "raw_hi": 65534,
    "scale": 0.01,
    "offset": 0,
    "min": 0,
    "max": 655.34
   }
  ]
 },
 "ctrl_currents": {
  "id": 793,
  "data_id": 2841,
  "period_s": 0.01,
  "sender": "controller",
  "fields": [
   {
    "name": "id_A",
    "start": 16,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.01,
    "offset": 0,
    "min": -327.67,
    "max": 327.67
   },
   {
    "name": "ibatt_A",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.01,
    "offset": 0,
    "min": -327.67,
    "max": 327.67
   },
   {
    "name": "measured_mask",
    "start": 48,
    "width": 3,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 7
   },
   {
    "name": "reconstructed_mask",
    "start": 51,
    "width": 3,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 7
   },
   {
    "name": "kcl_available",
    "start": 54,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "reserved",
    "start": 55,
    "width": 1,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "kcl_residual_A",
    "start": 56,
    "width": 8,
    "kind": "scaled",
    "signed": True,
    "invalid": -128,
    "raw_lo": -127,
    "raw_hi": 127,
    "scale": 0.1,
    "offset": 0,
    "min": -12.7,
    "max": 12.7
   }
  ]
 },
 "ctrl_energy": {
  "id": 800,
  "data_id": 2848,
  "period_s": 0.1,
  "sender": "controller",
  "fields": [
   {
    "name": "energy_J",
    "start": 16,
    "width": 32,
    "kind": "scaled",
    "signed": False,
    "invalid": 4294967295,
    "raw_lo": 0,
    "raw_hi": 4294967294,
    "scale": 0.1,
    "offset": 0,
    "min": 0,
    "max": 429496729.4
   },
   {
    "name": "p_batt_W",
    "start": 48,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 1.0,
    "offset": 0,
    "min": -32767,
    "max": 32767
   }
  ]
 },
 "ctrl_thermal": {
  "id": 801,
  "data_id": 2849,
  "period_s": 0.1,
  "sender": "controller",
  "fields": [
   {
    "name": "t_fet_degC",
    "start": 16,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.1,
    "offset": 0,
    "min": -3276.7,
    "max": 3276.7
   },
   {
    "name": "t_motor_degC",
    "start": 32,
    "width": 16,
    "kind": "scaled",
    "signed": True,
    "invalid": -32768,
    "raw_lo": -32767,
    "raw_hi": 32767,
    "scale": 0.1,
    "offset": 0,
    "min": -3276.7,
    "max": 3276.7
   },
   {
    "name": "derate",
    "start": 48,
    "width": 8,
    "kind": "scaled",
    "signed": False,
    "invalid": 255,
    "raw_lo": 0,
    "raw_hi": 254,
    "scale": 0.004,
    "offset": 0,
    "min": 0,
    "max": 1.0
   },
   {
    "name": "derate_reasons",
    "start": 56,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   }
  ]
 },
 "ctrl_validity": {
  "id": 802,
  "data_id": 2850,
  "period_s": 0.1,
  "sender": "controller",
  "fields": [
   {
    "name": "v_speed",
    "start": 16,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_ia",
    "start": 20,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_ib",
    "start": 24,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_ic",
    "start": 28,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_vbus",
    "start": 32,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_ibatt",
    "start": 36,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_t_fet",
    "start": 40,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_t_motor",
    "start": 44,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_throttle",
    "start": 48,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_sup_req",
    "start": 52,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_sup_limits",
    "start": 56,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "v_hall",
    "start": 60,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   }
  ]
 },
 "csia_advisory": {
  "id": 808,
  "data_id": 2856,
  "period_s": 0.1,
  "sender": "companion",
  "fields": [
   {
    "name": "trust",
    "start": 16,
    "width": 8,
    "kind": "scaled",
    "signed": False,
    "invalid": 255,
    "raw_lo": 0,
    "raw_hi": 254,
    "scale": 0.004,
    "offset": 0,
    "min": 0,
    "max": 1.0
   },
   {
    "name": "mode",
    "start": 24,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "observability",
    "start": 26,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "monitor_ok",
    "start": 28,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "evidence_fresh",
    "start": 29,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "reserved",
    "start": 30,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "evidence_mask",
    "start": 32,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "explanation",
    "start": 40,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "src_time_ms",
    "start": 48,
    "width": 16,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535
   }
  ]
 },
 "ctrl_identity": {
  "id": 816,
  "data_id": 2864,
  "period_s": 1.0,
  "sender": "controller",
  "fields": [
   {
    "name": "proto_major",
    "start": 16,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "proto_minor",
    "start": 20,
    "width": 4,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 15
   },
   {
    "name": "fw_major",
    "start": 24,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "fw_minor",
    "start": 32,
    "width": 8,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 255
   },
   {
    "name": "cal_version",
    "start": 40,
    "width": 16,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 65535
   },
   {
    "name": "cal_provenance",
    "start": 56,
    "width": 2,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 3
   },
   {
    "name": "build_is_sim",
    "start": 58,
    "width": 1,
    "kind": "bool",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 1
   },
   {
    "name": "hw_rev",
    "start": 59,
    "width": 5,
    "kind": "raw",
    "signed": False,
    "invalid": None,
    "raw_lo": 0,
    "raw_hi": 31
   }
  ]
 }
}

BY_ID = {m['id']: m for m in MESSAGES.values()}
for _n, _m in MESSAGES.items():
    _m['name'] = _n

class CodecError(ValueError):
    pass


def _crc8(data, crc=0xFF):
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc8_with_data_id(data_id, payload):
    return _crc8(bytes([data_id & 0xFF, data_id >> 8]) + bytes(payload)) ^ 0xFF


def _f32(x):
    if math.isnan(x) or math.isinf(x):
        return x
    if abs(x) > 3.4028234663852886e38:
        return math.copysign(math.inf, x)
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _round_half_away(x):
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def _put(buf, start, width, raw):
    raw &= (1 << width) - 1
    for k in range(width):
        bit = start + k
        if (raw >> k) & 1:
            buf[bit // 8] |= 1 << (bit % 8)


def _get(buf, start, width, signed):
    raw = 0
    for k in range(width):
        bit = start + k
        raw |= ((buf[bit // 8] >> (bit % 8)) & 1) << k
    if signed and raw & (1 << (width - 1)):
        raw -= 1 << width
    return raw


def encode(name, values, seq):
    """Encode physical values. Returns (bytes8, saturated_fields, invalid_fields).

    Raises CodecError for a missing field or a NaN in a field without sentinel."""
    m = MESSAGES[name]
    buf = bytearray(8)
    buf[1] = seq & 0xFF
    sat, inv = [], []
    for f in m["fields"]:
        if f["name"] not in values:
            raise CodecError(f"{name}: missing field {f['name']}")
        v = values[f["name"]]
        if f["kind"] == "bool":
            raw = 1 if v else 0
        elif f["kind"] == "raw":
            raw = int(v)
            if raw < f["raw_lo"] or raw > f["raw_hi"]:
                raw = min(max(raw, f["raw_lo"]), f["raw_hi"])
                sat.append(f["name"])
        else:
            x = _f32(float(v))
            if math.isnan(x):
                if f["invalid"] is None:
                    raise CodecError(f"{name}.{f['name']}: NaN but field has no invalid sentinel")
                raw = f["invalid"]
                inv.append(f["name"])
            else:
                if x < f["min"] or x > f["max"]:
                    x = min(max(x, f["min"]), f["max"])
                    sat.append(f["name"])
                raw = _round_half_away((x - f["offset"]) / f["scale"])
                raw = min(max(raw, f["raw_lo"]), f["raw_hi"])
        _put(buf, f["start"], f["width"], raw)
    buf[0] = crc8_with_data_id(m["data_id"], buf[1:])
    return bytes(buf), sat, inv


def decode(name_or_id, data):
    """Decode 8 bytes. Returns (values_dict, info_dict). info has 'status'
    ('ok' | 'bad_length' | 'bad_crc' | 'unknown_id'), 'seq', 'invalid' (fields
    that carried the sentinel -> NaN) and 'out_of_range' (raw beyond [min,max])."""
    m = MESSAGES.get(name_or_id) if isinstance(name_or_id, str) else BY_ID.get(name_or_id)
    if m is None:
        return {}, {"status": "unknown_id"}
    data = bytes(data)
    if len(data) != 8:
        return {}, {"status": "bad_length"}
    if crc8_with_data_id(m["data_id"], data[1:]) != data[0]:
        return {}, {"status": "bad_crc"}
    out, inv, oor = {}, [], []
    for f in m["fields"]:
        raw = _get(data, f["start"], f["width"], f["signed"])
        if f["kind"] == "bool":
            out[f["name"]] = bool(raw)
        elif f["kind"] == "raw":
            out[f["name"]] = raw
        elif f["invalid"] is not None and raw == f["invalid"]:
            out[f["name"]] = float("nan")
            inv.append(f["name"])
        else:
            x = _f32(raw * f["scale"] + f["offset"])
            if raw < f["raw_lo"] or raw > f["raw_hi"] or x < _f32(f["min"]) or x > _f32(f["max"]):
                oor.append(f["name"])
            out[f["name"]] = x
    return out, {"status": "ok", "seq": data[1], "invalid": inv, "out_of_range": oor}
