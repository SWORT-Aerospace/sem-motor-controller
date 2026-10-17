"""Builds and runs the evidence recorder's C tests (host, with sanitizers), and compiles the recorder for the
Cortex-M4F when that toolchain is installed (compile only: no firmware image, nothing runs on a target)."""
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ["research/recorder/src/bea_recorder.c", "firmware/src/calibration/mc_crc.c"]
INC = ["-Iresearch/recorder/include", "-Ifirmware/include"]


def test_recorder_host_tests_pass(tmp_path):
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler")
    exe = tmp_path / "test_bea_recorder"
    build = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-g", "-fsanitize=address,undefined",
                            "-fno-omit-frame-pointer", *INC, "-Ifirmware/tests", *SRC,
                            "research/recorder/tests/test_bea_recorder.c", "-o", str(exe)],
                           cwd=ROOT, capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "0 failures" in run.stdout


def test_recorder_compiles_for_cortex_m4f(tmp_path):
    cc = shutil.which("arm-none-eabi-gcc")
    if cc is None:
        pytest.skip("arm-none-eabi-gcc not installed")
    r = subprocess.run([cc, "-std=c11", "-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv4-sp-d16", "-Os",
                        "-Wall", "-Wextra", "-Werror", *INC, "-c", SRC[0], "-o", str(tmp_path / "bea.o")],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
