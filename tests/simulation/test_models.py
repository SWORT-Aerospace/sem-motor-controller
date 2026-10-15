"""Vehicle, inverter and optimisation models (SYNTHETIC parameters)."""
import dataclasses
import math

import numpy as np
import pytest

from models.inverter import losses as L
from models.optimization import dp
from models.optimization.strategies import (Command, DriverModel, EnvelopeBrakeCue, PaceCorrector, SimConfig,
                                            constant_speed, schedule_follower, simulate)
from models.optimization.track import Track, synthetic_track, synthetic_track_flat
from models.vehicle.longitudinal import (SYNTHETIC_VEHICLE as V, fit_coastdown, resistive_force,
                                         simulate_coastdown)
from models.vehicle.powertrain import (MeasuredLossMap, SyntheticPhysicsMap, check_no_double_counting)


# ---------------------------------------------------------------- vehicle
def test_force_signs_and_wind():
    assert resistive_force(V, 0.0) == 0.0                       # no rolling force at rest
    assert resistive_force(V, 5.0, grade=0.02) > resistive_force(V, 5.0)
    assert resistive_force(V, 5.0, grade=-0.02) < resistive_force(V, 5.0)
    head = resistive_force(V, 5.0, wind=-3.0)                   # headwind: v_air = 8
    tail = resistive_force(V, 5.0, wind=+3.0)                   # tailwind: v_air = 2
    assert head > resistive_force(V, 5.0) > tail
    # tailwind faster than the car pushes it (negative aero term)
    assert resistive_force(V, 1.0, wind=4.0) < resistive_force(V, 1.0, wind=0.0)
    assert resistive_force(V, 6.0, curvature=1 / 20) > resistive_force(V, 6.0)
    # coupled unpowered motor adds drag only without a freewheel
    assert resistive_force(V, 6.0, motor_coupled_unpowered=True) > resistive_force(V, 6.0)


def test_coastdown_wide_range_identifies_crr_and_cda():
    veh = dataclasses.replace(V, cda_m2=0.08)                    # a less slippery car for a clearer test
    t, v, m_eff = simulate_coastdown(veh, 14.0, 2.0, dt=0.5, noise_mps=0.0005)
    fit = fit_coastdown(t, v, m_eff, veh.mass_kg)
    assert fit.identifiable, fit.verdict
    assert fit.crr(veh.mass_kg, veh.drivetrain_drag_N) == pytest.approx(veh.crr, rel=0.15)
    assert fit.cda(veh.rho_air) == pytest.approx(veh.cda_m2, rel=0.15)


def test_coastdown_narrow_range_is_not_claimed_identifiable():
    t, v, m_eff = simulate_coastdown(V, 7.0, 6.0, dt=0.5, noise_mps=0.003)
    fit = fit_coastdown(t, v, m_eff, V.mass_kg)
    assert not fit.identifiable
    assert "NOT separately identifiable" in fit.verdict


# ---------------------------------------------------------------- inverter
def test_synchronous_conduction_quarter_rule_numerically():
    """Average of d(theta) * i(theta)^2 over a period equals I_pk^2/4 for any M, phi."""
    th = np.linspace(0, 2 * np.pi, 200001)[:-1]
    for M in (0.2, 0.8, 1.1):
        for phi in (0.0, 0.6, 1.2):
            d = 0.5 * (1 + M * np.sin(th))
            i = np.sin(th - phi)
            assert np.mean(d * i * i) == pytest.approx(0.25, abs=1e-6)
            d_svpwm = d + 0.5 * (M / 6) * np.sin(3 * th)        # third-harmonic zero sequence
            assert np.mean(d_svpwm * i * i) == pytest.approx(0.25, abs=1e-6)


def test_dc_link_ripple_formula_against_switching_simulation():
    """Independent check: simulate the inverter DC-side current with carrier
    PWM, remove the mean, compare RMS with the closed-form expression."""
    f1, fsw = 50.0, 20000.0
    I_pk, M, phi = 10.0, 0.6, 0.3
    t = np.arange(0, 1 / f1, 1 / (fsw * 400))
    tri = 2 * np.abs(((t * fsw) % 1.0) - 0.5)                    # 0..1 triangle carrier
    i_dc = np.zeros_like(t)
    for k in range(3):
        ang = 2 * np.pi * f1 * t - k * 2 * np.pi / 3
        d = 0.5 * (1 + M * np.sin(ang))
        upper_on = d > tri
        i_dc += upper_on * I_pk * np.sin(ang - phi)
    sim_rms = np.sqrt(np.mean((i_dc - i_dc.mean()) ** 2))
    formula = L.dc_link_ripple_rms(I_pk / math.sqrt(2), M, math.cos(phi))
    assert formula == pytest.approx(sim_rms, rel=0.03)


