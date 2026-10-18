# CAN protocol "semmc" (`protocol/`)

The message set that the motor controller and the companion computer exchange over CAN (Controller Area Network). The companion is the computer that runs the energy supervisor; the telematics unit is the proposed host. [protocol.yaml](protocol.yaml) is the single source of the message set. [../tools/gen_protocol.py](../tools/gen_protocol.py) generates matching C and Python codecs, golden test vectors and the message table [../docs/generated/can_messages.md](../docs/generated/can_messages.md) from it, and [../tools/gen_dbc.py](../tools/gen_dbc.py) generates a DBC file (the common CAN database format read by other teams' CAN tools).

**Status:** protocol version 1.1. Only host builds and host simulations use it; it has not been run on a physical CAN bus. The vehicle bus (bit rate, classic CAN or CAN FD (flexible data-rate), the identifier block for the controller) is not yet known ([../docs/ICD.md](../docs/ICD.md) section 2).

## 1. What the directory contains

```
protocol/
  protocol.yaml                       message set, framing rules, golden-vector inputs       (edit this)
  __init__.py                         empty package marker
  generated/__init__.py               empty package marker                                    (maintained)
  generated/semmc_protocol.h, .c      C codec                                                  (generated)
  generated/semmc_protocol.py         Python codec                                             (generated)
  generated/semmc_golden_vectors.c    C golden-vector self-check, linked into test_protocol    (generated)
  generated/semmc_base0x300.dbc       DBC for the identifier block at 0x300                    (generated)
  golden_vectors/vectors.json         expected bytes and decoded values per vector             (generated)
```

### 1.1 Message set

Sixteen messages, all 8-byte classic frames with 11-bit identifiers numbered in one block of 64 (0x300 to 0x33F). Twelve are sent by the controller and four by the companion. Field layouts, scaling and sentinels are in [../docs/generated/can_messages.md](../docs/generated/can_messages.md).

| ID | Message | Sender | Period | Content |
|---|---|---|---|---|
| 0x300 | `ctrl_fault` | controller | 1 s + on change | latched faults, first fault since reset, last reset reason, fault count |
| 0x308 | `sup_torque_req` | companion | 20 ms (provisional) | supervisory torque request, coast request, session tag, referenced limits set, source time |
| 0x309 | `sup_limits` | companion | 100 ms | supervisor bounds on torque and battery power (can only tighten controller limits) |
| 0x30A | `sup_hello` | companion | 500 ms | session announcement: protocol major/minor, role, companion session number |
| 0x310 | `ctrl_status` | controller | 20 ms | state, torque owner, supervisor link, session tag, boot id, simulation and calibration flags |
| 0x311 | `ctrl_cmd_trace` | controller | 20 ms | requested and accepted torque and the reason bits |
| 0x312 | `driver_controls` | controller | 20 ms | wired driver controls as seen by the controller (report only, never an input) |
| 0x313 | `ctrl_session` | controller | 500 ms + on change | session tag assigned to the echoed companion session; controller protocol version |
| 0x318 | `ctrl_motion` | controller | 10 ms | rotor mechanical speed, measured q-axis current, bus voltage |
| 0x319 | `ctrl_currents` | controller | 10 ms | d-axis current, battery current, phase-measurement provenance, Kirchhoff current-law (KCL) residual |
| 0x320 | `ctrl_energy` | controller | 100 ms | battery-side energy since boot, battery power |
| 0x321 | `ctrl_thermal` | controller | 100 ms | power-transistor and motor temperatures, derate factor and reasons |
| 0x322 | `ctrl_validity` | controller | 100 ms | validity nibble per signal (missing, stale, invalid, saturated) |
| 0x323 | `ctrl_energy_quality` | controller | 100 ms | integrated time and gap time of `ctrl_energy.energy_J` (added in 1.1) |
| 0x328 | `csia_advisory` | companion | 100 ms | advisory from the experimental CSIA sensor-consistency diagnostic; shadow only, the controller never acts on it |
| 0x330 | `ctrl_identity` | controller | 1 s | protocol, firmware and calibration identity, hardware revision |

No message commands transistors, PWM (pulse-width modulation) duty, arming, mode selection or fault reset. Those are local, wired controls of the controller.

### 1.2 Frame layout and encoding rules

| Item | Rule |
|---|---|
| Identifier | protocol number 0x300 to 0x33F. On the bus the 64-identifier block starts at the calibration parameter `supervision.can_id_base`, a multiple of 0x40 ([ADR-0012](../docs/decisions/ADR-0012-transport-neutral-interface.md)); the CRC data ID always uses the protocol number |
| Byte 0 | CRC-8/SAE-J1850 (cyclic redundancy check; polynomial 0x1D, initial value 0xFF, final exclusive-OR 0xFF) computed over the 16-bit data ID, low byte first, followed by bytes 1 to 7. Data ID = `(major << 11) \| id`, for example 0x0B08 for `sup_torque_req` in version 1.x. Check value for "123456789": 0x4B |
| Byte 1 | per-message sequence counter, unsigned 8 bit, wraps from 255 to 0 |
| Bits 16 to 63 | fields, Intel (least-significant-bit first) numbering: bit n is bit n % 8 of byte n / 8; multi-byte fields are little-endian |
| Field kinds | `raw` (unsigned integer), `bool` (1 bit), `scaled` (physical = raw x scale + offset; optional two's-complement `signed`; `min`, `max`, `unit`; optional `invalid` sentinel) |
| Encoding | value rounded to 32-bit float, clamped to [min, max] (flagged as saturated), raw = round-half-away-from-zero((x - offset) / scale) in double precision, clamped to the raw range. NaN (not a number, used for "no valid value") encodes as the `invalid` sentinel (flagged as invalid); a field without a sentinel refuses to encode NaN. Infinity saturates. Raw integers above their range saturate |
| Decoding | wrong length and CRC mismatch are rejected before any field is read; in a scaled field, the sentinel decodes to NaN (flagged as invalid), and a raw value outside the range or a value outside [min, max] is returned but flagged as out of range |

The CRC detects corruption, decoding under the wrong identifier and decoding under the wrong major version. It is not a security mechanism ([ADR-0005](../docs/decisions/ADR-0005-can-contract.md)).

### 1.3 What the generator checks in `protocol.yaml`

`load_spec` in `tools/gen_protocol.py` refuses a specification with a duplicate message name or identifier, an identifier outside 0x300 to 0x33F, a field outside bits 16 to 63 or wider than 32 bits, overlapping fields, a field named `seq` or `crc`, a `bool` wider than one bit, a scaled field whose [min, max] is not representable in its raw range, or an `invalid` sentinel that is not the raw minimum or maximum of its field. The sentinel is excluded from the raw range used for encoding.

### 1.4 Codec interfaces

**Python** (`protocol.generated.semmc_protocol`): `PROTOCOL_MAJOR`, `PROTOCOL_MINOR`, `SPEC_HASH`, `MESSAGES` (by name) and `BY_ID` (by identifier); `encode(name, values, seq)` returns `(bytes8, saturated_fields, invalid_fields)` and raises `CodecError` for a missing field or a NaN without sentinel; `decode(name_or_id, data)` returns `(values, info)` with `info["status"]` one of `ok`, `bad_length`, `bad_crc`, `unknown_id`, plus `seq`, `invalid` and `out_of_range`; `crc8_with_data_id(data_id, payload)`.

**C** (`semmc_protocol.h`): one struct `semmc_<message>_t` per message (`seq` plus the fields; scaled fields are `float`, bools are `bool`, raw fields `uint32_t`), `semmc_encode_<message>()` and `semmc_decode_<message>(in, len, out)`, both returning `semmc_result_t` (`status` of `SEMMC_OK`, `SEMMC_E_LEN`, `SEMMC_E_CRC` or `SEMMC_E_NAN`, and `saturated`, `invalid`, `out_of_range` bit masks indexed by the `SEMMC_F_<MESSAGE>_<FIELD>` macros). Also `SEMMC_ID_*`, `SEMMC_DATAID_*`, `SEMMC_PERIOD_US_*`, `semmc_msg_index()` and `semmc_crc8_data_id()`. The codec allocates no memory and performs no I/O; its conversions run in double precision and are meant for the slow loop only. On `SEMMC_E_NAN` the output frame is zeroed.

Both codecs share the same arithmetic, so a C and a Python encoder produce identical bytes; the golden vectors check this.

## 2. Who works here

* **Controls lead:** owns the protocol and the interface control document ([../docs/ICD.md](../docs/ICD.md)). A change to a frozen item needs a protocol version change and the agreement of the owners named there.
* **Telematics engineer:** consumes the controller messages and produces the companion messages (telematics node model, supervisor, log, uplink).
* **Vehicle team:** allocates the identifier block (`supervision.can_id_base`) and the bus parameters.
* **Other teams' CAN tools:** use the generated DBC, never the YAML.

## 3. Important files

Paths relative to this directory.

| File | What it does in the system | Inputs | Outputs |
|---|---|---|---|
| [protocol.yaml](protocol.yaml) | Single source of the CAN contract: protocol name and version, nominal bit rate and frame format, the 16 messages with identifier, sender, period and field layout, and the physical inputs of the 19 golden vectors. Every other file in this directory, apart from the two empty `__init__.py` files, is generated from it. | hand edits, reviewed by the protocol owners | the specification read by `tools/gen_protocol.py`, `tools/gen_dbc.py`, `tools/bus_load.py` and `tests/integration/test_dbc.py` |
| `generated/semmc_protocol.h`, `generated/semmc_protocol.c` | C codec compiled into the controller core library (`semmc_core` in [../firmware/CMakeLists.txt](../firmware/CMakeLists.txt)). The core uses it to decode supervisor frames before the freshness and session checks, and to encode every controller message it transmits. | 8-byte payloads and their length (decode); message structs (encode) | message structs with status and flag masks; 8-byte payloads with CRC and sequence |
| `generated/semmc_protocol.py` | Python codec with the same arithmetic. The host supervisor, co-simulation, telematics node model, log tools, pit ingestion, the Linux SocketCAN bridge proposed for a vehicle control unit, the demonstrations and the tests use it to build and read frames. | message name or identifier, physical values, sequence number, payload bytes | payload bytes with saturated and invalid field lists; decoded values with status, sequence and flags |
| `generated/semmc_golden_vectors.c` | C self-check `semmc_golden_check()`: encodes every golden vector and compares the bytes, decodes the expected bytes and compares every field, and checks that every single-bit flip in bytes 1 to 7 fails the CRC. Linked into the C test `test_protocol`. | the vectors embedded at generation time | number of failures (0 expected) |
| `golden_vectors/vectors.json` | Expected bytes, saturation and invalid flags and decoded values for each vector, computed by the Python codec at generation time; read by `tests/integration/test_protocol_python.py`. | `vectors:` section of `protocol.yaml` | reference data for the Python round-trip test |
| `generated/semmc_base0x300.dbc` | DBC description of all 16 messages at block base 0x300, with byte 0 and byte 1 as plain `crc8` and `seq` signals (a DBC cannot express the CRC) and the `invalid` sentinels as value tables. Checked against the codec with an independent parser (cantools) in `tests/integration/test_dbc.py`. | `protocol.yaml` | a file for other teams' CAN tools |

## 4. Inputs and outputs of the directory

**Input:** `protocol.yaml`, edited by hand.

**Outputs:** the generated codecs, golden vectors and DBC in this directory, and [../docs/generated/can_messages.md](../docs/generated/can_messages.md) (written by `tools/gen_protocol.py`). The generated files carry the protocol version and the spec hash (section 7).

**Consumers:**
* Firmware: `semmc_core` compiles `generated/semmc_protocol.c` and puts `protocol/generated` on the include path; `firmware/src/core/mc_core.c` encodes and decodes through it; `test_protocol` links the golden self-check. See [../firmware/README.md](../firmware/README.md).
* Host Python, importing the generated codec: `host/telemetry_adapter/supervisor.py` and `e2e.py` (supervisor, end-to-end co-simulation), `host/telematics/node.py`, `host/logger/semmc_log.py`, `host/pit/ingest.py`, `host/vcu_bridge/semmc_socketcan.py`. `host/csia_adapter/adapter.py` produces the field values of `csia_advisory` without importing the codec.
* Tools: `tools/run_host_demo.py`, `tools/make_replay_sample.py`, `tools/telematics_budget.py` (codec); `tools/bus_load.py` (reads `protocol.yaml` directly).
* Documents: [../docs/ICD.md](../docs/ICD.md) section 3 quotes the version and spec hash.

## 5. Dependencies on other directories

* [../tools/gen_protocol.py](../tools/gen_protocol.py) and [../tools/gen_dbc.py](../tools/gen_dbc.py) generate everything here; they need PyYAML ([../requirements.txt](../requirements.txt)). The DBC test also needs cantools.
* The generated Python codec uses only the standard library (`math`, `struct`); the generated C codec needs `<stdbool.h>`, `<stdint.h>`, `<math.h>` and `<string.h>`.
* The decisions behind the contract: [ADR-0005](../docs/decisions/ADR-0005-can-contract.md) (framing, integrity, session, freshness) as amended by [ADR-0012](../docs/decisions/ADR-0012-transport-neutral-interface.md) (identifier block per vehicle, transport-neutral core).

## 6. How to run and test

From the repository root, inside the virtual environment:

```sh
python3 tools/gen_protocol.py --check     # exit 1 with STALE lines if a generated file differs; prints nothing when current
python3 tools/gen_dbc.py --check          # prints "protocol/generated/semmc_base0x300.dbc: current" or STALE
python3 -m pytest tests/integration/test_protocol_python.py tests/integration/test_dbc.py
cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build -R test_protocol
```

`test_protocol_python.py` checks the CRC against an independent bitwise implementation, round-trips every golden vector, compares the codec with byte-by-byte hand calculations from `protocol.yaml` (two `sup_torque_req` frames, one `ctrl_energy_quality` frame), checks that a frame from another major version fails the CRC, rejects malformed input, runs `gen_protocol.py --check` and checks the bus-load budget. `test_dbc.py` decodes every vector with cantools at block bases 0x300 and 0x500. The C test `test_protocol` runs the golden self-check and covers wrong lengths, a payload decoded under another identifier, NaN and infinity encoding and out-of-range flags. How the protocol is used is tested elsewhere: the SocketCAN bridge in `tests/integration/test_vcu_bridge.py`, the supervisor in `tests/integration/test_supervisor.py`, and session, freshness, malformed and reordered frames inside the controller in `tests/integration/test_end_to_end.py`, `tests/fault_injection/test_fault_injection.py` and the C tests `test_freshness` and `test_core`; see [../tests/README.md](../tests/README.md).

## 7. Generated files: do not edit by hand

Paths relative to the repository root:

| File | Generated by | Regenerate with |
|---|---|---|
| `protocol/generated/semmc_protocol.h`, `protocol/generated/semmc_protocol.c`, `protocol/generated/semmc_protocol.py`, `protocol/generated/semmc_golden_vectors.c`, `protocol/golden_vectors/vectors.json`, `docs/generated/can_messages.md` | `tools/gen_protocol.py` | `python3 tools/gen_protocol.py` |
| `protocol/generated/semmc_base0x300.dbc` | `tools/gen_dbc.py` | `python3 tools/gen_dbc.py` |

`python3 tools/gen_dbc.py --base 0x500` writes a relocated DBC to `protocol/generated/semmc_base0x500.dbc` for a vehicle whose block starts elsewhere. That file is not committed and `--check` covers only the default base. In a relocated DBC the CRC data ID is still the canonical protocol number, so a tool that checks the CRC must use the protocol number, not the bus identifier. `protocol/generated/__init__.py` is an empty maintained file, not generated.

### 7.1 Spec hash and version rule

* **Spec hash:** the first 16 hexadecimal digits of the SHA-256 of the complete text of `protocol.yaml`, comments and whitespace included (currently `16ff00853dfda3ce`). It is written into every generated file, into `vectors.json`, into the DBC comment and into `docs/generated/can_messages.md`, and `docs/ICD.md` quotes it. Any edit to `protocol.yaml`, even to a comment, therefore makes every generated file stale: `gen_protocol.py --check` and `gen_dbc.py --check` exit 1, and the CI step "Generated files are current", `test_generated_files_are_current` and `test_committed_dbc_is_current` fail until the files are regenerated and committed with the YAML. For this reason the header comment of the frozen 1.x file is kept verbatim (ADR-0012).
* **Version:** `protocol.major` and `protocol.minor` in `protocol.yaml`. The major version is part of every CRC data ID, so a frame encoded under another major fails the CRC, and the controller counts a `sup_hello` with another major as `rx_proto_mismatch` and ignores it. Minor versions are additive ([../docs/ICD.md](../docs/ICD.md) section 3): 1.1 added `ctrl_energy_quality` and left every 1.0 message unchanged. A change to an existing message (identifier, field position, width, scaling, sentinel) is therefore not a minor change. Nothing in the tooling enforces the bump: the generator recomputes the expected golden-vector bytes from whatever the YAML says.

### 7.2 How to change a message safely

1. Agree the change with the protocol owners (ICD). Decide the version: a new message is a minor bump; a change to an existing message needs a new major version.
2. Edit `protocol.yaml`: the message or field, `protocol.major` or `protocol.minor`, and at least one entry in `vectors:` for every new or changed message (for scaled fields with a sentinel, add a saturating and a NaN case, as the existing `sup_torque_req` vectors do).
3. Regenerate: `python3 tools/gen_protocol.py` and `python3 tools/gen_dbc.py`.
4. Review the diff of `golden_vectors/vectors.json`. Under a minor bump, the bytes of every unchanged message must be unchanged (only the hash and version change); under a major bump every CRC byte changes.
5. Update the code that fills or reads the changed fields: `firmware/src/core/mc_core.c` and the Python users listed in section 4. Most controller messages are filled in `mc_core.c` with positional struct initialisers, in YAML field order. Adding or removing a field breaks the build (`-Wextra -Werror`), but reordering fields, or renaming a field without changing its type, compiles silently and shifts or mislabels values, so check each initialiser by hand.
6. Update the tests that hold independent expectations:
   * the hand calculations in `tests/integration/test_protocol_python.py` if `sup_torque_req` or `ctrl_energy_quality` changes;
   * the identifier list in `firmware/tests/test_protocol.c` (`test_ids_form_one_64_number_block`) for a new message;
   * the frame-rate totals in `tests/hardware/test_clock_and_telematics.py` (394 controller and 72 supervisor frames/s) and the bus-load figures in `tests/integration/test_math_spec.py` if a period changes;
   * the recorded log `tests/simulation/replay_sample.semmc.log`, with `python3 tools/make_replay_sample.py` after building in the default `build/` directory, if the major version or a `sup_*` message changes (its frames carry CRC bytes).
7. Update `docs/ICD.md` (version and spec hash) and the figures in `docs/MATH_SPEC.md` that depend on the change.
8. Run the checks of section 6, then the whole suite (`ctest --test-dir build` and `python3 -m pytest -rs`).

## 8. Current limitations

* The vehicle bus is unknown: 500 kbit/s is assumed in the analyses, and the identifier block is not allocated (null in the unconfigured vehicle configuration).
* `sup_torque_req` timing (50 Hz with a 100 ms timeout) is provisional and for simulation only, pending a hazard and latency analysis; a hardware build refuses it.
* The CRC is an integrity check, not authentication; the bus is treated as physically trusted.
* The golden vectors are computed by the project's own Python codec, so they check C and Python agreement, not correctness against an outside reference. The independent references are the hand-calculated frames, the bitwise CRC reference and the cantools decoding of the DBC.
* No automatic check ties a wire-format change to a version bump (section 7.1).
* The comment above the `vectors:` section of `protocol.yaml` says a subset of the vectors is hand-verified in a file named `test_protocol_handcalc.py` in tests/integration. No such file exists; the hand calculations are in `tests/integration/test_protocol_python.py`, and the comment cannot be corrected without changing the spec hash. The file's header comment likewise still gives the CHUDS reference project (Cornell's CAN system) as the rationale for the identifier block; ADR-0012 records the correction.
* `test_ids_form_one_64_number_block` in `firmware/tests/test_protocol.c` lists 15 of the 16 identifiers (it omits `ctrl_energy_quality`, 0x323).
* Nothing has been run on a physical CAN bus or with another team's tools; the DBC has only been parsed by cantools.
