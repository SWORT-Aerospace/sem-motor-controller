# Bench bring-up checklist (draft, for the vehicle team): SUPERSEDED

> **Superseded by [`BENCH_ACCEPTANCE.md`](../BENCH_ACCEPTANCE.md) (v0.6),** generated from `hardware/acceptance/procedures.yaml` with sourced limits, stop conditions, record templates and a record checker. Kept as the record of v0.2 to v0.5; its safety rules carried over.

**Precondition: this checklist applies to a board built from a REVIEWED, non-draft schematic and layout.** No board exists yet. The draft schematic is not fabrication-ready (rating-dependent parts UNRESOLVED, pinouts UNVERIFIED).

Energized steps are performed only by qualified team members, under their lab's safety procedure, with a second person present. Nothing in this repository performs or automates them. Record every measurement in `bench/records/<board-serial>/<step>.md`, with instrument, date, operator and photos. A step passes only on the recorded evidence.

Stage numbers refer to `docs/VALIDATION_PLAN.md`.

## Current and energy limits: specify each one, verify each one (v0.3)
**A bench-supply current limit bounds only the battery-input (DC) current. It does not bound the phase current.** At low speed the motor's phase voltage is small, so the bridge can circulate a phase current many times larger than the supply current at the same power. The DC-link capacitors can also deliver a short current pulse far above the supply limit. Every energized stage therefore states **both** limits in its header, and records both:

| Quantity | Bounded by | Verified by |
|---|---|---|
| Battery-input current (DC) | bench-supply CC limit; firmware `limits.battery_current_limit_A` | supply readout, INA228 reading, DMM in series |
| Phase current | firmware `limits.max_phase_current_A` (current reference and loop); hardware over-current trip (VDS OCP and/or comparator); the dummy-load impedance at stage 4 | **current probe on a phase lead** and `ctrl_currents`; never inferred from the supply reading |
| Command-ceiling compliance | the controller's L2 ceiling (host-tested, `docs/CONTROL_CONTRACT.md`) | `ctrl_cmd_trace` accepted torque against the ceiling; a command bound is not a current measurement |

**DC-link stored energy.** E = ½·C·V². Example only (C and V are not selected): 470 µF at 48 V stores 0.54 J, and a short across the link is limited only by ESR and wiring (hundreds of amperes for microseconds). Before any touch or probe change: supply off, then measure V_DC with a DMM and wait for it to fall below 5 V. An open precharge bypass does **not** discharge the link. The design must include a bleeder or a documented discharge procedure; record its time constant at stage 4.

**Regenerative overvoltage, with regeneration disabled.** Firmware regeneration is disabled (ADR-0007), but the MOSFET body diodes still rectify the motor's back-EMF into the DC link whenever the line-to-line peak back-EMF exceeds V_DC. A bench supply usually cannot sink current, so the link voltage rises. Rectification starts at about ω_m = V_DC / (√3·p·λ) (p pole pairs, λ peak phase flux linkage; both unknown until the motor is identified). Therefore:
* never spin the rotor (by hand, by the stand or by coasting) above that speed with the board connected;
* set and test the hardware OV trip (BKIN2) at stage 3, knowing that it stops switching but **cannot stop body-diode rectification**;
* at stage 5 use a supply that can sink current, or a clamp or brake resistor sized for the stored rotor energy, before running at speed.

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
- [ ] 2.4 Clock: HSE running at the **selected** frequency (not selected yet: `hardware/timing/clock_tree_alternatives.md`); FDCAN loopback mode passes.
- [ ] 2.5 Calibration blob loads. A **hardware-mode** blob validated by `tools/config_tool.py --mode hw` is required; the synthetic blob must be refused (expect FAULT_LATCHED(CONFIG_INVALID)).
- [ ] 2.6 Startup states with the MCU held in reset (NRST low): DRV ENABLE low, INHx/INLx low, PRECHG_EN low (measure each).
- [ ] 2.7 HW_PERMIT: safety-loop input de-energised → low; energised (loop voltage through R_LED) → high. Watchdog: stop kicking WDI → WDO low → HW_PERMIT low, MCU reset. Record the timeout.
- [ ] 2.8 Driver inputs: each switch, both throttle tracks (open wire reads 0, implausible), brake polarity.
- [ ] 2.9 CAN: connect a USB-CAN adapter at the **vehicle bus's** bit rate (unknown; telematics proposal: CAN 2.0B) with termination as planned. `ctrl_status` and `ctrl_identity` decode with `host/logger` or the generated DBC. Frames fall within `can_id_base` … `can_id_base + 0x3F`. Bus load as predicted for that bus.
- [ ] 2.10 INA228: I²C ID read; VBUS reading against a DMM.

