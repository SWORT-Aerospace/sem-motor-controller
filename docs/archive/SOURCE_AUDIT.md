# Source audit

Audit date 2026-10-14. Every material claim in this project is tagged:
**[V]** verified from a source read during this audit (v0.1) · **[P]** proposed engineering decision · **[A]** assumption for simulation · **[U]** unknown, needs measurement or user input · **[S]** search-snippet only (not evidence; recorded so it can be checked).

## 1. Workspace

| Item | Finding |
|---|---|
| Working repository | `andrefp-co/swort` (SWORT website deploy output; commits authored by the owner), branch `claude/nice-bell-98hxr2`, base `33a71cc`. Clean before work. [V] |
| Placement | New self-contained directory `sem-motor-controller/` (ADR-0001). No other path modified. [P] |
| Attachments `bk4000tg_kicad.zip`, `telemetry.pdf` | **Not present** in the container (`/mnt/user-data/uploads` and `/mnt/attach` are empty; a filesystem search found nothing). **None of the "known findings" about the attached PCB or the telemetry proposal could be rechecked.** They are carried below as reported by the user, marked [U]. |
| Network | Only GitHub and PyPI were reachable. `www.ti.com`, `www.st.com`, `www.infineon.com`, `www.shellecomarathon.com`, `schmid-elektronik.ch`, `www.mdpi.com`, `mdpi-res.com`, `doi.org` were blocked (proxy 403 / DNS). Datasheets, rules and papers are therefore **[S] at best**. |

## 2. Repositories inspected (read-only)

| Repository | Commit | License | Use in this project |
|---|---|---|---|
| `SWORT-Aerospace/csia-trust-layer` | `848f5563a528ae5ca3c2d3883c86d7287d6a4585` (v0.8.0) | **Proprietary (SWORT LLC)**: evaluation/internal assessment only; "No redistribution, sublicensing, production deployment, or use in safety-critical operations without a written commercial license" | Pinned dependency (`third_party/csia-trust-layer.lock`), fetched to `.deps/`. **No source copied.** Using it on a vehicle, even in shadow mode, needs the owner's written license decision (§6). |
| `cornellev/uc26_sensor_reader` | `3471a9737b8b3dcacc15901cd6b6b51011f614ec` | MIT | Evidence only; nothing copied |
| `cornellev/urban-concept` | `c422c0f2d794926b9aa6400e094f2faebe4a9e5a` | MIT | Evidence only (CAN ID map); nothing copied |
| `STMicroelectronics/STM32_open_pin_data` | `7d1f1514ed5583ec5007ad91236b4e1d377295b1` | BSD-3-Clause | Read by `tools/pin_allocation.py` (sparse checkout of `mcu/STM32G474*.xml`); not vendored |

### 2.1 CSIA paths inspected
`LICENSE`; `pyproject.toml`; `csia/__init__.py`; `csia/trust_engine/engine.py` (`TrustCore.step`, `EngineConfig`); `csia/trust_graph/graph.py`; `csia/native/csia_core.c`, `build.sh`; `docs/embedded/NATIVE_RUNTIME_STATUS.md`; `csia/runtime/online.py` (freshness handling, lines ~45, 603–622); `csia/diagnosis/hypothesis.py` (AMBIGUOUS outcome, lines 80, 263, 507, 614); directory listing of `campaigns/ papers/ datasets/ reports/ research/ experiments/ deliverables/ artifacts/` (not modified).

| Recheck item | Verdict | Evidence |
|---|---|---|
| Physical relationships are aircraft-specific | **[V]** | `csia/trust_graph/graph.py` nodes `imu0, imu1, baro, mag, gps, motor_esc, battery, vibration`; edges include `altitude_baro`, `attitude_gravity_mag`, `vibration_prop_freq`, `power_thrust` |
| Native C kernel is not the production runtime | **[V]** | `docs/embedded/NATIVE_RUNTIME_STATUS.md`: "The C core is not on any production execution path"; the runtime is Python `TrustCore` via `OnlineTrustLayer` |
| Historical STM32 timing figures are estimates | **[V]** | Same file: "≈ 7–15 µs on STM32H743; Estimate; Extrapolation from host timing. No target measurement exists." (H743, not G4) |
| Native kernel precision | **[V]** double | `csia_core.c` uses `double` throughout; status doc: "implementation is `double`" |
| Missing evidence retains an old trust belief | **[V]** | `csia_core.c`: Beta update only `if (fresh[i] && wsum > 0.0)`; otherwise `alpha/beta` are held. `engine.py` mirrors this ("Absence of evidence is absence: hold the Beta belief"). The adapter therefore reports freshness, evidence and `trust_current` **separately** (`host/csia_adapter/adapter.py`). |
| Diagnosis can report ambiguity | **[V]** | `hypothesis.py` `IsolationOutcome.AMBIGUOUS`; "Ambiguity is reported, not resolved by argmax" |
| Core usable for non-aircraft signals | **[V]** | `TrustCore(names, cfg).step(edges, phys, hist, var_ratio, fresh)` takes arbitrary node names and edge dicts; the import path needs numpy only (verified by import during the v0.1 audit) |

### 2.2 Cornell repositories: recheck of reported findings

> **v0.3 provenance label.** The Cornell repositories are **reference projects**. Nothing in them is a fact about our vehicle: not CHUDS, the VCU, the CAN bit timing, the emergency messages or the harness. `docs/archive/PROVENANCE_AUDIT.md` lists where earlier versions of this project assumed otherwise and what was corrected.
(Detailed file:line evidence was in the v0.1 research notes, which are not part of the repository; summary here.)

