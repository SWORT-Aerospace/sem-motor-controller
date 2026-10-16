# Inputs needed from the team (v0.4, prioritised)

Each item unblocks named work. Until it arrives the value stays null in the configuration and every dependent result stays synthetic. Add files under `docs/reference/` (datasheets in `docs/reference/datasheets/`, vehicle files in `docs/reference/vehicle/`) or attach them to a GitHub issue in this repository; one issue per item keeps the answer, its author and its date together. The longer v0.3 questionnaire (`PHYSICAL_TEAM_QUESTIONNAIRE.md`) remains the detailed reference.

| # | Input | Unblocks | From |
|---|---|---|---|
| 1 | **Motor**: datasheet or type (sinusoidal PMSM or trapezoidal BLDC), pole pairs, phase resistance, Ld/Lq, flux linkage or Kt, continuous and peak current, Hall placement and supply, temperature sensor | FOC vs six-step (`METHOD_SELECTION.md` 3), current and voltage ratings, MOSFETs, shunts, dead time, PWM frequency, every power-stage BOM line | vehicle team |
| 2 | **Battery and BMS**: chemistry, series cells, maximum voltage, continuous and peak discharge current, connector | voltage ratings, fuse, TVS, precharge, bulk capacitors, battery current limit | vehicle team |
| 3 | **Battery-power map near cruise** (bench: speed × torque grid, power at the bus shunt) and a **coast-down** (speed vs time, flat road) | the energy-strategy decision: pulse-and-coast only if battery power is non-convex in torque (`MATH_SPEC.md` 4.5); DP and policy parameters | controls lead with the vehicle team, at bench stage 6 |
| 4 | **Event rules**: Chapter I and the event's Chapter II (PDFs): time limit, laps, stops, energy meter | DP constraints, rules compliance | team lead |
| 5 | **Vehicle CAN bus**: CAN 2.0B or FD, bit rate and sample point, the 64-identifier block for the controller, other traffic, termination positions | clock tree, DBC base, bus-load check (`ICD.md` 2) | vehicle team, telematics engineer |
| 6 | **`telemetry.pdf` and `bk4000tg_kicad.zip`** (referenced, not received) | review of the existing telemetry design and prior board | whoever holds them |
| 7 | **Driver controls**: throttle sensor type and tracks, brake switch NO/NC, dead-man contacts, safety-loop voltage, which switches exist | input circuits, HW_PERMIT optocoupler, wired authority (`ICD.md` 6) | vehicle team |
| 8 | **Supervisor placement**: the STM32U575 measurements of `ICD.md` 12 (task jitter under logging and LTE, CAN RX at 466 frames/s, flash bandwidth, RAM), or another computer, or manual only | ECO operation | telematics engineer |
| 9 | **Log storage plan**: 8 MB lasts 14.6 min at the full rate; microSD, compression or decimation | `ICD.md` 9 | telematics engineer |
| 10 | **Wheel sensors**: pulses per revolution, channel assignment, wheel circumference | wheel speed, CSIA wheel relationships | vehicle team |
| 11 | **Connectors and harness**: types and pinouts for battery, phases, driver controls, halls, CAN | `ICD.md` 11, BOM connector lines | vehicle team |
| 12 | **Gate-off coast behaviour**: a minimum gate-off dwell or policy hysteresis (speed hold switched the gates 2752 times in 260 s on the host plant) | first powered test | controls lead, decision |
| 13 | **Bench and people**: current-limited supply, oscilloscope with differential probe, current probe, ST-LINK, USB-CAN; who performs and signs energised tests | bring-up stages 2 to 7 (`hardware/bringup/BENCH_BRINGUP_CHECKLIST.md`) | team lead |
| 14 | **Datasheets** of the candidate parts: STM32G474 DS12288 and RM0440, DRV8353, INA228, TJA1051, LM5164, TLV755P, MAX6369 | pinout verification (`hardware/selection/PINOUT_VERIFICATION.md`), timing constants marked [R] | anyone with access |
| 15 | **Budget inputs**: a live PCB quote for the board size and copper weight, distributor quotes, an inventory of owned passives and equipment | closing the price spread (`hardware/bom/README.md`) | team lead |
