# BOM files

| File | What it is | Status |
|---|---|---|
| `BOM_draft.csv` | generated from the schematic data (`tools/gen_kicad_schematic.py`), grouped by value and part | DRAFT; ratings UNRESOLVED where marked |
| `pricing.yaml` | price evidence per line: evidence class (snippet / representative / allowance), source, retrieval date, availability, alternate | snapshots and allowances, not quotes |
| `BOM_priced.csv` | `BOM_draft.csv` + pricing (`tools/price_bom.py`): MPN or candidate, package (footprints UNASSIGNED), rating basis, supplier, dated unit price low/high, extended, availability, alternate, selection status | NOT ORDER-READY |
| `BOM_candidates.csv` | v0.1 conditional BOM (kept as a record) | superseded by the files above |

Budget scenarios: `docs/BUDGET.md`. Nothing has been purchased.
