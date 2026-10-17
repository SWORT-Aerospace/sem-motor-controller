"""Project procurement file: validation rules, estimate references, subtotals and the generated tables."""
import copy
import json

import yaml

from tools import gen_procurement as gp


def _data():
    return yaml.safe_load(gp.SRC.read_text())


def _refs():
    return gp.load_refs()


def test_committed_file_is_valid_and_tables_are_current():
    d = _data()
    b, p = _refs()
    assert gp.validate(d, b, p) == []
    assert gp.render_readme(d, gp.README.read_text(), b, p) == gp.README.read_text()
    assert gp.doc(d, b, p) == gp.DOC.read_text()


def test_requested_lines_and_categories_are_present():
    d = _data()
    assert list(d["categories"]) == ["controller", "telemetry", "shared", "fabrication", "shipping_tax",
                                     "spares_revision", "development", "recurring", "contingency"]
    names = {it["item"] for it in d["items"]}
    for n in ("NUCLEO-U575ZI-Q development board", "Telematics PCB fabrication and assembly", "Wheel-speed Hall sensor",
              "Wheel magnets and mounting hardware", "6-axis IMU", "Temperature sensors/probes",
              "GNSS receiver/module, if not included in the PCB assembly", "Active GNSS antenna",
              "LTE modem, if not included in the PCB assembly", "LTE antenna", "SIM card and data plan",
              "Protected DC-DC supply for the telemetry unit, if not included in the PCB assembly",
              "CAN transceiver/interface, if not included in the PCB assembly",
              "Local log storage (microSD card and socket), if not included in the PCB assembly",
              "Telemetry harness (sensor cables and connectors)", "Driver display", "Optional steering-angle sensor",
              "Controller board parts, one board", "Controller PCB fabrication (5 boards, 4-layer, 2 oz outer copper)"):
        assert n in names, n
    cat = {it["id"]: it["category"] for it in d["items"]}
    assert cat["nucleo"] == "development" and cat["dcdc"] == "shared" and cat["sim"] == "recurring"


def test_controller_estimates_reproduce_the_priced_bom_without_double_counting():
    """The motor-controller lines (less the enclosure, which budget.json counts under integration, the revision and
    the assembly-service alternative) add up to the budget's controller-only figure; the shared, bench-load and
    equipment lines add up to its integration and equipment figures. Every budget.json entry is therefore used
    once."""
    d = _data()
    b, p = _refs()
    s1 = b["scenarios"][d["estimate_scenario"]]
    lines = {it["id"]: gp.cost(it, d, b, p) for it in d["items"]}
    mc = [k for i, k in lines.items() if i.startswith("mc_") and i not in ("mc_enclosure", "mc_revision",
                                                                     "mc_assembly_service")]
    assert abs(sum(k["line"][0] for k in mc) - s1["controller_only"][0]) < 1e-6
    assert abs(sum(k["line"][1] for k in mc) - s1["controller_only"][1]) < 1e-6
    inc = [lines[i] for i in ("power_connectors", "signal_connectors", "wire", "mc_enclosure", "bench_load")]
    assert [sum(k["line"][j] for k in inc) for j in (0, 1)] == s1["incremental"]
    eq = [lines[i] for i in ("swd", "usb_can", "bench_supply", "dmm")]
    assert [sum(k["line"][j] for k in eq) for j in (0, 1)] == s1["equipment_if_not_owned"]
    tot = gp.summary(d, b, p)["total"]
    assert abs(tot["est"][0] - s1["complete_buying_equipment"][0]) < 1e-6
    assert abs(tot["est"][1] - s1["complete_buying_equipment"][1]) < 1e-6


def test_readme_numbers_follow_budget_json():
    d = _data()
    b, p = _refs()
    s1 = b["scenarios"][d["estimate_scenario"]]
    block = gp.readme_block(d, b, p)
    lo, hi = s1["complete_buying_equipment"]
    assert f"**${lo:,.0f} to ${hi:,.0f}**" in block
    plo, phi = s1["parts"]
    page = gp.doc(d, b, p)
    assert f"| Controller board parts, one board | " in page and f"est. {plo:,.0f} to {phi:,.0f}" in page
    changed = copy.deepcopy(b)
    changed["scenarios"][d["estimate_scenario"]]["parts"] = [100.0, 300.0]
    assert "est. 100 to 300" in gp.doc(d, changed, p)


def test_no_line_is_selected_ordered_or_received_without_evidence():
    for it in _data()["items"]:
        assert it["status"] in ("Candidate", "Blocked"), it["id"]     # nothing selected or ordered yet


