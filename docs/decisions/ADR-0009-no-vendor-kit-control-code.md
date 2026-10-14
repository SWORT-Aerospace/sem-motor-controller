# ADR-0009 — Purpose-built control core; MCSDK for reference only

**Context.** ST X-CUBE-MCSDK (latest seen 6.4.x, license SLA0048 "Ultimate Liberty", snippet-level) supports STM32G4 and provides a complete FOC stack. The SEM rules (UNVERIFIED search extracts) require a *purpose-built* controller and state that "motor controller evaluation kits, individual kit components, and their software are outlawed."

**Decision.** The control core (`firmware/src/*`) is project-written, portable C11 and host-tested. MCSDK may be consulted as a reference (ADC triggering, TIM1 configuration patterns, its documented algorithms) but **generated MCSDK motor-control code is not used** until (a) the 2027 rule text is read and (b) the organizers confirm whether a vendor SDK counts as "kit software". ST HAL/LL peripheral drivers (BSD-3) are treated like the permitted "single-board computer" parts. This is also pending confirmation.

**Assessment of duplicating MCSDK.** Duplication is limited to what the vehicle needs: one motor, hall FOC, no field weakening and no sensorless operation. The duplicated pieces are small (≈ 3 kB of fast-loop code on M4F) and fully tested on the host.
