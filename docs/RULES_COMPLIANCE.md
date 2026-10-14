# Rules compliance map (Shell Eco-marathon)

> **Every rule cited here is UNVERIFIED.** No official rules document could be opened (shellecomarathon.com blocked). Text comes from search-engine extracts of the official 2026 Chapter I PDF (`shell-eco-marathon-2026-official-rules-chapter-one-nine-sep.pdf`, dated 2025-09-12 by its URL), earlier editions, 2026 inspection checklists, and the official "5 technical tips" page. The **2027 Chapter I exists and has not been read.** Before any design review, someone must read Articles 16, 31, 37, 43, 53, 56, 57 and 66 of the edition in force, and the event's Chapter II.

Status codes: **S26** 2026 Ch I extract · **S25** earlier edition · **CHK** 2026 inspection checklist item · **OFF** official web page extract · **NF** not found.

| Topic | Rule (as extracted) | Art. | Status | Design response in this project |
|---|---|---|---|---|
| Voltage | "maximum voltage on board of any vehicle at any point must not exceed 60 Volts max by design" | 57a | S26, CHK ("Max 60 V Peak") | EL-1. Validator rule `BUS_RATING_MARGIN` checks against the inverter rating, **not** yet against 60 V. Add a rule-limit check once verified. With a 12S Li-ion pack (50.4 V) the transient margin can be at most ~19 %. |
| One battery, no accessory battery (BEV) | "only one vehicle battery is allowed"; BEV "an accessory battery is not allowed" | 57b | S26 | All electronics (controller logic, companion, modem) are powered from the propulsion battery **downstream of the joulemeter**, so auxiliary power is a measured efficiency term (H6). |
| Lithium capacity, BMS | < 1000 Wh; BMS "tailored to the lithium chemistry"; cell-level protection for self-built packs | 57d | S25 / S26 / CHK | Battery-side, outside controller scope. The controller limit is ≤ the BMS limit (`BATT_CURRENT_LIMIT`). |
| Fuse | on the positive conductor, ≤ 300 mm from the + terminal; no auto-reclosing devices | 57e | S25 / S26 / CHK | Vehicle harness; the controller adds its own input protection; coordination analysis in calcs §8. |
| E-stop | must "provide a physical isolation of the propulsion battery"; "air gap … relay or a physical switch"; "use of a power controller or other logic systems to drive an isolation device is not permitted"; relays normally open; internal + external | 37 | S25 / S26 / CHK | Boundary F: the controller only **senses** the chain (`estop_chain_ok` → DISARMED). Precharge and discharge are needed because every enable is a hard connect. |
| Dead-man | the driver "must directly engage the switch continuously while driving"; separate from the e-stop | 37i | S26 / CHK | `driver_present` input → torque 0 immediately (T18). The hardware chain should also remove drive enable (schematic plan). |
| Joulemeter | supplied by the organizers; installed "between the battery and the vehicle electrical system"; results in km/kWh | 56 | S26 / CHK | The controller's own energy meter is for strategy and calibration; it is compared against the official joulemeter in validation (VALIDATION_PLAN §5). |
| Horn | automotive, > 85 dBA @ 4 m; not required to be measured | 31, 56c iv | S26 | Not in controller scope. |
| Purpose-built controller | "MUST be purpose-built … Modifications to purchased motor controllers or the use of purchased motor controller evaluation kits are not acceptable"; tips page: kits "and their software are outlawed"; etch "SEM" on the PCB | 66a | S25 / CHK / OFF | ADR-0009: own control core, no MCSDK-generated code pending clarification; "SEM" etch in the schematic plan; design documentation = this repository. |
| Drivetrain | one electric storage device; up to two motors | 66 | S25 | Single motor assumed. |
| Supercapacitors / capacitor energy | count toward the 60 V cap; separate storage looks disallowed for BEV (inference) | 57a / 66 | S25 + inference | The DC-link is not used as a deliberate energy store; capacitance sized for ripple only. **NF:** no rule on controller input capacitors. |
| Regeneration | no explicit rule; 2025: negative net joulemeter energy gives no credit | — | NF / S25 | Deferred (ADR-0007). |
| Driver communications | "Only handsfree communication devices are allowed" | 16 | S26 | No driver-facing comms in the controller. |
| Telemetry | organizers no longer supply the on-board computer (2026); may require an organizer telemetry system | — | S26 | Companion computer is the team's data system; cellular monitoring-only (G). |
| Remote control | prohibited in the autonomous chapter (411c); **NF** for the Mileage Challenge | Ch IV | S26 | No remote command path exists by design (SAF-8, ADR-0010). |
| Cruise control / automatic speed control | **NF** | — | NF | ECO_ASSIST is driver-selected, driver-cancellable, and requires the dead-man. **Organizer confirmation is needed** that supervisory torque assistance is permitted in the Mileage Challenge. |
| Brakes | two hydraulic systems, one per axle; 20 % incline test | 43 | S26 / S25 | Mechanical, driver-controlled (H). A brake switch is wired to the controller. |
| Attempt format | US 2025: "four (4) consecutive laps in a maximum time of 35 minutes … approximately 25 km/h" | Ch II | S25 | The DP takes `t_max` and a reserve as inputs; values for 2026/2027 are unknown. |
| Data & Telemetry Off-Track Award (Schmid bootcamp) | connect the energy sensors to your onboard computer and IoT platform | — | OFF | The companion and logger design supports this; no controller impact. |

## Open rule questions for the organizers
1. Does a vendor motor-control SDK (e.g. ST MCSDK), or vendor HAL drivers, count as "kit software" under Art. 66a?
2. Is driver-selectable supervisory torque assistance (no steering, driver-cancellable) permitted in the Mileage Challenge?
3. Is regenerative braking permitted for BEV, and how is it counted?
4. Do controller input/DC-link capacitors fall under any energy-storage restriction?
5. Is the e-stop relay coil inside or outside the joulemeter measurement?