## Stage 3: gates, power stage disabled from the bus
Gate driver supplied (VM from the current-limited supply at a low voltage within ROC). Bridge drains **not** connected to a bus capable of delivering current, or MOSFETs not fitted.
- [ ] 3.1 DRV SPI: read the status registers; write the configuration (IDRIVE, dead time, OCP mode = latched shutdown, CSA gain); read back.
- [ ] 3.2 PWM at 20 kHz, 10 % duty, with outputs enabled. Scope: GHx/GLx complementary; **measure the dead time at the gate**, which must be ≥ the configured value.
- [ ] 3.3 Break latency: pull nFAULT (or the BKIN pin) low. Record the time from the edge to all gates low. Repeat for BKIN2 (OV comparator input forced). Confirm MOE stays cleared until firmware re-arms.
- [ ] 3.4 ENABLE path: open the safety loop while PWM runs; all gates low. Record the latency.
- [ ] 3.5 CSA zero-current offsets: driver auto-calibration plus the MCU zero sample. Record per phase; compare with the error budget.

## Stage 4: first energized switching (low voltage, current-limited)
Supply ≤ the lowest planned bus voltage. **Battery-input limit: supply CC ≤ 1 A. Phase-current limit: firmware `max_phase_current_A` ≤ the dummy load's rating, hardware trip set just above it, both recorded and checked with a current probe.** Resistive-inductive dummy load (no motor). Precharge test first; record the link discharge time.
- [ ] 4.1 Precharge: link voltage rises through R_pre. Firmware closes the bypass only above 0.95·V_BAT. Record the time and the inrush.
- [ ] 4.2 Double-pulse test on one leg (low current): switch-node overshoot and ringing. **This sets `inverter.transient_margin_fraction` and the measured V_DS margin.**
- [ ] 4.3 Current-sample settling: step the load current and record the CSA output settling after the low-side turn-on. **This sets `inverter.current_sample_settle_s`**; validator rule 39 then checks `voltage_limit_fraction`.
- [ ] 4.4 Hardware over-current trip: raise the current limit stepwise to the planned trip. Record the trip current and latency (VDS OCP and/or comparator).
- [ ] 4.5 Phase-current gain calibration against a reference meter. Record the residual gain error per phase.

## Stage 5: motor on a stand (wheel free, both current limits low)
**Battery-input limit: supply CC (value per the team's procedure). Phase-current limit: firmware `max_phase_current_A` at a small fraction of the motor's continuous rating (rating unknown) and the hardware trip, verified with a current probe on a phase lead.** Speed kept below the rectification speed above, unless the supply can sink current or a clamp is fitted.
- [ ] 5.1 Hall table and offset (`motor.hall_code_to_sector`, `motor.hall_angle_offset_rad`): turn the rotor by hand and log the codes; then a low-current alignment.
- [ ] 5.2 Measure Rs, Ld/Lq and λ (method in VALIDATION_PLAN stage 5). Write `config/vehicle.<name>.yaml` with `provenance: bench_measured`; it must validate in hw mode.
- [ ] 5.3 Current-loop step response at low current.
- [ ] 5.4 Fault injection repeated from the host list: hall disconnect, phase-sense loss, CAN unplug, brake, dead-man, e-stop.

## Exit to stage 6 (loaded thermal and efficiency)
Only with stages 1–5 passed and recorded, the review checklist signed, and the hazard and latency analysis available for supervisory timing.
