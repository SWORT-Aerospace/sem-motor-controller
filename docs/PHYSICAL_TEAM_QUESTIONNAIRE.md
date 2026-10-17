# Physical-team questionnaire (short, v0.3)

Please answer what you can, with units and the source (datasheet with page, measurement, or team decision). **"Unknown" is a valid answer.** Priority 1 blocks the power stage and most of the budget; priority 2 fixes the bus and the crystal.

## Priority 1: motor identity and battery / BMS limits
1. **Motor:** make, model and datasheet. Brushless (PMSM/BLDC) with halls, or brushed?
2. **Motor currents:** peak phase current and for how long; continuous current.
3. **Motor constants:** pole pairs; phase resistance; inductance; back-EMF constant (with its definition); maximum speed; winding temperature sensor type.
4. **Battery:** chemistry and series cell count; minimum, nominal and fully charged voltage.
5. **BMS:** continuous and peak discharge current; short-circuit current; does it publish on CAN (which messages and rates)?
6. **Where are** the joulemeter, the e-stop isolation and the main fuse relative to the motor controller and the telematics unit? Which battery feeds the electronics?

## Priority 2: the actual telemetry interface
7. **Is the telematics unit built**, or only drawn (v0.1, 14/10/2026)? Which CAN transceiver does it use, and does the STM32U575 run its FDCAN in classic mode?
8. **Bus:** CAN 2.0B or CAN FD; bit rate and sample point; 11 or 29-bit identifiers.
9. **Identifier map**, or a DBC, for the BMS, wheel-speed and driver-input nodes. Which 64-identifier block can the motor controller use?
10. **Wiring:** where the two 120 Ω terminations are; connector type and pinout; stub lengths; do supply and ground run in the harness?
11. **Supervision:** should the telematics unit run the supervisor task (ECO torque requests at 50 Hz), or does the vehicle drive in MANUAL only for now?
12. **Logging:** is the microSD fitted? Which signals must be logged, and at what rate? Is the LTE link one-way (vehicle → pit)?
13. **Driver controls:** throttle sensor and output range; brake switch contact; dead-man contacts and safety-loop voltage; which switches exist (arm, ECO/MANUAL, cancel, fault reset)?

## Priority 3: available equipment
14. Do you have:
    * a current-limited bench supply (maximum V and A; **can it sink current?**);
    * an oscilloscope (bandwidth and channels);
    * a **differential probe**;
    * a **current probe**;
    * a DMM;
    * an electronic load or power resistors;
    * an ST-LINK;
    * a USB-CAN adapter;
    * reflow or a hot plate;
    * a microscope?
15. Who performs and signs bench measurements, and what is the lab's procedure for energized tests? Is a spare motor (or a small BLDC) available for the first runs?

## Files to attach directly
* `bk4000tg_kicad.zip` and `telemetry.pdf`: supplied in another tool, never received here.
* The 2027 Chapter I and the event's Chapter II rule PDFs.
* Datasheet PDFs: STM32G474 (DS12288), RM0440, DRV8353, INA228, TJA1051, LM5164.
