"""Telemetry procurement file: validation rules, totals and the generated tables."""
import copy

import yaml

from tools import gen_procurement as gp


def _data():
    return yaml.safe_load(gp.SRC.read_text())


def test_committed_file_is_valid_and_tables_are_current():
    d = _data()
    assert gp.validate(d) == []
    assert gp.render_readme(d, gp.README.read_text()) == gp.README.read_text()
    assert gp.doc(d) == gp.DOC.read_text()


def test_requested_lines_are_present():
    names = {it["item"] for it in _data()["items"]}
    for n in ("NUCLEO-U575ZI-Q development board", "Telematics PCB fabrication and assembly", "Wheel-speed Hall sensor",
              "Wheel magnets and mounting hardware", "6-axis IMU", "Temperature sensors/probes",
              "GNSS receiver/module, if not included in the PCB assembly", "Active GNSS antenna",
              "LTE modem, if not included in the PCB assembly", "LTE antenna", "SIM card and data plan",
              "Protected DC-DC power supply, if not included in the PCB assembly",
              "CAN transceiver/interface, if not included in the PCB assembly", "Connectors and wiring", "Driver display",
              "Optional steering-angle sensor"):
        assert n in names, n


def test_no_line_is_selected_ordered_or_received_without_evidence():
    for it in _data()["items"]:
        assert it["status"] in ("Candidate", "Blocked"), it["id"]     # nothing selected or ordered yet


def test_price_needs_a_dated_source_and_orders_need_evidence():
    d = _data()
    bad = copy.deepcopy(d)
    bad["items"][0]["unit_cost_usd"] = 25.0
    assert any("price.date" in e for e in gp.validate(bad))
    bad["items"][0]["price"] = {"supplier": "X", "reference": "quote 1", "date": "16/10/2026"}
    assert any("YYYY-MM-DD" in e for e in gp.validate(bad))
    bad = copy.deepcopy(d)
    bad["items"][0]["status"] = "Ordered"
    assert any("order_evidence" in e for e in gp.validate(bad))
    bad["items"][0]["status"] = "Bought"
    assert any("not one of" in e for e in gp.validate(bad))
    bad = copy.deepcopy(d)
    bad["items"].append(copy.deepcopy(bad["items"][0]))
    assert any("duplicate" in e for e in gp.validate(bad))


def test_totals_count_priced_lines_only_and_never_assembly_parts():
    d = _data()
    d["items"][0].update(unit_cost_usd=30.0, qty=2, price={"supplier": "S", "reference": "R", "date": "2026-10-16"})
    gnss = next(it for it in d["items"] if it["id"] == "gnss")
    gnss.update(unit_cost_usd=20.0, in_assembly=True, price={"supplier": "S", "reference": "R", "date": "2026-10-16"})
    assert gp.validate(d) == []
    s = gp.summary(d)
    assert s["subtotal"] == 60.0 and s["priced"] == 1 and s["counted"] == len(d["items"]) - 1
    table = "\n".join(gp.table(d))
    assert "| NUCLEO-U575ZI-Q development board | 2 | 30.00 | 60.00 | Candidate |" in table
    assert "in the PCB assembly line; not counted again" in table


def test_unknown_budget_prints_no_zero_total():
    block = gp.readme_block(_data())
    assert "$0" not in block and "0.00" not in block
    assert "TBD" in block and "unconfirmed" in block and "not stated" in block
