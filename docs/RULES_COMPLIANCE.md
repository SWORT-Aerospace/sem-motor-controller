# Rules compliance map (Shell Eco-marathon)

> **v0.5: the 2026 Chapter I text was read.** Source: "Shell Eco-marathon 2026 Official Rules, Chapter I" (title in the PDF metadata and on every page), 49 pages, PDF created 2025-09-02 and modified 2025-09-03, SHA-256 `50c57850c3d8388568509c50e75fee6dd9d34bbd26c139ea5c27e4df10aa9653`. It is a third-party copy in `enseashellecomarathon/Eco-Marathon-Vehicule-hybride-optimise-course-d-endurance` @ `3ae934c`, `shell-eco-marathon-2026-official-rules-chapter-1.pdf`, not compared with the organisers' file (shellecomarathon.com is blocked here). The organisers may have published later amendments; the event's Chapter II and the 2027 Chapter I have not been read. Rows marked **R26** were checked against this text; page numbers are the printed ones. Rows still marked S26/S25/CHK/OFF/NF are unverified as before.

Status codes: **R26** read in the 2026 Ch I copy above · **S26** 2026 Ch I search extract · **S25** earlier edition · **CHK** 2026 inspection checklist item · **OFF** official web page extract · **NF** not found.

## Electrical and data-system rules read in the 2026 text (R26)

| Art. (page) | Text | Consequence for this project |
|---|---|---|
| 57a (p. 30) | "the maximum voltage on board of any vehicle at any point must not exceed 60 Volts max by design" | The battery's maximum charged voltage plus transients must stay under 60 V; the team-reported 48 V nominal (`docs/BATTERY.md`) does not show this. |
| 57b (p. 30) | "only one vehicle battery is allowed"; for Battery Electric vehicles "an accessory battery is not allowed" | The telematics unit, display and sensors run from the propulsion battery. A backup or charger battery on the telematics board (the proposal names a BQ25622E charger IC) is not allowed unless it falls under 57i. |
| 57i (p. 31) | "Only Driver communications (see Article 16), driver display, or ventilation devices are allowed to be powered using built-in batteries. These devices must be unmodified and self-contained." | A driver display may use its own built-in battery only if it is an unmodified, self-contained device. A battery added to power a custom display is not permitted; such a display is powered from the vehicle system and measured. |
| 56d (p. 29) | "All electrical energy used by the vehicle, except for specific systems explicitly exempted (i.e., the horn circuit, systems covered in Article 57i), must be measured by the joulemeter. This includes all propulsion and non-propulsion electrical components." | Telematics, LTE modem, GNSS, sensors and any vehicle-powered display count against the result. Their consumption is an energy term (`docs/ENERGY_METHODS.md`). |
| 56c i (p. 29) | "The joulemeter must be installed between the battery and the vehicle electrical system." | The controller's input meter sees less than the joulemeter: everything else downstream of the joulemeter (telematics, display, sensors) is outside it. |
| 56c ii (p. 29) | "For vehicles with a supercapacitor, an additional joulemeter must be installed between the supercapacitor and the vehicle electrical system" | Open question for the organisers before any hold-up supercapacitor is added to the telematics unit for log flushing. |
| 54b, 54d (pp. 27-28) | results "based on the propulsion energy consumed PLUS the electrical energy consumed by the vehicle as measured by a joulemeter"; Battery Electric results in km/kWh "using a joulemeter supplied by the Organisers"; negative net energy gives no credit | The official energy figure is the joulemeter's; the controller and telematics measurements are for strategy and analysis. |
| 37e (p. 20) | the emergency shutdown "must provide a physical isolation of the propulsion battery from the vehicle electrical system"; "The use of a power controller or other logic systems to drive an isolation device is not permitted." | An emergency stop removes telematics power at once: the local log must survive abrupt power loss (STLG loses at most the open block, `docs/ICD.md` 9). |
| 57g (p. 31) | "All vehicle electrical circuits must be protected against electrical overload." | The telematics supply needs its own fuse or current limit. |
| 57j (p. 31) | "All electrical/electronic enclosures purchased or built by the Teams must be made of transparent material or at least have a transparent cover" | Telematics and controller enclosures: transparent material or cover. |
| 57k (p. 31) | wiring "neat, secured"; "Splices are not allowed"; connections "visible and easily accessible" | Harness and connector choices (procurement line "Connectors and wiring"). |
| 66a (p. 37) | "The motor controller MUST be purpose-built for Shell Eco-marathon"; no modified purchased controllers or purchased evaluation kits; "the text “SEM” must be included in the mask of the PCB etching"; software "developed or integrated for Shell Eco-marathon" | Confirms the controller rows below. A development board (Nucleo) for the telematics unit is not a motor controller; using one in the vehicle is a separate question for the organisers. |
| 16 (p. 12) | "Only handsfree communication devices are allowed, provided both hands of the driver remain on the steering system." | Driver communications only. |
| 37i (p. 21) | dead man's device; an electric switch must be engaged "continuously while driving"; separate from the emergency shutdown unless functionally identical | Matches the dead-man row below. |
| Foreword (p. 1) | "Telemetry kit removed, with teams encouraged to develop their own systems." | The team's own telemetry is expected; no organiser telemetry system in 2026. |

Inconsistency in the text: Article 31d (p. 19) says the horn energy is exempt "see Article 56c:iv", but the horn clause is 56c iii.

