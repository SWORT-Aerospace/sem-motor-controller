# ADR-0013: Telematics is the deliverable; the controller is another team's; the unit only listens

**Status:** Accepted (v0.7, 2026-10-18). Supersedes, for the deliverable, the controller scope of ADR-0002 to ADR-0005 and ADR-0009 to ADR-0012, which stay in force for the deferred controller development.

## Context
Up to v0.6 this repository designed a custom motor controller (STM32G474, DRV8353, INA228, power stage) together with a telematics unit that also ran an ECO supervisor sending torque requests to the controller. The team then corrected the scope: another team builds the vehicle's motor controller. Our deliverable is telematics: sensor acquisition, reception of the controller's data, local logging, uplink, pit tools, energy analysis and the CSIA monitors in shadow mode.

## Decision
1. **Scope.** The telematics unit and the pit software are the deliverable. Every module is classified as active telematics, reusable simulator or reference, or deferred controller ([`../scope.yaml`](../scope.yaml), [`../generated/scope.md`](../generated/scope.md)). Nothing on the telematics path builds, fabricates or needs our controller; its tests run as a separate suite (`pytest -m controller`) and CI job.
2. **Receive-only.** The deployed telematics application sends nothing to the controller: no torque request, no arming, no fault reset, no configuration change, and it takes no part in protection or precharge. The CAN controller runs in bus-monitoring mode and the transceiver's transmitter is disabled in hardware. Polling the controller would be a separate decision, with the controller team's written agreement.
3. **The ECO supervisor leaves the deployed path.** It is kept as a legacy mode (`host/telemetry_adapter/legacy_node.py`, `--legacy-supervised` on the legacy demonstrations), never selected by default.
4. **Controller data through adapters.** Controller reception is an adapter that turns frames into a common measurement record: source, signal, unit, receive time, sample time only when the source gives one, timestamp uncertainty, the source's sequence counter only when it has one, validity, provenance. Local record identifiers are kept separate from source sequence numbers. Our `semmc` message set is a simulation fixture; the real controller is read through a DBC adapter with a unit-checked mapping once its team supplies the DBC.
5. **Missing is not zero.** A missing, stale or invalid value is recorded and reported as such (null, with its validity), never as zero; standstill is reported only with positive evidence.
6. **Analysis is offline or advice.** Energy figures come only from valid, time-aligned voltage and current, with the missing intervals, the boundary (controller input or battery) and the uncertainty stated. Strategy results go to the driver as advice; there is no automatic speed control. CSIA stays in shadow mode (ADR-0008) and its frozen evaluation is unchanged.
7. **Budget from telematics lines only.** The telematics cost is summed from its own lines ([`../TELEMATICS_BOM.md`](../TELEMATICS_BOM.md)), never by subtracting controller subtotals from the earlier combined budget.

## Consequences
* New code: `host/telematics/measurement.py`, `signals.py`, `controller_adapter.py`, `wheel.py`, `sim_vehicle.py`; the node rewritten without a supervisor (`sem.telemetry.v4`); the pit's `measurements` table and two-boundary energy; the NUCLEO-U575ZI-Q firmware in `telematics/firmware/`.
* The pit rejects a live message that carries a supervisor or controller-command block, and the demonstration checks that no command frame is sent.
* A firmware that only listens does not by itself prove electrical noninterference: the bench checks E1 to E6 ([`../../telematics/firmware/BENCH.md`](../../telematics/firmware/BENCH.md) section 6) come before any vehicle bus.
* The controller items of the blocker register (power-stage ratings, precharge, footprints, the current loop) are marked as the controller track and block no telematics stage ([`../IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md)).
* No controller work is deleted; the v0.6 records stay as they were written.
