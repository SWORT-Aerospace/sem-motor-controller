# Controller interface request (for the motor-controller team)

**From:** the telematics team. **To:** the team that builds the vehicle's motor controller. **Status:** open; no answer received yet.

We build the telematics unit: it records the controller's data next to our own sensors (wheel speed, GNSS, IMU, temperatures), logs everything on the vehicle and sends a summary to the pit. **It only listens.** It sends no frame to the controller: no torque request, no arming, no fault reset, no configuration change, and it takes no part in protection or precharge. We do not assume we may change your firmware.

Our own CAN message set (`semmc`, [`protocol/protocol.yaml`](../protocol/protocol.yaml)) exists only as a simulation fixture for our tests; we do not expect your controller to use it. We will read whatever your controller already sends. If it already broadcasts what section 3 lists as essential, you change nothing.

Please answer what you can and mark the rest unknown; an unknown stays unknown in our records.

## 1. Controller and contact

| # | Question | Your answer |
|---|---|---|
| 1.1 | Controller model and firmware version (or "own design", with its revision) | |
| 1.2 | Contact for interface questions (name, channel) | |
| 1.3 | Is a protocol document or a DBC file available to us? May we keep a copy in our repository? | |

## 2. Transport and electrical interface

| # | Question | Your answer |
|---|---|---|
| 2.1 | Bus type: CAN classic, CAN FD (with or without bit-rate switching), or something else (UART, RS-485, analog) | |
| 2.2 | Bit rate (nominal; and data-phase rate if FD) and sample point, if you set it | |
| 2.3 | Identifier format: 11-bit or 29-bit; identifier range in use | |
| 2.4 | Termination: where are the bus's 120 Ohm terminators, and is one in the controller? (We will not add one unless you ask.) | |
| 2.5 | Transceiver part number in the controller (for its common-mode range and unpowered behaviour) | |
| 2.6 | Connector at the controller (part number), pinout for CANH, CANL, CAN ground, and any supply pin; where on the harness may we tap in? | |
| 2.7 | Ground: is the CAN ground the controller's logic ground, the battery negative, or isolated? Where should our unit's ground meet it? | |
| 2.8 | Is the CAN side isolated from the power stage? | |
| 2.9 | Other nodes on the bus and their traffic (for the bus-load and termination picture) | |

## 3. Signals