def test_loss_breakdown_monotonic_and_parallel_tradeoff():
    from models.vehicle.powertrain import SYNTHETIC_FET as F, SYNTHETIC_GATE as G
    op = L.InverterOperatingPoint(v_bus_V=46, i_ph_pk_A=20, m_index=0.8, cos_phi=0.95, f_sw_Hz=20e3, deadtime_s=200e-9)
    a = L.inverter_losses(F, G, op)
    b = L.inverter_losses(F, G, dataclasses.replace(op, f_sw_Hz=40e3))
    assert b["switching_W"] == pytest.approx(2 * a["switching_W"])
    assert b["conduction_W"] == pytest.approx(a["conduction_W"])
    # paralleling halves conduction but raises gate-charge-limited switching and gate losses
    c = L.inverter_losses(F, G, dataclasses.replace(op, n_parallel=2))
    assert c["conduction_W"] == pytest.approx(a["conduction_W"] / 2)
    assert c["switching_W"] > a["switching_W"] and c["gate_drive_W"] > a["gate_drive_W"]
    # at light load, paralleling can INCREASE total loss
    light = dataclasses.replace(op, i_ph_pk_A=2.0)
    assert L.inverter_losses(F, G, dataclasses.replace(light, n_parallel=2))["total_W"] > \
        L.inverter_losses(F, G, light)["total_W"]


def test_precharge_and_shunt_and_bus_margin():
    p = L.precharge(c_F=1e-3, v_V=50.4, r_ohm=47.0)
    assert p["tau_s"] == pytest.approx(0.047)
    assert p["resistor_energy_J"] == pytest.approx(0.5 * 1e-3 * 50.4 ** 2)
    sh = L.shunt(1e-3, 40.0, 0.8, 0.9, 20.0, 3.3, 12, 100e-6)
    assert sh["i_full_scale_A"] == pytest.approx(82.5)
    assert sh["offset_A"] == pytest.approx(0.1)               # 100 uV / 1 mOhm
    assert sh["p_each_W"] == pytest.approx(1e-3 * 1600 / 4)
    assert L.max_bus_voltage(50.4, 0.25, 0.0) == pytest.approx(63.0)


def test_measured_map_refuses_extrapolation_and_double_count(tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("# includes=motor_copper,inverter,drivetrain ; v_bus=46 ; provenance=TEST\n"
                 "speed_rad_s,torque_Nm,p_loss_W\n0,0,1\n0,1,5\n100,0,2\n100,1,9\n")
    m = MeasuredLossMap.from_csv(f, V)
    assert m.p_batt(V.wheel_radius_m * 50 / V.gear_ratio, 0.5, 46) == pytest.approx(50 * 0.5 + 4.25)
    with pytest.raises(ValueError):
        m.p_batt(20.0, 0.5, 46)
    with pytest.raises(ValueError):
        check_no_double_counting(V, m)  # V has drivetrain_eff 0.95 but the map includes drivetrain


# ---------------------------------------------------------------- optimisation
@pytest.fixture(scope="module")
def short_track():
    t = synthetic_track()
    return dataclasses.replace(t, laps=1)


@pytest.fixture(scope="module")
def pmap():
    return SyntheticPhysicsMap(V)


def test_dp_meets_time_from_standing_start(short_track, pmap):
    cfg = dp.DPConfig(ds_m=20.0, dv_mps=0.4, n_torque=6, t_max_s=270.0, reserve_s=10.0)
    r = dp.solve(short_track, V, pmap, cfg)
    assert r.feasible and r.time_s <= 260.0 + 1e-6
    assert r.v[0] == 0.0 and r.v[1] > 0.0
    assert np.all(r.v <= np.array([short_track.v_limit(x) for x in r.s]) + 1e-6)


def test_dp_energy_decreases_with_more_time(short_track, pmap):
    e = []
    for tmax in (260.0, 300.0, 360.0):
        r = dp.solve(short_track, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, n_torque=6, t_max_s=tmax, reserve_s=0))
        assert r.feasible
        e.append(r.energy_J)
    assert e[0] > e[1] > e[2]


