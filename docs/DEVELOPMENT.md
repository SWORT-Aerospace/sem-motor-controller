# Development guide

The longer procedures behind README section F: setting up, the everyday loop, regenerating files, the hardware checks, the full verification and what CI runs. Every command is run from the repository root inside the virtual environment. Tool-by-tool detail (inputs, outputs, side effects) is in [`../tools/README.md`](../tools/README.md); build detail for the C core is in [`../firmware/README.md`](../firmware/README.md) section 7.

## 1. Setting up

| Need | For | Install (Ubuntu 24.04) |
|---|---|---|
| gcc, CMake 3.20 or newer, Ninja | the C core and its tests | `sudo apt-get install build-essential cmake ninja-build` |
| Python 3.11 or newer with `venv` | everything in Python | `sudo apt-get install python3-venv` |
| Python packages (pinned) | models, codecs, MQTT client, KiCad file handling | `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt` |
| CSIA core (pinned commit) | CSIA tests and the shadow replay | `python3 tools/fetch_csia.py` (checks the commit against `third_party/csia-trust-layer.lock`) |
| Mosquitto | the MQTT tests and `run_mqtt_demo.py` | `sudo apt-get install mosquitto` (the service need not run; the tools start their own broker on a free loopback port). Elsewhere, point `SEMMC_MOSQUITTO` at the executable. |
| `arm-none-eabi-gcc` with newlib | the Cortex-M4F portability compile | `sudo apt-get install gcc-arm-none-eabi libnewlib-arm-none-eabi` |
| KiCad 7 (`kicad-cli`) | schematic connectivity check | `sudo apt-get install kicad` |
| KiCad 8 | the ERC | `ppa:kicad/kicad-8.0-releases` (as in CI); KiCad 7's `kicad-cli` has no ERC |

## 2. Everyday loop

```sh
cmake -S firmware -B build -G Ninja && cmake --build build && ctest --test-dir build --output-on-failure
python3 -m pytest -q                      # SEMMC_REQUIRE_MQTT=1 turns a missing broker into a failure
python3 tools/check_links.py              # run it without a pipe: its exit code is the result
```

The host build uses AddressSanitizer and UndefinedBehaviorSanitizer by default; `-DSEMMC_SANITIZE=OFF` disables them. `SEMMC_BUILD_DIR` points the Python tests at another build directory.

Longer property soak: `./build/test_core_properties 300 30 0x5EED2026` (arguments: seeds, seconds per seed, base seed).

Cortex-M4F compile of the portable core (compile check only; no firmware image):

```sh
cmake -S firmware -B build-arm -G Ninja -DCMAKE_TOOLCHAIN_FILE=$PWD/firmware/cmake/arm-none-eabi-cortex-m4f.cmake \
  -DSEMMC_PORTABLE_ONLY=ON -DSEMMC_SANITIZE=OFF -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build build-arm && arm-none-eabi-size -t build-arm/libsemmc_core.a
```

## 3. Regenerating files

Generated files are never edited by hand. Edit the source, run the generator, commit both.

| Source | Generator | Writes | CI check |
|---|---|---|---|
| `config/parameters.yaml` | `python3 tools/gen_config.py` | `config/vehicle.schema.json`, `firmware/include/semmc/mc_params_generated.h` | `--check` |
| `protocol/protocol.yaml` | `python3 tools/gen_protocol.py` | C and Python codecs, golden vectors, `docs/generated/can_messages.md` | `--check` |
| `protocol/protocol.yaml` | `python3 tools/gen_dbc.py` | `protocol/generated/semmc_base0x300.dbc` | `--check` |
| `hardware/bom/BOM_draft.csv`, `hardware/bom/pricing.yaml` | `python3 tools/price_bom.py` | `hardware/bom/BOM_priced.csv`, `docs/BUDGET.md`, `docs/generated/budget.json` | none: re-run and commit after a pricing change |
| `hardware/bom/procurement.yaml` (+ `budget.json`) | `python3 tools/gen_procurement.py` | the README budget table, `docs/PROCUREMENT.md` | `--check` |
| the generator's design data | `python3 tools/gen_kicad_schematic.py` | `hardware/kicad/*`, `hardware/bom/BOM_draft.csv` | `--check` then `git diff` (note: `--check` rewrites the files before comparing) |
| sensor and coast-down assumptions in the tools | `python3 tools/wheel_sensor_check.py`, `python3 tools/coastdown_sensitivity.py` | `docs/generated/wheel_sensor_check.md`, `docs/generated/coastdown_sensitivity.md` | `--check` |

