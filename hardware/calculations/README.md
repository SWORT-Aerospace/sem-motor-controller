# Electrical calculations

Parameterised calculations live in `models/inverter/losses.py` (functions documented with formulas). The SYNTHETIC study is produced by:

    python3 tools/run_electrical_calcs.py   # -> docs/generated/electrical_calcs_synthetic.md, docs/figures/electrical_sensitivity_synthetic.png

Covered: design bus voltage with margin; MOSFET hot RDS(on) (iterative Tj), conduction (synchronous-MOSFET form, numerically verified), switching from gate charge and driver current, Coss, gate drive, dead-time body diode, reverse recovery; paralleling trade-off; shunt dissipation vs resolution vs offset; DC-link ripple (Kolar–Round form, verified against a switching simulation), ESR heating, ripple voltage bound; precharge time, pulse energy and peak power; junction temperature; conductor loss; fuse coordination checks; auxiliary energy per run; tornado sensitivity; and the table of which missing measurements dominate each selection.

MOSFET data used are **search-snippet values (UNVERIFIED)**; operating points are **synthetic**.
