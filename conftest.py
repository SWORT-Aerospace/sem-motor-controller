"""Pytest configuration: project root on sys.path, suite markers, and the on-demand builds.

Every test is marked with its suite from docs/scope.yaml (tools/scope.py): `telematics` (the delivery),
`reference` (reusable simulation and reference) or `controller` (deferred controller development). Run the
delivery without the controller: python -m pytest -m "telematics or reference". A telematics or reference
test that asks for the controller build (`build_dir` and the fixtures based on it) fails: the telematics
delivery must not need our controller.

The controller's C host build (CMake) is created on demand for the controller suite:
cmake -S firmware -B build && cmake --build build. The telematics firmware's host build (telematics/firmware,
its portable library and unit tests) is created on demand by `telematics_build`.
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
TM_BUILD = pathlib.Path(os.environ.get("TM_BUILD_DIR", ROOT / "build-telematics"))

from tools import scope  # noqa: E402

_SCOPE = scope.load()


def pytest_configure(config):
    for s, meaning in _SCOPE["suites"].items():
        config.addinivalue_line("markers", f"{s}: {meaning} (docs/scope.yaml)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        rel = pathlib.Path(str(item.fspath)).resolve().relative_to(ROOT).as_posix()
        suite = scope.test_suite(f"{rel}::{item.name}", _SCOPE)
        if suite not in _SCOPE["suites"]:
            raise pytest.UsageError(f"{rel}: no suite in docs/scope.yaml")
        item.add_marker(getattr(pytest.mark, suite))
        needs = sorted(CONTROLLER_FIXTURES & set(getattr(item, "fixturenames", ())))
        if suite != "controller" and needs:
            raise pytest.UsageError(f"{item.nodeid} is in the {suite} suite but uses {needs} (the controller build): "
                                    "the telematics delivery must not need our controller (docs/scope.yaml)")


CONTROLLER_FIXTURES = {"build_dir", "host_exe", "cfgcheck_exe", "synthetic_blob"}


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


def _ensure_telematics_build():
    gen = ["-G", "Ninja"] if shutil.which("ninja") else []
    if not (TM_BUILD / "CMakeCache.txt").exists():
        subprocess.run(["cmake", "-S", str(ROOT / "telematics" / "firmware"), "-B", str(TM_BUILD), *gen], check=True)
    subprocess.run(["cmake", "--build", str(TM_BUILD)], check=True)
    return TM_BUILD


@pytest.fixture(scope="session")
def telematics_build():
    return _ensure_telematics_build()


@pytest.fixture(scope="session")
def host_exe(build_dir):
    return build_dir / "semmc_host"


@pytest.fixture(scope="session")
def cfgcheck_exe(build_dir):
    return build_dir / "semmc_cfgcheck"


@pytest.fixture(scope="session")
def synthetic_blob(build_dir):
    return build_dir / "cal" / "synthetic.bin"
