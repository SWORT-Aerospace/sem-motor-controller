"""Hardware draft tooling: schematic connectivity, pin allocation, timing rule, pricing coverage.
These check the DRAFT's internal consistency; they are not a design review or hardware validation."""
import csv
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed")
def test_schematic_connectivity_matches_intent():
    r = subprocess.run([sys.executable, "tools/gen_kicad_schematic.py", "--check"], cwd=ROOT, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "problems: 0" in (ROOT / "hardware/kicad/CONNECTIVITY_CHECK.md").read_text()


def test_phase_currents_on_three_adcs_and_two_break_inputs():
    rows = {r["function"]: r for r in csv.DictReader((ROOT / "hardware/interfaces/pin_allocation_STM32G474VBCETx.csv").open())}
    a, b, c = (rows[f"ISENSE_{x}"]["signal"] for x in "ABC")
    assert a.startswith("ADC1_") and b.startswith("ADC2_") and c.split("_")[0] in ("ADC3", "ADC4", "ADC5")
    assert rows["PWM_BREAK"]["signal"] == "TIM1_BKIN" and rows["PWM_BREAK2"]["signal"] == "TIM1_BKIN2"
    assert "PRECHG_EN" in rows


def test_timing_budget_two_valid_phases_at_configured_limit():
    subprocess.run([sys.executable, "tools/timing_budget.py"], cwd=ROOT, check=True, capture_output=True)
    t = json.loads((ROOT / "hardware/timing/timing_budget.json").read_text())
    assert t["window"]["min_valid_phases_over_svpwm_angles"] >= 2
    assert t["pwm"]["deadtime_achieved_s"] >= 200e-9


def test_every_bom_line_is_priced_with_an_evidence_class():
    subprocess.run([sys.executable, "tools/price_bom.py"], cwd=ROOT, check=True, capture_output=True)
    draft = list(csv.DictReader((ROOT / "hardware/bom/BOM_draft.csv").open()))
    priced = list(csv.DictReader((ROOT / "hardware/bom/BOM_priced.csv").open()))
    assert len(draft) == len(priced)
    assert all(p["evidence"] in ("snippet", "representative", "allowance") for p in priced)
    assert all(float(p["unit_low"]) <= float(p["unit_high"]) for p in priced)
    budget = (ROOT / "docs/BUDGET.md").read_text()
    assert "Nothing has been purchased" in budget
