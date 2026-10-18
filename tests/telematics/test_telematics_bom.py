"""The telematics bill of materials (tools/telematics_bom.py, hardware/telematics/bom.yaml)."""
import copy
import math

from tools import telematics_bom as tb

CONTROLLER_WORDS = ("mosfet", "drv835", "ina228", "gate driver", "shunt", "precharge", "bus capacitor", "dc-link",
                    "stm32g474", "heatsink", "pcb fabrication", "stencil")


def test_totals_are_sums_of_their_own_lines():
    d = tb.load()
    t = tb.totals(d)
    a_lines = [l for l in d["lines"] if l["config"] == "A" and l.get("low") is not None]
    parts = [l for l in a_lines if l["id"] != "shipping"]
    plo = sum(l["qty"] * l["low"] for l in parts)
    lo = sum(l["qty"] * l["low"] for l in a_lines)
    assert math.isclose(t["A"]["low"], round(lo, 2))                   # 0 % tax at the low end
    phi = sum(l["qty"] * l["high"] for l in parts)
    hi = sum(l["qty"] * l["high"] for l in a_lines) + 0.10 * phi
    assert math.isclose(t["A"]["high"], round(hi, 2)) and math.isclose(t["A"]["parts_low"], round(plo, 2))
    assert t["A"]["low"] < t["B"]["low"] < t["B_with_display"]["low"]
    assert t["B"]["high"] - t["A"]["high"] > 0


def test_unknown_prices_stay_unknown_and_are_listed():
    d = tb.load()
    t = tb.totals(d)
    assert "wedge_s" in t["unpriced_lines"]
    d2 = copy.deepcopy(d)
    next(l for l in d2["lines"] if l["id"] == "imu")["low"] = None
    assert "imu" in tb.totals(d2)["unpriced_lines"]


def test_no_controller_parts_and_every_line_has_a_source():
    d = tb.load()
    for l in d["lines"]:
        text = f"{l['item']} {l.get('part') or ''}".lower()
        assert not any(w in text for w in CONTROLLER_WORDS), l["id"]
        assert l.get("source") and l["evidence"] in ("snippet", "allowance"), l["id"]
    assert d["retrieved"] == "2026-10-18"
    assert {l["config"] for l in d["lines"]} <= {"A", "B", "B_display", "recurring", "recurring_once",
                                                 "recurring_per_mb", "equipment", "tax"}


def test_page_is_current_and_keeps_the_battery_as_reported():
    text = tb.render(tb.load(), tb.totals(tb.load()))
    assert tb.DOC.read_text() == text
    assert "48 V nominal, 10 Ah, as the vehicle team reports it" in text
    assert "Nothing has been ordered and no price is a quote" in text
