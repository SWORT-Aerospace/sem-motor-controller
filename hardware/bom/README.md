# BOM files

Nothing has been purchased, and no line has a dated supplier quote.

| File | What it is | Maintained | Status |
|---|---|---|---|
| `BOM_draft.csv` | generated from the schematic data (`tools/gen_kicad_schematic.py`), grouped by value and part | generated | DRAFT; ratings UNRESOLVED where marked |
| `pricing.yaml` | price evidence per BOM line: manufacturer and datasheet of the candidate, evidence class (snippet / representative / allowance), source, retrieval date, availability, unchecked alternates; project items, equipment, spares and the revision allowance | by hand | snapshots and allowances, not quotes |
| `BOM_priced.csv` | `BOM_draft.csv` plus pricing (`tools/price_bom.py`): manufacturer, MPN or candidate, quantity, package (footprints UNASSIGNED), functional block, rating basis, datasheet and its register status, supplier, dated unit price low/high, extended, availability, selection status, unchecked alternate, evidence | generated | NOT ORDER-READY |
| `procurement.yaml` | the project's procurement lines in nine categories (controller, telemetry, shared wiring and power, fabrication and assembly, shipping and tax, spares and revision, development equipment, recurring connectivity, contingency) and the build scenarios evaluated against the $500 and $1,000 budget | by hand | estimates and TBD; nothing ordered |
| `BOM_candidates.csv` | v0.1 conditional BOM (kept as a record) | by hand | superseded by the files above |

## Reading the columns

* **Selection status.** No line is "Selected" (requirements and compatibility checked against a primary datasheet): the lines are UNRESOLVED (a rating waits for the battery, motor or harness), CANDIDATE (a part named, its datasheet row still open in [`../selection/DATASHEET_REGISTER.md`](../selection/DATASHEET_REGISTER.md)), design values and typical values to verify, or bench-only items such as test points.
* **Alternates are leads, not approved substitutes.** No alternate has been checked against a primary document. One needs more than a part swap: the STM32G474VCT6 (256 KB flash) would hold the image, but the current linker layout puts the calibration page at 0x0807F000, beyond its flash, and its other differences are unchecked (`firmware/platform/stm32g4/README.md`, memory map).
* **No double counting.** Parts inside the telematics PCB assembly line are listed with `in_assembly` and not counted again; the assembly-service line is an alternative to the stencil and consumables lines, not an addition; the revision line is optional.
* **Protection is not a budget variable.** Every build in `procurement.yaml` contains every controller line; the generator refuses a build that leaves one out.

## Regenerating

```
python3 tools/price_bom.py          # BOM_priced.csv, docs/BUDGET.md, docs/generated/budget.json
python3 tools/gen_procurement.py    # docs/PROCUREMENT.md (the v0.6 combined table)
```

Budget scenarios of the controller: [`../../docs/BUDGET.md`](../../docs/BUDGET.md). All project lines and the builds: [`../../docs/PROCUREMENT.md`](../../docs/PROCUREMENT.md).
