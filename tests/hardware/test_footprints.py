"""Footprint assignment and its check (tools/check_footprints.py, hardware/footprints/)."""
import copy
import subprocess
import sys

import pytest

from tools import check_footprints as cf

ROOT = cf.ROOT
pytestmark = pytest.mark.skipif(not (cf.LIB / "Resistor_SMD.pretty").exists(),
                                reason="pinned footprints not fetched (python3 tools/check_footprints.py --fetch)")


def test_check_passes_and_report_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_footprints.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_every_bom_line_has_one_disposition_and_counts_add_up():
    ev = cf.evaluate(cf.load())
    assert ev["problems"] == []
    assert sum(ev["counts"].values()) == len(ev["rows"]) == 122
    assert ev["counts"]["verified"] > 0 and ev["counts"]["pinout_blocked"] == 2  # DRV8353 and the RPP block


def _entry(a, ref):
    return next(e for e in a["lines"] if ref in e["refs"])


def test_wrong_footprint_is_rejected():
    a = copy.deepcopy(cf.load())
    _entry(a, "R1001")["footprint"] = "Package_TO_SOT_SMD:SOT-23-5"  # five pads for a two-pin resistor
    probs = cf.evaluate(a)["problems"]
    assert any("R1001" in p and "pads differ" in p for p in probs)
    assert any("R1001" in p and "filters" in p for p in probs)
    a = copy.deepcopy(cf.load())
    _entry(a, "C1103")["footprint"] = "Capacitor_SMD:C_1206_3216Metric"  # assignment says 0603
    assert any("C1103" in p and "package 0603" in p for p in cf.evaluate(a)["problems"])


def test_dispositions_must_match_the_bom():
    a = copy.deepcopy(cf.load())
    e = _entry(a, "Q301")
    e["disposition"] = "verified"  # verified without a footprint
    assert any("Q301" in p and "disposition verified" in p for p in cf.evaluate(a)["problems"])
    a = copy.deepcopy(cf.load())
    _entry(a, "R1001")["refs"].remove("R1001")
    probs = cf.evaluate(a)["problems"]
    assert any("R1001: in the BOM, no footprint disposition" in p for p in probs)


def test_schematic_and_bom_carry_the_assigned_footprints():
    import csv
    fp = {r: e.get("footprint", "") for e in cf.load()["lines"] for r in e["refs"]}
    for row in csv.DictReader(cf.BOM.open()):
        assert row["footprint"] == fp[row["refs"].split()[0]]
    net = (ROOT / "hardware" / "kicad" / "semmc.net").read_text()
    assert '(comp (ref "U801")\n      (value "STM32G474VET6")\n      (footprint "Package_QFP:LQFP-100_14x14mm_P0.5mm")' in net
    assert cf.TABLE.read_text() == cf.lib_table(cf.load())
