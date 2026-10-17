# Host end-to-end demonstration (HOST SIMULATION)

Run `HOSTSIM-0001`, 120 s, commit `e1b59a60614f` plus uncommitted changes (the commit that adds these outputs). Command: `python3 tools/run_host_demo.py --out build/host_demo`. Synthetic plant, synthetic sensors, simulated LTE and MQTT; nothing here was measured on hardware.

| Check | Result | Evidence |
|---|---|---|
| `control_unaffected_by_logging_and_lte` | PASS | supervisor requests/s during flash stall [50], during LTE outage [50]; controller ECO_ASSIST in 2200/2200 steps of those windows |
| `log_drops_counted_not_hidden` | PASS | queue drops 396 (all during the flash stall), high water 512/512; records written 70506 = imported 70506; storage drops 0 |
| `supervisor_loss_exits_eco_by_timeout_no_silent_resume` | PASS | supervisor stopped at 45.00 s, ECO left at 45.10 s; supervisor back at 45.30 s, ECO re-entered at 46.00 s after the driver's re-selection at 46.00 s |
| `brake_keeps_authority` | PASS | brake at 95.00 s, ECO left at 95.00 s; max accepted torque while braking 0.000 N*m over 200 steps; ECO again at 98.00 s after re-selection at 98.00 s |
| `offline_import_complete_and_idempotent` | PASS | blocks 282 ok / 0 corrupt, records 70506, bad-CRC frames 0; second import added 0 rows |
| `live_path_validated_and_accounted` | PASS | published 240, stored 228 (30 replayed after the outage), rejected 2 {'not JSON (JSONDecodeError)': 1, 'ctrl.vbus_V=9999.0 outside [0.0, 100.0]': 1}, dropped on the car 10 (expected 10); every sequence number accounted for: True |
| `utc_alignment_with_quality` | PASS | largest UTC error 0.72 us with PPS (60535 records); 7.4 us in holdover (9971 records, GNSS outage 15 s, bound 50 ppm x age) |
| `energy_boundary_and_gaps_reported` | PASS | controller input energy (bus shunt) 5.805 kJ vs simulated battery-terminal energy 5.797 kJ: 0.139 % apart; integrated 120.00 s, gap 0.00 s (last ctrl_energy_quality before the end of the run) |
| `pit_csia_replay_runs` | PASS | 1200 ticks; wheel_l fault detected after 0.1 s |
| `pit_shadow_replay_r3v_and_csia2_reported` | PASS | 1200 ticks, data class synthetic (host simulation); injected wheel_l dropout: R3v 0.3 s, CSIA2 0.3 s (first correct attribution after onset); wrong or unexplained suspect ticks R3v 0, CSIA2 0; report pit_replay/report.md with 3 insufficient-evidence notes |

## Storage

STLG log 1122 KiB for 120 s = 9.35 KiB/s; the 8 MB flash of the telematics proposal holds 14.6 min at this rate (every frame of the semmc block plus the unit's own sensors, no compression).

## Pit-side CSIA replay (shadow; not an evaluation)

1200 ticks at 10 Hz; front-left wheel hall lost from 80 to 90 s: attributed to wheel_l 0.1 s after onset. Ticks naming any other suspect, or naming one outside the fault window: 65; ambiguous ticks: 530; unobservable ticks: 5. Host runtime per tick: mean 1.44 ms, p99 2.73 ms, max 4.06 ms; peak traced Python memory 1785 KiB (x86-64 CPython, not a target figure).

Relationship failures (lambda > lam_fail) outside the injected fault window: E6_power_balance 507 ticks.

Two causes, both in the frozen v1 adapter's power balance (E6), measured on this run: (1) E6 compares the latest p_dc (ctrl_energy, 10 Hz) with the latest iq and rotor speed (100 Hz) at the tick, without time alignment; with the speed-hold policy moving iq between p_dc samples the residual standard deviation at cruise (25-45 s) is 28.9 W, against 1.4 W when iq and speed are interpolated to the p_dc sample time (allowed 1 sigma about 5.7 W). (2) Its loss model (8 % of mechanical power + 3 W) does not describe this plant's copper loss: a fit of p_dc - p_mech gives 0.159 iq^2 + 3.02 W (1.5 R iq^2 with R = 0.1 ohm), so at launch current the I^2R loss reads as a fault. The v1 synthetic evaluation generated p_dc with the adapter's own loss form and constant current within pulses, so it tested neither. docs/csia/EVALUATION_PROTOCOL_v2.md treats both with a frozen protocol and a new untouched evaluation set (results: docs/csia/EVALUATION_RESULTS_v2.md).
