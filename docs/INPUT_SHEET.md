# Request to the physical team (v0.7)

**Scope (v0.7).** The motor controller is built by another team; what we ask *them* is in
[`CONTROLLER_INTERFACE_REQUEST.md`](CONTROLLER_INTERFACE_REQUEST.md) (bus, connector, ground, DBC, signals). This
page is what we ask the vehicle's physical team. For the telematics delivery only four of the seven items matter;
they are marked **telematics** below. The others served our own controller design, which is deferred: they block
nothing on the telematics path ([`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)).

Documents and photos first. Each item names what it unlocks; the register [`BLOCKERS.md`](BLOCKERS.md) tracks them.
Until an answer arrives the value stays null and everything that depends on it stays blocked or synthetic.

How to send: put files under `docs/reference/vehicle/` or attach them to a GitHub issue in this repository, one
issue per item, so the answer, its author and its date stay together.

Already received: the battery is **48 V nominal, 10 Ah** (team message, 2026-10-16, not datasheet-verified). The
maximum charged voltage, the cut-off voltage, the current limits and the chemistry are not inferred from it.

| Telematics needs it for | Items |
|---|---|
| the unit's input protection (TVS, fuse, DC-DC input range) and the battery-side monitor's range | 1 (the battery's maximum voltage) |
| wheel speed and distance (circumference, magnets), the energy model | 3 |
| who else is on the bus, termination, where to tap in | 5, now asked of the controller team first |
| rule edition: telemetry power, joulemeter position, attempt length (log storage) | 7 |
| nothing (deferred controller development) | 2, 4, 6 |

| # | Item | Send | Unlocks |
|---|---|---|---|
| 1 | **Battery and BMS** (telematics: maximum voltage) | model numbers of the battery and the BMS; a photo of the battery label; both datasheets | every voltage rating of the power stage (MOSFETs, capacitors, TVS, fuse, precharge resistor), the over-voltage trip and its pass criteria, the logic-supply undervoltage lockout; the battery current limit, fuse and bus shunt (B-BAT-V, B-BAT-I, B-OVTRIP) |
| 2 | **Motor** (deferred controller) | model number; a nameplate photo; the datasheet; photos of the phase, hall and temperature connectors | MOSFET and shunt current ratings, the current-sense range, the motor parameters, the hall input circuit, three connectors (B-MOTOR) |
| 3 | **Drivetrain** (telematics) | wheel circumference (or the tyre size, with a sidewall photo); the gear or chain ratio between motor and wheel; whether there is a freewheel; the vehicle mass with driver | vehicle speed from the motor, the top-speed headroom, coasting behaviour, the energy model and the speed-hold policy (B-DRIVETRAIN) |
| 4 | **Controls and safety** (deferred controller) | pedal model and datasheet; the brake and other switch types (normally open or closed); how the emergency stop, dead-man and safety loop are wired and at what voltage; a photo of the dashboard controls | the pedal plausibility check, the safety-loop input, the driver-controls connector (B-PEDAL, B-LOOP, B-NTC) |
| 5 | **Vehicle CAN bus** (telematics; ask the controller team first) | if the vehicle has one: the nodes on it, bit rate, classic or FD, which identifiers the controller may use, where it is terminated. **If no bus exists yet, this is a team design decision**: whether the controller needs one and what else would sit on it | the crystal, CAN in the firmware, the termination jumpers, supervised ECO mode (B-CAN) |
| 6 | **Mechanics and harness** (deferred controller; the telematics unit's mounting and connectors come later) | photos and part numbers of the mating connectors (battery, motor phases, halls, motor temperature, driver controls, CAN); photos and dimensions of where the controller mounts; whether a metal plate can carry the MOSFETs' heat | the board outline, the six connector footprints and the thermal design; the layout cannot start without them (B-HARNESS, B-MECH) |
| 7 | **Event** (telematics) | the event name and the official rule PDF of the edition that applies | discharge time, the purpose-built-controller rule, joulemeter and telemetry power (B-RULES) |

## Not for the physical team (as recorded in v0.6)

* **Primary datasheets** (DRV8353, INA228, STM32G474 documents and the other candidate parts): a documentation
  task, listed in [`reference/datasheets/README.md`](reference/datasheets/README.md) and request D1 of
  [`BLOCKERS.md`](BLOCKERS.md).
* **Team decisions, when the board is closer to ordering**: hand assembly or an assembly service, copper weight
  and fabricator (B-ASSY); who performs and signs energised tests and which bench equipment the team owns
  ([`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md)); where the ECO supervisor runs and the log storage
  (`ICD.md` 9 and 12); the driver display, and the event country and mobile operator for the optional LTE link;
  the telemetry files `telemetry.pdf` and `bk4000tg_kicad.zip` if the existing telemetry board is to be reused.
* **Measurements later**, with a board or the vehicle: a battery-power map near cruise and a coast-down
  (`MATH_SPEC.md` 4.5); wheel-sensor magnet count, radius and air gap; steering lock-to-lock angle (optional).
* **Controller engineering items** decided without the physical team: register settings, the start-up
  parameters, the coasting gate-off dwell (speed hold switched the gates 2752 times in 260 s on the host plant).

## Old item numbers

v0.6 earlier numbering: Q1 -> 1, Q2 -> 2, Q3 -> D1 (documentation), Q4 -> 5, Q5 -> 6, Q6 -> 4, Q7 -> 7, Q8 and
Q9 to Q12 -> team decisions above, Q13 -> controller engineering, Q14 to Q16 -> measurements later; the wheel
circumference of Q15 is now item 3. The detailed v0.3 questionnaire is in
[`archive/PHYSICAL_TEAM_QUESTIONNAIRE.md`](archive/PHYSICAL_TEAM_QUESTIONNAIRE.md).
