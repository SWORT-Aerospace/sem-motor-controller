# config: vehicle and controller configuration

`config/` holds the motor controller's configuration: which parameters exist, the structure a configuration file must have, a synthetic configuration that lets the software run in simulation, and the real-vehicle configuration, which stays unconfigured until its values are measured or verified. Nothing here describes real hardware yet: every number in use is a synthetic placeholder.

## 1. Files

| File | Role | Edited by hand? |
|---|---|---|
| [`parameters.yaml`](parameters.yaml) | Parameter registry: the single source of truth for every configuration parameter (identifier, type, plausibility bounds, whether it is required for a simulation or a hardware build) | yes |
| [`vehicle.schema.json`](vehicle.schema.json) | JSON Schema of the structure of `vehicle.*.yaml` | **no: generated** from `parameters.yaml` |
| [`vehicle.synthetic.yaml`](vehicle.synthetic.yaml) | Synthetic configuration for host simulation, tests and model development; every value is a placeholder | yes, for simulation needs only |
| [`vehicle.unconfigured.yaml`](vehicle.unconfigured.yaml) | Real-vehicle configuration: null wherever a value has not been measured or verified; fails hardware validation by design | yes, only to enter verified or measured values |

Run every command below from the repository root, inside the environment created from [`../requirements.txt`](../requirements.txt) (PyYAML and jsonschema are needed).

## 2. The parameter registry (`parameters.yaml`)

Each entry of `params:` describes one parameter of the calibration:

| Field | Meaning |
|---|---|
| `id` | Stable numeric identifier in the binary calibration blob. Identifiers are unique and lie in 1 to 255; an identifier is never reused. An array occupies `id` to `id + array - 1`. |
| `path` | Dotted path in `vehicle.*.yaml`, for example `motor.phase_resistance_ohm` |
| `kind` | `real`, `int`, `bool` or `enum` (an enum names one of the `enums:` lists, such as `provenance: {unset, synthetic, bench_measured}`) |
| `min`, `max` | Inclusive plausibility bounds for `real` and `int`. They are deliberately wide, to catch typing and unit errors (millihenry typed as henry), not to encode design limits |
| `req_sim` | The value must be non-null for a host simulation build |
| `req_hw` | The value must be non-null for a hardware-enabled build |
| `array` | Number of elements, for array parameters |

The registry currently holds 82 parameters (91 blob elements, because `motor.hall_code_to_sector` has 8 elements and `inverter.current_offset_counts` has 3), 7 enumerations and 7 text fields under `strings:` (calibration identifier, who measured, when, instrument references, motor model, competition event, hazard-analysis reference). Text fields are not in the blob; they are carried as metadata. Almost every parameter is required in both modes; the exceptions are `motor.hall_supply_V` (not required for simulation) and `motor.inertia_kg_m2` and `vehicle.drivetrain_efficiency` (not required for hardware).

Units are SI (International System of Units) unless the name says otherwise (`degC` is written in the name). The sign and transform conventions (battery current positive on discharge, amplitude-invariant Clarke transform, line-to-neutral resistance and inductance, and so on) are listed at the top of the file; every configuration repeats them in its `conventions:` block, and the schema accepts no other value.

## 3. The JSON schema (`vehicle.schema.json`, generated)

The schema checks structure only: every section and every key must be present (an unknown value is written as `null`, never left out), no unknown key is accepted (a misspelt key is rejected), enum fields take one of their names, numbers stay within the registry bounds, and the conventions must have their fixed values. Whether a value is required for a build, and the cross-parameter engineering rules, are checked by `tools/config_tool.py` and by the C validator `firmware/src/calibration/mc_config.c`, which implement the same rule set. Rule codes are stable numbers; `tests/integration/test_config_parity.py` feeds identical modified configurations to both validators and requires identical codes.

## 4. The synthetic configuration (`vehicle.synthetic.yaml`)

For simulation only. Every number was chosen so that the host simulation, the tests and the models can run while the real motor, battery and vehicle are unknown; none is measured or taken from a datasheet. The values are consistent with each other (they pass the cross-parameter rules), which says nothing about real hardware. Its motor is fictional (`SYNTHETIC-PMSM-A`; PMSM: permanent-magnet synchronous motor), and its battery (12 cells in series, 43.2 V nominal) is a placeholder, not the team's battery.

* `calibration.provenance` is `synthetic` and `physical_output_permitted` is `false`; the validator rejects a synthetic configuration that tries to enable a physical output.
* It is valid for `--mode sim` and invalid for `--mode hw` (7 issues: synthetic provenance, physical output not permitted, missing measurement metadata and hazard-analysis reference, provisional supervision timing).
* The C build encodes it into `build/cal/synthetic.bin`, the blob used by the host executable, the tests and the demonstrations in [`../host/README.md`](../host/README.md). The host tools read the YAML too (wheel circumference, gear ratio, torque limit, and pole pairs and flux linkage for the torque constant).
* Its values must never be copied into `vehicle.unconfigured.yaml` ([`../docs/OPEN_PARAMETERS.md`](../docs/OPEN_PARAMETERS.md) lists each synthetic value next to how the real one is to be obtained).

## 5. The unconfigured hardware configuration (`vehicle.unconfigured.yaml`)

Every value that has not been verified from a source or measured on the real vehicle is `null`, and a null is never replaced by a plausible default (architecture decision record [`../docs/decisions/ADR-0006-unknowns-never-defaulted.md`](../docs/decisions/ADR-0006-unknowns-never-defaulted.md)). Apart from `schema_version`, `label` and the conventions, the only non-null entries are the placeholders `calibration.id: "UNSET"`, `calibration.provenance: unset` and `supervision.timing_status: provisional_simulation_only`, the notes, and three decisions marked `DECISION` in the file: `physical_output_permitted: false`, `regen_enabled: false` (ADR-0007, regeneration deferred) and `regen_current_limit_A: 0.0`.

