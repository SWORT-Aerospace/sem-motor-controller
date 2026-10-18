"""Protection topology and cross-artefact consistency of the draft hardware (tools/hw_consistency.py).

The checks run on the netlist KiCad exports. Each mutation test breaks one
protection path in a copy of that netlist and requires the checker to FAIL,
so a passing result is not vacuous.
"""
import pathlib
import re

import pytest

from tools import hw_consistency as HC

NET = pathlib.Path(HC.NET)


def _status(results, prefix):
    return next(s for c, s, _d in results if c.startswith(prefix))


def test_committed_design_has_no_contradiction():
    res = HC.run()
    failed = [(c, d) for c, s, d in res if s == "FAIL"]
    assert not failed, failed
    for p in ("PR1", "PR2", "PR3", "PR4", "PR5", "PR6", "PR7", "PN1", "BM1", "PW1"):
        assert _status(res, p) == "PASS", p


@pytest.fixture
def mutated(tmp_path, monkeypatch):
    def make(transform):
        text = transform(NET.read_text())
        p = tmp_path / "semmc.net"
        p.write_text(text)
        monkeypatch.setattr(HC, "NET", p)
        return HC.run()
    return make


def test_missing_enable_pull_down_is_caught(mutated):
    # R403 (DRV_EN_GATED -> GND) disconnected from GND: move its pin 2 onto a dummy net
    res = mutated(lambda t: re.sub(r'(\(node \(ref "R403"\) \(pin "2"\)[^\n]*\n)', "", t, count=1))
    assert _status(res, "PR3") == "FAIL" or _status(res, "PR1") == "FAIL"


def test_nfault_not_on_break_input_is_caught(mutated):
    # the MCU pin on DRV_NFAULT moved: nFAULT no longer reaches TIM1_BKIN (pin 46)
    res = mutated(lambda t: t.replace('(node (ref "U801") (pin "46") (pinfunction "PE15")',
                                      '(node (ref "U801") (pin "45") (pinfunction "PE14")', 1))
    assert _status(res, "PR4") == "FAIL"


def test_mcu_driving_enable_directly_is_caught(mutated):
    # an MCU output wired straight onto the driver ENABLE net bypasses HW_PERMIT
    res = mutated(lambda t: t.replace('(node (ref "U801") (pin "7") (pinfunction "PC13") (pintype "bidirectional"))',
                                      '(node (ref "U801") (pin "82") (pinfunction "PD0") (pintype "output"))', 1))
    assert _status(res, "PR1") == "FAIL"


def test_bench_gate_disable_path_holds_on_the_committed_netlist():
    res = HC.run()
    for p in ("BP1", "BP2", "BP3", "BP4"):
        assert _status(res, p) == "PASS", p
    assert _status(res, "BP5") == "OPEN"          # needs the DRV8353 data sheet


def test_pwm_pin_wired_to_a_gate_is_caught(mutated):
    # the MCU's PWM_A_HI net also reaching the high-side MOSFET gate: the bench image could then switch it
    res = mutated(lambda t: t.replace('    (net (code "69") (name "/bridge/GH_A")\n',
                                      '    (net (code "69") (name "/bridge/GH_A")\n'
                                      '      (node (ref "U801") (pin "15") (pinfunction "PC0") (pintype "bidirectional"))\n', 1))
    assert _status(res, "BP2") == "FAIL"


def test_second_path_charging_the_link_is_caught(mutated):
    # a resistor from the battery side straight onto VDC would power the driver with the precharge resistor unfitted
    def add(t):
        t = re.sub(r'(\(net \(code "\d+"\) \(name "/VBAT_SH"\)\n)', r'\1      (node (ref "R999") (pin "1") (pintype "passive"))\n', t, count=1)
        return re.sub(r'(\(net \(code "\d+"\) \(name "VDC"\)\n)', r'\1      (node (ref "R999") (pin "2") (pintype "passive"))\n', t, count=1)
    res = mutated(add)
    assert _status(res, "BP3") == "FAIL"