def test_dp_mandatory_stop(pmap):
    trk = Track(lap_length_m=600.0, laps=1, grade_segments=[], curvature_segments=[], stop_positions_m=[300.0])
    r = dp.solve(trk, V, pmap, dp.DPConfig(ds_m=10.0, dv_mps=0.2, n_torque=6, t_max_s=200.0, reserve_s=0))
    assert r.feasible
    k = int(round(300.0 / 10.0))
    assert r.v[k] == 0.0 and r.v[k + 1] > 0.0


def test_infeasible_time_is_reported(short_track, pmap):
    r = dp.solve(short_track, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, n_torque=6, t_max_s=60.0, reserve_s=0))
    assert not r.feasible


def test_schedule_export_is_bounded(tmp_path, short_track, pmap):
    r = dp.solve(short_track, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, n_torque=6, t_max_s=270.0, reserve_s=10))
    out = tmp_path / "s.csv"
    dp.export_schedule(r, out, torque_bound_Nm=1.0, model_label="test")
    lines = out.read_text().splitlines()
    assert lines[0].startswith("# SYNTHETIC")
    hdr = lines[1].split(",")
    rows = [dict(zip(hdr, x.split(","))) for x in lines[2:]]
    torques = [float(x["controller_torque_Nm"]) for x in rows]
    assert max(torques) <= 1.0 and min(torques) >= 0.0


def _follow(r, pace=None, lead=1.0):
    return schedule_follower(r.s, r.u_torque, r.kind, r.t, 2.0, pace, r.u_brake_N, cue_lead_s=lead,
                             release_lead_s=0.7 * lead, v_nodes=r.v, m_brake_kg=V.m_eff(coupled=not V.freewheel))


# ------------------------------------------------- v0.2 actuator model regressions
@pytest.fixture(scope="module")
def plan_a(pmap):
    trk = dataclasses.replace(synthetic_track(), laps=1)
    return trk, dp.solve(trk, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, t_max_s=260.0, reserve_s=10.0,
                                                    v_margin_mps=0.3))


def test_dp_braking_is_exported_as_driver_brake_never_coast(tmp_path, plan_a):
    trk, r = plan_a
    assert r.feasible
    brake = r.kind == dp.BRAKE
    assert brake.any(), "descent into the R=20 m corner needs braking on this track"
    assert np.all(r.u_brake_N[brake] > 0) and np.all(r.u_torque[brake] == 0)
    assert not np.any(r.u_coast & brake)                       # braking is never reported as coast
    assert np.all(r.u_brake_N[~brake] == 0)                    # and never hidden in coast/propel rows
    out = tmp_path / "s.csv"
    dp.export_schedule(r, out, 2.0, "t")
    lines = out.read_text().splitlines()
    hdr = lines[1].split(",")
    rows = [dict(zip(hdr, x.split(","))) for x in lines[2:]]
    for row in rows:
        if row["action"] == "coast":
            assert float(row["driver_brake_force_N"]) == 0.0
        if row["action"] == "driver_brake":
            assert float(row["controller_torque_Nm"]) == 0.0 and float(row["brake_energy_J"]) > 0
    g = dp.export_guidance(r, tmp_path / "g.csv", dp.GuidanceAssumptions())
    assert g and abs(sum(b["energy_J"] for b in g) - r.brake_energy_J) < 1e-6
    assert "reaction" in (tmp_path / "g.csv").read_text().splitlines()[0]


def test_dp_brake_energy_is_force_times_distance(plan_a):
    trk, r = plan_a
    k = np.where(r.kind == dp.BRAKE)[0]
    dist = r.s[k + 1] - r.s[k]
    assert np.allclose(r.e_brake_J[k], r.u_brake_N[k] * dist)
    # segment energy balance (energy form of the dynamics), braking segments
    m = V.m_eff(coupled=not V.freewheel)
    for j in k:
        vm = 0.5 * (r.v[j] + r.v[j + 1])
        f_res = resistive_force(V, vm, trk.grade(r.s[j]), 0.0, trk.curvature(r.s[j]))
        lhs = 0.5 * m * (r.v[j + 1] ** 2 - r.v[j] ** 2)
        rhs = -(f_res + r.u_brake_N[j]) * (r.s[j + 1] - r.s[j])
        assert lhs == pytest.approx(rhs, rel=0.05, abs=5.0)