| Reported finding | Verdict | Evidence |
|---|---|---|
| Older reader uses independently generated sensor timestamps | **[V]**, with nuance | `uc26_sensor_reader/README.md:66-67` "timestamps are generated independently on each sensor microcontroller"; Picos stamp with their own `time_us_64()` (`spi_slave.c:216`, `rpm_firmware.c:208`). Nuance: `global_ts`/GPS time come from the Pi's monotonic clock (`write_shm.cpp:578, 627`). The newer CAN telemetry carries **no** timestamp. |
| Retains filtered speed after invalid RPM | **[V]** | `write_shm.cpp:602-604` keeps the previous estimate; the failed frame gives NaN (679-681); the `Filtered` struct has no validity or timestamp (221-223). The same code is in `urban-concept/telem/shm/write_shm.cpp:582-596`. |
| Hard-coded current offset | **[V]** | `write_shm.cpp:633` `f32_le_bytes(p + 4) - 0.45f; // temp bias needed` (also `urban-concept/.../write_shm.cpp:618`) |
| Newer repo has CAN-FD infrastructure and distributed firmware | **[V]** | `cev-lib/chuds/`, `cev-lib/RP2040_MCP251863_Driver`; five RP2040 projects in `elec/CMakeLists.txt:40-44` |
| Wheel fields = edge counts per window | **[V]** | `chuds/catalog.hpp:36-37, 52-53` "wheel edges in the last window"; window = 100 ms publish period; the fields are misleadingly named `rpm_*` |
| 500 ms joulemeter interval, placeholder calibration | **[V]** | `elec/src/joulemeter/config.hpp:29` `kReportPeriodMs = 500`; lines 22-26 "placeholder until hardware is set" (zero offset 0.0, 3.3/200 V/A) |
| No complete traction-controller implementation | **[V]** | No motor-control/PWM/inverter/FOC code. The only PWM is a wiper servo (`back_aux/main.cpp:106-113`). The drive-command timeout is an open question (`chuds/docs/addressing.md:67-68`). |
| CAN IDs in use | **[V]** | 11-bit; class (3 bits) + subaddress. Emergency `0x000–0x0FF`, Command `0x100–0x1FF`, Telemetry `0x200–0x2FF`; **`0x300–0x7FF` rejected**. Used: `0x108` BodyState, `0x210` front_aux, `0x220` back_aux, `0x230` joulemeter, `0x140` (doc example only). CAN-FD, BRS, 500 kbit/s / 2 Mbit/s at 80 % sample point (`chuds/frame.hpp:16-19`). The table is "Provisional until the team ratifies" (`chuds/README.md:112`). |
| Category | **[V]** Urban Concept (`urban-concept/README.md:3`) |
| Vehicle parameters | Cornell wheel diameter 0.58166 m (`write_shm.cpp:36`), 32 pulses/rev in old firmware **[V for Cornell's car]**. These are **not** assumed to be our vehicle. Motor, gear, battery, mass, fuses: **NOT FOUND**. |

### 2.3 Attached PCB and telemetry proposal (reported by user, NOT rechecked)
STM32U575, NEO-M9N, A7672X, MC3419, NOR flash, BQ25622E, MCU FDCAN RX/TX on a header, no traction inverter or CAN transceiver, R8 at the charger ILIM pin marked TBD, four layers; the proposal describes a battery-electric **Prototype**. **[U]** All unverified here because the attachments were unavailable. The board is not treated as a motor-controller base in any case: it has no power stage and no transceiver.

## 3. Web references (all blocked; status recorded honestly)

| Reference | What was obtained | Status |
|---|---|---|
| SEM Global Rules page, 2026/2027 Chapter I | Search extracts only (2026 Ch I file name dated 2025-09-12; 2027 Ch I exists, contents unread) | **[S]**: see RULES_COMPLIANCE.md |
| schmid-elektronik.ch/bootcamp-sem26 | Search extracts: a 1-hour data/telemetry bootcamp (joulemeter, telemetry wiki, Off-Track award); no power-electronics content | **[S]** |
| TI TIDA-010056 / TIDUEQ9A | Snippets: TIDUEQ9A is the TIDA-010056 guide (Rev A, 2019): 54 V, 1.5 kW, DRV8350R + 6× CSD19536KTT, sensored **trapezoidal** 20 kHz, MSP430 | **[S]**: a usable *power-stage/layout* reference, not an FOC reference |
| TIDA-010250 | Snippet: 165–265 VAC input, IGBT, 1 kW | **[S]**: mains design, **not** our reference (as the brief warned) |
| DRV8353, INA228, TCAN1042HGV, STM32G474VE, STSPIN32G4 | Snippet-level ratings and revisions (see BOM `revision` column) | **[S]** |
| MDPI Energies 15(10)3631, 16(3)1394, 16(6)2682 | Titles and DOIs only | **INACCESSIBLE**: no content used |

## 4. Toolchain used (actual)

gcc 13.3.0 · cmake 3.28.3 · ninja · arm-none-eabi-gcc 13.2.1 (portability compile only) · Python 3.13 with numpy 2.5.3, matplotlib 3.10.7, PyYAML 6.0.1, jsonschema 4.26.0, pytest 8.4.2 (pinned in `requirements.txt`) · ASan/UBSan.

## 5. What was not copied
No code was copied from any inspected repository. The CSIA core is imported at runtime from a pinned checkout. ST pin XML is read at tool runtime, not committed.

## 6. License actions required (owner)
* Decide in writing whether the CSIA core may be used in a **vehicle** context (even shadow mode). The current license text excludes "production deployment" and "safety-critical operations" without a written commercial license.
* Confirm the redistribution status of this project's own code (no license file added; inherits the host repository's terms by default).
