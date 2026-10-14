# Design review checklist (stage 0 gate)

- [ ] Every UNFROZEN item in ARCHITECTURE_FREEZE §7 has a measured or datasheet-verified value with a reference
- [ ] Max voltage at every node ≤ 60 V by design, including measured overshoot (verify the rule edition in force)
- [ ] MOSFET V_DS, gate-driver VM/VDRAIN and capacitor voltage ratings derated against measured worst case (absolute maximum ≠ operating)
- [ ] Phase RMS, phase peak and battery average currents each used for the right component (conduction/thermal vs pulse vs fuse/connector)
- [ ] Hardware overcurrent trip < current-sense full scale; latency measured; independent of firmware
- [ ] Enable chain: firmware can only disable; e-stop/dead-man/watchdog act without the MCU
- [ ] Precharge resistor pulse energy and the discharge path documented
- [ ] Low-side sampling window ≥ dead time + settling + ADC sample at max duty
- [ ] CSA offset calibration procedure and drift budget
- [ ] INA228 shunt and range for battery current; energy accumulator overflow check for the run length
- [ ] Thermal: transient Zth with the measured current profile; enclosure ambient
- [ ] Creepage/clearance, connector current ratings, fuse coordination with the harness
- [ ] "SEM" etched on the PCB; design documentation for technical inspection
- [ ] Pin allocation re-checked in CubeMX (AF numbers, ADC channel speed, OPAMP/COMP routing) and against errata
- [ ] Test points on every rail, gate and switch node; Kelvin connections for shunts
- [ ] CSIA license decision recorded (if the adapter runs on the vehicle)
