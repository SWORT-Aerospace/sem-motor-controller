# Bench bring-up checklist (draft, for the vehicle team)

**Precondition: this checklist applies to a board built from a REVIEWED, non-draft schematic and layout.** No board exists yet. The draft schematic is not fabrication-ready (rating-dependent parts UNRESOLVED, pinouts UNVERIFIED).

Energized steps are performed only by qualified team members, under their lab's safety procedure, with a second person present. Nothing in this repository performs or automates them. Record every measurement in `bench/records/<board-serial>/<step>.md`, with instrument, date, operator and photos. A step passes only on the recorded evidence.

Stage numbers refer to `docs/VALIDATION_PLAN.md`.

## Stage 1: unpowered (no supply connected)
- [ ] 1.1 Visual and microscope inspection: solder bridges on QFN/LQFP; polarity of electrolytics, TVS, LEDs; MOSFET orientation.
- [ ] 1.2 Resistance VBAT_PROT–PGND, VDC–PGND, +5V–GND, +3V3–GND: no short. Record the values; the DC link reads as charging capacitance.
- [ ] 1.3 Each gate to source: R_GS ≈ driver pull-down value (expected from DS: open); no gate short.
- [ ] 1.4 Shunt resistances, 4-wire (Kelvin), against the BOM value.
- [ ] 1.5 PGND–GND star point: continuity only at the net tie.
- [ ] 1.6 Protection fuse fitted and of the selected rating.

## Stage 2: logic only (bus NOT connected, power stage unpowered)
Supply: current-limited bench supply into VBAT_PROT at a voltage above the buck's UVLO, **limit 100 mA**. If the board allows it, the gate-driver VM is not connected at this stage; otherwise the bridge is depopulated or VDC is isolated by the precharge bypass being open (default).
- [ ] 2.1 Ramp the supply slowly. Input current at idle: record it; it feeds the H6 auxiliary-energy budget.
- [ ] 2.2 +5V, +3V3, +3V3A within tolerance; ripple on +3V3A (scope, 20 MHz BW).
- [ ] 2.3 SWD connect; read the MCU ID. Flash the bring-up firmware. **Needed and not yet written: STM32G4 platform layer** (`firmware/platform/stm32g4/README.md`).
- [ ] 2.4 Clock: HSE 8 MHz running; FDCAN loopback mode passes.
- [ ] 2.5 Calibration blob loads. A **hardware-mode** blob validated by `tools/config_tool.py --mode hw` is required; the synthetic blob must be refused (expect FAULT_LATCHED(CONFIG_INVALID)).
- [ ] 2.6 Startup states with the MCU held in reset (NRST low): DRV ENABLE low, INHx/INLx low, PRECHG_EN low (measure each).
- [ ] 2.7 HW_PERMIT: safety-loop input de-energised → low; energised (loop voltage through R_LED) → high. Watchdog: stop kicking WDI → WDO low → HW_PERMIT low, MCU reset. Record the timeout.
- [ ] 2.8 Driver inputs: each switch, both throttle tracks (open wire reads 0, implausible), brake polarity.
- [ ] 2.9 CAN: connect a USB-CAN adapter at 500 kbit/s with termination as planned. `ctrl_status` and `ctrl_identity` decode with `host/logger`. Frames fall within 0x300–0x33F. Bus load as predicted (`docs/generated/bus_load.md`).
- [ ] 2.10 INA228: I²C ID read; VBUS reading against a DMM.

## Stage 3: gates, power stage disabled from the bus
Gate driver supplied (VM from the current-limited supply at a low voltage within ROC). Bridge drains **not** connected to a bus capable of delivering current, or MOSFETs not fitted.
- [ ] 3.1 DRV SPI: read the status registers; write the configuration (IDRIVE, dead time, OCP mode = latched shutdown, CSA gain); read back.
- [ ] 3.2 PWM at 20 kHz, 10 % duty, with outputs enabled. Scope: GHx/GLx complementary; **measure the dead time at the gate**, which must be ≥ the configured value.
- [ ] 3.3 Break latency: pull nFAULT (or the BKIN pin) low. Record the time from the edge to all gates low. Repeat for BKIN2 (OV comparator input forced). Confirm MOE stays cleared until firmware re-arms.
- [ ] 3.4 ENABLE path: open the safety loop while PWM runs; all gates low. Record the latency.
- [ ] 3.5 CSA zero-current offsets: driver auto-calibration plus the MCU zero sample. Record per phase; compare with the error budget.

## Stage 4: first energized switching (low voltage, current-limited)
Supply ≤ the lowest planned bus voltage, **current limit ≤ 1 A**, resistive-inductive dummy load (no motor). Precharge test first.
- [ ] 4.1 Precharge: link voltage rises through R_pre. Firmware closes the bypass only above 0.95·V_BAT. Record the time and the inrush.
- [ ] 4.2 Double-pulse test on one leg (low current): switch-node overshoot and ringing. **This sets `inverter.transient_margin_fraction` and the measured V_DS margin.**
- [ ] 4.3 Current-sample settling: step the load current and record the CSA output settling after the low-side turn-on. **This sets `inverter.current_sample_settle_s`**; validator rule 39 then checks `voltage_limit_fraction`.
- [ ] 4.4 Hardware over-current trip: raise the current limit stepwise to the planned trip. Record the trip current and latency (VDS OCP and/or comparator).
- [ ] 4.5 Phase-current gain calibration against a reference meter. Record the residual gain error per phase.

## Stage 5: motor on a stand (wheel free, current limit low)
- [ ] 5.1 Hall table and offset (`motor.hall_code_to_sector`, `motor.hall_angle_offset_rad`): turn the rotor by hand and log the codes; then a low-current alignment.
- [ ] 5.2 Measure Rs, Ld/Lq and λ (method in VALIDATION_PLAN stage 5). Write `config/vehicle.<name>.yaml` with `provenance: bench_measured`; it must validate in hw mode.
- [ ] 5.3 Current-loop step response at low current.
- [ ] 5.4 Fault injection repeated from the host list: hall disconnect, phase-sense loss, CAN unplug, brake, dead-man, e-stop.

## Exit to stage 6 (loaded thermal and efficiency)
Only with stages 1–5 passed and recorded, the review checklist signed, and the hazard and latency analysis available for supervisory timing.
