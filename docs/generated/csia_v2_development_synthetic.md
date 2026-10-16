# CSIA v2: DEVELOPMENT set results (used for design)

SYNTHETIC, shadow mode. Protocol: `docs/csia/EVALUATION_PROTOCOL_v2.md`. Every monitor passes through the same 3-tick node-level debounce.

Scenarios: 36 (8 fault-free), 2.20 h outside fault windows. Residual threshold lambda = 9.0. E6 model: R = 0.0997 ohm, c_sw = 0.125 W/A, P0 = 3.16 W, s0 = 2.20 W (fitted on development nominal data).

| monitor | FA episodes / h (95 % upper if 0) | false attributions / h | coverage | correctly attributed | misattributed | median ambiguity | median latency s | median eligible-evidence latency s | host ms / tick | peak KiB |
|---|---|---|---|---|---|---|---|---|---|---|
| B1: range / NaN / freshness | 26.9 | 26.9 | 11 % | 3 / 28 | 5 | 0.00 | 0.4 | 32.7 | 0.074 | 331 |
| R3: calibrated residuals (v2 set) + gates, detection only | 0.5 | 0.0 | 64 % | 0 / 28 | 0 | 1.00 | 0.9 | 0.8 | 0.219 | 341 |
| R3v: R3 + majority-vote attribution | 0.5 | 0.0 | 64 % | 14 / 28 | 0 | 0.07 | 0.9 | 0.8 | 0.202 | 341 |
| CSIA1: frozen v1 adapter (corroboration attribution) | 31.4 | 30.1 | 61 % | 17 / 28 | 8 | 0.02 | 0.9 | 0.8 | 0.375 | 502 |
| CSIA2: v2 adapter: v2 power balance + corroboration attribution | 0.5 | 0.0 | 64 % | 18 / 28 | 1 | 0.02 | 0.9 | 0.8 | 0.363 | 502 |
| TRUST2: TrustCore belief threshold (v2 adapter) | 50.6 | 58.3 | 82 % | 16 / 28 | 11 | 0.83 | 9.4 | 9.4 | 0.390 | 344 |
| B1+CSIA2: B1 + CSIA2 | 27.3 | 26.9 | 71 % | 20 / 28 | 6 | 0.01 | 0.4 | 0.8 | 0.438 | 506 |

False-alarm episodes by implicated nodes (top):

* B1: gnss 59
* R3: dc_meter,phase_current 1
* R3v: dc_meter,phase_current 1
* CSIA1: dc_meter,phase_current 61, dc_meter 8
* CSIA2: dc_meter,phase_current 1
* TRUST2: dc_meter,phase_current 33, gnss,imu,rotor,wheel_drive 14, imu,rotor,wheel_drive 11, imu 7, dc_meter 7, gnss,imu,rotor,wheel_drive,wheel_l 6
* B1+CSIA2: gnss 59, dc_meter,phase_current 1

Per fault kind (CSIA2): detected / attributed / misattributed of n; median unobservable fraction of the fault window; scenarios never eligible.

| kind | n | det | attr | mis | wrong nodes | unobservable | never eligible |
|---|---|---|---|---|---|---|---|
| wheel_l_dropout | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| wheel_r_dropout | 2 | 2 | 2 | 0 | – | 0.13 | 0 |
| wheel_l_intermittent | 2 | 2 | 2 | 1 | imu | 0.00 | 0 |
| rotor_stuck | 2 | 0 | 0 | 0 | – | 0.90 | 1 |
| rotor_scale | 2 | 0 | 0 | 0 | – | 0.39 | 0 |
| rotor_dropout | 2 | 0 | 0 | 0 | – | 1.00 | 2 |
| gnss_offset | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| gnss_drift | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| imu_bias | 2 | 0 | 0 | 0 | – | 0.00 | 0 |
| imu_drift | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| current_bias | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| current_drift | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| dc_gain | 2 | 2 | 2 | 0 | – | 0.00 | 0 |
| dc_drift | 2 | 0 | 0 | 0 | – | 0.00 | 0 |

## Pre-registered decision (protocol section 6)

* CSIA2_vs_R3v: +4 attributed, +1 misattributed, +0.00 FA/h -> increment NOT supported
* TRUST2_vs_R3v: +2 attributed, +11 misattributed, +50.09 FA/h -> increment NOT supported
* Recommended monitor: **R3v**

Runtime 85 s on this host. Host CPU and memory figures are x86-64 CPython, not target figures.
