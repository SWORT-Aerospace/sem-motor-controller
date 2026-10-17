# ADR-0005: CAN contract v1

> **Amended by [ADR-0012](ADR-0012-transport-neutral-interface.md) (v0.3).** The message set, framing, integrity and session rules stand. The CHUDS references below describe a **reference project**, not our vehicle; the bus identifier block and the bit rate are now per-vehicle choices.

* **IDs:** 11-bit `0x300–0x33F`. Cornell's CHUDS (`cornellev/urban-concept@c422c0f`) uses `0x000–0x2FF` and *rejects* `0x300–0x7FF`, so there is no collision or mis-decode if the bus is ever shared. Consequence: on a shared bus every CHUDS frame has higher priority. The worst-case response estimate is still 3.6 ms for `sup_torque_req` against its 20 ms period (`tools/bus_load.py`, conservative model).
* **Framing:** 8-byte classic frames (FD-tolerant controller, so they coexist with CHUDS CAN-FD); 500 kbit/s nominal (CHUDS arbitration rate); Intel bit order.
* **Integrity:** byte 0 = CRC-8/SAE-J1850 over a 16-bit Data ID (`major << 11 | id`) followed by bytes 1–7. Byte 1 = u8 sequence. This detects corruption, wrong-ID and wrong-version decoding, and stale buffers combined with the sequence/time checks. **It is not authentication.** The bus is a physically trusted domain, and the cellular path must never write to it.
* **Session:** the companion announces `sup_hello{companion_session}`. The controller assigns an 8-bit `session_tag` (derived from its boot id) and echoes it in `ctrl_session`. A supervisor session is established only after both `sup_limits` and `sup_torque_req` carry that tag. A controller reboot or companion reboot invalidates the session, and ECO then needs a new driver edge.
* **Freshness:** a request renews validity only if its sequence advanced **and** its companion timestamp advanced consistently with local time. Duplicates, reordered frames and re-sent cached samples never renew.
* **Atomic multi-frame updates:** each request names the limits set it was computed against (`limits_ref`). The controller keeps the current and previous committed sets, and bounds each request by **its referenced set**. This fixed a real transient-dropout bug found in co-simulation.
* **Provisional timing:** 50 Hz request and 100 ms timeout, **simulation only**, pending the vehicle hazard and latency analysis. A hardware build refuses `timing_status = provisional_simulation_only`.
* **No PWM, arming, mode or reset messages exist.**
