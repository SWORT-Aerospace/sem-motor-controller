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

# Decided from the development pilot (research/RESULTS.md section 2) before any final episode exists.
EPISODES = {"none": 40, "HB": 30, "HT": 30, "HL": 30, "HL_grade": 20, "HU_gain": 20}
SCHEDULERS = ["A", "B", "C", "D", "E", "F"]
ABLATIONS = ["F_noamb", "F_notiming", "F_doublecount"]
PAIRED = [["F", "A"], ["F", "B"], ["F", "C"], ["F", "D"], ["F", "E"],
          ["F", "F_noamb"], ["F", "F_notiming"], ["F", "F_doublecount"]]


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
        "calibration": {**cal["engine"], "aligned_thresholds": cal["aligned_thresholds"],
                        "frozen_monitors": {k: cal["frozen_monitors"][k] for k in ("e6", "lam", "trust_thr")}},
        "compare": {"window_s": [45.0, 70.0], "mht_p_accept": 0.95},
        "analysis": {"paired": PAIRED, "bootstrap_resamples": 4000, "bootstrap_seed": 1,
                     "primary": "PREREGISTRATION.md section 3"},
        "frozen_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FROZEN},
    }
    (ROOT / "research" / "preregistration.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    print(f"wrote research/preregistration.json ({len(FROZEN)} frozen files, D budget {man['budgets']['d_budget_bytes']} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
