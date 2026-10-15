# Vehicle-team input sheet (one page)

Please fill in and return. Every item **blocks** something specific (right column). Give units and the source of each answer: datasheet with page, measurement with the instrument, or a team decision. "Unknown" is a valid answer.

| # | Group | Needed (units) | Unblocks |
|---|---|---|---|
| M1 | **Motor** | Make, model, datasheet; type (PMSM sinusoidal / BLDC trapezoidal / brushed) | architecture path (ADR-0003); everything below |
| M2 | Motor | Peak phase current (A) and allowed duration (s); continuous current (A rms) | MOSFETs, shunts, CSA gain, heatsink, DC-link capacitors, fuse, budget |
| M3 | Motor | Pole pairs; line-to-line R (Ω, at °C); line-to-line L (H); back-EMF constant (V_LL peak per rad/s, or V/krpm with definition) | current-loop gains; speed limits; validator rules |
| M4 | Motor | Max speed (rpm); winding temperature limit (°C) and sensor type (NTC/PTC/KTY/none) | protection limits; temperature input bias |
| M5 | Motor | Hall sensors: supply voltage, output type (open-collector / push-pull), connector pinout | hall input stage; jumper setting |
| B1 | **Battery / BMS** | Chemistry; series cells; min / nominal / max-charged voltage (V) | V_DS ratings (≥ 1.5 × V_max), OV trip, buck UVLO, every 100 V-class choice |
| B2 | Battery / BMS | BMS continuous and peak discharge current (A, s); short-circuit current (A) | battery current limit; fuse breaking capacity |
| B3 | Battery / BMS | Where the joulemeter and the vehicle e-stop and fuse sit relative to the controller connector | precharge location; energy accounting |
| D1 | **Drivetrain** | Gear ratio; loaded wheel circumference (m); freewheel or clutch (yes/no) | speed scaling; coast model; optimiser |
| D2 | Drivetrain | Vehicle mass with driver (kg); category (Prototype / Urban Concept) | optimiser; stops; torque needs |
| D3 | Drivetrain | Is a step drop in motor torque acceptable for the chain/belt (backlash, shock)? | control contract L2 (hard ceilings step down) |
| C1 | **Driver controls** | Throttle: sensor type, supply, output range (V), one or two tracks | throttle input scaling and plausibility |
| C2 | Driver controls | Brake switch contact (NO/NC); dead-man switch: number of contacts; safety-loop voltage (V) | input polarity; opto LED resistor; HW_PERMIT |
| C3 | Driver controls | Arm, eco/manual mode, cancel and fault-reset switches: available or to be added? | wired driver authority (ADR-0010) |
| H1 | **Harness / CAN** | Bus topology: where the two 120 Ω terminations are; connector type; where the controller taps in, and its stub length; cable | termination jumpers; connector selection |
| H2 | Harness / CAN | Reserve 0x300–0x33F (CHUDS class 3) for the motor controller, or move to CHUDS framing? Should the controller obey CHUDS Emergency STOP? | `docs/CAN_INTEGRATION.md` §5 |
| H3 | Harness / CAN | Who runs the supervisor (companion) software: the VCU or a separate computer? | supervisor deployment |
| H4 | Harness / CAN | Please send `bk4000tg_kicad.zip` and `telemetry.pdf`. They were not available here: not in the uploads, the attachments or Drive. | prior-board review; telemetry transport |
| R1 | **Event rules** | Event and year; 2027 Chapter I and the event's Chapter II (PDFs); attempt format (laps, time limit, stops) | rules map; optimiser constraints |
| R2 | Event rules | Organiser answers to `docs/RULES_RECONCILIATION.md` §3 (kit components, HAL/LL, SDK, bench boards, precharge bypass) | platform-layer approach; compliance |
| T1 | **Test equipment** | Available: current-limited bench supply (V/A max), oscilloscope (BW, channels), **differential probe**, current probe, DMM, electronic load or power resistors, ST-LINK, USB-CAN adapter, reflow or hot plate, microscope | bring-up plan; the "equipment" line in the budget |
| T2 | Test equipment | Who performs and signs bench measurements; the lab's safety procedure for energized tests | validation stages 2–7 |
| T3 | Test equipment | A spare motor (or a small BLDC) for the first current-limited bench runs: yes / no | shortest path to the bench demo |

**Most urgent: M1, M2, B1, B2, T1.** They fix the power stage, the board copper and heatsink, most of the budget spread, and the bring-up plan.
