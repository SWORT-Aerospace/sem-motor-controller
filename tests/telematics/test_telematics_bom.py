"""The telematics bill of materials (tools/telematics_bom.py, hardware/telematics/bom.yaml)."""
import copy
import math
import re

from tools import telematics_bom as tb

CONTROLLER_WORDS = ("mosfet", "drv835", "ina228", "gate driver", "shunt", "precharge", "bus capacitor", "dc-link",
                    "stm32g474", "heatsink", "pcb fabrication", "stencil")


def _cum(d, configs):
    return [l for l in d["lines"] if l["config"] in configs and l.get("low") is not None]


def test_totals_are_sums_of_their_own_lines():
    d = tb.load()
    t = tb.totals(d)
    for name, configs in tb.CONFIGS:
        lines = _cum(d, configs)
        parts = [l for l in lines if l["id"] != "shipping"]
        assert math.isclose(t[name]["low"], round(sum(l["qty"] * l["low"] for l in lines), 2))   # 0 % tax at the low end
        hi = sum(l["qty"] * l["high"] for l in lines) + 0.10 * sum(l["qty"] * l["high"] for l in parts)
        assert math.isclose(t[name]["high"], round(hi, 2)), name
    assert t["bench"]["high"] < t["A"]["low"] < t["B"]["low"] < t["B_with_display"]["low"]
    # options are in no total
    d2 = copy.deepcopy(d)
    for l in d2["lines"]:
        if l["config"] == "option":
            l["low"] = l["high"] = 1e6
    assert tb.totals(d2)["A"] == t["A"] and set(t["options_not_counted"]) == {"storage_card", "storage_socket",
                                                                             "temp_probes"}


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
    assert {l["config"] for l in d["lines"]} <= {"bench", "A", "B", "B_display", "option", "recurring", "recurring_once",
                                                 "recurring_per_mb", "equipment", "tax"}


def test_no_assumed_pack_and_the_vehicle_supply_stays_blocked():
    """The pack's maximum voltage is unknown: no line assumes a cell count, the TVS / DC-DC pair that broke the
    clamp rule is rejected, and the vehicle power connection is blocked; the bench needs none of it."""
    raw = tb.SRC.read_text()
    assert not re.search(r"\b1[0-9]S\b|54\.6 V", raw)
    d = tb.load()
    assert d["supply"]["battery_max_V"] is None and d["supply"]["vehicle_power_connection"] == "blocked"
    v = tb.supply_verdicts(d["supply"])
    assert v and not any(p["accepted"] for p in v)
    assert any("93.6 V" in r and "75 V" in r for r in v[0]["reasons"])
    for i in ("tvs", "dcdc", "fuse", "fuse_holder"):
        l = next(x for x in d["lines"] if x["id"] == i)
        assert l["blocked_by"] == "B-BAT-V" and l["config"] == "A"
    assert not [l for l in d["lines"] if l["config"] == "bench" and l.get("blocked_by")]
    bench_text = " ".join(f"{l['item']} {l.get('part')}" for l in d["lines"] if l["config"] == "bench").lower()
    assert not any(w in bench_text for w in ("tvs", "dc-dc", "fuse", "schottky"))
    # unblocking without a pack voltage is refused
    d2 = copy.deepcopy(d)
    d2["supply"]["vehicle_power_connection"] = "allowed"
    assert any("blocked while battery_max_V is unknown" in e for e in tb.validate(d2))


def test_every_bench_sensor_and_storage_part_has_its_firmware_driver():
    d = tb.load()
    assert tb.validate(d) == []
    bench = {l["id"]: l for l in d["lines"] if l["config"] == "bench"}
    for i in ("mcu", "nor_chip", "imu", "tmp117", "can_xcvr"):
        assert bench[i].get("driver") and bench[i].get("checks"), i
    assert "W25Q128JV" in bench["nor_chip"]["part"] and "TMP117" in bench["tmp117"]["item"]
    assert "ISM330DHCX" in bench["imu"]["part"] and "TJA1051" in bench["can_xcvr"]["part"]
    # nothing in the bench or in A needs a driver that is not written
    for l in d["lines"]:
        if l["config"] in ("bench", "A"):
            assert "ds18b20" not in f"{l['item']} {l.get('part')}".lower(), l["id"]
            assert "microsd" not in l["item"].lower(), l["id"]
    d2 = copy.deepcopy(d)
    next(l for l in d2["lines"] if l["id"] == "tmp117")["checks"] = "0x9999"
    next(l for l in d2["lines"] if l["id"] == "imu")["driver"] = "telematics/firmware/src/nope.c"
    err = tb.validate(d2)
    assert any("tmp117" in e for e in err) and any("imu" in e and "does not exist" in e for e in err)
    # the firmware probes every TMP117 address the configuration uses
    main = (tb.ROOT / "telematics/firmware/platform/u575/main_u575.c").read_text()
    assert "0x48u; a <= 0x4Bu" in main


