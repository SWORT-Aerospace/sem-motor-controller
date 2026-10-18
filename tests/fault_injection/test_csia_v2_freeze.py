"""CSIA v2 is frozen before its evaluation set is generated (docs/csia/EVALUATION_PROTOCOL_v2.md)."""
import hashlib
import json
import pathlib

from host.csia_adapter import eval_set_v2 as ES2

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_v2_frozen_files_match_manifest():
    man = json.loads((ROOT / "docs/csia/V2_FREEZE.json").read_text())["frozen_files_sha256"]
    changed = [f for f, h in man.items() if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h]
    assert not changed, (f"frozen CSIA v2 files changed: {changed}. Record the change in "
                         "docs/csia/EVALUATION_PROTOCOL_v2.md section 7.")


def test_v2_sets_are_disjoint_from_each_other_and_from_v1():
    dev = {s.seed for s in ES2.dev_set()}
    ev = set(ES2.EVAL_NOMINAL_SEEDS) | set(range(ES2.EVAL_FAULT_SEED0, ES2.EVAL_FAULT_SEED0 + 70))
    v1 = set(range(1000, 1024)) | set(range(2000, 2070)) | {7}
    assert not dev & ev and not dev & v1 and not ev & v1
    assert len(dev) == 8 + 28
