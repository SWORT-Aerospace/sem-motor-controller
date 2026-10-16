# CSIA v2: EVALUATION set results (run once)

SYNTHETIC, shadow mode. Protocol: `docs/csia/EVALUATION_PROTOCOL_v2.md`. Every monitor passes through the same 3-tick node-level debounce.

Scenarios: 94 (24 fault-free), 5.78 h outside fault windows. Residual threshold lambda = 9.0. E6 model: R = 0.0997 ohm, c_sw = 0.125 W/A, P0 = 3.16 W, s0 = 2.20 W (fitted on development nominal data).

| monitor | FA episodes / h (95 % upper if 0) | false attributions / h | coverage | correctly attributed | misattributed | median ambiguity | median latency s | median eligible-evidence latency s | host ms / tick | peak KiB |
|---|---|---|---|---|---|---|---|---|---|---|
| B1: range / NaN / freshness | 36.2 | 36.2 | 7 % | 5 / 70 | 16 | 0.00 | 0.4 | 0.3 | 0.074 | 372 |
| R3: calibrated residuals (v2 set) + gates, detection only | 1.0 | 0.0 | 80 % | 0 / 70 | 0 | 1.00 | 2.7 | 1.1 | 0.214 | 720 |
| R3v: R3 + majority-vote attribution | 1.0 | 0.0 | 80 % | 34 / 70 | 0 | 0.56 | 2.7 | 1.1 | 0.196 | 341 |
| CSIA1: frozen v1 adapter (corroboration attribution) | 35.7 | 32.9 | 80 % | 49 / 70 | 16 | 0.04 | 3.2 | 1.5 | 0.341 | 505 |
| CSIA2: v2 adapter: v2 power balance + corroboration attribution | 1.0 | 0.0 | 80 % | 48 / 70 | 4 | 0.04 | 2.7 | 1.1 | 0.355 | 502 |
| TRUST2: TrustCore belief threshold (v2 adapter) | 53.5 | 56.5 | 84 % | 38 / 70 | 22 | 0.80 | 9.1 | 8.4 | 0.354 | 344 |
| B1+CSIA2: B1 + CSIA2 | 37.2 | 36.2 | 87 % | 53 / 70 | 19 | 0.03 | 1.2 | 1.1 | 0.434 | 506 |

False-alarm episodes by implicated nodes (top):

* B1: gnss 209
* R3: dc_meter,phase_current 6
* R3v: dc_meter,phase_current 6
* CSIA1: dc_meter,phase_current 193, dc_meter 13
* CSIA2: dc_meter,phase_current 6
* TRUST2: dc_meter,phase_current 97, imu,rotor,wheel_drive 33, gnss,imu,rotor,wheel_drive 32, imu 18, gnss 16, rotor,wheel_drive 14
* B1+CSIA2: gnss 209, dc_meter,phase_current 6

Per fault kind (CSIA2): detected / attributed / misattributed of n; median unobservable fraction of the fault window; scenarios never eligible.

| kind | n | det | attr | mis | wrong nodes | unobservable | never eligible |
|---|---|---|---|---|---|---|---|
| wheel_l_dropout | 5 | 5 | 5 | 2 | imu, wheel_r | 0.00 | 0 |
| wheel_r_dropout | 5 | 5 | 5 | 0 | – | 0.00 | 0 |
| wheel_l_intermittent | 5 | 5 | 5 | 2 | imu | 0.00 | 0 |
| rotor_stuck | 5 | 3 | 0 | 0 | – | 0.61 | 1 |
| rotor_scale | 5 | 1 | 0 | 0 | – | 0.86 | 2 |
| rotor_dropout | 5 | 0 | 0 | 0 | – | 1.00 | 3 |
| gnss_offset | 5 | 5 | 5 | 0 | – | 0.00 | 0 |
| gnss_drift | 5 | 5 | 4 | 0 | – | 0.00 | 0 |
| imu_bias | 5 | 4 | 3 | 0 | – | 0.00 | 0 |
| imu_drift | 5 | 5 | 4 | 0 | – | 0.00 | 0 |
| current_bias | 5 | 5 | 5 | 0 | – | 0.00 | 0 |
| current_drift | 5 | 5 | 5 | 0 | – | 0.00 | 0 |
| dc_gain | 5 | 4 | 3 | 0 | – | 0.00 | 0 |
| dc_drift | 5 | 4 | 4 | 0 | – | 0.00 | 0 |

## Pre-registered decision (protocol section 6)

* CSIA2_vs_R3v: +14 attributed, +4 misattributed, +0.00 FA/h -> increment NOT supported
* TRUST2_vs_R3v: +4 attributed, +22 misattributed, +52.47 FA/h -> increment NOT supported
* Recommended monitor: **R3v**

Runtime 191 s on this host. Host CPU and memory figures are x86-64 CPython, not target figures.
