"""Primary-document manifest: the rendered list is current, and a received file is pinned by its hash."""
import copy

import yaml

from tools import check_datasheets as cd


def _data():
    return yaml.safe_load(cd.SRC.read_text())


def test_committed_manifest_is_current_and_ordered():
    d = _data()
    assert cd.check(d) == []
    ids = [x["id"] for x in sorted(d["documents"], key=lambda x: x["priority"])]
    assert ids[:3] == ["DRV8353", "INA228", "DS12288"]
    for x in d["documents"]:
        assert x["part"] and x["unlocks"] and "official_url" in x


def test_a_received_file_is_pinned_by_its_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "DIR", tmp_path)
    d = copy.deepcopy(_data())
    doc = next(x for x in d["documents"] if x["id"] == "INA228")
    (tmp_path / doc["file"]).write_bytes(b"%PDF-1.7 test")
    msgs = cd.record(d)
    assert any("INA228: recorded" in m for m in msgs)
    assert cd.status(doc) == "file present, revision not recorded"     # the tool never guesses a revision
    doc["received"].update(revision="Rev. X", date="2026-10")
    assert cd.status(doc) == "received"
    (tmp_path / doc["file"]).write_bytes(b"%PDF-1.7 changed")
    assert any("does not match its recorded SHA-256" in e for e in cd.check(d))
