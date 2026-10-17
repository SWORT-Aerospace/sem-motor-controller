# Shadow replay report: run `HOSTSIM-0001`

Data class: **synthetic (host simulation)** (run kind: HOST SIMULATION - not a vehicle run; calibration provenance: synthetic; vehicle configuration: `config/vehicle.synthetic.yaml`). Monitors B1, R3v (selected) and CSIA2 (experimental), frozen v2 classes and thresholds (`docs/csia/V2_FREEZE.json`, residual threshold 9); vehicle parameters from the run: {'wheel_radius_m': 0.238732414637843, 'gear_ratio': 10.0, 'kt_Nm_per_A': 0.06, 'freewheel': False}. Shadow mode: advisory only: no CAN, MQTT or controller interface; no torque command; no protection change.

## Input signals

| Signal | Samples | Ticks with a fresh sample |
|---|---|---|
| rotor | 11934 | 100% |
| iq | 11934 | 100% |
| iq_ref | 5968 | 100% |
| kcl | 11934 | 100% |
| p_dc | 1194 | 100% |
| wheel_l | 1193 | 99% |
| wheel_r | 1193 | 99% |
| wheel_drive | 1193 | 99% |
| gnss | 1041 | 87% |
| imu_ax | 11934 | 99% |
| imu_gz | 11934 | 99% |
| grade | 1041 | 100% |

## Relationships

| Relationship | Needs | Active ticks (of 1200) |
|---|---|---|
| E1_rotor_wheeldrive | rotor, wheel_drive | 1177 |
| E2_wheel_lr_yaw | wheel_l, wheel_r, imu_gz | 1176 |
| E3a_gnss_wheel_l | gnss, wheel_l, imu_gz | 1018 |
| E3b_gnss_wheel_r | gnss, wheel_r, imu_gz | 1018 |
| E4_imu_wheel_l | imu_ax, wheel_l, grade | 1169 |
| E6_power_balance | p_dc, iq, rotor | 1193 |
| E7_gnss_wheeldrive | gnss, wheel_drive | 961 |
| P_phase_current | iq, iq_ref, kcl | 0 |

## Attribution episodes (after the 3-tick persistence filter)

* B1: 32.832-32.832 s ['imu']; 32.932-32.932 s ['imu', 'phase_current', 'rotor']; 33.032-33.232 s ['dc_meter', 'gnss', 'imu', 'phase_current', 'rotor', 'wheel_drive', 'wheel_l', 'wheel_r']; 33.332-33.332 s ['dc_meter', 'wheel_drive', 'wheel_l', 'wheel_r']; 62.232-76.832 s ['gnss']
* R3v: 82.032-91.732 s ['wheel_l']
* CSIA2: 82.032-91.732 s ['wheel_l']

## Against the injected faults (synthetic ground truth from the run metadata)

| Monitor | Fault | First correct attribution after onset | Ticks with a wrong or unexplained suspect |
|---|---|---|---|
| B1 | wheel_dropout wheel_l 81.735-91.736 s | not attributed | 153 |
| R3v | wheel_dropout wheel_l 81.735-91.736 s | 0.3 s | 0 |
| CSIA2 | wheel_dropout wheel_l 81.735-91.736 s | 0.3 s | 0 |

## Insufficient evidence

* road grade is assumed flat (no route map): relationships using grade (E4) rest on that assumption
* relationship P_phase_current never active: no evidence about its endpoints from it
* sensor configuration provisional (wheel_ppr PROVISIONAL; channel assignment PROVISIONAL; temperature probe part and placements PROPOSED)

A synthetic run shows how the monitors behave on the host model; it is not evidence about real sensors. The frozen evaluation (`docs/csia/EVALUATION_RESULTS_v2.md`) found that CSIA2 did not meet its pre-registered criterion against R3v; this report does not change that.
