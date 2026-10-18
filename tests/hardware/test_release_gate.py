"""The fabrication release gate: a failing gate never produces fabrication outputs, and its committed report is
current."""
import pathlib
import subprocess
import sys

from tools import release_gate

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_gate_report_is_current_and_names_every_condition():
    results = release_gate.evaluate()
    assert [r[0] for r in results] == [f"G{i}" for i in range(1, 8)]
    assert (ROOT / "docs/generated/release_gate.md").read_text() == release_gate.report(results)


def test_failing_gate_builds_no_package(tmp_path):
    if all(ok for _, _, ok, _ in release_gate.evaluate()):
        return  # the board is releasable: nothing to check here
    out = tmp_path / "pkg"
    r = subprocess.run([sys.executable, str(ROOT / "tools/release_gate.py"), "--package", str(out)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 1
    assert "NOT built" in r.stdout
    assert not out.exists()
