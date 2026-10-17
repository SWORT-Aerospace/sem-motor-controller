# Shadow replay report: run `HOSTMQTT-0001`

Data class: **synthetic (host simulation)** (run kind: HOST SOFTWARE with a real local MQTT broker - not a vehicle run; calibration provenance: synthetic; vehicle configuration: `config/vehicle.synthetic.yaml`). Monitors B1, R3v (selected) and CSIA2 (experimental), frozen v2 classes and thresholds (`docs/csia/V2_FREEZE.json`, residual threshold 9); vehicle parameters from the run: {'wheel_radius_m': 0.238732414637843, 'gear_ratio': 10.0, 'kt_Nm_per_A': 0.06, 'freewheel': False}. Shadow mode: advisory only: no CAN, MQTT or controller interface; no torque command; no protection change.

## Input signals

| Signal | Samples | Ticks with a fresh sample |
|---|---|---|
| rotor | 12001 | 100% |
| iq | 12001 | 100% |
| iq_ref | 6001 | 100% |
| kcl | 12001 | 100% |
| p_dc | 1201 | 100% |
| wheel_l | 1200 | 100% |
| wheel_r | 1200 | 100% |
| wheel_drive | 1200 | 100% |
| gnss | 1098 | 92% |
| imu_ax | 12001 | 100% |
| imu_gz | 12001 | 100% |
| grade | 1098 | 100% |

## Relationships

| Relationship | Needs | Active ticks (of 1200) |
|---|---|---|
| E1_rotor_wheeldrive | rotor, wheel_drive | 1184 |
| E2_wheel_lr_yaw | wheel_l, wheel_r, imu_gz | 1184 |
| E3a_gnss_wheel_l | gnss, wheel_l, imu_gz | 1076 |
| E3b_gnss_wheel_r | gnss, wheel_r, imu_gz | 1076 |
| E4_imu_wheel_l | imu_ax, wheel_l, grade | 1184 |
| E6_power_balance | p_dc, iq, rotor | 1200 |
| E7_gnss_wheeldrive | gnss, wheel_drive | 1017 |
| P_phase_current | iq, iq_ref, kcl | 0 |

## Attribution episodes (after the 3-tick persistence filter)

* B1: 92.232-101.832 s ['gnss']
* R3v: none
* CSIA2: none

## Insufficient evidence

* road grade is assumed flat (no route map): relationships using grade (E4) rest on that assumption
* relationship P_phase_current never active: no evidence about its endpoints from it
* sensor configuration provisional (wheel_ppr PROVISIONAL; channel assignment PROVISIONAL; temperature probe part and placements PROPOSED)
* no ground truth in the run metadata: detections are listed, not scored

A synthetic run shows how the monitors behave on the host model; it is not evidence about real sensors. The frozen evaluation (`docs/csia/EVALUATION_RESULTS_v2.md`) found that CSIA2 did not meet its pre-registered criterion against R3v; this report does not change that.
