"""HARDWARE_REQUIRED: tests that need the NUCLEO-U575ZI-Q on the bench (telematics/firmware/BENCH.md).

They are skipped unless SEMMC_HARDWARE=1, and never run in cloud CI: a pass here needs the board, the generator and the
operator. A pass is BENCH evidence only together with a filled run sheet (research/vehicle_validation/RUN_SHEET.md).

    SEMMC_HARDWARE=1 SEMMC_BENCH_CAPTURE=capture_B3.txt SEMMC_BENCH_PULSE_HZ=100 python3 -m pytest tests/hardware_required
"""
import os
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.hardware_required
ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_board_log_passes_the_pulse_to_database_chain(tmp_path):
    cap, hz = os.environ.get("SEMMC_BENCH_CAPTURE"), os.environ.get("SEMMC_BENCH_PULSE_HZ")
    if not cap or not hz:
        pytest.fail("set SEMMC_BENCH_CAPTURE (UART capture of DUMP after BENCH.md B3) and SEMMC_BENCH_PULSE_HZ")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "run_bench_chain.py"), "--uart-capture", cap, "--pulse-hz",
                        hz, "--circumference", "0.1", "--ppr", "1", "--out", str(tmp_path / "chain")],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "(BENCH): PASS" in r.stdout
