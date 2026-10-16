# Speed hold vs pulse-and-coast on the host plant (HOST SIMULATION)

Command: `python3 tools/run_policy_comparison.py --duration 300`. Each policy is the supervisor of the co-simulation; its requests pass the controller core; energy is the host plant's battery-terminal energy. Window: whole pulse-and-coast cycles after 40 s (gate-on to gate-on), or 40 s to the end for steady policies. Synthetic configuration and plant.

| policy | J/m | vs speed hold | mean speed m/s | gates off | window s | remaining dKE J/m | copper J/m | kt iq w J/m | other J/m | gate-on events |
|---|---|---|---|---|---|---|---|---|---|---|
| speed hold 6.0 m/s | 3.996 | +0.0 % | 6.09 | 27 % | 260 | -0.004 | 0.090 | 3.440 | 0.465 | 2752 |
| pulse 1.0 N*m, coast 5.5-6.5 m/s | 4.450 | +11.4 % | 5.99 | 91 % | 223 | -0.006 | 0.544 | 3.373 | 0.533 | 11 |
| pulse 2.0 N*m, coast 5.5-6.5 m/s | 4.947 | +23.8 % | 6.03 | 95 % | 221 | +0.002 | 1.007 | 3.398 | 0.542 | 10 |
| pulse 1.0 N*m, coast 5.0-7.0 m/s | 4.499 | +12.6 % | 5.97 | 92 % | 207 | +0.009 | 0.560 | 3.412 | 0.527 | 4 |

Reading the table: 'kt iq w' is the electromagnetic work, 'copper' the I^2R loss computed from the measured currents (1.5 R (id^2 + iq^2)), 'other' the remainder (inverter and plant terms). The electromagnetic work per metre is set by the road load and is nearly the same for every policy at the same mean speed, so the policies differ through the copper loss (higher pulses: more I^2R) and through the 'other' term. This host plant has no loss that is independent of torque while driving; the optimisation study's synthetic physics map has one (iron loss ~ w^1.5), and there pulse-and-coast saves energy (`optimization_synthetic.md` 4b). Which case the vehicle is in has to be measured.
