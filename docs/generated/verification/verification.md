# Verification record (full mode)

Commit `4c8b5bf25882c188603642e84134fed653f1c1fe` on `eng/v0.4-verification-integration`; working tree dirty before the run: no.

Environment: python 3.13.16; platform Linux-6.18.44-fc-v139-x86_64-with-glibc2.39; gcc gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0; cmake cmake version 3.28.3; arm-none-eabi-gcc arm-none-eabi-gcc (15:13.2.rel1-2) 13.2.1 20231009; kicad-cli 7.0.11.

| Check | Group | Status | rc | s | Summary |
|---|---|---|---|---|---|
| `gen_config` | generation | **PASS** | 0 | 0.1 |  |
| `gen_protocol` | generation | **PASS** | 0 | 0.1 |  |
| `gen_dbc` | generation | **PASS** | 0 | 0.1 | protocol/generated/semmc_base0x300.dbc: current |
| `fetch_csia` | dependencies | **PASS** | 0 | 1.4 | fetched CSIA 848f5563a528ae5ca3c2d3883c86d7287d6a4585 into .deps/csia-trust-layer |
| `cfg_synthetic_sim` | configuration | **PASS** | 0 | 0.2 | config/vehicle.synthetic.yaml: VALID for mode=sim |
| `cfg_unconfigured_hw` | configuration | **PASS** | 1 | 0.3 | config/vehicle.unconfigured.yaml: INVALID (93 issue(s)) for mode=hw |
| `c_configure` | firmware | **PASS** | 0 | 0.4 | -- Build files have been written to: /tmp/claude-0/-home-user/43ac6c92-6ed7-5c4a-aeaf-a4d9ad0cd833/scratchpad/final/repo/build |
| `c_build` | firmware | **PASS** | 0 | 2.1 |  |
| `ctest` | firmware | **PASS** | 0 | 17.2 | 7: 326246 checks, 0 failures<br>8: 1237899 checks, 0 failures<br>100% tests passed, 0 tests failed out of 8 |
| `property_soak` | firmware | **PASS** | 0 | 130.8 | 100 seeds x 30 s from base seed 0x01234567<br>slow steps 3000000, ECO steps 641109 (entries 1632), brake steps 321447, recovery checks 1257928<br>13733755 checks, 0 failures |
| `arm_configure` | portability | **PASS** | 0 | 0.4 | -- Build files have been written to: /tmp/claude-0/-home-user/43ac6c92-6ed7-5c4a-aeaf-a4d9ad0cd833/scratchpad/final/repo/build-arm |
| `arm_build` | portability | **PASS** | 0 | 0.9 |  |
| `arm_size` | portability | **PASS** | 0 | 0.0 | 31955	      0	      0	  31955	   7cd3	(TOTALS)<br>soft-double calls in mc_core_fast_step: 0 |
| `pytest` | python | **PASS** | 0 | 84.1 |  |
| `replay` | host simulation | **PASS** | 0 | 0.6 | 6.140 s  req   1.200  acc   0.704  CLAMP_DERATE\|SLEW<br>6.160 s  req   1.200  acc   0.804  CLAMP_DERATE\|SLEW<br>44 distinct requested/accepted/reason combinations; full table in build/replay/commands.csv |
| `contract_report` | host simulation | **PASS** | 0 | 0.4 | contract violations in 'after' run: none |
| `host_demo` | host simulation | **PASS** | 0 | 24.5 | DEMO PASS energy_boundary_and_gaps_reported: controller input energy (bus shunt) 5.805 kJ vs simulated battery-terminal energy 5.797 kJ: 0.1<br>DEMO PASS pit_csia_replay_runs: 1200 ticks; wheel_l fault detected after 0.1 s<br>DEMO ALL PASS: 9/9 checks; outputs in build/host_demo |
| `optimisation_full` | studies | **PASS** | 0 | 577.3 |  |
| `electrical` | studies | **PASS** | 0 | 1.6 | \| 20 \| 1.33 \| 0.37 \|<br>\| 30 \| 1.33 \| 0.16 \|<br>\| 40 \| 1.46 \| 0.09 \| |
| `csia_dev_study` | studies | **PASS** | 0 | 7.3 | - B2 raises an alarm on a residual but cannot say which sensor is wrong; B1 only sees stale/NaN/out-of-range values, so stuck-in-range, bias<br>- Ambiguous ticks are periods where the evidence supports disagreement only; the adapter reports them instead of guessing.<br>Adapter + CSIA TrustCore tick time on this host (x86-64, CPython, HOST BENCHMARK - not a target measurement): mean 0.20 ms, max 2.65 ms at 1 |
| `policy_comparison` | studies | **PASS** | 0 | 131.5 | pulse 1.0 N*m, coast 5.5-6.5 m/s           4.450 J/m at 5.99 m/s, gates off 91 %, dKE -0.006 J/m, cu 0.544, mech 3.373, other 0.533, window <br>pulse 2.0 N*m, coast 5.5-6.5 m/s           4.947 J/m at 6.03 m/s, gates off 95 %, dKE +0.002 J/m, cu 1.007, mech 3.398, other 0.542, window <br>pulse 1.0 N*m, coast 5.0-7.0 m/s           4.499 J/m at 5.97 m/s, gates off 92 %, dKE +0.009 J/m, cu 0.560, mech 3.412, other 0.527, window  |
| `csia_eval_v1_rerun` | studies | **PASS** | 0 | 203.0 | "lat_detect_med": 0.9782878877182384<br>}<br>} |
| `kicad_connectivity` | hardware | **PASS** | 0 | 15.1 | * intended nets: 135<br>* problems: 0 |
| `kicad_drift` | hardware | **PASS** | 0 | 0.0 |  |
| `pin_type_check` | hardware | **PASS** | 0 | 0.1 | 173 nets, 0 findings -> hardware/kicad/PIN_TYPE_CHECK.md |
| `hw_consistency` | hardware | **PASS** | 0 | 0.1 | OPEN  TM3 dead time and PWM frequency: synthetic 200 ns at 20 kHz; dead time depends on the selected MOSFETs' switching times, PWM frequency<br>OPEN  PW2 rail current budgets: supply currents of the candidate ICs were not read from primary datasheets; regulator ratings vs loads to be<br>wrote hardware/review/CONSISTENCY_CHECK.md: {'PASS': 14, 'OPEN': 4} |
| `kicad_erc` | hardware | **NOT AVAILABLE** | 2 | 0.1 | kicad-cli 7.0.11: 'sch erc' needs KiCad 8 or newer (or run ERC from the Eeschema GUI). |
| `timing_budget` | hardware | **PASS** | 0 | 0.1 | "min_valid_phases_over_svpwm_angles": 2,<br>"worst_angle_deg": 5.500000000000001<br>} 34 2e-07 |
| `clock_tree` | hardware | **PASS** | 0 | 1.3 | wrote /tmp/claude-0/-home-user/43ac6c92-6ed7-5c4a-aeaf-a4d9ad0cd833/scratchpad/final/repo/hardware/timing/clock_tree_alternatives.md (28 clo |
| `hardware_calcs` | hardware | **PASS** | 0 | 0.2 | wrote /tmp/claude-0/-home-user/43ac6c92-6ed7-5c4a-aeaf-a4d9ad0cd833/scratchpad/final/repo/hardware/calculations/current_sense_error_budget.m |
| `price_bom` | hardware | **PASS** | 0 | 0.1 | **Conclusion: the budget is not shown to be feasible.** At least one range reaches past its limit, so feasibility cannot be claimed until th |
| `telematics_budget` | integration | **PASS** | 0 | 0.1 | controller 394 f/s, supervisor 72 f/s; flash lasts 16.9 min for semmc frames |

Regenerated tracked files that differ from the committed versions: `M docs/generated/csia_comparison_synthetic.md`, ` M docs/generated/csia_evaluation_synthetic.json`, ` M docs/generated/csia_evaluation_synthetic.md`, ` M docs/generated/optimization_synthetic.json`, ` M docs/generated/optimization_synthetic.md`.

Totals: {'PASS': 31, 'FAIL': 0, 'NOT AVAILABLE': 1}. Commands are run from the repository root; logs are in `logs/`.