For every signal you can provide: message identifier and name, start bit and length, byte order, signed or unsigned, scale and offset, unit, update rate, the raw value that means "invalid" or "not available", any validity flag, any rolling counter or checksum, and whether the frame carries the time the value was sampled. A DBC file answers most of this. **Please add a recording** (a `candump -L` log or your tool's export, at least 60 s at standstill and 60 s while driving or on the bench with the motor turning), so we can test our decoder against real frames before we meet the vehicle.

### 3.1 Essential (energy at the controller input)

| Signal | Unit | Rate we need | Why |
|---|---|---|---|
| DC voltage at the controller input | V | 10 Hz or faster | energy = integral of V x I; also the battery-sag picture |
| DC current into the controller input (sign convention: positive on discharge?) | A | 10 Hz or faster, ideally in the same frame as the voltage or with a sample time | as above; V and I must be aligned in time |
| For both: the accuracy (gain and offset over temperature) and the sample-to-transmit delay | % / A / ms | once | our energy figure reports its uncertainty; without these it states "sensor accuracy not stated" |

If V and I are sent in different frames, a sample time or a shared counter lets us align them; otherwise we align by receive time and report the uncertainty (one message period each).

### 3.2 Optional (diagnostics, shadow-mode consistency checks; nothing depends on them)

| Signal | Unit | Use |
|---|---|---|
| Motor speed (mechanical, or electrical with the pole-pair count) | rad/s or rpm | cross-check with the wheel sensors and GNSS; drivetrain slip |
| Phase current (q-axis or RMS) and torque reference | A, N*m | load and efficiency analysis; the shadow monitors' current relationships |
| Controller's own DC power and energy counter, and how long it integrated | W, J, s | cross-check with our V x I integration |
| Power-stage and motor temperature | degC | thermal picture next to our probes |
| State and fault codes, with their meanings | code | to mark intervals where the data are not normal running |
| Validity flags per measurement | flag | so a value the controller knows is bad is never recorded as good |

### 3.3 Timing and behaviour

| # | Question | Your answer |
|---|---|---|
| 3.3.1 | Broadcast periods per message; anything sent only on change or on request? | |
| 3.3.2 | Behaviour at power-up and in a fault: does it keep broadcasting, and what do the values read then? | |
| 3.3.3 | Any rolling counter or checksum per message (so we can detect lost or corrupted frames)? | |

## 4. If something essential is missing

We would then ask for exactly this, as a broadcast your controller sends on its own (we still send nothing):

* one 8-byte classic frame, at 10 Hz or faster, holding DC voltage (unsigned, 0.01 V per bit), DC current (signed, 0.01 A per bit), a validity bit for each, and a 4-bit or 8-bit rolling counter; any free identifier you choose; and its definition as a DBC entry.

If you prefer that we ask for the data (request and response, "polling") instead, that is a separate decision: it would make our unit transmit on your bus, which we have not planned and would only do with your written agreement on the request frame, its rate and what your controller does if requests stop. Initially we stay receive-only.

## 5. Electrical noninterference (our side; for your review)

A unit whose firmware only listens can still disturb a bus electrically. What we do about each way it could:

| Risk | What we do | How it is checked (telematics/firmware/BENCH.md section 7) |
|---|---|---|
| Our transceiver drives the bus (firmware fault, a stuck pin) | the CAN controller runs in bus-monitoring mode (sends nothing, not even the acknowledge bit); the transceiver's transmitter is disabled in hardware (TJA1051T/3 silent pin held high); the TXD line cannot override it | E1: our node's own output, not the whole bus (your traffic drives the shared bus dominant, as it should). (a) On an isolated bench bus with no other node, the transmitter's input forced low and high with the silent pin high: CANH-CANL stays recessive, and goes dominant only in the control with the silent pin low. (b) With one sender: every frame ends in an acknowledge error and our TX line stays high, so no dominant bit comes from our node. (c) With an acknowledging node added: the error counters are the same over 10,000 frames with and without our unit |
| The unit loads the bus when unpowered | transceiver whose data sheet states no bus load when unpowered (TJA1051: "disengages from the bus when not powered up"; SN65HVD230: "unpowered node does not disturb the bus") | E2: no change in error counters or waveform with the unit unpowered; leakage within the data sheet |
| An extra terminator | the breakout's terminator switched off unless you ask for it | E3: CANH-CANL resistance with and without the unit, bus unpowered (about 60 Ohm for a bus terminated at both ends) |
| Bus loading and stubs | one more receiver (its input capacitance per the transceiver data sheet) on a stub as short as the harness allows | E4: stub length within what you allow for your bus; your bit rate tells the limit |
| Ground differences and loops | one ground connection at the point you name (2.7); the unit's own supply is not chosen yet (blocked until the pack's maximum voltage is known, docs/TELEMATICS_BOM.md), and is to be isolated so the CAN ground is the only ground link; no USB-connected laptop on the vehicle while it runs | E5 |
| Back-feeding your logic supply | the unit takes no supply from your connector | E6 |

Bus load from our unit: zero frames. Your frames are unchanged by our presence.

## 6. What we will do with your answer

1. Write a mapping from your DBC to our signal registry ([`host/telematics/signals.py`](../host/telematics/signals.py)) and read your frames with our DBC adapter ([`host/telematics/controller_adapter.py`](../host/telematics/controller_adapter.py)), with units checked against your DBC.
2. Replay your recording through it and send you the decoded values and their validity, so you can check that we read your data the way you mean it.
3. Bench-test the electrical checks of section 5 with your connector pinout before connecting to the vehicle, and share the results.
4. Only after you agree: connect, receive-only, at a time you choose.
