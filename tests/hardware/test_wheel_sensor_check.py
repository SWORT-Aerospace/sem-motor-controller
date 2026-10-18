"""Wheel-magnet detection arithmetic (tools/wheel_sensor_check.py), checked by hand."""
import math

from tools import wheel_sensor_check as w


def test_field_window_hand_example():
    # 10 km/h on a 1.5 m wheel: 1.852 rev/s; magnet at 10 cm moves at 2*pi*0.1*1.852 = 1.1636 m/s;
    # a 10 mm window lasts 8.594 ms; with 4 magnets the gap is (0.6283/4 - 0.01)/1.1636 = 126.4 ms.
    d = w.windows(10 / 3.6, 1.5, 0.10, 0.010, 4)
    assert math.isclose(d["n"], 1.85185, rel_tol=1e-4)
    assert math.isclose(d["t_w"], 0.0085944, rel_tol=1e-4)
    assert math.isclose(d["t_g"], 0.12640, rel_tol=1e-3)
    assert math.isclose(d["f_p"], 7.4074, rel_tol=1e-4)


def test_sampled_detection_probability_and_guaranteed_speed():
    assert math.isclose(w.p_detect(0.0085944, 0.050), 0.171888, rel_tol=1e-4)
    assert w.p_detect(0.2, 0.075) == 1.0
    # every pass guaranteed only while t_w >= t_S,max: 0.01*1.5/(2*pi*0.1*0.075) m/s = 1.146 km/h
    assert math.isclose(w.v_guaranteed_kmh(1.5, 0.10, 0.010, 0.075), 1.1459, rel_tol=1e-3)


def test_report_uses_datasheet_sampling_periods():
    assert w.SAMPLED["DRV5032 20 Hz versions"] == (0.027, 0.050, 0.075)       # SLVSDC7F p. 6
    assert w.SAMPLED["DRV5032FB (5 Hz)"] == (0.117, 0.200, 0.286)
    assert w.CONT_DELAY_MAX_S == 25e-6 and w.CONT_BW_MIN_HZ == 20e3           # SLIS163G p. 6
    assert "not suitable for wheel speed" in w.report()