def test_page_is_current_and_keeps_the_battery_as_reported():
    text = tb.render(tb.load(), tb.totals(tb.load()))
    assert tb.DOC.read_text() == text
    assert "48 V nominal, 10 Ah, as the vehicle team reports it" in text
    assert "Nothing has been ordered and no price is a quote" in text
    assert "**the vehicle power connection is blocked**" in text and "13S" not in text


PLAN = tb.ROOT / "docs" / "TELEMETRY_BOM_PLAN.md"


def _money(lo, hi):
    f = lambda x: f"{x:,.2f}"                                   # noqa: E731
    return f(lo) if math.isclose(lo, hi) else f"{f(lo)} to {f(hi)}"


def _tables(text):
    """Every pipe table of a page as (header cells, body rows)."""
    out, cur = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            cur = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cur is None:
            cur = (cells, [])
            out.append(cur)
        elif not set("".join(cells)) <= set("-: "):
            cur[1].append(cells)
    return out


def test_bom_plan_lists_every_line_once_with_the_bom_s_quantity_and_prices():
    d = tb.load()
    lines = {l["id"]: l for l in d["lines"]}
    seen = []
    for head, rows in _tables(PLAN.read_text()):
        if head[0] != "ID":
            continue
        q, u, ext = head.index("Qty"), head.index("Unit (USD)"), head.index("Line (USD)")
        lo = hi = 0.0
        for row in rows:
            m = re.fullmatch(r"`(\w+)`", row[0])
            if not m:                                               # the table's total: the sum of its rows
                assert row[0] == "**Total**" and row[ext] == f"**{_money(lo, hi)}**", row
                continue
            l = lines[m.group(1)]
            seen.append(l["id"])
            assert row[q] == str(l["qty"]), l["id"]
            if l["low"] is None:
                assert row[u] == row[ext] == "unknown", l["id"]
                continue
            assert row[u] == _money(l["low"], l["high"]), l["id"]
            assert row[ext] == _money(l["qty"] * l["low"], l["qty"] * l["high"]), l["id"]
            lo, hi = lo + l["qty"] * l["low"], hi + l["qty"] * l["high"]
    listed = [l["id"] for l in d["lines"] if l["config"] in ("bench", "A", "B", "B_display", "option", "equipment")]
    assert sorted(seen) == sorted(listed)                            # the whole BOM, each line once


def test_bom_plan_stage_totals_recurring_cost_and_battery_are_the_bom_s():
    import yaml
    d = tb.load()
    t = tb.totals(d)
    lines = {l["id"]: l for l in d["lines"]}
    text = PLAN.read_text()
    minimal = [lines[i] for i in yaml.safe_load((tb.ROOT / "telematics/bench/bench.yaml").read_text())["minimal"]["parts"]]
    stages = {r[0]: r[2] for head, rows in _tables(text) if head[0] == "Stage" and "Within $500?" in head for r in rows}
    assert stages["Minimal bench"] == _money(round(sum(l["qty"] * l["low"] for l in minimal), 2),
                                             round(1.10 * sum(l["qty"] * l["high"] for l in minimal), 2))
    for stage, key in (("Full bench", "bench"), ("Configuration A", "A"), ("Configuration B", "B"),
                       ("B with display", "B_with_display")):
        assert stages[stage] == _money(t[key]["low"], t[key]["high"]), stage
        if key != "B_with_display":
            assert f"**${t[key]['low']:,.2f} to ${t[key]['high']:,.2f}**" in text      # the lead's figures
    for config, words in (("bench", "before tax; the minimal bench"), ("A", "to the bench kit before tax"),
                          ("B", "LTE uplink, $")):
        part = [l for l in d["lines"] if l["config"] == config and l["low"] is not None]
        lo, hi = sum(l["qty"] * l["low"] for l in part), sum(l["qty"] * l["high"] for l in part)
        assert f"${lo:,.2f} to ${hi:,.2f}" in text and words in text, config
    r = t["recurring"]
    assert f"${r['per_month_low']:.2f} to ${r['per_month_high']:.2f} a month" in text
    assert f"{r['mb_per_running_hour']:.1f} MB per running hour" in text
    assert "**48 V nominal, 10 Ah, as the vehicle team reports it**" in text
    assert "Nothing has been ordered and no price is a quote" in text
