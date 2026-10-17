# Physical validation plan for the research extension

Nothing in this study has been measured on hardware. This plan lists the experiments that would test its assumptions, in the order they can be done, with the minimum equipment. Electrical and timing experiments come first; load tests come last. Faults are injected only into shadow copies of a signal, never into a path the controller's protection uses. Every bench session follows the staged gates and the lab's procedure in [`../docs/VALIDATION_PLAN.md`](../docs/VALIDATION_PLAN.md), and nothing is energised without the person named for energised tests (input sheet item 13).

## 1. What blocks what today [F]

| Needed | Status | Consequence |
|---|---|---|
| The controller board (bus meter, phase shunts) | draft schematic only, not built | E1 and E2 on the real bus meter wait for stage 4 of the validation plan; a stand-in rig (below) can start now |
| Telemetry-unit firmware and platform layer | not written ([`../docs/TELEMETRY_EMBEDDED_PORT.md`](../docs/TELEMETRY_EMBEDDED_PORT.md)) | the recorder runs on a host only; E4 waits for the port |
| A request path from the pit to the vehicle | does not exist ([`PROTOCOL.md`](PROTOCOL.md) section 3) | E4 also needs this transport decision |
| IMU | candidate parts only (`hardware/bom/procurement.yaml`, line `imu`) | E5's grade test waits for a fitted, calibrated IMU |
| Equipment the team owns | not known (input sheet items 13 to 15) | every line below says what to use if owned and what to procure otherwise |

## 2. Minimum equipment, owned first

The cost of every procured line is TBD or an estimate in [`../docs/PROCUREMENT.md`](../docs/PROCUREMENT.md). This plan does **not** claim that the research fits the vehicle budget. That question stays open until the development boards, the missing sensors and the equipment below are costed.

| Purpose | Use if owned | Otherwise | Procurement line |
|---|---|---|---|
| Independent current and voltage reference | two bench multimeters (current in series, voltage at the meter's inputs), or a calibrated shunt with a data-acquisition input; the uncertainty of each written down | a bench DMM | `dmm` |
| Timing reference | an oscilloscope or logic analyser that records a GPIO edge and the CAN bus together; GNSS PPS as the absolute reference | borrowed from the lab | `scope` (assumed borrowed) |
| Controlled current steps | an electronic load or switched power resistors on a current-limited supply | power resistors | `bench_load` (blocked on the reviewed design), `bench_supply` (blocked on the pack voltage) |
| Telemetry unit stand-in | a NUCLEO-U575ZI-Q with a CAN transceiver | the development board | `nucleo` |
| CAN injection and recording | a USB-CAN adapter | a CANable-class adapter | `usb_can` |
| Stand-in bus meter (before the controller exists) | an INA228 evaluation board | to be added to the procurement file if this route is chosen | not listed yet |
| Motor setup for load tests | the reviewed motor on a stand (validation plan stage 5) | none: wait | none |

## 3. Experiments

Each experiment replaces an assumption of [`HARNESS.md`](HARNESS.md) or [`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) with a measured bound, and records the uncertainty of the reference used.

**E1. Bus-meter zero and gain** (replaces the zero-offset bound of 5 mA and the gain bound of 0.5 %).
- With the gates off (R3's condition), record the meter's current for 60 s at three temperatures.
- Then record at five load points against the reference.
- **Result:** offset and gain with their uncertainty. The identifiability matrix rows for HB use them directly.
- **Stand-in:** an INA228 evaluation board on the NUCLEO with the same averaging settings, before the controller exists.

**E2. Relative timing of the electrical and motor records** (replaces the 5 ms timing bound, and finds an averaging lag).
- Apply a current step with a known edge, marked by a GPIO toggled at the switching instant.
- Record when the step appears in the bus-current records and in the phase-current records, as the telemetry unit stamps them.
- Repeat 50 times and at each averaging setting of the meter.
- **Result:** the distribution of the relative delay, and whether it behaves as a delay, a first-order lag or an averaging window ([`IDENTIFIABILITY.md`](IDENTIFIABILITY.md) section 4). A bound above 5 ms changes the timing hypothesis's detection limit and must be reported before any HT result is used.

**E3. Shadow-path fault injection.**
- On recorded bench data, apply the study's faults to a copy of the bus-current stream: an offset, a delay, a gain error.
- Apply them in the pit replay or in a shadow buffer in the telemetry unit, never in the controller.
- Run the frozen diagnosis on each copy.
- **Result:** whether the attribution survives real noise, quantisation and receipt jitter. These are bench data with injected faults; they do not show vehicle performance.

**E4. Recorder on the target.**
- Port `research/recorder` to the telemetry unit once its platform layer exists.
- Measure with the cycle counter, under full log load:
  - the execution time of `bea_on_record`, `bea_on_request` and `bea_poll`;
  - the stack;
  - the RAM;
  - behaviour when the log queue is saturated and when the link drops.
- **Result:** measured maxima on the target. They are still not a worst-case execution time; a WCET needs a static analysis or a documented measurement argument.

**E5. Load and grade** (separately, after stage 5 of the validation plan).
- Run coast-down tests with a known added drag (a towed mass or a set brake drag), on level ground and on a surveyed slope.
- Calibrate the IMU mounting at rest in both directions of travel.
- **Result:**
  - the achievable IMU bias bound (the study assumes 0.005 m/s² calibrated, 0.05 m/s² not);
  - whether drag and grade separate as section 3 of the identifiability analysis predicts.
- Headwind cannot be separated with any planned sensor and is not tested.

## 4. Order and exact next action

1. E1 and E2 on the stand-in rig: NUCLEO plus INA228 evaluation board, bench supply and switched resistors. This needs no controller board.
2. E3 on the data of step 1.
3. E1 and E2 again on the controller's bus meter at validation stage 4.
4. E4 once the telemetry firmware exists.
5. E5 after validation stage 5.

**Exact next physical action.** Confirm which items of section 2 the team or the lab already owns (input sheet items 13 to 15). Then run E2 on the stand-in rig: a 2 A current step through an INA228 evaluation board at its intended averaging setting, timestamped by the NUCLEO, with the GPIO edge on a scope channel, 50 repetitions. This needs only the NUCLEO, the evaluation board, a current-limited supply, a power resistor with a switch, and a scope or logic analyser. Its result decides whether the timing hypothesis can be detected at the sizes the study uses.
