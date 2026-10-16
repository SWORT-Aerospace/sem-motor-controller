# CAN integration: reference-project analysis (Cornell CHUDS): OPTIONAL ADAPTER

> **v0.3 status: REFERENCE PROJECT, NOT OUR VEHICLE.** Everything below describes Cornell's CHUDS bus, observed in a reference repository. It was written in v0.2 as if it were our vehicle's bus; that was an unsupported assumption (`docs/PROVENANCE_AUDIT.md`). Our vehicle's telematics proposal (v0.1, 14/10/2026) shows a **CAN 2.0B** bus. The actual bus is **UNKNOWN** until the team confirms it (`docs/VEHICLE_INTERFACE_MATRIX.md`).
> * CHUDS support stays an **optional adapter**: the core is transport-neutral and the identifier block is a calibration value (ADR-0012).
> * "The controller must run in FD mode" applies **only if** our bus is CAN FD.
> * "Schematic changed to a 40 MHz crystal" is **withdrawn** in any case: the crystal is unselected (`hardware/timing/clock_tree_alternatives.md`).

Evidence: Cornell `urban-concept@c422c0f` (shallow clone; read, not modified) and this repository. **Non-overlapping identifiers do not prove integration.** This document lists what has to match beyond the IDs: physical layer, bit timing, frame format, filters, arbitration, the receiving software, and the wiring. None of it has been tested on the bus.

## 1. What the bus is (from the vehicle team's code)

| Item | Value | Source |
|---|---|---|
| Protocol | CHUDS, a CAN FD application protocol, "draft, pending team ratification" | `cev-lib/chuds/docs/addressing.md:3` |
| Bit rates | 500 kbit/s nominal, 2 Mbit/s data (BRS set on transmit) | `cev-lib/chuds/frame.hpp:16-19`; `socketcan_transport.hpp:153` |
| Sample points | 80 % nominal, 80 % data | `frame.hpp:18-19` |
| VCU link | `ip link set can0 up type can bitrate 500000 sample-point 0.80 dbitrate 2000000 dsample-point 0.80 fd on restart-ms 100` | `tools/can0-up.service`, `tools/can_link_args.cpp` |
| Node controllers | MCP251863 (CAN FD controller + transceiver), one acceptance filter set to accept **all** frames | `RP2040_MCP251863_Driver/src/mcp251863.cpp:422-428` |
| Frame acceptance in software | **classic, remote and extended frames rejected as `ForeignFrame`** | `socketcan_transport.hpp:197-210`, `mcp_transport.hpp:134-136`, `addressing.md` |
| ID layout | 3-bit class + 8-bit subaddress: Emergency 0x000–0x0FF, Command 0x100–0x1FF, Telemetry 0x200–0x2FF, **Reserved 0x300–0x7FF for future classes** | `addressing.md` |
| Payload | `[type][body_len][body…]`; no magic byte ("any 11-bit CAN-FD frame with a plausible header decodes as CHUDS") | `addressing.md` |
| Emergency STOP | 0x000 (most severe) from the VCU; "every node with outputs goes to safe states"; the aux nodes act on it | `addressing.md`; `elec/src/front_aux/main.cpp:99`, `back_aux/main.cpp:173` |
| Drive-command timeout | open question in CHUDS | `addressing.md`, open questions |
| Wiring, connector, termination, stub lengths | **not documented in the repository** | n/a |

## 2. What the controller must do to coexist

