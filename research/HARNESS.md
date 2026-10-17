# Evaluation harness: what is simulated, and how

The harness (`research/bea/harness.py`) produces one episode at a time, in separate layers:

1. truth plant;
2. sensors and faults;
3. transport and clocks;
4. vehicle log and live summary;
5. pit access.

The diagnosis and the schedulers receive only the pit-access object. Fault labels stay in the episode specification, which only the scorer (`research/bea/scoring.py`) reads. Every number below is a synthetic assumption **[A]** unless marked as a repository fact **[F]**. Nothing is measured.

## 1. Episodes

| Item | Value |
|---|---|
| Duration | 90 s |
| Fault onset | uniform in 25 to 45 s (none for normal episodes) |
| Drive cycle | one of three, drawn per episode: pulse-and-coast between v_lo and v_hi (v_lo 4.5 to 6 m/s, band 1.5 to 3 m/s, pulse acceleration 0.3 to 0.6 m/s²); speed hold with a proportional controller and a new set point every 12 to 25 s; mixed (speed hold until 45 s, then pulse-and-coast) |
| Torque slew | 20 N m/s |
| Controller's knowledge | nominal resistance only: the drive cycle reacts to the true plant, but its feed-forward uses the nominal model |
| Splits | development seeds 100000 + i, calibration 200000 + i, final seeds derived from the pre-registration commit |

## 2. Truth plant

The plant is the repository's SYNTHETIC vehicle and motor (`models/vehicle/`) [F], with true deviations drawn per episode inside 0.9 times the "known" nuisance bounds of `research/bea/relations.py`. The deviations cover:

- rolling resistance and drag area;
- mass (and so effective mass);
- torque constant and winding resistance;
- iron-loss coefficient and motor friction;
- a constant loss offset and a switching loss per ampere;
- grade and along-track headwind;
- bus-meter zero offset and gain;
- IMU bias.

The inverter-input power is the repository's synthetic loss map with no auxiliary load, because the auxiliaries are outside the bus meter ([`PROTOCOL.md`](PROTOCOL.md) section 4) [F]. The pack is a 48 V source (team-reported nominal, used only as an operating point) behind 0.1 Ω. The plant runs at 500 Hz.

Plant-level faults:

- **HL**: an extra opposing force, as a step at onset;
- **HL_grade**: an uphill grade step at onset;
- **HB+HL**: both a bias and an extra force (robustness set only).

## 3. Sensors and sensor-level faults

| Channel | Rate | Model |
|---|---|---|
| bus current (`ctrl_currents.ibatt_A`) | 100 Hz | true inverter-input current × (1 + gain error) + zero offset + noise 0.02 A, quantised to 0.01 A [F: scale] |
| bus voltage, iq, rotor speed (`ctrl_motion`) | 100 Hz | noise 0.01 V, 0.01 A and 0.002 m/s equivalent; quantised to 0.01 V, 0.01 A and 0.05 rad/s [F: scales]. Rotor speed is reported as 0 while coasting (freewheel open) |
| battery power (`ctrl_energy.p_batt_W`) | 10 Hz | V·I of the frame values, rounded to 1 W [F: scale] |
| command trace (`ctrl_cmd_trace`) | 50 Hz | accepted torque, and whether the gates are off |
| wheel counts | 0.1 s windows | floor of distance × 32 / 1.5 m (provisional pulses per revolution and circumference, as `host/telematics/sensors.py`) |
| IMU | 100 Hz | specific force (acceleration plus g·sin(grade)) + bias + noise 0.05 m/s² |
| GNSS speed | 10 Hz | noise 0.05 m/s |

Controller samples are taken at the 10 ms cycle plus up to 0.3 ms of task jitter.

Sensor-level faults:

- **HB**: a bias added to the bus current after onset.
- **HT**: the bus meter's voltage and current reach the frames late. On the development and final splits this is a pure delay. The robustness set also uses a first-order lag and an averaging window.
- **HU_gain**: an unmodelled gain error of the bus current. No modelled hypothesis covers it, so the correct outcome is "no modelled cause fits".

## 4. Transport and clocks

- **Controller frames.**
  - Bus latency is 0.25 ms, plus 0 to 0.5 ms queueing, plus the send jitter.
  - Loss is a Gilbert-Elliott burst model: 0.05 % entry into the bad state, 20 % exit, 50 % loss while bad.
  - 0.05 % of frames are duplicated and 0.05 % are swapped with a neighbour.
  - Every frame carries its per-message 8-bit sequence counter and no source time [F].
- **Receipt stamps** are in the telemetry unit's clock: `LocalClock` from `host/telematics/clocks.py` [F], with an offset of 0.5 to 3 s and a drift of ±50 ppm drawn per episode.
- **Telemetry-unit sensors** are stamped at acquisition in that same clock.
- **Live summary.** Built as `host/telematics/node.py` builds `sem.telemetry.v2` [F]: latest values, the mean of the battery-power frames since the previous message, and the latest wheel window, every 0.5 s. It reaches the pit 0.3 s later. In 20 % of episodes the uplink is down for 2 to 10 s; messages then wait in a 30-message backlog and are replayed, flagged.

## 5. Pit access and costs

The pit can only:

- read the summaries that have arrived;
- issue requests;
- read the responses that have arrived.

Time runs forward only. A request reaches the vehicle after half the round-trip time (0.6 s round trip). Its records are fixed then: only records the vehicle had received by that moment, within the 600 s retained depth.

The response arrives after three delays:

- the flash read, at 1 MB/s;
- the transfer, at the 20 kB/s left for responses on the uplink;
- the other half of the round trip.

**Costs, charged per request** (the wire format of the proposed recorder, [`RECORDER.md`](RECORDER.md)):

- 32 bytes of request;
- each record at its STLG size (controller frames 17 bytes, IMU 14, wheel window 11, GNSS 16) [F];
- 28 bytes of chunk header and CRC per response chunk of at most 512 bytes.

Clock metadata costs 96 bytes and reports the receipt-interval jitter of the bus-current frames over the last 10 s, computed between consecutive sequence numbers only.

**Not modelled (limitations):**

- modem energy, and how it depends on byte count;
- loss of a response;
- a request lost on its way to the vehicle;
- flash wear;
- the unit's CPU load.

Bytes are a cost the study reports; it does not claim that fewer bytes means less modem energy.

## 6. Causality checks

`tests/research/test_harness.py` checks five things:

- a response never arrives before it could;
- a buffer response never contains a record received after the request reached the vehicle;
- a capture is delivered only after its window;
- the pit cannot move time backwards;
- the pit-side objects expose no label, truth or plant field.

The schedulers and the diagnosis receive only a `View`, built from arrived data. The episode runner (evaluator side) reads the episode's duration and clock from the specification to drive the simulation, and copies the label into the result for the scorer; nothing it passes to a scheduler carries either.
