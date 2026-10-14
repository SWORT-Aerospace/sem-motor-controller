# ADR-0007 — Deferred features

Active regeneration (`limits.regen_enabled` must be false; validator rule `REGEN_DEFERRED`), field weakening, variable switching frequency, discontinuous PWM, MTPA, and online parameter adaptation are deferred until their baseline benefit **and** hazards are measured. Reasons:
* Regenerative braking legality is not established (no rule found; a 2025 clause gives no credit for negative net energy).
* The battery/BMS charge acceptance is unknown.
* Regeneration pumps the DC bus toward the (unverified) 60 V by-design limit.
* No source in hand quantifies the benefit for this vehicle (MDPI P3 inaccessible).

Coasting is gate-off by default in the synthetic config. The config validator rejects any configuration whose line-line back-EMF at the overspeed trip exceeds the minimum battery voltage (`BACKEMF_EXCEEDS_MIN_BUS`), so gate-off coasting cannot become uncontrolled rectification braking.
