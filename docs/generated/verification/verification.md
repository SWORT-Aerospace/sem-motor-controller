# Verification record (full mode)

Commit `75f1b24ce5c710db6143ae83f118bc0f2cba06c7` on `eng/v0.5-telemetry-integration`; working tree dirty before the run: no.

Environment: python 3.13.16; platform Linux-6.18.44-fc-v139-x86_64-with-glibc2.39; gcc gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0; cmake cmake version 3.28.3; arm-none-eabi-gcc arm-none-eabi-gcc (15:13.2.rel1-2) 13.2.1 20231009; kicad-cli 7.0.11; mosquitto mosquitto version 2.0.18.

| Check | Group | Status | rc | s | Summary |
|---|---|---|---|---|---|
| `gen_config` | generation | **PASS** | 0 | 0.1 |  |
| `gen_protocol` | generation | **PASS** | 0 | 0.1 |  |
| `gen_dbc` | generation | **PASS** | 0 | 0.1 | protocol/generated/semmc_base0x300.dbc: current |
| `fetch_csia` | dependencies | **PASS** | 0 | 0.0 |  |
| `cfg_synthetic_sim` | configuration | **PASS** | 0 | 0.2 | config/vehicle.synthetic.yaml: VALID for mode=sim |
| `cfg_unconfigured_hw` | configuration | **PASS** | 1 | 0.2 | config/vehicle.unconfigured.yaml: INVALID (93 issue(s)) for mode=hw |
| `c_configure` | firmware | **PASS** | 0 | 0.1 | -- Build files have been written to: <repo>/build |
| `c_build` | firmware | **PASS** | 0 | 0.0 |  |
| `ctest` | firmware | **PASS** | 0 | 13.1 | 7: 326246 checks, 0 failures<br>8: 1237899 checks, 0 failures<br>100% tests passed, 0 tests failed out of 8 |
| `property_soak` | firmware | **PASS** | 0 | 101.9 | 100 seeds x 30 s from base seed 0x01234567<br>slow steps 3000000, ECO steps 641109 (entries 1632), brake steps 321447, recovery checks 1257928<br>13733755 checks, 0 failures |
| `arm_configure` | portability | **PASS** | 0 | 0.2 | -- Build files have been written to: <repo>/build-arm |
| `arm_build` | portability | **PASS** | 0 | 0.7 |  |
| `arm_size` | portability | **PASS** | 0 | 0.0 | 31955	      0	      0	  31955	   7cd3	(TOTALS)<br>soft-double calls in mc_core_fast_step: 0 |
| `pytest` | python | **PASS** | 0 | 91.6 |  |
| `replay` | host simulation | **PASS** | 0 | 0.3 | 6.140 s  req   1.200  acc   0.704  CLAMP_DERATE\|SLEW<br>6.160 s  req   1.200  acc   0.804  CLAMP_DERATE\|SLEW<br>44 distinct requested/accepted/reason combinations; full table in build/replay/commands.csv |
| `contract_report` | host simulation | **PASS** | 0 | 0.3 | contract violations in 'after' run: none |
| `host_demo` | host simulation | **PASS** | 0 | 18.2 | DEMO PASS pit_csia_replay_runs: 1200 ticks; wheel_l fault detected after 0.1 s<br>DEMO PASS pit_shadow_replay_r3v_and_csia2_reported: 1200 ticks, data class synthetic (host simulation); injected wheel_l dropout: R3v 0.3 s,<br>DEMO ALL PASS: 10/10 checks; outputs in build/host_demo |
| `pit_replay` | host simulation | **PASS** | 0 | 1.3 | REPLAY ENERGY NOTE: a wheel dropout reads as zero counts and shortens the distance; compare with rotor speed or GNSS<br>REPLAY ENERGY NOTE: energy at the controller input; the official joulemeter also counts the telemetry unit, sensors, display and wiring down<br>REPLAY ENERGY NOTE: wheel channel wheel_l covers 635.0 m, 8.8 % less than the longest (695.9 m): missed pulses or a dropout on that channel |
| `mqtt_demo` | host simulation | **PASS** | 0 | 64.2 | MQTT ALL PASS: 12/12 checks; outputs in build/mqtt_demo |
| `optimisation_full` | studies | **PASS** | 0 | 318.8 |  |
| `electrical` | studies | **PASS** | 0 | 0.8 | \| 20 \| 1.33 \| 0.37 \|<br>\| 30 \| 1.33 \| 0.16 \|<br>\| 40 \| 1.46 \| 0.09 \| |
| `csia_dev_study` | studies | **PASS** | 0 | 4.5 | - B2 raises an alarm on a residual but cannot say which sensor is wrong; B1 only sees stale/NaN/out-of-range values, so stuck-in-range, bias<br>- Ambiguous ticks are periods where the evidence supports disagreement only; the adapter reports them instead of guessing.<br>Adapter + CSIA TrustCore tick time on this host (x86-64, CPython, HOST BENCHMARK - not a target measurement): mean 0.15 ms, max 0.73 ms at 1 |
| `policy_comparison` | studies | **PASS** | 0 | 85.7 | pulse 1.0 N*m, coast 5.5-6.5 m/s           4.450 J/m at 5.99 m/s, gates off 91 %, dKE -0.006 J/m, cu 0.544, mech 3.373, other 0.533, window <br>pulse 2.0 N*m, coast 5.5-6.5 m/s           4.947 J/m at 6.03 m/s, gates off 95 %, dKE +0.002 J/m, cu 1.007, mech 3.398, other 0.542, window <br>pulse 1.0 N*m, coast 5.0-7.0 m/s           4.499 J/m at 5.97 m/s, gates off 92 %, dKE +0.009 J/m, cu 0.560, mech 3.412, other 0.527, window  |
| `csia_eval_v1_rerun` | studies | **PASS** | 0 | 130.8 | "lat_detect_med": 0.9782878877182384<br>}<br>} |
| `wheel_sensor_check` | hardware | **PASS** | 0 | 0.0 | docs/generated/wheel_sensor_check.md: current |
| `coastdown_sensitivity` | studies | **PASS** | 0 | 0.1 | docs/generated/coastdown_sensitivity.md: current |
| `procurement_tables` | hardware | **PASS** | 0 | 0.1 | procurement tables current: 39 lines, 0 quoted, 17 estimated, 19 unpriced, 3 not counted |
| `doc_links` | documentation | **PASS** | 0 | 0.1 | links: 108 Markdown files checked, 0 broken |
| `kicad_connectivity` | hardware | **PASS** | 0 | 9.2 | * intended nets: 135<br>* problems: 0 |
| `kicad_drift` | hardware | **PASS** | 0 | 0.0 |  |
| `pin_type_check` | hardware | **PASS** | 0 | 0.0 | 173 nets, 0 findings -> hardware/kicad/PIN_TYPE_CHECK.md |
| `hw_consistency` | hardware | **PASS** | 0 | 0.1 | OPEN  TM3 dead time and PWM frequency: synthetic 200 ns at 20 kHz; dead time depends on the selected MOSFETs' switching times, PWM frequency<br>OPEN  PW2 rail current budgets: supply currents of the candidate ICs were not read from primary datasheets; regulator ratings vs loads to be<br>wrote hardware/review/CONSISTENCY_CHECK.md: {'PASS': 14, 'OPEN': 4} |
| `kicad_erc` | hardware | **NOT AVAILABLE** | 2 | 0.1 | kicad-cli 7.0.11: 'sch erc' needs KiCad 8 or newer (or run ERC from the Eeschema GUI). |
| `timing_budget` | hardware | **PASS** | 0 | 0.0 | "min_valid_phases_over_svpwm_angles": 2,<br>"worst_angle_deg": 5.500000000000001<br>} 34 2e-07 |
| `clock_tree` | hardware | **PASS** | 0 | 0.8 | wrote <repo>/hardware/timing/clock_tree_alternatives.md (28 clock trees x 4 bus cases) |
| `hardware_calcs` | hardware | **PASS** | 0 | 0.1 | wrote <repo>/hardware/calculations/current_sense_error_budget.md <repo>/hardware/calculations/power_stage_envelope.md |
| `price_bom` | hardware | **PASS** | 0 | 0.1 | **Conclusion: the budget is not shown to be feasible.** At least one range reaches past its limit, so feasibility cannot be claimed until th |
| `telematics_budget` | integration | **PASS** | 0 | 0.0 | controller 394 f/s, supervisor 72 f/s; flash lasts 16.9 min for semmc frames |

Regenerated tracked files that differ from the committed versions: `M docs/generated/csia_comparison_synthetic.md`, ` M docs/generated/csia_evaluation_synthetic.json`, ` M docs/generated/csia_evaluation_synthetic.md`, ` M docs/generated/optimization_synthetic.json`, ` M docs/generated/optimization_synthetic.md`.

Totals: {'PASS': 37, 'FAIL': 0, 'NOT AVAILABLE': 1}. Commands are run from the repository root; logs are in `logs/`.