| Requirement | Why | Status |
|---|---|---|
| FDCAN in **FD mode** (FD operation enabled) with data-phase timing **2 Mbit/s at 80 %**, even though semmc v1 transmits only classic frames | Every node checks the CRC of every frame. A node sampling the data phase at the wrong rate sees errors in every CHUDS frame and sends error frames, which would disrupt the whole bus. | Firmware platform layer not written; values in `docs/generated/can_bit_timing.md` |
| FDCAN kernel clock 20 or 40 MHz | 8 MHz gives a 75 % data sample point; 42.5/85 MHz cannot produce 2 Mbit/s | v0.2 chose a 40 MHz crystal; **withdrawn in v0.3** (crystal unselected; PLL-derived kernel clocks also work) |
| Transceiver CAN FD-capable | the same physical bus carries 2 Mbit/s data phases | TJA1051T/3 is CAN FD-rated (snippet) |
| Transmit classic 8-byte frames on 0x300–0x33F | CHUDS nodes ignore classic frames, so no misinterpretation as CHUDS | protocol v1.0 (frozen) |
| Do not transmit FD frames | an FD frame in any class would be decoded as CHUDS (no magic byte) | design rule; enforced by the platform layer (to be written) |
| Accept only the semmc supervisor IDs | firmware already rejects other IDs (`rx_unknown`) | done (host-tested) |
| Termination | split termination fitted only if this node is a bus end | harness unknown; solder jumpers in the draft |

## 3. Identifier allocation (needs a team decision)

The semmc range 0x300–0x33F does not overlap today's CHUDS classes, but CHUDS **reserves** 0x300–0x7FF for future classes. Integration therefore needs one of:
* **(Recommended for the first vehicle version)** The vehicle team ratifies a reservation of 0x300–0x33F (or the whole of class 3) for the motor controller in `addressing.md`. Nothing else changes on their nodes.
* Alternatively, the controller becomes a CHUDS node. Its messages are carried as CHUDS Telemetry (0x2NN) and Command (0x1NN) FD frames, with semmc's sequence, session and CRC inside the body. This is a protocol v2.0 decision: it would also need the CHUDS header and FD transmission in the firmware, and every golden vector regenerated.

**Arbitration.** At 0x300+ every semmc frame loses arbitration to all CHUDS traffic. The supervisor-request worst-case response time must therefore include the CHUDS load (`docs/generated/bus_load.md` counts it conservatively) and must be re-measured on the real bus.

## 4. Receiving software (what changes on the VCU)

The CHUDS library on the VCU will never deliver semmc frames (classic frames are `ForeignFrame`). A separate raw SocketCAN consumer is required:
* `host/vcu_bridge/semmc_socketcan.py` (**proposal**, in this repository; not pushed to the vehicle team's repository):
  * opens a raw socket on `can0` with `CAN_RAW_FD_FRAMES` (to coexist) and a filter id 0x300 / mask 0x7C0;
  * decodes with the generated codec;
  * sends the supervisor frames as classic frames.
* Tested: framing, filter range, decode, and rejection of CHUDS FD, extended and corrupted frames (`tests/integration/test_vcu_bridge.py`).
* **Not tested**: a real socket. This container has no `AF_CAN` support. Test on the VCU with `vcan` and then on the bus.
* The telemetry pipeline (`telem/`, shared memory) needs a consumer for these messages. Its owner and format are a vehicle-team decision.

## 5. Decisions needed from the vehicle team
1. Reserve 0x300–0x33F (or class 3) for the motor controller, or move semmc to CHUDS framing (v2.0).
2. Should the controller act on CHUDS Emergency STOP? Recommended: yes, as an additional L1 inhibit (torque 0, safe direction), released only by the wired driver controls. This adds FD reception and decoding of the 0x000–0x0FF class to the firmware. Not implemented.
3. Bus topology:
   * where the two 120 Ω terminations are;
   * the connector type;
   * where the controller taps in, and its stub length;
   * cable type (twisted pair, shield);
   * whether CAN ground and power are carried in the harness.
4. Who runs the supervisor (companion) software: the VCU or a separate computer. It must send `sup_hello`, `sup_limits` and `sup_torque_req` at the rates in `INTERFACE_CONTROL.md`.
5. The telemetry proposal (`telemetry.pdf`) referenced by the user is **not available** in this environment: not in `/mnt/user-data/uploads`, not in `/mnt/attach`, not in the container's filesystem, and not in Google Drive (searched for "telemetry"). Its transport (cellular? which modem? which broker?) is therefore unconfirmed.