It fails `--mode hw` by design. At present the result is **93 issues**: 84 required values missing, 6 required text fields empty, 2 provenance issues (not `bench_measured`, physical output not explicitly permitted) and 1 supervision timing not hazard-analysed. It also fails `--mode sim` (85 issues), so it cannot drive a simulation either.

A hardware-enabled CMake configure (`-DSEMMC_HARDWARE_BUILD=ON`) runs `tools/config_tool.py validate <config> --mode hw` on this file by default (`SEMMC_VEHICLE_CONFIG`) and stops with "Hardware build refused". Even with a valid configuration it stops afterwards, because the STM32G4 platform layer is not implemented ([`../firmware/CMakeLists.txt`](../firmware/CMakeLists.txt)).

**Battery.** The team reported **48 V nominal and 10 Ah rated** (team message of 2026-10-16; not verified against a datasheet). These values are recorded only in `battery.notes`. The verified fields (`battery.nominal_voltage_V`, cell count, voltage limits, BMS current limits; BMS: battery management system) stay null until the battery and BMS datasheets confirm them; 10 Ah is a charge capacity, not a current limit. Details and what is still required: [`../docs/BATTERY.md`](../docs/BATTERY.md).

## 6. Commands

| Command | What it does | Exit status |
|---|---|---|
| `python3 tools/gen_config.py` | Writes `config/vehicle.schema.json` and `firmware/include/semmc/mc_params_generated.h` from `parameters.yaml` | 0 |
| `python3 tools/gen_config.py --check` | Compares both files with what the generator would write, without writing; run in continuous integration (CI) | 0 current, 1 stale |
| `python3 tools/config_tool.py validate config/vehicle.synthetic.yaml --mode sim` | Validates a configuration (schema, required text fields, required values, ranges, cross-parameter rules) on the values rounded to 32-bit floats, as the blob stores them; prints every issue with its rule code | 0 valid, 1 invalid, 2 usage or file error |
| `python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw` | The same in hardware mode; CI requires this to fail | currently 1 (93 issues) |
| `python3 tools/config_tool.py blob config/vehicle.synthetic.yaml --mode sim -o build/cal.bin` | Validates, then writes the binary calibration blob (header `SMCB` of 32 bytes, one 8-byte entry per non-null element, a CRC-32 check value (32-bit cyclic redundancy check) at the end; 764 bytes for the synthetic file). Nothing is written when the configuration is invalid, unless `--allow-invalid` is given (negative tests only) | as `validate` |

Results on 2026-10-17: `gen_config.py --check` exit 0; synthetic `--mode sim` VALID; synthetic `--mode hw` INVALID (7 issues); unconfigured `--mode hw` INVALID (93 issues); unconfigured `--mode sim` INVALID (85 issues); `tests/integration/test_config_parity.py` 81 passed.

## 7. Generated from `parameters.yaml` (do not edit by hand)

`tools/gen_config.py` (registry loader: `tools/config_registry.py`) generates two files, each headed "GENERATED from config/parameters.yaml by tools/gen_config.py - do not edit":

* `config/vehicle.schema.json`: the JSON Schema of section 3.
* `firmware/include/semmc/mc_params_generated.h`: the C parameter-identifier enumeration, the enumeration codes, and the parameter table (`MC_PARAM_TABLE_INIT`: identifier, kind, required-for-simulation and required-for-hardware flags, bounds, path for each of the 91 elements) that the firmware validator uses.

The C build also generates `build/cal/synthetic.bin` and `build/cal/unconfigured.bin` from the YAML files with `config_tool.py blob` (the unconfigured one with `--allow-invalid`, for negative tests). After a change to `parameters.yaml`, run `python3 tools/gen_config.py` and commit the regenerated files.

## 8. How a measured value enters

1. Find the parameter in [`../docs/OPEN_PARAMETERS.md`](../docs/OPEN_PARAMETERS.md), which says how each one is obtained (measure, datasheet, team decision, rules, calculation) and which convention applies.
2. Obtain the value from a measurement or a verified source, never from the synthetic file.
3. Record its provenance in `docs/OPEN_PARAMETERS.md`, as the header of `vehicle.unconfigured.yaml` requires: where the value came from (the measurement or the source document). For a bench calibration, the hardware mode also requires the text fields `calibration.measured_by`, `calibration.measured_at` and `calibration.instrument_refs`.
4. Replace the `null` in `vehicle.unconfigured.yaml` with the value, in the units and conventions of the registry.
5. Run `python3 tools/config_tool.py validate config/vehicle.unconfigured.yaml --mode hw`. The number of issues falls, and cross-parameter rules (codes 10 to 40) start to apply as soon as every value a rule involves is present, so a new value can reveal an inconsistency.

A hardware build needs, beyond every required value: `calibration.provenance: bench_measured`, `physical_output_permitted: true` set explicitly, the measurement metadata (`measured_by`, `measured_at`, `instrument_refs`), a hazard-analysis reference and `timing_status: hazard_analysed`.

To add a parameter: add it to `parameters.yaml` with a new identifier, run `python3 tools/gen_config.py`, add the key to both `vehicle.*.yaml` files (the schema requires every key; `null` in the unconfigured file), and add any cross-parameter rule to both `tools/config_tool.py` and `firmware/src/calibration/mc_config.c` so the parity test still passes.