def test_price_needs_a_dated_source_and_orders_need_evidence():
    d = _data()
    b, p = _refs()
    i = next(n for n, it in enumerate(d["items"]) if it["id"] == "nucleo")
    bad = copy.deepcopy(d)
    bad["items"][i]["unit_cost_usd"] = 25.0
    assert any("price.date" in e for e in gp.validate(bad, b, p))
    bad["items"][i]["price"] = {"supplier": "X", "reference": "quote 1", "date": "16/10/2026"}
    assert any("YYYY-MM-DD" in e for e in gp.validate(bad, b, p))
    bad = copy.deepcopy(d)
    bad["items"][i]["status"] = "Ordered"
    assert any("order_evidence" in e for e in gp.validate(bad, b, p))
    bad["items"][i]["status"] = "Bought"
    assert any("not one of" in e for e in gp.validate(bad, b, p))
    bad = copy.deepcopy(d)
    bad["items"].append(copy.deepcopy(bad["items"][i]))
    assert any("duplicate" in e for e in gp.validate(bad, b, p))


def test_estimate_references_must_resolve_and_not_mix_with_quotes():
    d = _data()
    b, p = _refs()
    i = next(n for n, it in enumerate(d["items"]) if it["id"] == "mc_pcb")
    bad = copy.deepcopy(d)
    bad["items"][i]["estimate"] = {"budget": "controller_items/No such line"}
    assert any("does not resolve" in e for e in gp.validate(bad, b, p))
    bad = copy.deepcopy(d)
    bad["items"][i].update(unit_cost_usd=50.0, price={"supplier": "S", "reference": "R", "date": "2026-10-17"})
    assert any("only one of" in e for e in gp.validate(bad, b, p))
    bad = copy.deepcopy(d)
    bad["items"][i]["estimate"] = {"pricing": "equipment/Oscilloscope"}   # 0 to 0 in pricing.yaml
    assert any("not_budgeted" in e for e in gp.validate(bad, b, p))


def test_totals_count_priced_lines_only_and_never_assembly_or_optional_parts():
    d = _data()
    b, p = _refs()
    base = gp.summary(d, b, p)["total"]
    nuc = next(it for it in d["items"] if it["id"] == "nucleo")
    nuc.update(unit_cost_usd=30.0, qty=2, price={"supplier": "S", "reference": "R", "date": "2026-10-16"})
    gnss = next(it for it in d["items"] if it["id"] == "gnss")
    gnss.update(unit_cost_usd=20.0, in_assembly=True, price={"supplier": "S", "reference": "R", "date": "2026-10-16"})
    assert gp.validate(d, b, p) == []
    t = gp.summary(d, b, p)["total"]
    assert t["quoted"] == 60.0 and t["n_quoted"] == 1
    assert t["unpriced"] == base["unpriced"] - 2 and t["not_counted"] == base["not_counted"] + 1
    assert abs(t["est"][0] - base["est"][0] - 60.0) < 1e-9
    table = "\n".join(gp.table(d, b, p))
    assert "| NUCLEO-U575ZI-Q development board |" in table and "| 2 | 30.00 | 60.00 | Candidate |" in table
    assert "in the PCB assembly line; not counted again" in table
    rev = next(it for it in d["items"] if it["id"] == "mc_revision")
    assert rev["optional"] and gp.counted(rev, gp.cost(rev, d, b, p)) is False


def test_unknown_costs_print_tbd_never_zero_and_no_budget_fit_is_claimed():
    d = _data()
    for block in (gp.readme_block(d), gp.doc(d)):
        assert "$0 " not in block and "| 0.00 |" not in block and "est. 0 to 0" not in block
        assert "TBD" in block and "unconfirmed" in block and "not established" in block
        assert "fits" not in block.replace("a fit within", "")
    assert "not budgeted" in gp.doc(d)                 # the borrowed oscilloscope is shown, not priced at zero


def test_builds_keep_the_whole_controller_and_match_the_priced_bom():
    d = _data()
    b, p = _refs()
    s1 = b["scenarios"][d["estimate_scenario"]]
    mini = next(x for x in d["builds"] if x["id"] == "minimum")
    s = gp.build_sums(mini, d, b, p)
    assert not s["owned"][2] and not s["bought"][2]                       # every line of the minimum build is priced
    assert [round(v, 6) for v in s["owned"][:2]] == [round(v, 6) for v in s1["complete_owned_equipment"]]
    assert [round(v, 6) for v in s["bought"][:2]] == [round(v, 6) for v in s1["complete_buying_equipment"]]
    full = gp.build_sums(next(x for x in d["builds"] if x["id"] == "full"), d, b, p)
    assert full["owned"][2] and "not established" in gp.verdict(*full["owned"], 1000)
    bad = copy.deepcopy(d)
    next(x for x in bad["builds"] if x["id"] == "minimum")["includes"].remove("mc_thermal")
    assert any("protection is never deferred" in e for e in gp.validate(bad, b, p))
    bad = copy.deepcopy(d)
    next(x for x in bad["builds"] if x["id"] == "logging")["includes"].append("display")
    next(x for x in bad["builds"] if x["id"] == "logging")["deferred"][-2]["lines"].append("display")
    assert any("both included and deferred" in e for e in gp.validate(bad, b, p))
    assert gp.verdict(100, 900, [], 500).startswith("straddles") and gp.verdict(600, 900, [], 500).startswith("over")


def test_budget_json_is_the_file_price_bom_writes():
    b = json.loads(gp.BUDGET.read_text())
    assert "S1 one functional prototype" in b["scenarios"] and "by_evidence" in b
