#!/usr/bin/env python3
"""Run every reproducible check of this repository and write a verification record.

    python3 tools/verify_all.py --out build/verify            # quick: CI-sized studies
    python3 tools/verify_all.py --out build/verify --full     # full studies + frozen CSIA re-run

Run it from a clean checkout inside a virtual environment created from
requirements.txt (python3 -m venv .venv && . .venv/bin/activate &&
pip install -r requirements.txt). It records, for every check: the exact
command, exit code, expected outcome, duration and the summary lines of the
output, then lists every tracked file whose regenerated content differs from
the committed one. Logs go to OUT/logs/, the record to OUT/verification.json
and OUT/verification.md.

Everything here runs on the host (x86-64 Linux) against synthetic models and
the host build of the firmware core. None of it is a hardware measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

# id, group, command, expected ("zero" | "nonzero"), summary regex, timeout s, full_only
CHECKS = [
    ("gen_config", "generation", [PY, "tools/gen_config.py", "--check"], "zero", r".+", 120, False),
    ("gen_protocol", "generation", [PY, "tools/gen_protocol.py", "--check"], "zero", r".+", 120, False),
    ("gen_dbc", "generation", [PY, "tools/gen_dbc.py", "--check"], "zero", r".+", 120, False),
    ("fetch_csia", "dependencies", [PY, "tools/fetch_csia.py"], "zero", r"fetched.*", 600, False),
    ("cfg_synthetic_sim", "configuration", [PY, "tools/config_tool.py", "validate", "config/vehicle.synthetic.yaml",
                                            "--mode", "sim"], "zero", r"VALID.*|INVALID.*", 120, False),
    ("cfg_unconfigured_hw", "configuration", [PY, "tools/config_tool.py", "validate",
                                              "config/vehicle.unconfigured.yaml", "--mode", "hw"], "nonzero",
     r"INVALID.*", 120, False),
    ("c_configure", "firmware", ["cmake", "-S", "firmware", "-B", "build", "-G", "Ninja",
                                 f"-DPython3_EXECUTABLE={PY}"], "zero", r"-- Build files.*", 600, False),
    ("c_build", "firmware", ["cmake", "--build", "build"], "zero", r"(warning|error).*", 1200, False),
    ("ctest", "firmware", ["ctest", "--test-dir", "build", "--output-on-failure", "-V"], "zero",
     r"\d+ checks, \d+ failures|tests passed.*|tests failed.*", 1200, False),
    ("property_soak", "firmware", ["build/test_core_properties", "100", "30"], "zero",
     r"\d+ seeds.*|slow steps.*|\d+ checks, \d+ failures", 3600, True),
    ("arm_configure", "portability", ["cmake", "-S", "firmware", "-B", "build-arm", "-G", "Ninja",
                                      "-DCMAKE_TOOLCHAIN_FILE=" + str(ROOT / "firmware/cmake/arm-none-eabi-cortex-m4f.cmake"),
                                      "-DSEMMC_PORTABLE_ONLY=ON", "-DSEMMC_SANITIZE=OFF",
                                      "-DCMAKE_BUILD_TYPE=MinSizeRel"], "zero", r"-- Build files.*", 600, False),
    ("arm_build", "portability", ["cmake", "--build", "build-arm"], "zero", r"(warning|error).*", 1200, False),
    ("arm_size", "portability", ["arm-none-eabi-size", "-t", "build-arm/libsemmc_core.a"], "zero",
     r".*\(TOTALS\)", 120, False),
    ("pytest", "python", [PY, "-m", "pytest", "-rs", "-p", "no:cacheprovider"], "zero",
     r"=+ .*(passed|failed|error).* =+|^SKIPPED.*|^FAILED.*", 3600, False),
    ("replay", "host simulation", [PY, "host/replay/replay.py", "tests/simulation/replay_sample.semmc.log",
                                   "--out", "build/replay"], "zero", r".+", 600, False),
    ("contract_report", "host simulation", [PY, "tools/control_contract_report.py", "--build", "build"], "zero",
     r"contract violations.*", 600, False),
    ("host_demo", "host simulation", [PY, "tools/run_host_demo.py", "--out", "build/host_demo"], "zero",
     r"^DEMO .*", 1800, False),
    ("optimisation_quick", "studies", [PY, "tools/run_optimization.py", "--quick"], "zero", r".*kJ.*", 3600, False),
    ("optimisation_full", "studies", [PY, "tools/run_optimization.py"], "zero", r".*kJ.*", 7200, True),
    ("electrical", "studies", [PY, "tools/run_electrical_calcs.py"], "zero", r".+", 600, False),
    ("csia_dev_study", "studies", [PY, "tools/run_csia_study.py"], "zero", r".+", 1800, False),
    ("policy_comparison", "studies", [PY, "tools/run_policy_comparison.py", "--duration", "300"], "zero",
     r"^(speed hold|pulse).*", 1800, True),
    ("csia_eval_v1_rerun", "studies", [PY, "tools/run_csia_evaluation.py"], "zero", r".+", 7200, True),
    ("kicad_connectivity", "hardware", [PY, "tools/gen_kicad_schematic.py", "--check"], "zero",
     r"\* problems: \d+|\* intended nets.*", 1200, False),
    ("kicad_drift", "hardware", ["git", "diff", "--exit-code", "--stat", "--", "hardware/kicad",
                                 "hardware/bom/BOM_draft.csv", ":!hardware/kicad/semmc.net"], "zero", r".+", 120, False),
    ("pin_type_check", "hardware", [PY, "tools/pin_type_check.py"], "zero", r".*findings.*", 300, False),
    ("hw_consistency", "hardware", [PY, "tools/hw_consistency.py"], "zero", r"^wrote .*|^(FAIL|OPEN) .*", 300, False),
    ("kicad_erc", "hardware", ["bash", "tools/run_kicad_erc.sh"], "zero", r".+", 1200, False),
    ("timing_budget", "hardware", [PY, "tools/timing_budget.py"], "zero", r".+", 300, False),
    ("clock_tree", "hardware", [PY, "tools/clock_tree.py"], "zero", r".+", 300, False),
    ("hardware_calcs", "hardware", [PY, "tools/hardware_calcs.py"], "zero", r".+", 300, False),
    ("price_bom", "hardware", [PY, "tools/price_bom.py"], "zero", r"\*\*Conclusion.*", 300, False),
    ("telematics_budget", "integration", [PY, "tools/telematics_budget.py"], "zero", r".+", 300, False),
]


def tool_versions() -> dict:
    def v(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
        except Exception as e:  # noqa: BLE001 - record any failure as text
            return f"unavailable ({type(e).__name__})"
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "gcc": v(["gcc", "--version"]), "cmake": v(["cmake", "--version"]),
            "arm-none-eabi-gcc": v(["arm-none-eabi-gcc", "--version"]), "kicad-cli": v(["kicad-cli", "version"])}


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def soft_double_calls(lib: pathlib.Path) -> int | None:
    """Count calls to soft-float double helpers inside mc_core_fast_step (Cortex-M4F has a single-precision FPU)."""
    if not lib.exists() or shutil.which("arm-none-eabi-objdump") is None:
        return None
    dis = subprocess.run(["arm-none-eabi-objdump", "-d", str(lib)], capture_output=True, text=True).stdout
    m = re.search(r"<mc_core_fast_step>:\n(.*?)\n\n", dis, re.S)
    return None if m is None else len(re.findall(r"__aeabi_d|__aeabi_f2d|__muldf3|__adddf3", m.group(1)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "verify")
    ap.add_argument("--full", action="store_true", help="full-resolution studies and the frozen CSIA re-run")
    ap.add_argument("--only", nargs="*", help="run only these check ids")
    a = ap.parse_args()
    out = a.out if a.out.is_absolute() else ROOT / a.out
    (out / "logs").mkdir(parents=True, exist_ok=True)
    rec = {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
           "dirty_before": git("status", "--porcelain", "--untracked-files=no").splitlines(),
           "tools": tool_versions(), "mode": "full" if a.full else "quick", "checks": []}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for cid, group, cmd, expect, rx, tmo, full_only in CHECKS:
        if a.only and cid not in a.only:
            continue
        if full_only and not a.full:
            continue
        if not a.full and cid == "optimisation_quick":
            pass
        elif a.full and cid == "optimisation_quick":
            continue
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=tmo, env=env)
            rc, text = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            rc, text = -9, (e.stdout or "") + f"\nTIMEOUT after {tmo} s"
        except FileNotFoundError as e:
            rc, text = 127, f"command not found: {e}"
        dt = time.time() - t0
        (out / "logs" / f"{cid}.log").write_text(f"$ {' '.join(map(str, cmd))}\n{text}")
        lines = [ln.strip() for ln in text.splitlines() if re.search(rx, ln.strip())]
        ok = (rc == 0) if expect == "zero" else (rc != 0 and rc not in (-9, 127))
        if cid == "kicad_erc" and rc == 2:
            status = "NOT AVAILABLE"
        else:
            status = "PASS" if ok else "FAIL"
        item = {"id": cid, "group": group, "command": " ".join(map(str, cmd)).replace(str(ROOT) + "/", ""),
                "expected": expect, "rc": rc, "status": status, "seconds": round(dt, 1), "summary": lines[-6:]}
        if cid == "arm_size":
            item["soft_double_calls_in_fast_step"] = soft_double_calls(ROOT / "build-arm" / "libsemmc_core.a")
        rec["checks"].append(item)
        print(f"{status:13s} {cid:22s} rc={rc:<4d} {dt:7.1f} s  {lines[-1][:110] if lines else ''}", flush=True)
    changed = git("status", "--porcelain", "--untracked-files=no").splitlines()
    rec["regenerated_tracked_files_changed"] = [c for c in changed if c not in rec["dirty_before"]]
    rec["counts"] = {s: sum(1 for c in rec["checks"] if c["status"] == s) for s in ("PASS", "FAIL", "NOT AVAILABLE")}
    (out / "verification.json").write_text(json.dumps(rec, indent=1))
    L = [f"# Verification record ({rec['mode']} mode)", "",
         f"Commit `{rec['commit']}` on `{rec['branch']}`; working tree dirty before the run: "
         f"{'no' if not rec['dirty_before'] else ', '.join(rec['dirty_before'])}.", "",
         "Environment: " + "; ".join(f"{k} {v}" for k, v in rec["tools"].items()) + ".", "",
         "| Check | Group | Status | rc | s | Summary |", "|---|---|---|---|---|---|"]
    for c in rec["checks"]:
        summ = "<br>".join(s.replace("|", "\\|")[:140] for s in c["summary"][-3:])
        if "soft_double_calls_in_fast_step" in c:
            summ += f"<br>soft-double calls in mc_core_fast_step: {c['soft_double_calls_in_fast_step']}"
        L.append(f"| `{c['id']}` | {c['group']} | **{c['status']}** | {c['rc']} | {c['seconds']} | {summ} |")
    L += ["", "Regenerated tracked files that differ from the committed versions: " +
          (", ".join(f"`{x}`" for x in rec["regenerated_tracked_files_changed"]) or "none") + ".", "",
          f"Totals: {rec['counts']}. Commands are run from the repository root; logs are in `logs/`.", ""]
    (out / "verification.md").write_text("\n".join(L))
    print(f"wrote {out / 'verification.md'}: {rec['counts']}")
    return 0 if rec["counts"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
