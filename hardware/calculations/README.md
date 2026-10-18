# Electrical calculations

Parameterised calculations live in `models/inverter/losses.py` (functions documented with formulas). The SYNTHETIC study is produced by:

    python3 tools/run_electrical_calcs.py   # -> docs/generated/electrical_calcs_synthetic.md, docs/figures/electrical_sensitivity_synthetic.png

Covered: design bus voltage with margin; MOSFET hot RDS(on) (iterative Tj), conduction (synchronous-MOSFET form, numerically verified), switching from gate charge and driver current, Coss, gate drive, dead-time body diode, reverse recovery; paralleling trade-off; shunt dissipation vs resolution vs offset; DC-link ripple (Kolar–Round form, verified against a switching simulation), ESR heating, ripple voltage bound; precharge time, pulse energy and peak power; junction temperature; conductor loss; fuse coordination checks; auxiliary energy per run; tornado sensitivity; and the table of which missing measurements dominate each selection.

MOSFET data used are **search-snippet values (UNVERIFIED)**; operating points are **synthetic**.

## v0.2 additions
* `ov_trip_worst_case.md` (`tools/ov_trip_worst_case.py`, inputs `ov_trip_inputs.yaml`): over-voltage comparator trip and release at every corner; the device terms are null until the data sheets are read (B-OVTRIP).
* `current_sense_error_budget.md` (`tools/hardware_calcs.py`): input-referred phase-current error over full-scale current × CSA gain, before and after calibration.
* `power_stage_envelope.md` (`tools/hardware_calcs.py`): loss and junction-temperature envelope over phase current and bus voltage for the snippet-valued candidate MOSFETs; DC-link ripple table.
* Timing and sampling-window budget: `hardware/timing/timing_budget.md` (`tools/timing_budget.py`), enforced by validator rule 39.
