# Shell Eco-marathon rules vs the exact hardware and software (v0.2)

> **Superseded by [`RULES_COMPLIANCE.md`](RULES_COMPLIANCE.md)** (v0.5, checked against the 2026 Chapter I text). Kept as the v0.2 record; the statements below are not updated.

**Evidence status: every rule text below is UNVERIFIED.** No official rule PDF could be opened from this environment. The quotes are web-search extracts:
* 2025 Chapter I, Art. 66a;
* the 2026 event checklists ("Purpose built motor controller (66 a)");
* the 2026 Chapter IV exemption for the autonomous competition;
* the official "technical tips" page (undated).

The 2027 Chapter I text **must be read** before any conclusion here is treated as final. The details are in `RULES_COMPLIANCE.md` and the session research notes.

## 1. What the text says, and what it does not

| Text (extract) | Scope as written |
|---|---|
| "the motor controller MUST be purpose-built for Shell Eco-marathon. Modifications to purchased motor controllers or the use of purchased motor controller evaluation kits are not acceptable." (Art. 66a, 2025 extract) | (a) purpose-built controller; (b) no purchased motor controller, modified or not; (c) no purchased **motor-controller evaluation kit** |
| "Motor controller evaluation kits, individual kit components, and their software are outlawed." (tips page) | (d) no kit, no individual **component of such a kit**, and no **software of such a kit** |
| "individual system components like a single-board control computer and the power driver stage can be specified and integrated into the system" (tips page) | (e) the team may specify and integrate components, including a control computer and a power driver stage |
| "Teams that design their own controller or power stages on a PCB should have the letters 'SEM' etched onto the board" (tips page) | (f) etch "SEM" on custom PCBs |
| "include design documentation on the purpose-built motor controller" (2020/2025 extract) | (g) design documentation |

**Not addressed by any extract found:**
* general-purpose MCU support libraries (CMSIS, ST HAL/LL), compilers and code generators for clock or pin initialisation;
* a vendor motor-control SDK obtained on its own rather than as the software of a purchased kit;
* using an evaluation board **on the bench only**, never in the vehicle.

These are open questions for the organisers. They are **neither prohibited nor permitted** by the text in hand, and this project does not treat "kit software is outlawed" as a ban on all vendor SDKs.

## 2. Element-by-element mapping

| Element of this design | Relevant text | Assessment | Confidence / action |
|---|---|---|---|
| Custom PCB designed by the team (KiCad draft) with an MCU, gate driver, MOSFETs and sensing | (a), (e) | consistent: a purpose-built controller assembled from specified components | medium (text unverified); add the "SEM" etch (f) to the layout checklist |
| STM32G474 MCU (an IC) | (e) | an individual IC, not a kit or a kit's board. (d) "individual kit components" is read as the boards or modules of a kit, not semiconductor parts that also appear on evaluation boards. **Interpretation to confirm.** | ask the organisers (§3 Q1) |
| DRV8353 gate driver (an IC) | (e), (d) | as above: the IC, not a DRV835x evaluation module | ask (§3 Q1) |
| Control firmware `firmware/src/*` (state machine, arbiter, FOC, protection, freshness, configuration) | (a) | project-written, host-tested; no kit software | high |
| ST CMSIS / HAL / LL for peripheral bring-up (platform layer, not yet written) | not addressed | general MCU support, not motor-controller kit software; **not prohibited by the quoted text** | ask (§3 Q2) before relying on it; a register-level LL/CMSIS-only platform is the low-risk path |
| ST X-CUBE-MCSDK (FOC library, Motor Control Workbench) | (d) "their software": ambiguous, because MCSDK is also the software shipped with ST motor-control kits | **not used**: not needed (the control core exists and is tested) and its status is ambiguous. This is not a claim that vendor SDKs in general are banned. | ask (§3 Q3) only if a future decision wants it |
| TI motor-control software for the DRV8353 (EVM GUI, firmware examples) | (d) | not used; the DRV8353 is configured by project code over SPI | high |
| Evaluation boards for bench development only (e.g. a NUCLEO board as a programmer) | not addressed for bench-only use | never installed in the vehicle; an ST-LINK programmer is a tool | ask (§3 Q4) if any evaluation board is used for firmware development |
| Companion computer, CSIA, optimiser, telemetry | (e) single-board control computer | team software on a general-purpose computer | high; its energy counts (joulemeter placement, Art. 56c extract) |
| E-stop isolation | Art. 37 extract: "The use of a power controller or other logic systems to drive an isolation device is not permitted" | the controller only **senses** the safety loop (opto). Isolation is vehicle hardware; the board's precharge bypass is not the isolation device. | medium: confirm the precharge bypass is not considered an "isolation device" (§3 Q5) |
| Dead-man | Art. 37i extract | in the vehicle safety loop (hardware) and sensed by firmware | medium |

## 3. Questions for the organisers (and the 2027 rule text)
1. Does "individual kit components" refer to boards and modules of a kit, or also to ICs that appear on evaluation boards (for example a gate-driver IC used on the team's own PCB)?
2. May a purpose-built controller use the MCU vendor's general peripheral libraries (CMSIS, HAL/LL) and pin/clock initialisation generators?
3. Is a vendor motor-control SDK (for example ST MCSDK), used without any purchased kit, "kit software" under Art. 66a?
4. May an evaluation board be used on the bench during development if it is never installed in the vehicle?
5. Is an on-board precharge bypass switch controlled by the motor controller acceptable, given that the e-stop isolation device is separate, vehicle-level and not logic-driven?
6. 2027 Chapter I: confirm the Art. 66a wording, the battery voltage limit, the joulemeter position and the documentation requirements for the controller.
