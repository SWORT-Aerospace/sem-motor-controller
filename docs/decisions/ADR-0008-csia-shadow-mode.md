# ADR-0008 — CSIA shadow mode and evidence gate

CSIA runs on the companion as a vehicle adapter (`host/csia_adapter`) wrapping the pinned `TrustCore` (Python, double precision). The controller only tracks and re-reports `csia_advisory` frames; `mc_csia_may_restrict()` is hard-wired `false`.

**Why not more now.**
* The CSIA research relationships are aircraft-specific.
* The native C kernel is documented by CSIA itself as **not on any production path**, and its STM32H743 timing figures are **estimates**.
* CSIA *holds* a stale trust belief when evidence disappears, so trust alone cannot gate commands.

The adapter therefore reports freshness, evidence, observability and trust separately, and it never forces single-sensor blame.

**Evidence gate before CSIA may restrict supervisory commands** (all required; see VALIDATION_PLAN §6):
1. ≥ 10 h of in-vehicle shadow data across representative normal events.
2. A nuisance-alarm rate below a pre-registered bound.
3. Detection and isolation of every injected fault class within pre-registered latency, with zero misattributions.
4. Measured incremental benefit over B1/B2 baselines.
5. A target timing benchmark (or a float port validated against defined numerical tolerances — not claimed parity).
6. A new ADR.

Restriction would only ever **tighten** supervisory bounds. It never commands torque and never acts on the controller's own protection.