Order after a pricing change: `price_bom.py`, then `gen_procurement.py` (it reads `budget.json`).

Demonstration outputs committed under `docs/generated/` are refreshed with `--samples`:

```sh
python3 tools/run_host_demo.py --out build/host_demo --samples docs/generated/host_demo
python3 tools/run_mqtt_demo.py --out build/mqtt_demo --samples docs/generated/mqtt_demo
```

`run_mqtt_demo.py` deletes its `--out` directory before it runs. The synthetic studies: `python3 tools/run_optimization.py` (full resolution; rewrites `docs/generated/optimization_synthetic.*`, the DP CSV files and `docs/figures/dp_plan_synthetic.png`); `--quick` writes to `build/optimization_quick/` and leaves the committed files alone.

## 4. Hardware checks

| Check | Command | Result |
|---|---|---|
| Schematic connectivity | `python3 tools/gen_kicad_schematic.py --check` | `hardware/kicad/CONNECTIVITY_CHECK.md`; exit 1 on any mismatch |
| Cross-artefact consistency | `python3 tools/hw_consistency.py` | `hardware/review/CONSISTENCY_CHECK.md`: PASS, FAIL or OPEN per item |
| Pin types | `python3 tools/pin_type_check.py` | `hardware/kicad/PIN_TYPE_CHECK.md` |
| ERC (KiCad 8) | `bash tools/run_kicad_erc.sh`, then `python3 tools/erc_summary.py hardware/kicad/ERC_REPORT.json --fail-on-errors` | `hardware/kicad/ERC_REPORT.*` (not tracked; CI keeps it as an artifact). Last CI result: 0 errors, 9 warnings |

The checks show that the files agree with each other; none shows that the circuit works ([`../hardware/README.md`](../hardware/README.md) section 6).

## 5. Full verification

```sh
python3 tools/verify_all.py --out build/verify            # quick mode
python3 tools/verify_all.py --full --out build/verify     # adds the soak, the full optimisation and the CSIA v1 re-run
```

It writes a record of every command, exit code, expected outcome, duration and summary lines, and lists the tracked files whose content changed during the run. Check that list before committing. A check that needs a tool you do not have (KiCad 8, Mosquitto) is recorded as NOT AVAILABLE, not as a pass. The last recorded result is in [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md).

## 6. Continuous integration

`.github/workflows/ci.yml` runs two jobs on GitHub-hosted Ubuntu 24.04 runners: `host` (generator checks, configuration validation, C build and tests, schematic connectivity gate, pytest with a required broker, the three host demonstrations, the Cortex-M4F compile, quick studies) and `erc` (KiCad 8 ERC). The step-by-step list is in [`../tools/README.md`](../tools/README.md) section 2. A change is not called fixed until a GitHub-hosted run has completed successfully on its commit.

## 7. Adding a test or a check

* A new behaviour gets a test that fails without the change and passes with it.
* Python tests go under `tests/<area>/` ([`../tests/README.md`](../tests/README.md)); C tests under `firmware/tests/` with an entry in `firmware/CMakeLists.txt`.
* A new generator gets a `--check` form and a line in the CI generator step.
* A new reproducible check is added to the `CHECKS` table of `tools/verify_all.py` with its expected outcome.
* New current documents are added to `CURRENT` in `tools/check_links.py`, so their backtick paths are checked too.

## 8. Documentation conventions

* Current documents contain no em dashes and no product or assistant branding (`tests/integration/test_docs.py`).
* Unknown values are written as unknown or TBD, never as zero; synthetic, provisional and team-reported values are labelled as such.
* "Host" means implemented and tested on a computer; "proposed" means not built; nothing is physically tested yet. A document that describes hardware behaviour says which.
* Superseded documents are kept and labelled in [`README.md`](README.md); they are not rewritten.
