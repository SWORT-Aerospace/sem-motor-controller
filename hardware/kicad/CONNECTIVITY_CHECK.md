# Schematic connectivity check (generated)

kicad-cli 7.0.11 exported the netlist of the draft; every intended net was compared with KiCad's computed connectivity (same node set).

* intended nets: 136
* KiCad nets: 174 (of which no-connect singletons: 38)
* problems: 0

No mismatches: KiCad connectivity equals the intended connectivity.

This checks connectivity only. It is not an electrical rules check (the KiCad ERC runs separately: `tools/run_kicad_erc.sh` with KiCad 8 or newer, in the CI `erc` job) and not a design review.
