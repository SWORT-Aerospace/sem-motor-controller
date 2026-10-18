"""Acceptance procedures and the blocker register: generated documents are current, references resolve, and
the record checker enforces its rules (no invented limit, stop limits, blocked steps, evidence)."""
import copy
import pathlib
import re

import yaml

from tools import acceptance, blockers

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _params():
    return {p["path"] for p in yaml.safe_load((ROOT / "config/parameters.yaml").read_text())["params"]}


def test_generated_documents_are_current():
    proc, blk = acceptance.load_procedures(), acceptance.load_blockers()
    assert (ROOT / "docs/BENCH_ACCEPTANCE.md").read_text() == acceptance.render(proc, blk)
    assert (ROOT / "docs/BLOCKERS.md").read_text() == blockers.render(yaml.safe_load((ROOT / "docs/blockers.yaml").read_text()))


def test_procedure_references_resolve():
    proc, blk = acceptance.load_procedures(), acceptance.load_blockers()
    params = _params()
    ids = [s["id"] for st in proc["stages"] for s in st["steps"]]
    assert len(ids) == len(set(ids))
    for st in proc["stages"]:
        for b in [st.get("blocked_by")] + [s.get("blocked_by") for s in st["steps"]]:
            assert b is None or b in blk, b
        for s in st["steps"]:
            assert s["kind"] in ("measurement", "observation")
            if s["kind"] == "measurement":
                assert s.get("unit") and s.get("limit"), s["id"]
                lim = s["limit"]
                assert "pending" in lim or "source" in lim, f"{s['id']}: a limit needs a source or a pending reason"
                for v in (lim.get("min"), lim.get("max")):
                    if isinstance(v, str):
                        assert v.startswith("cfg:") and v[4:] in params, f"{s['id']}: {v}"
    text = (ROOT / "hardware/acceptance/procedures.yaml").read_text()
    for path, wildcard in re.findall(r"\b((?:limits|inverter|power|controls|sensing|supervision|motor|battery)\.[A-Za-z0-9_]+)(\*?)", text):
        assert path in params or (wildcard and any(p.startswith(path) for p in params)), path


def test_blockers_named_by_open_items_exist_and_closed_ones_have_evidence():
    data = yaml.safe_load((ROOT / "docs/blockers.yaml").read_text())
    ids = {b["id"] for b in data["blockers"]}
    groups = {g["id"] for g in data["groups"]}
    for b in data["blockers"]:
        if b["status"] == "closed":
            assert b.get("evidence"), b["id"]
        else:
            assert b.get("group") in groups | {"team"}, b["id"]
    for g in groups:
        assert any(b.get("group") == g for b in data["blockers"]), g
    assert "48 V nominal, 10 Ah" in data["battery_as_reported"]
    assert ids >= {"B-DRV", "B-INA", "B-CAN", "B-VEH"}


def _filled_s3(tmp_path):
    proc, blk = acceptance.load_procedures(), acceptance.load_blockers()
    rec = acceptance.template(proc, "S3", "SN-TEST")
    rec.update(operator="A", witness="B", firmware={"image": "semmc_stm32g474.elf", "revision": "x", "sha256": "0" * 64})
    for e in rec["equipment"]:
        e["serial"] = "123"
    (tmp_path / "scope.png").write_bytes(b"")
    vals = {"S3.1": 3.31, "S3.2": 3.30, "S3.3": 5.02, "S3.4": 12.0, "S3.5": 500.1, "S3.6": 0.102, "S3.7": 10001.0}
    for sid, v in vals.items():
        st = rec["steps"][sid]
        st.update(value=v, instrument="DMM 1", evidence=["scope.png"])
        st["result"] = "pass" if sid in ("S3.1", "S3.2", "S3.6") else "recorded"
    return proc, blk, rec


def test_a_complete_record_passes(tmp_path):
    proc, blk, rec = _filled_s3(tmp_path)
    errors, summary = acceptance.check(proc, blk, rec, tmp_path, None)
    assert errors == [] and summary["stage_passed"]


def test_checker_rejects_wrong_or_invented_verdicts(tmp_path):
    proc, blk, rec = _filled_s3(tmp_path)
    bad = copy.deepcopy(rec)
    bad["steps"]["S3.1"]["value"] = 3.9                       # above the MCU's 3.6 V
    assert any("gives fail" in e for e in acceptance.check(proc, blk, bad, tmp_path, None)[0])
    bad = copy.deepcopy(rec)
    bad["steps"]["S3.5"]["result"] = "pass"                    # tolerance pending: cannot pass
    assert any("must be 'recorded'" in e for e in acceptance.check(proc, blk, bad, tmp_path, None)[0])
    bad = copy.deepcopy(rec)
    bad["steps"]["S3.6"]["value"] = 0.005                      # shorter than the 20 ms kick gap
    bad["steps"]["S3.6"]["result"] = "fail"
    errors = acceptance.check(proc, blk, bad, tmp_path, None)[0]
    assert any("S3.7: run after S3.6 failed a stop limit" in e for e in errors)
    bad = copy.deepcopy(rec)
    bad["steps"]["S3.1"]["evidence"] = ["missing.png"]
    assert any("not found" in e for e in acceptance.check(proc, blk, bad, tmp_path, None)[0])
    bad = copy.deepcopy(rec)
    bad["witness"] = None
    assert any("witness" in e for e in acceptance.check(proc, blk, bad, tmp_path, None)[0])


def test_blocked_steps_and_configuration_limits(tmp_path):
    proc, blk = acceptance.load_procedures(), acceptance.load_blockers()
    rec = acceptance.template(proc, "S5", "SN-TEST")
    assert rec["steps"]["S5.7"]["result"] == "blocked"         # B-DRV open
    rec["steps"]["S5.7"].update(result="recorded", value=2048, instrument="debugger")
    assert any("B-DRV is open" in e for e in acceptance.check(proc, blk, rec, tmp_path, None)[0])
    # S5.3's limit comes from the calibration: null -> only 'recorded'; a value -> judged.
    rec = acceptance.template(proc, "S5", "SN-TEST")
    rec["steps"]["S5.3"].update(result="pass", value=0.02, instrument="bench_read")
    assert any("S5.3" in e and "recorded" in e for e in acceptance.check(proc, blk, rec, tmp_path, None)[0])
    cfg = {"controls": {"throttle_track_tolerance": 0.05}}
    assert not any("S5.3" in e for e in acceptance.check(proc, blk, rec, tmp_path, cfg)[0])
    rec["steps"]["S5.3"]["value"] = 0.08
    assert any("S5.3" in e and "gives fail" in e for e in acceptance.check(proc, blk, rec, tmp_path, cfg)[0])
