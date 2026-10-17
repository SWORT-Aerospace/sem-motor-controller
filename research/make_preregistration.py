"""Writes research/preregistration.json: the frozen protocol of the final evaluation.

    python3 research/make_preregistration.py

Run once, after the development pilot, then commit the manifest together with research/PREREGISTRATION.md.
The final seeds are derived from the hash of that commit (research/run_final.py), so the final episodes do
not exist until the protocol is fixed. Every file the final run depends on is listed with its SHA-256;
run_final.py refuses to run if any of them has changed.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PILOT = ROOT / "research" / "generated" / "pilot"
FROZEN = sorted(
    [str(p.relative_to(ROOT)) for p in (ROOT / "research" / "bea").glob("*.py")]
    + ["research/run_final.py", "research/generated/pilot/calibration.json",
       "research/recorder/include/bea_recorder.h", "research/recorder/src/bea_recorder.c",
       "models/vehicle/longitudinal.py", "models/vehicle/powertrain.py", "models/inverter/losses.py",
       "host/telematics/clocks.py"]
    + [str(p.relative_to(ROOT)) for p in (ROOT / "host" / "csia_adapter").glob("*.py")])

# Decided from the development pilot (research/RESULTS.md section 2) before any final episode exists;
# the reasons are in research/PREREGISTRATION.md.
EPISODES = {"none": 60, "HB": 40, "HT": 40, "HL": 30, "HL_grade": 30, "HU_gain": 30}
SCHEDULERS = ["A", "B", "C", "D", "E", "F"]
ABLATIONS = ["F_noamb", "F_notiming", "F_doublecount"]
PAIRED = [["F", "A"], ["F", "B"], ["F", "C"], ["F", "D"], ["F", "E"],
          ["F", "F_noamb"], ["F", "F_notiming"], ["F", "F_doublecount"]]


def _gt(of, bound, value):
    return {"of": of, "bound": bound, "op": ">", "value": value}


def _lt(of, bound, value):
    return {"of": of, "bound": bound, "op": "<", "value": value}


ENDPOINTS = [
    {"id": "P1", "kind": "paired", "a": "F", "b": "D", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "primary: does F diagnose more fault episodes correctly than random requests at F's mean budget?",
     "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S1", "kind": "paired", "a": "F", "b": "A", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "do F's requests add correct diagnoses to the summary alone?", "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S2", "kind": "paired", "a": "F", "b": "E", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "is the ambiguity-directed rule better than information gain?", "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S3", "kind": "paired", "a": "F", "b": "B", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "does F match fetching everything at a fraction of the bytes?",
     "criterion": [_gt("correct", "lo", -0.05), _lt("bytes", "hi", 0.0)]},
    {"id": "S4", "kind": "paired", "a": "F", "b": "C", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "is F better than capturing on detection?", "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S5", "kind": "paired", "a": "F", "b": "F_noamb", "episodes": "faults", "metrics": ["correct", "bytes"],
     "question": "ablation: does the engine's ambiguity information save bytes without losing correct diagnoses?",
     "criterion": [_lt("bytes", "hi", 0.0), _gt("correct", "lo", -0.05)]},
    {"id": "S6", "kind": "paired", "a": "F", "b": "F_notiming", "episodes": "HT", "metrics": ["correct"],
     "question": "ablation: is the timing allowance needed to diagnose timing errors?", "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S7", "kind": "paired", "a": "F", "b": "F_notiming", "episodes": "faults", "metrics": ["correct", "wrong"],
     "question": "ablation: timing allowance, over all fault episodes", "criterion": []},
    {"id": "S8", "kind": "paired", "a": "F", "b": "F_doublecount", "episodes": "faults", "metrics": ["correct", "wrong"],
     "question": "ablation: does treating the summary and the frames as independent change the result?", "criterion": []},
    {"id": "S9", "kind": "proportion", "scheduler": "F", "episodes": "faults", "among": "supported", "categories": ["wrong"],
     "question": "risk: wrong cause among F's supported decisions on fault episodes", "criterion": [_lt("proportion", "hi", 0.05)]},
    {"id": "S10", "kind": "proportion", "scheduler": "F", "episodes": "faults", "categories": ["correct"],
     "question": "coverage: fault episodes F diagnoses correctly", "criterion": []},
    {"id": "S11", "kind": "proportion", "scheduler": "F", "episodes": "HU", "categories": ["correct"],
     "question": "abstention: unmodelled faults F reports as \"no modelled cause fits\"", "criterion": []},
    {"id": "S12", "kind": "proportion", "scheduler": "F", "episodes": "HU", "categories": ["wrong"],
     "question": "abstention failure: unmodelled faults F attributes to a modelled cause", "criterion": []},
    {"id": "S13", "kind": "proportion", "scheduler": "F", "episodes": "H0", "categories": ["false_alarm", "false_alarm_wrong"],
     "question": "clean episodes with an alarm (F; the summary monitor is shared by all)", "criterion": []},
    {"id": "S14", "kind": "paired_engines", "a": "reference/frames", "b": "MHT/frames", "kinds": ["HB", "HT", "HL", "HL_grade"],
     "question": "identical full-rate records: reference diagnosis against the calibrated multiple-hypothesis baseline",
     "criterion": []},
    {"id": "S15", "kind": "paired_engines", "a": "reference/frames", "b": "aligned/frames", "kinds": ["HB", "HT", "HL", "HL_grade"],
     "question": "identical full-rate records: reference diagnosis against the aligned residual monitor",
     "criterion": [_gt("correct", "lo", 0.0)]},
    {"id": "S16", "kind": "paired_engines", "a": "reference/frames", "b": "R3v", "kinds": ["HB", "HT", "HL", "HL_grade"],
     "question": "identical records: reference diagnosis against the frozen R3v", "criterion": []},
]


def main() -> int:
    cal = json.loads((PILOT / "calibration.json").read_text())
    rows = [json.loads(line) for line in (PILOT / "dev_results.jsonl").read_text().splitlines()]
    f_bytes = [r["bytes"] for r in rows if r["scheduler"] == "F"]
    man = {
        "version": 1,
        "note": "Frozen protocol of the final evaluation. Synthetic host simulation only.",
        "episodes": EPISODES,
        "schedulers": SCHEDULERS,
        "ablations": {"schedulers": ABLATIONS},
        "budgets": {"byte_budget": 200000, "deadline_s": 40.0, "decide_after_s": 20.0,
                    "d_budget_bytes": int(sum(f_bytes) / len(f_bytes))},
        "calibration": {**cal["engine"], "aligned_thresholds": cal["aligned_thresholds"], "mht_prior_h0": cal["mht_prior_h0"],
                        "frozen_monitors": {k: cal["frozen_monitors"][k] for k in ("e6", "lam", "trust_thr")}},
        "compare": {"window_s": [45.0, 70.0], "mht_p_accept": 0.95},
        "analysis": {"paired": PAIRED, "bootstrap_resamples": 4000, "bootstrap_seed": 1, "target_risk": 0.05,
                     "primary": "P1", "reasons": "research/PREREGISTRATION.md"},
        "endpoints": ENDPOINTS,
        "frozen_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FROZEN},
    }
    (ROOT / "research" / "preregistration.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    print(f"wrote research/preregistration.json ({len(FROZEN)} frozen files, D budget {man['budgets']['d_budget_bytes']} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
