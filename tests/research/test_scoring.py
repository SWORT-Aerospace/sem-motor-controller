"""Scoring: categories, and risk against coverage when only the most confident decisions are kept."""
import math

from research.bea.scoring import confidence, coverage_at_risk, score, selective


def _res(label, outcome, hyps, detect=40.0, J=None):
    return {"label": label, "outcome": outcome, "hypotheses": hyps, "t_detect_true": detect,
            "t_decide_true": None if detect is None else detect + 10.0, "cleared_alarms": [], "J": J or {}}


def test_categories():
    assert score(_res("HB", "supported", ("HB",)), 30.0)["category"] == "correct"
    assert score(_res("HB", "supported", ("HL",)), 30.0)["category"] == "wrong"
    assert score(_res("HL_grade", "supported", ("HL",)), 30.0)["category"] == "correct"   # no IMU: one class
    assert score(_res("HT", "unresolved", ("HB", "HT")), 30.0)["category"] == "unresolved_incl"
    assert score(_res("HU_gain", "no_fit", ()), 30.0)["category"] == "correct"
    assert score(_res("none", "consistent", (), detect=None), math.inf)["category"] == "clean"
    assert score(_res("none", "supported", ("HB",)), math.inf)["category"] == "false_alarm_wrong"
    assert score(_res("HB", "consistent", (), detect=None), 30.0)["category"] == "missed"


def test_confidence_is_the_gap_to_the_next_cause():
    assert confidence(_res("HB", "supported", ("HB",), J={"H0": 90.0, "HB": 50.0, "HT": 70.0, "HL": 61.0})) == 11.0
    assert confidence(_res("HB", "unresolved", ("HB", "HL"), J={"H0": 90.0, "HB": 50.0, "HL": 51.0})) == -math.inf


def test_selective_risk_and_coverage():
    conf = [9.0, 8.0, 7.0, 1.0, -math.inf]          # four supported decisions, the least confident one wrong
    wrong = [False, False, False, True, False]
    assert selective(conf, wrong, 5, 0.8) == 0.25     # all four kept
    assert selective(conf, wrong, 5, 0.6) == 0.0      # the three most confident kept
    assert math.isnan(selective(conf, wrong, 5, 1.0))  # cannot cover the abstention
    assert coverage_at_risk(conf, wrong, 5, 0.0) == 0.6
    assert coverage_at_risk(conf, wrong, 5, 0.25) == 0.8
