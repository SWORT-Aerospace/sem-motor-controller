# Run sheet (copy one per run into `records/`, fill in during the run)

A run sheet turns a protocol into a result. Without one, the run is not a result. Copy this file to
`records/<EXP-id>_<date>_<run>.md`, fill every field, and keep it with the log, the database and the review. Do not
edit a filled sheet after the analysis: corrections are added below with their date.

| Field | Value |
|---|---|
| Protocol and version | EXP-0? (commit of this folder) |
| Data class | BENCH / HIL / VEHICLE |
| Date, place, people | |
| Unit: board, firmware commit, image SHA-256 | |
| Storage: internal flash or NOR | |
| Vehicle team present and operating the vehicle (vehicle runs) | yes / no / not a vehicle run |
| Parameters used and their source (circumference, ppr, gear ratio, freewheel, coast-down) | |
| Independent ground truth: instrument, settings, calibration date | |
| What was done and when (disturbance, times by the ground-truth clock) | |
| Environment: temperature, wind, track surface, slope | |
| Log file, database, review output (paths and SHA-256) | |
| Expected signature (from the protocol) | |
| Observed result (from the review, with receipt times) | |
| Verdict: SUPPORTS / FALSIFIES / INAPPLICABLE, with the reason | |
| Deviations from the protocol | |
| Boundary check: nothing was sent to the motor controller; the unit's CAN interface was in bus-monitoring mode | |
| Signatures | |

## Corrections

(date, who, what, why)
