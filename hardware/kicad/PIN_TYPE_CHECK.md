# Pin-type rule check on the KiCad-exported netlist (generated; NOT a KiCad ERC)

> `tools/pin_type_check.py` on `hardware/kicad/semmc.net` (exported by kicad-cli 7.0.11 from the draft). Connectivity and pin types are KiCad's. **This is not an ERC**: a real ERC (KiCad 8+, `tools/run_kicad_erc.sh`) was not possible in this environment and remains a blocker. Neither check shows that the circuit is electrically correct; that needs review and measurement.

Nets checked: 173. Rails with a PWR_FLAG (read from the sheets): `+3V3A`, `+5V`, `GND`, `PGND`, `VBAT_PROT`, `VDC`. Findings: 0 (none).

| Rule | Severity | Net | Pins |
|---|---|---|---|

Rules: R1 output-output conflict; R2 power input with no power output on the net (KiCad reports this unless a PWR_FLAG marks the rail as driven); R3 input with nothing able to drive it; R4 pin alone on its net without a no-connect marker; R5 open-drain without a pull-up (design rule, not in KiCad ERC).
