"""Claim discipline and the statements the documentation must keep (HOST-TESTED: text and register checks)."""
import copy
import pathlib

from tools import claims

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_claims_register_passes_and_nothing_is_above_host_tested_without_a_record():
    d = claims.load()
    assert claims.check(d) == []
    for c in d["claims"]:
        assert c["label"] in ("SIMULATED", "HOST-TESTED"), c["id"]      # no run sheet exists yet


def test_a_physical_label_without_a_run_sheet_is_refused():
    d = copy.deepcopy(claims.load())
    d["claims"][0]["label"] = "VEHICLE-TESTED"
    assert any("needs a filled run sheet" in e for e in claims.check(d))
    d["claims"][0]["evidence"]["records"] = ["research/vehicle_validation/records/README.md"]
    assert any("does not state data class VEHICLE" in e for e in claims.check(d))
    d = copy.deepcopy(claims.load())
    d["claims"][0]["statement"] += " and it is proven"
    assert any("overclaiming" in e for e in claims.check(d))
    d = copy.deepcopy(claims.load())
    d["claims"][0]["evidence"]["tests"] = ["tests/telematics/test_claims_and_docs.py::test_that_does_not_exist"]
    assert any("not found" in e for e in claims.check(d))


def test_overclaim_scan_flags_positive_claims_only():
    flag = (lambda s: bool(claims.CLAIM.search(s) and not claims.NEGATION.search(s)))
    assert flag("The wheel input is validated on the vehicle.") and flag("The unit is race-ready.")
    assert flag("The design was proven in the field.")
    assert not flag("Nothing here is vehicle-validated.") and not flag("It is not proven.")


def test_readme_states_the_boundary_verbatim():
    text = (ROOT / "README.md").read_text()
    assert ("This repository implements vehicle telemetry and evidence analysis. It has no propulsion authority. "
            "CSIA integration is shadow/advisory only.") in text


def test_current_state_has_every_audit_section():
    text = (ROOT / "docs" / "CURRENT_STATE.md").read_text()
    for h in ("## IMPLEMENTED", "## PARTIAL", "## PLACEHOLDER", "## UNVERIFIED", "## BLOCKED", "## OUT OF SCOPE",
              "## After the evidence-platform change"):
        assert h in text, h


def test_hardware_open_items_cover_the_required_topics():
    text = (ROOT / "docs" / "HARDWARE_OPEN_ITEMS.md").read_text()
    for topic in ("13S", "TVS", "DC-DC", "TMP117 versus DS18B20", "Controller CAN format",
                  "Hall sensor electrical characteristics", "External storage hardware",
                  "STM32U575 register-level assumptions"):
        assert topic in text, topic
    assert "not decided in software" in text


def test_every_protocol_has_ground_truth_falsifiers_and_no_result():
    d = ROOT / "research" / "vehicle_validation"
    for n in ("EXP-01_wheel_speed_corruption", "EXP-02_motor_effort_response", "EXP-03_shared_power_disturbance",
              "EXP-04_timing_degradation"):
        text = (d / f"{n}.md").read_text()
        assert "**NOT RUN** (physical)" in text
        for h in ("## Independent ground truth", "## Supports, falsifies, inapplicable", "## Expected signature"):
            assert h in text, (n, h)
    assert [p.name for p in (d / "records").iterdir()] == ["README.md"]      # no physical record claimed
