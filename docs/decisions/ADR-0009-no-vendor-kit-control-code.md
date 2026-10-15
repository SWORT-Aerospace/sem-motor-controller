# ADR-0009 — Purpose-built control core; MCSDK for reference only

**Context.** ST X-CUBE-MCSDK (latest seen 6.4.x, license SLA0048 "Ultimate Liberty", snippet-level) supports STM32G4 and provides a complete FOC stack. The SEM rules (UNVERIFIED search extracts) require a *purpose-built* controller and state that "motor controller evaluation kits, individual kit components, and their software are outlawed."

**Decision.** The control core (`firmware/src/*`) is project-written, portable C11 and host-tested. MCSDK may be consulted as a reference (ADC triggering, TIM1 configuration patterns, its documented algorithms) but **generated MCSDK motor-control code is not used** until (a) the 2027 rule text is read and (b) the organizers confirm whether a vendor SDK counts as "kit software". ST HAL/LL peripheral drivers (BSD-3) are treated like the permitted "single-board computer" parts. This is also pending confirmation.

**Assessment of duplicating MCSDK.** Duplication is limited to what the vehicle needs: one motor, hall FOC, no field weakening and no sensorless operation. The duplicated pieces are small (≈ 3 kB of fast-loop code on M4F) and fully tested on the host.

**Scope clarification (v0.2).**
* This ADR is **not** a ruling that vendor SDKs or libraries are prohibited. The rule text in hand (unverified extracts) bans:
  * purchased controllers;
  * purchased motor-controller evaluation kits;
  * the individual components of such kits;
  * the software of such kits.
* It does not address general MCU libraries (CMSIS, HAL/LL), a vendor SDK obtained without a kit, or bench-only use of evaluation boards.
* MCSDK is not used because the project does not need it and because its "kit software" status is ambiguous.
* HAL/LL use for the platform layer is undecided and pending the organisers' answer. A register-level LL/CMSIS platform is the low-risk default.
* Element-by-element mapping and organiser questions: `docs/RULES_RECONCILIATION.md`.
