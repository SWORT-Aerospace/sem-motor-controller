"""Every numerical example in docs/MATH_SPEC.md, recomputed with the implementing code.

If a model changes, this test fails until the document is updated with it.
C-side examples (arbiter bounds, transforms, freshness lag, energy gaps) are
checked in firmware/tests (test_state_machine.c test_math_spec_examples,
test_control.c, test_freshness.c, test_core.c).
"""
import math

import pytest

from host.csia_adapter.adapter_v2 import E6Model
from host.telematics.clocks import UtcEstimator
from models.inverter.losses import InverterOperatingPoint, inverter_losses
from models.vehicle.longitudinal import SYNTHETIC_VEHICLE as P, resistive_force, tractive_force
from models.vehicle.powertrain import SYNTHETIC_FET, SYNTHETIC_GATE, SYNTHETIC_MOTOR, SyntheticPhysicsMap
from protocol.generated import semmc_protocol as proto
from tools.bus_load import analyse

G = 9.80665


def test_1_vehicle_dynamics():
    r = P.wheel_radius_m
    assert r == pytest.approx(0.238732, abs=1e-6)                       # 1.50 m / 2 pi
    assert P.m_eff(False) == pytest.approx(101.053, abs=1e-3)           # 100 + 0.06 / r^2
    assert P.m_eff(True) == pytest.approx(101.404, abs=1e-3)            # + 2e-4 * 10^2 / r^2
    assert P.crr * P.mass_kg * G == pytest.approx(2.4517, abs=1e-4)      # rolling
    assert 0.5 * 1.2 * 0.035 * 7.0 ** 2 == pytest.approx(1.029, abs=1e-6)   # aero at 7 m/s
    assert resistive_force(P, 7.0) == pytest.approx(3.7807, abs=1e-4)   # + 0.3 N drivetrain drag
    assert resistive_force(P, 7.0, grade=math.atan(0.01)) == pytest.approx(13.587, abs=1e-3)   # 1 % grade
    assert tractive_force(P, 1.0) == pytest.approx(39.794, abs=1e-3)    # 1 N*m * 10 * 0.95 / r
    assert resistive_force(P, 7.0) * 7.0 == pytest.approx(26.46, abs=0.01)   # wheel power at 7 m/s


def test_2_motor_and_inverter():
    assert SYNTHETIC_MOTOR.kt == pytest.approx(0.06)                     # 1.5 p lambda
    iq = 1.0 / SYNTHETIC_MOTOR.kt
    assert 1.5 * SYNTHETIC_MOTOR.rs_ohm * iq * iq == pytest.approx(41.667, abs=1e-3)   # copper at 1 N*m
    w = 7.0 * P.gear_ratio / P.wheel_radius_m
    assert w == pytest.approx(293.215, abs=1e-3)
    assert SYNTHETIC_MOTOR.k_iron_W_per_rad_s15 * w ** 1.5 == pytest.approx(10.04, abs=0.01)
    pm = SyntheticPhysicsMap(P)
    b = pm.breakdown(7.0, 0.1, 46.0)
    assert b["shaft_W"] == pytest.approx(29.32, abs=0.01)
    assert b["motor_cu_fe_W"] == pytest.approx(10.50, abs=0.01)
    assert b["total_W"] == pytest.approx(44.65, abs=0.01)
    assert pm.p_batt(7.0, 0.0, 46.0, 25.0, "coast_gate_off") == pytest.approx(3.0)
    op = InverterOperatingPoint(v_bus_V=46.0, i_ph_pk_A=5.0, m_index=0.5, cos_phi=0.95, f_sw_Hz=20000.0,
                                deadtime_s=200e-9, tj_C=60.0)
    L = inverter_losses(SYNTHETIC_FET, SYNTHETIC_GATE, op)
    assert L["gate_drive_W"] == pytest.approx(6 * 60e-9 * 10.0 * 20000.0)   # 6 Qg Vdrv fsw = 72 mW
    assert L["total_W"] == pytest.approx(0.686, abs=1e-3)


def test_4_dp_transition():
    m = P.m_eff(True)
    v0, ds, T = 7.0, 10.0, 0.5
    F = tractive_force(P, T)
    v1 = v0
    for _ in range(20):                                                   # v_mid fixed point, as dp.py
        v1 = math.sqrt(v0 * v0 + 2 * ds * (F - resistive_force(P, 0.5 * (v0 + v1))) / m)
    dt = 2 * ds / (v0 + v1)
    p = SyntheticPhysicsMap(P).p_batt(0.5 * (v0 + v1), T, 46.0)
    assert (F, v1, dt) == (pytest.approx(19.897, abs=1e-3), pytest.approx(7.2230, abs=1e-4),
                           pytest.approx(1.4062, abs=1e-4))
    assert p * dt == pytest.approx(246.8, abs=0.1)


def test_5_csia_power_balance_v2():
    m = E6Model(R_ohm=0.0997, c_sw_W_per_A=0.125, p0_W=3.16, s0_W=2.20)
    iq, w, kt = 15.0, 250.0, 0.06
    p_mech = kt * iq * w
    cu = 1.5 * m.R_ohm * iq * iq
    expected = p_mech + cu + m.c_sw_W_per_A * iq + m.p0_W
    var = (m.u_R * cu) ** 2 + (m.u_rel * p_mech) ** 2 + m.s0_W ** 2 + 1.0 ** 2
    assert (p_mech, cu, expected) == (pytest.approx(225.0), pytest.approx(33.65, abs=0.01),
                                      pytest.approx(263.69, abs=0.01))
    assert math.sqrt(var) == pytest.approx(8.77, abs=0.01)
    r = 3 * math.sqrt(var)                                              # lambda = r^2 / var = 9 at 3 sigma
    assert r * r / var == pytest.approx(9.0)


def test_6_telematics_and_protocol():
    C, ppr, win = 1.50, 32, 0.1
    assert 5 * C / (ppr * win) == pytest.approx(2.344, abs=1e-3)        # 5 hall edges in 100 ms
    assert C / (ppr * win) == pytest.approx(0.469, abs=1e-3)            # quantisation step
    est = UtcEstimator()
    for k in range(4):
        est.add_edge(10.0 + k * 1.00004, 1_792_141_210 + k)            # local clock 40 ppm fast
    u, q, _ = est.utc(12.5)
    assert q == "pps" and u == pytest.approx(1_792_141_210 + 2.5 / 1.00004, abs=1e-6)
    assert proto._crc8(b"123456789") ^ 0xFF == 0x4B                    # CRC-8/SAE-J1850 check value
    res = analyse()
    c_us = next(m["C_us"] for m in res["messages"] if m["name"] == "sup_torque_req")
    assert c_us == pytest.approx(270.0)                                 # (55 + 10*8) bits * 2 us at 500 kbit/s
    assert 47 + 8 * 8 + (34 + 8 * 8 - 1) // 4 == 55 + 10 * 8           # exact stuffing bound for n = 8
    assert res["semmc_utilisation"] == pytest.approx(0.126, abs=0.0005)
    assert 8 * 1024 * 1024 / (9.35 * 1024) / 60 == pytest.approx(14.6, abs=0.05)   # (6.4)
