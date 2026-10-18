"""ERC record tied to the schematic inputs (tools/erc_record.py) and its use by the release gate (G5)."""
import json

from tools import erc_record as er


def test_committed_record_matches_the_current_schematic():
    ok, text = er.status()
    assert ok, text
    r = er.load()
    assert r["kicad_version"] == "8.0.9" and r["errors"] == 0 and "actions/runs/" in r["run"]


def test_any_input_change_invalidates_the_record(tmp_path, monkeypatch):
    before = er.inputs_hash()
    sheet = sorted(er.KICAD.glob("*.kicad_sch"))[1]
    copy = tmp_path / "kicad"
    copy.mkdir()
    for p in er.KICAD.iterdir():
        if p.is_file():
            (copy / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(er, "KICAD", copy)
    assert er.inputs_hash() == before                      # same bytes, same hash
    (copy / sheet.name).write_bytes(sheet.read_bytes().replace(b"(uuid", b"(uuid ", 1))
    assert er.inputs_hash() != before
    ok, text = er.status()
    assert not ok and "other schematic inputs" in text


def test_report_counts(tmp_path):
    rep = {"kicad_version": "8.0.9", "sheets": [{"violations": [{"severity": "warning", "type": "pin_not_driven"},
                                                                {"severity": "error", "type": "pin_conflict"}]}]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rep))
    assert er.report_counts(p) == ("8.0.9", 1, 1, ["pin_not_driven"])
