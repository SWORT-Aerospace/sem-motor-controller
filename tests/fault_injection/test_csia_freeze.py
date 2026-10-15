"""The CSIA development set and evaluation harness are frozen (docs/csia/EVALUATION_PROTOCOL.md).
A change to a frozen file must be a deliberate, recorded post-freeze change, not a silent re-tune."""
import hashlib
import json
import pathlib

from host.csia_adapter import eval_set as ES

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_frozen_files_match_manifest():
    man = json.loads((ROOT / "docs/csia/DEV_SET_FREEZE.json").read_text())["frozen_files_sha256"]
    changed = [f for f, h in man.items() if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    assert not changed, (f"frozen CSIA files changed: {changed}. Record the change in "
                         "docs/csia/EVALUATION_PROTOCOL.md section 5 and evaluate on a NEW held-out set.")


def test_eval_set_is_disjoint_from_development_and_deterministic():
    a, b = ES.build_eval_set(), ES.build_eval_set()
    assert [s.seed for s in a] == [s.seed for s in b]
    assert 7 not in {s.seed for s in a}                       # development seed
    assert all(s.seed >= 1000 for s in a)
    kinds = {s.fault.kind for s in a if s.fault}
    assert {"wheel_r_dropout", "rotor_scale", "rotor_dropout", "gnss_drift", "dc_drift"} <= kinds
    assert sum(1 for s in a if s.fault is None) == 24 and sum(1 for s in a if s.fault) == 70
