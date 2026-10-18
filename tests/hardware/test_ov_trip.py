"""Over-voltage trip worst-case tool (tools/ov_trip_worst_case.py)."""
import copy
import subprocess
import sys

import yaml

from tools import ov_trip_worst_case as ov

ROOT = ov.ROOT


def inputs():
    return yaml.safe_load(ov.SRC.read_text())


def test_report_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "ov_trip_worst_case.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_nominal_thresholds_by_hand():
    e = ov.evaluate(inputs())
    trip, rel = e["nominal"]
    assert abs(rel - 390.0 / 400.0) < 1e-12  # tripped: V+ = V_ref x R_h / (R_s + R_h), output at 0 V
    # released: about 2 uA from the pull-up through 390 k + 10 k raises V+ by 10 k x 2 uA = 20 mV
    i = (3.3 - 2.495) / (10e3 + 390e3 + 10e3)
    assert abs(trip - (2.495 + 10e3 * i) / 2.495) < 1e-12
    lo_t, hi_t, lo_r, hi_r = e["resistors_only"]
    assert lo_t < trip < hi_t and lo_r < rel < hi_r


def test_full_worst_case_only_when_every_bound_exists():
    e = ov.evaluate(inputs())
    assert "worst_case" not in e and "V_os_V max" in e["missing"]
    # INVENTED device bounds, only to exercise the evaluation: not data-sheet values.
    d = copy.deepcopy(inputs())
    d["devices"]["V_ref_V"].update(min=2.48, max=2.51)
    d["supply"]["V_3V3_V"].update(min=3.2, max=3.4)
    for k, v in {"V_os_V": 0.005, "I_bias_A": 1e-9, "V_OL_V": 0.2, "I_leak_out_A": 1e-7,
                 "I_leak_pin_A": 1e-6}.items():
        d["devices"][k]["max"] = v
    d["devices"]["V_hys_internal_V"]["nominal"] = 0.0
    e2 = ov.evaluate(d)
    assert e2["missing"] == []
    lo_t, hi_t, lo_r, hi_r = e2["worst_case"]
    r_lo_t, r_hi_t, r_lo_r, r_hi_r = e2["resistors_only"]
    assert lo_t < r_lo_t and hi_t > r_hi_t and lo_r < r_lo_r and hi_r > r_hi_r
    # The 5 mV offset alone moves the trip by 5 mV / 2.495 V = 0.2 % of the set point.
    assert hi_t - r_hi_t > 0.002
    assert "Full worst case | pending" not in ov.render(d)
