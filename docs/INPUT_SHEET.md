# Questionnaire for the physical team (v0.6)

Answer in this order: documents and photos first (part A), then team decisions (part B). Measurements (part C)
come later and need a board or the vehicle. Each question names what its answer unlocks; the register
[`BLOCKERS.md`](BLOCKERS.md) tracks them. Until an answer arrives the value stays null in the configuration and
everything that depends on it stays blocked or synthetic.

How to send: put files under `docs/reference/` (datasheets in `docs/reference/datasheets/`, photos and vehicle
files in `docs/reference/vehicle/`) or attach them to a GitHub issue in this repository, one issue per question,
so the answer, its author and its date stay together.

Already received: the battery is **48 V nominal, 10 Ah** (team message, 2026-10-16, not datasheet-verified). The
maximum charged voltage, the cut-off voltage, the current limits and the chemistry are not inferred from it.

## A. Documents and photos (send first)

| # | Ask | Send | Unlocks |
|---|---|---|---|
| Q1 | **Battery and BMS** | model numbers of the battery and the BMS; a photo of the battery label; both datasheets | every voltage rating of the power stage (MOSFETs, capacitors, TVS, fuse, precharge), the over-voltage trip and the logic-supply undervoltage lockout; the battery current limit, fuse and bus shunt (B-BAT-V, B-BAT-I) |
| Q2 | **Motor** | model number; a nameplate photo; the datasheet; photos of the phase, hall and temperature connectors | MOSFET and shunt current ratings, the current-sense gain, the motor parameters of the controller, the hall input circuit, three connectors (B-MOTOR) |
| Q3 | **Datasheet PDFs** (this environment cannot download them) | the files listed in [`hardware/selection/DATASHEET_REGISTER.md`](../hardware/selection/DATASHEET_REGISTER.md): DRV8353 (SLVSDY6), INA228, STM32G474 DS12288, RM0440, ES0430, MAX6369, TJA1051, LM5164, TLV755P, TLV7041, TL431; or ask the environment owner to allow ti.com, st.com, nxp.com, analog.com and onsemi.com | the gate-driver pinout and firmware (the motor cannot be driven without it), the battery-side meter and the precharge, footprints, the timing values now marked as assumptions (B-DRV, B-INA, B-ST-DOCS, B-PART-DOCS) |
| Q4 | **Vehicle CAN bus** | a description: the nodes on the bus, bit rate, classic CAN or CAN FD, the identifier block for the motor controller (64 consecutive identifiers), where the bus is terminated | the crystal choice (16 MHz proposed), CAN on in the firmware, the termination jumpers, supervised ECO mode (B-CAN) |
| Q5 | **Connectors and mounting** | photos of the mating connectors with part numbers (battery, motor phases, halls, motor temperature, driver controls, CAN); photos and dimensions of where the controller mounts; whether a metal plate can carry the MOSFETs' heat | the board outline, connector footprints and the thermal design: the layout cannot start without them (B-HARNESS, B-MECH) |
| Q6 | **Driver controls and sensors** | pedal model and datasheet (one or two tracks, output range); the brake switch type (normally open or normally closed) and the other switches; the safety-loop voltage and how the emergency stop and dead-man are wired; the power-stage NTC the team wants | the pedal calibration and plausibility check, the safety-loop optocoupler resistor, the temperature conversion (B-PEDAL, B-LOOP, B-NTC) |
| Q7 | **Event and rules** | the event name and the official rule PDF of the edition that applies | discharge requirements, the purpose-built-controller rule, joulemeter and telemetry power (B-RULES) |
| Q8 | **Telemetry files** | `telemetry.pdf` and `bk4000tg_kicad.zip` (referenced, not received) | which telemetry parts the existing board already has; how it is powered without an accessory battery (Article 57b) |

## B. Team decisions

| # | Decide | Unlocks |
|---|---|---|
| Q9 | Hand assembly or an assembly service; outer copper weight; the PCB fabricator | footprint variants, stencil, layout rules, the fabrication budget line (B-ASSY) |
| Q10 | Where the ECO supervisor runs (the telematics MCU, another computer, or manual only) and the log storage (8 MB lasts 14.6 min at the full rate; microSD, compression or decimation) | the supervisor task budget and the log plan (`ICD.md` 9 and 12) |
| Q11 | Who performs and signs energised tests; which bench equipment the team owns (current-limited supply, oscilloscope and differential probe, current probe, ST-LINK, USB-CAN) | acceptance stages S2 to S8 ([`BENCH_ACCEPTANCE.md`](BENCH_ACCEPTANCE.md)); the equipment lines of the budget |
| Q12 | The driver display (type and power) and the event country and mobile operator | the display line, the LTE modem variant and SIM |
| Q13 | A minimum gate-off dwell or hysteresis for coasting (speed hold switched the gates 2752 times in 260 s on the host plant) | the first powered test of the speed-hold policy |

## C. Measurements (later, need a board or the vehicle)

| # | Measure | When | Unlocks |
|---|---|---|---|
| Q14 | Battery-power map near cruise (speed x torque grid, power at the bus shunt) and a coast-down (speed against time on a flat road) | acceptance S8 / vehicle | the energy-strategy decision (`MATH_SPEC.md` 4.5) |
| Q15 | Wheel sensors: maximum speed, wheel circumference, which wheels, magnet count and radius, air gap, and the field window of one magnet pass | vehicle | the wheel-speed sensor line and the wheel relationships of the diagnosis |
| Q16 | Steering geometry (optional): lock-to-lock angle at the sensor position | vehicle | the steering-angle sensor |

## Old item numbers

v0.5 items map to: 1 -> Q2, 2 -> Q1, 3 -> Q14, 4 -> Q7, 5 -> Q4, 6 -> Q8, 7 -> Q6, 8 -> Q10, 9 -> Q10, 10 -> Q15,
11 -> Q5, 12 -> Q13, 13 -> Q11, 14 -> Q3, 15 -> Q9 and `BLOCKERS.md` B-QUOTE, 16 -> Q12, 17 -> Q12, 18 -> Q8,
19 -> Q16. The detailed v0.3 questionnaire is in [`archive/PHYSICAL_TEAM_QUESTIONNAIRE.md`](archive/PHYSICAL_TEAM_QUESTIONNAIRE.md).
