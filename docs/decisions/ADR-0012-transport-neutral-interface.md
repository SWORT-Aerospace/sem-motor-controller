# ADR-0012 — Transport-neutral core; CAN identifier block per vehicle; CHUDS only as an optional adapter

**Status:** Accepted (v0.3). The vehicle bus is still to be confirmed.

## Context
v0.2 treated Cornell's CHUDS CAN FD bus (a reference project) as our vehicle's bus. It let that bus choose:
* the controller's CAN mode (FD enabled at 500k/2M);
* the crystal (40 MHz);
* the identifier argument (outside CHUDS's classes);
* the VCU-side consumer.

Our vehicle's telematics proposal (v0.1, 14/10/2026) shows a CAN 2.0B bus, an STM32U575 telematics unit and an LTE/MQTT pipeline, without bit rate or identifier map. Neither proposal is confirmed hardware.

## Decision
1. **The controller core is transport-neutral.** It exchanges 8-byte protocol messages identified by the protocol's canonical numbers (`mc_core_on_msg_rx`, `mc_core_msg_tx_poll`, `mc_core_on_link_state`). Every message carries its own data id, sequence and CRC, so integrity does not depend on the transport's addressing.
2. **The CAN binding is one adapter** (`firmware/src/transport/mc_can_binding.c`). It places the 64 message numbers at an 11-bit block whose base is the calibration parameter `supervision.can_id_base`:
   * multiple of 0x40, validator rule 40, C and Python parity-tested;
   * null in the unconfigured config, so a hardware build cannot run until the vehicle team allocates the block;
   * 0x300 in the synthetic config.
3. **The CRC data id stays the canonical number**, so both ends must agree on the base:
   * a base mismatch shows up as foreign identifiers (supervisor timeout, then ECO → READY with zero torque), not as accepted frames;
   * a frame misplaced inside the block fails its CRC.
4. **Bit rate, classic or FD mode, crystal and transceiver are per-vehicle selections**, made after the bus is confirmed (`hardware/timing/clock_tree_alternatives.md`).
5. **CHUDS is an optional adapter** (`docs/CAN_INTEGRATION.md`, `host/vcu_bridge/`). It is kept for the case where the vehicle bus turns out to be CHUDS-like. It is not a design input.
6. **Manual driving never depends on any link.** Driver authority stays wired (ADR-0010). The pit/cloud link is never in the real-time chain (`docs/COMBINED_ARCHITECTURE.md`).

## Consequences
* The frozen v1 message set, golden vectors and spec hash are unchanged; `protocol.yaml`'s header comment still cites CHUDS as the v1 rationale and is kept verbatim (editing it would change the spec hash).
* New tests:
  * `test_can_binding_relocates_block`, `test_core_message_interface_is_transport_neutral` (C);
  * validator mutations `can_id_base_unaligned`, `can_id_base_range` (C/Python parity);
  * `test_relocated_block_is_translated_to_protocol_numbers` (bridge);
  * `tests/integration/test_dbc.py`: the DBC for other teams' tools, cross-checked with cantools.
* A non-CAN transport would need its own binding: framing, link-loss detection, latency analysis. None is implemented.