| Topic | Rule (as extracted) | Art. | Status | Design response in this project |
|---|---|---|---|---|
| Voltage | "maximum voltage on board of any vehicle at any point must not exceed 60 Volts max by design" | 57a | R26, CHK ("Max 60 V Peak") | EL-1. Validator rule `BUS_RATING_MARGIN` checks against the inverter rating, **not** yet against 60 V. Add a rule-limit check once verified. With a 12S Li-ion pack (50.4 V) the transient margin can be at most ~19 %. |
| One battery, no accessory battery (BEV) | "only one vehicle battery is allowed"; BEV "an accessory battery is not allowed" | 57b | R26 | All electronics (controller logic, companion, modem) are powered from the propulsion battery **downstream of the joulemeter**, so auxiliary power is a measured efficiency term (H6). |
| Lithium capacity, BMS | < 1000 Wh; BMS "tailored to the lithium chemistry"; cell-level protection for self-built packs | 57d | R26 ("The maximum capacity of any Lithium-based battery used is 1,000 Wh", Wh = Ah x nominal V if not rated in Wh) | Battery-side, outside controller scope. The controller limit is ≤ the BMS limit (`BATT_CURRENT_LIMIT`). |
| Fuse | on the positive conductor, ≤ 300 mm from the + terminal; no auto-reclosing devices | 57e | R26 | Vehicle harness; the controller adds its own input protection; coordination analysis in calcs §8. |
| E-stop | must "provide a physical isolation of the propulsion battery"; "air gap … relay or a physical switch"; "use of a power controller or other logic systems to drive an isolation device is not permitted"; relays normally open; internal + external | 37 | R26 | Boundary F: the controller only **senses** the chain (`estop_chain_ok` → DISARMED). Precharge and discharge are needed because every enable is a hard connect. |
| Dead-man | the driver "must directly engage the switch continuously while driving"; separate from the e-stop | 37i | R26 | `driver_present` input → torque 0 immediately (T18). The hardware chain should also remove drive enable (schematic plan). |
| Joulemeter | supplied by the organizers; installed "between the battery and the vehicle electrical system"; results in km/kWh | 56 | R26 | The controller's own energy meter is for strategy and calibration; it is compared against the official joulemeter in validation (VALIDATION_PLAN §5). |
| Horn | automotive, > 85 dBA @ 4 m; not required to be measured | 31, 56c iii | R26 | Not in controller scope. |
| Purpose-built controller | "MUST be purpose-built … Modifications to purchased motor controllers or the use of purchased motor controller evaluation kits are not acceptable"; tips page: kits "and their software are outlawed"; etch "SEM" on the PCB | 66a | R26 (Art. 66a), OFF (tips page) | ADR-0009: own control core, no MCSDK-generated code pending clarification; "SEM" etch in the schematic plan; design documentation = this repository. |
| Drivetrain | one electric storage device; up to two motors | 66 | R26 ("a maximum of one electric storage device, and up to two electric motors") | Single motor assumed. |
| Supercapacitors / capacitor energy | count toward the 60 V cap; separate storage looks disallowed for BEV (inference) | 57a / 66 | S25 + inference | The DC-link is not used as a deliberate energy store; capacitance sized for ripple only. **NF:** no rule on controller input capacitors. |
| Regeneration | no explicit rule; 2025: negative net joulemeter energy gives no credit | n/a | NF / S25 | Deferred (ADR-0007). |
| Driver communications | "Only handsfree communication devices are allowed" | 16 | R26 | No driver-facing comms in the controller. |
| Telemetry | organizers no longer supply the on-board computer (2026); may require an organizer telemetry system | n/a | S26 | Companion computer is the team's data system; cellular monitoring-only (G). |
| Remote control | prohibited in the autonomous chapter (411c); **NF** for the Mileage Challenge | Ch IV | S26 | No remote command path exists by design (SAF-8, ADR-0010). |
| Cruise control / automatic speed control | **NF** | n/a | NF | ECO_ASSIST is driver-selected, driver-cancellable, and requires the dead-man. **Organizer confirmation is needed** that supervisory torque assistance is permitted in the Mileage Challenge. |
| Brakes | two hydraulic systems, one per axle; 20 % incline test | 43 | S26 / S25 | Mechanical, driver-controlled (H). A brake switch is wired to the controller. |
| Attempt format | US 2025: "four (4) consecutive laps in a maximum time of 35 minutes … approximately 25 km/h" | Ch II | S25 | The DP takes `t_max` and a reserve as inputs; values for 2026/2027 are unknown. |
| Data & Telemetry Off-Track Award (Schmid bootcamp) | connect the energy sensors to your onboard computer and IoT platform | n/a | OFF | The companion and logger design supports this; no controller impact. |

## Open rule questions for the organizers
1. Does a vendor motor-control SDK (e.g. ST MCSDK), or vendor HAL drivers, count as "kit software" under Art. 66a? (The text in hand does not decide this; the project does not assume a blanket ban. See `RULES_RECONCILIATION.md`.)
2. Is driver-selectable supervisory torque assistance (no steering, driver-cancellable) permitted in the Mileage Challenge?
3. Is regenerative braking permitted for BEV, and how is it counted?
4. Do controller input/DC-link capacitors fall under any energy-storage restriction?
5. Is the e-stop relay coil inside or outside the joulemeter measurement?
