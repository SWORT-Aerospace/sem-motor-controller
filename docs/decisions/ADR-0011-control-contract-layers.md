# ADR-0011: Four-layer control contract; hard ceilings clamp, envelopes ramp boundedly

**Status:** Accepted (supersedes the slew and limits-selection behaviour of v0.1)

**Context.** A review of v0.1 `mc_arbiter.c` / `mc_core.c` found three defects:
* a reduced local ceiling was approached by slewing at the fast rate instead of being applied;
* a supervisor envelope reduction was followed at the comfort rate;
* a request referencing an older, looser limits set was bounded by that set even after a tighter one had been committed.

A synthetic harness confirmed all three (`docs/generated/control_contract_before_after.md`).

**Decision.**
* Separate L0 independent hardware shutdown, L1 immediate inhibits, L2 local hard ceilings, L3 supervisory envelopes and L4 requests with comfort slew (`docs/CONTROL_CONTRACT.md`).
* L2 clamps `accepted` and `iq_ref` on the update in which the ceiling is computed. It is the final clamp in the arbiter.
* L3 reductions ramp at ≥ `slew_down_fast`, with the worst case bounded by the supervision timeout (validator rule 38).
* The envelope is `min(newest committed set, referenced set)`. A same-`limits_seq` refresh no longer evicts the previous set.

**Consequences.**
* Torque steps down on ceiling reductions, which is safe for a propulsion-only drive. Driveline shock is a vehicle input.
* One v0.1 test expectation that encoded the defect was corrected and made stricter.
* CAN v1.0 is unchanged. Companions must change `limits_seq` whenever the content changes.