def test_torque_only_is_reported_infeasible_on_descent_into_corner(pmap):
    trk = dataclasses.replace(synthetic_track(), laps=1)
    r = dp.solve(trk, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, policy="propulsion_coast", t_max_s=260.0,
                                           reserve_s=10.0))
    assert not r.feasible
    assert "coasting alone" in r.infeasible_reason
    _, env, bad = dp.coast_envelope(trk, V)
    assert bad is not None and 600.0 <= bad <= 1000.0


def test_torque_only_feasible_on_flat_track_without_any_braking(pmap):
    trk = dataclasses.replace(synthetic_track_flat(), laps=1)
    r = dp.solve(trk, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, policy="propulsion_coast", t_max_s=260.0,
                                           reserve_s=10.0))
    assert r.feasible and not np.any(r.kind == dp.BRAKE) and r.brake_energy_J == 0.0
    x = simulate(trk, V, pmap, _follow(r), SimConfig())
    assert x.valid and x.brake_energy_J == 0.0 and x.brake_applications == 0


def test_simulator_has_no_hidden_braking(pmap):
    trk = dataclasses.replace(synthetic_track(), laps=1)
    x = simulate(trk, V, pmap, constant_speed(7.5, V), SimConfig())   # no brake cue at all
    assert x.brake_energy_J == 0.0 and x.brake_applications == 0
    assert x.overspeed_events > 0 and not x.valid                    # violations recorded, not corrected


def test_braking_plan_executes_with_driver_model_and_brake_override(pmap, plan_a):
    trk, r = plan_a
    x = simulate(trk, V, pmap, _follow(r), SimConfig(driver=DriverModel(1.0, 0.7, 1.0)), record=True)
    assert x.finished and x.overspeed_events == 0 and x.brake_applications > 0 and x.brake_energy_J > 0
    braking = x.trace["brake_N"] > 0
    assert braking.any() and np.all(x.trace["torque"][braking] == 0.0)   # brake override (L1)
    assert abs(x.reconciliation["residual_J"]) < 1e-6 * max(1.0, x.reconciliation["tractive_work_J"]) + 1e-3


def test_late_driver_is_detected_as_overspeed_not_hidden(pmap, plan_a):
    trk, r = plan_a
    late = simulate(trk, V, pmap, _follow(r), SimConfig(driver=DriverModel(2.5, 0.7, 0.6)))
    assert late.overspeed_events > 0 and late.max_overspeed_mps > 0.0


def test_acceleration_limit_reduces_torque_and_keeps_energy_consistent(pmap):
    trk = dataclasses.replace(synthetic_track_flat(), laps=1)
    tight = SimConfig(a_max=0.3)
    x = simulate(trk, V, pmap, constant_speed(6.0, V, brake=EnvelopeBrakeCue(trk, V)), tight)
    assert x.accel_limited_steps > 0
    rec = x.reconciliation
    assert abs(rec["residual_J"]) < 1e-3
    assert rec["battery_minus_tractive_J"] > 0                         # losses + aux are positive


def test_power_map_charges_motor_friction_power(pmap):
    b = pmap.breakdown(6.0, 1.0, 46.0)
    w = 6.0 * V.gear_ratio / V.wheel_radius_m
    assert b["motor_friction_W"] == pytest.approx(pmap.motor.friction_Nm * w)
    parts = b["shaft_W"] + b["motor_friction_W"] + b["motor_cu_fe_W"] + b["inverter_W"] + b["aux_W"]
    assert parts == pytest.approx(b["total_W"])
    assert b["inverter_W"] > 0


def test_pace_correction_bounded_and_effective(short_track, pmap):
    r = dp.solve(short_track, V, pmap, dp.DPConfig(ds_m=20.0, dv_mps=0.4, n_torque=6, t_max_s=270.0, reserve_s=10))
    pc = PaceCorrector(k_Nm_per_s=0.05, bound_Nm=0.3)
    assert pc.delta(1000.0, 0.0) == 0.3 and pc.delta(0.0, 1000.0) == -0.3
    heavy = dataclasses.replace(V, crr=V.crr * 1.3)
    sim = SimConfig()
    ctrl = _follow(r)
    no = simulate(short_track, heavy, SyntheticPhysicsMap(heavy), ctrl, sim)
    ctrl_p = _follow(r, pc)
    yes = simulate(short_track, heavy, SyntheticPhysicsMap(heavy), ctrl_p, sim)
    assert yes.time_s < no.time_s
    assert yes.time_s <= 270.0
