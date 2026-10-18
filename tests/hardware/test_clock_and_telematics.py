"""Regression tests for the v0.3 clock-tree and telematics-budget claims (host computations only)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import clock_tree as ct  # noqa: E402
import telematics_budget as tb  # noqa: E402


def _fd_case():
    return next(c for c in ct.BUS_CASES if c["key"] == "FD")


def test_8mhz_crystal_reaches_fd_500k_2m_at_80_80_with_160mhz_cpu():
    """The withdrawn v0.2 claim said an 8 MHz crystal cannot place the data-phase sample point at 80 %."""
    pll = max(ct.pll_configs(8e6, 160e6), key=lambda p: (p["vin"], -p["M"]))
    best = ct.evaluate(8e6, 160e6, pll, _fd_case())
    assert best is not None and best["f_kernel"] == 40e6 and not best["above_48MHz"]
    assert abs(best["nominal"]["sp"] - 0.80) < 1e-9 and abs(best["data"]["sp"] - 0.80) < 1e-9
    assert best["same_tq"] and best["tol"]["df_max"] > 50 * ct.OSC_BUDGET


def test_every_candidate_tree_has_a_feasible_classic_timing():
    for hse in (8e6, 12e6, 16e6, 20e6, 24e6, 40e6):
        for sc in (170e6, 160e6, 150e6, 144e6):
            pll = max(ct.pll_configs(hse, sc), key=lambda p: (p["vin"], -p["M"]))
            for key in ("C250", "C500", "C1M"):
                case = next(c for c in ct.BUS_CASES if c["key"] == key)
                b = ct.evaluate(hse, sc, pll, case)
                assert b is not None and b["tol"]["df_max"] > 10 * ct.OSC_BUDGET, (hse, sc, key)


def test_pll_settings_respect_published_ranges():
    for hse in (8e6, 16e6, 25e6, 40e6):
        for p in ct.pll_configs(hse, 170e6):
            assert 1 <= p["M"] <= 16 and 8 <= p["N"] <= 127 and p["R"] in (2, 4, 6, 8)
            assert ct.VCO_IN[0] <= p["vin"] <= ct.VCO_IN[1] and ct.VCO_OUT[0] <= p["vco"] <= ct.VCO_OUT[1]


def test_dead_time_code_matches_timing_budget_at_170mhz():
    code, achieved = ct.dtg(200e-9, 170e6)
    assert code == 0x22 and abs(achieved - 200e-9) < 1e-12


def test_controller_frame_rate_and_flash_fill_time():
    rows = tb.semmc_rates()
    f_ctrl = sum(f for _n, _i, s, f in rows if s == "controller")
    f_sup = sum(f for _n, _i, s, f in rows if s != "controller")
    assert round(f_ctrl) == 394 and round(f_sup) == 72   # protocol 1.1: + ctrl_energy_quality at 10 Hz
    t_fill = tb.FLASH_B * tb.FLASH_USABLE / ((f_ctrl + f_sup) * tb.REC_CAN_B)
    assert 16 * 60 < t_fill < 18 * 60          # ~17 min: a 40 min attempt does not fit at full rate
