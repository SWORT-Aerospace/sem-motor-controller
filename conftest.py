"""Pytest configuration: project root on sys.path and the host C build.

The C host build (CMake) is created on demand so `pytest` works from a clean
checkout: cmake -S firmware -B build && cmake --build build.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
BUILD = pathlib.Path(os.environ.get("SEMMC_BUILD_DIR", ROOT / "build"))


def _ensure_build():
    exe = BUILD / "semmc_host"
    if not exe.exists():
        gen = ["-G", "Ninja"] if shutil.which("ninja") else []
        subprocess.run(["cmake", "-S", str(ROOT / "firmware"), "-B", str(BUILD), *gen], check=True)
    subprocess.run(["cmake", "--build", str(BUILD)], check=True)
    return BUILD


@pytest.fixture(scope="session")
def build_dir():
    return _ensure_build()


@pytest.fixture(scope="session")
def host_exe(build_dir):
    return build_dir / "semmc_host"


@pytest.fixture(scope="session")
def cfgcheck_exe(build_dir):
    return build_dir / "semmc_cfgcheck"


@pytest.fixture(scope="session")
def synthetic_blob(build_dir):
    return build_dir / "cal" / "synthetic.bin"
