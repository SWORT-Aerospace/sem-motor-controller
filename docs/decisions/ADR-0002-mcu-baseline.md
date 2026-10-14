# ADR-0002 — MCU baseline

**Options evaluated (once).**

| | STM32G474 + external SPI gate driver | STSPIN32G4 (G431 + driver in one package) |
|---|---|---|
| CAN | 3× FDCAN | 1× FDCAN (snippet) |
| ADCs for phase currents | 5 ADCs; dual simultaneous sampling | 2 ADCs (snippet) |
| I/O for wired driver controls, watchdog, diagnostics | LQFP100: 34 spare after full allocation (verified against ST pin data) | VFQFPN-64; fewer |
| Gate drive | external (DRV8353 class: up to 1 A source / 2 A sink, snippet) | 1 A source/sink (snippet) |
| Failure-mode coupling | MCU and driver are separate devices; driver VDS protection is independent of MCU state | shared package |
| Board area | larger | smaller |

**Decision.** STM32G474, LQFP100, conditional on AF/timing review in CubeMX and the errata review (ES0430). STSPIN32G4 is kept as a fallback for a compact revision. Do not repeat this evaluation without new requirements.

**Evidence.** Pin check: `tools/pin_allocation.py` against `STM32_open_pin_data@7d1f151` (BSD-3). Device data from datasheets: **UNVERIFIED** (st.com unreachable; search-snippet level only).
