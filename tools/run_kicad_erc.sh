#!/usr/bin/env bash
# Run a real KiCad ERC on the draft schematic (KiCad 8 or newer; KiCad 7 has no `sch erc`).
#
#   tools/run_kicad_erc.sh            -> hardware/kicad/ERC_REPORT.rpt (+ ERC_REPORT.json when supported)
#
# Without KiCad 8+: open hardware/kicad/semmc.kicad_sch in Eeschema (KiCad 7 or newer),
# Inspect > Electrical Rules Checker > Run ERC, and save the report to the same path.
# Commit the report together with the KiCad version line it prints. The ERC result is a
# schematic check only: it does not show that the circuit is electrically correct.
set -euo pipefail
cd "$(dirname "$0")/.."
SCH=hardware/kicad/semmc.kicad_sch
ver=$(kicad-cli version 2>/dev/null || true)
major=${ver%%.*}
if [[ -z "$ver" || "$major" -lt 8 ]]; then
  echo "kicad-cli ${ver:-not found}: 'sch erc' needs KiCad 8 or newer (or run ERC from the Eeschema GUI)." >&2
  exit 2
fi
echo "KiCad $ver"
# A fresh KiCad install has no global symbol library table, and ERC then reports every
# standard symbol as "library not in the configuration". Install KiCad's own default table,
# only when none exists (never overwrite a user's configuration).
cfg_dir="${XDG_CONFIG_HOME:-$HOME/.config}/kicad/${major}.0"
if [[ ! -f "$cfg_dir/sym-lib-table" && -f /usr/share/kicad/template/sym-lib-table ]]; then
  mkdir -p "$cfg_dir"
  cp /usr/share/kicad/template/sym-lib-table "$cfg_dir/sym-lib-table"
  echo "installed KiCad's default global sym-lib-table into $cfg_dir"
fi
# Compare the schematic's embedded symbols with the pinned KiCad 8.0.9 libraries it was generated from
# (tools/fetch_kicad_symbols.py), not with whatever library version the installed package carries: the
# default table resolves ${KICAD8_SYMBOL_DIR}/<lib>.kicad_sym.
symdir="${SEMMC_KICAD_SYMBOL_DIR:-$PWD/build/kicad-symbols-8.0.9}"
if [[ ! -f "$symdir/power.kicad_sym" ]]; then
  echo "$symdir has no symbol libraries: run python3 tools/fetch_kicad_symbols.py" >&2
  exit 2
fi
export KICAD8_SYMBOL_DIR="$symdir"
echo "symbol libraries: $symdir"
# The project's fp-lib-table (written by tools/check_footprints.py) resolves ${KICAD8_FOOTPRINT_DIR}/<lib>.pretty;
# point it at the pinned copy of the footprints the assignment uses (tools/check_footprints.py --fetch).
fpdir="${SEMMC_KICAD_FOOTPRINT_DIR:-$PWD/build/kicad-footprints-8.0.9}"
if [[ ! -d "$fpdir/Resistor_SMD.pretty" ]]; then
  echo "$fpdir has no footprints: run python3 tools/check_footprints.py --fetch" >&2
  exit 2
fi
export KICAD8_FOOTPRINT_DIR="$fpdir"
echo "footprint libraries: $fpdir"
kicad-cli sch erc --severity-all --units mm --format report --output hardware/kicad/ERC_REPORT.rpt "$SCH" || true
kicad-cli sch erc --severity-all --units mm --format json --output hardware/kicad/ERC_REPORT.json "$SCH" 2>/dev/null || true
grep -E "^\*\* ERC messages|^ \*\* ERC messages|errors|warnings" hardware/kicad/ERC_REPORT.rpt | tail -3 || true
echo "Report: hardware/kicad/ERC_REPORT.rpt (KiCad $ver). Review every error and warning; do not suppress them to pass."
