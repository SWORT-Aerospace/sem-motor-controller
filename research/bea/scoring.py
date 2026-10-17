"""Scoring (evaluator only): compares an episode result with its label. Nothing here is visible to the
diagnostic or the schedulers."""
from __future__ import annotations

import math

LABEL_CLASS = {"none": "H0", "HB": "HB", "HT": "HT", "HL": "HL", "HL_grade": "HL", "HU_gain": "HU",
               "HB+HL": "multiple", "HT+HB": "multiple"}


def label_class(kind: str, imu_available: bool) -> str:
    if kind == "HL_grade" and imu_available:
        return "HL_grade"
    return LABEL_CLASS[kind]


def score(res: dict, onset_true: float, imu_available: bool = False) -> dict:
    """One episode: category, delays, set size and inclusion of the true class."""
    truth = label_class(res["label"], imu_available)
    out, hyps = res["outcome"], tuple(res["hypotheses"])
    hl_like = {"HL", "HL_grade"}
    def is_true(h):
        return h == truth or (truth == "HL" and h in hl_like) or (truth == "HL_grade" and h == "HL_grade")
    detected = res["t_detect_true"] is not None
    cleared = res.get("cleared_alarms", [])
    if truth == "H0":
        cat = "false_alarm_wrong" if out == "supported" else ("false_alarm" if detected or cleared else "clean")
    elif truth == "HU":
        cat = "correct" if out == "no_fit" else ("wrong" if out == "supported" else
                                                 "missed" if not detected else "unresolved")
    elif truth == "multiple":
        cat = "wrong" if out == "supported" else ("missed" if not detected else "flagged")
    elif not detected:
        cat = "missed"
    elif out == "supported":
        cat = "correct" if is_true(hyps[0]) else "wrong"
    elif out == "unresolved":
        cat = "unresolved_incl" if any(is_true(h) for h in hyps) else "unresolved_excl"
    elif out == "no_fit":
        cat = "no_fit"
    else:
        cat = "undecided"
    t_det = res["t_detect_true"]
    t_dec = res["t_decide_true"]
    return {"truth": truth, "category": cat, "set_size": len(hyps), "alarms": len(cleared) + int(detected),
            "cleared_alarms": len(cleared),
            "true_in_set": any(is_true(h) for h in hyps),
            "detect_delay_s": (t_det - onset_true) if detected and math.isfinite(onset_true) else None,
            "decide_delay_s": (t_dec - onset_true) if t_dec is not None and math.isfinite(onset_true) else None,
            "early_alarm": detected and math.isfinite(onset_true) and t_det < onset_true}


def confidence(res: dict) -> float:
    """How clearly a single supported cause beat the next modelled cause at the final decision (difference
    of fit statistics); -inf when no single cause was supported. Used only to trace risk against coverage."""
    if res["outcome"] != "supported" or not res.get("J"):
        return -math.inf
    faults = sorted(v for h, v in res["J"].items() if h != "H0")
    return faults[1] - faults[0] if len(faults) > 1 else math.inf


def selective(conf: list, wrong: list, n: int, coverage: float) -> float:
    """Risk (wrong among supported) when only the most confident decisions are kept, enough of them to
    cover `coverage` of the n fault episodes; nan if the scheduler supported fewer than that."""
    k = int(math.ceil(coverage * n - 1e-9))
    ranked = sorted((c, w) for c, w in zip(conf, wrong) if c > -math.inf)[::-1]
    if k == 0 or k > len(ranked):
        return math.nan
    return sum(w for _, w in ranked[:k]) / k


def coverage_at_risk(conf: list, wrong: list, n: int, risk: float) -> float:
    """Largest coverage at which keeping the most confident supported decisions gives risk <= `risk`."""
    ranked = sorted((c, w) for c, w in zip(conf, wrong) if c > -math.inf)[::-1]
    best, bad = 0, 0
    for k, (_, w) in enumerate(ranked, 1):
        bad += w
        if bad / k <= risk:
            best = k
    return best / n if n else math.nan
