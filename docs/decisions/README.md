# Architecture decision log

| ADR | Title | Status |
|---|---|---|
| [0001](ADR-0001-repository-placement.md) | Project placement inside SWORT, separate from CSIA research | Accepted (placement to be confirmed by owner) |
| [0002](ADR-0002-mcu-baseline.md) | STM32G474 (LQFP100) baseline; STSPIN32G4 evaluated once, not selected | Accepted (conditional) |
| [0003](ADR-0003-motor-architecture.md) | Three-phase inverter + sensored FOC, conditional on motor | Accepted (conditional on C1) |
| [0004](ADR-0004-unfrozen-power-stage.md) | Power-stage ratings remain unfrozen until measured | Accepted |
| [0005](ADR-0005-can-contract.md) | CAN contract: IDs, framing, integrity, session handshake | Accepted |
| [0006](ADR-0006-unknowns-never-defaulted.md) | Unknown parameters stay null; hardware build fails closed | Accepted |
| [0007](ADR-0007-regen-deferred.md) | Active regeneration, field weakening, adaptive control deferred | Accepted |
| [0008](ADR-0008-csia-shadow-mode.md) | CSIA in shadow mode behind an evidence gate | Accepted |
| [0009](ADR-0009-no-vendor-kit-control-code.md) | Purpose-built control core; ST MCSDK used for reference only | Accepted (pending rule verification) |
| [0010](ADR-0010-wired-driver-authority.md) | Driver controls wired to the controller, never via CAN | Accepted |
