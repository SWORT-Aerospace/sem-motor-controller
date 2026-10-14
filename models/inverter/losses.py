"""Parameterized power-stage calculations for a two-level three-phase MOSFET inverter.

Every input is explicit; nothing here selects a part. Formulas are standard
first-order engineering approximations (stated per function) and must be
checked against measurements and the chosen parts' datasheets. Currents are
kept separate:
    I_ph_pk   phase peak current [A]
    I_ph_rms  phase RMS current  [A] = I_ph_pk / sqrt(2) for sinusoidal current
    I_batt    battery (DC) average current [A] = P_dc / V_bus
Modulation index M is the phase-voltage peak divided by V_bus/2 (SPWM-normalised;
linear SVPWM reaches M = 2/sqrt(3) ~ 1.155).
"""
from __future__ import annotations

import dataclasses
import math


@dataclasses.dataclass(frozen=True)
class MosfetParams:
    rds_on_25_ohm: float          # max at 25 degC, VGS = gate drive voltage
    rds_tc_per_K: float           # normalised RDS(on) temperature coefficient (e.g. 0.005-0.008/K)
    qg_C: float                   # total gate charge at V_gs
    qgd_C: float                  # Miller charge
    qgs2_C: float                 # gate charge from Vth to Miller plateau (≈ Qgs/2 if unknown)
    qoss_C: float                 # output charge at the operating V_ds
    qrr_C: float                  # body-diode reverse recovery charge (at di/dt of use)
    vf_body_V: float              # body-diode forward voltage at the relevant current
    v_plateau_V: float            # Miller plateau voltage
    rg_internal_ohm: float = 1.0
    rth_jc_K_W: float = 0.5
    label: str = "UNSELECTED"

    def rds_hot(self, tj_C: float) -> float:
        return self.rds_on_25_ohm * (1.0 + self.rds_tc_per_K * (tj_C - 25.0))


@dataclasses.dataclass(frozen=True)
class GateDriveParams:
    v_drive_V: float              # gate drive amplitude
    i_source_A: float             # configured peak source current
    i_sink_A: float               # configured peak sink current
    rg_external_ohm: float = 0.0


@dataclasses.dataclass(frozen=True)
class InverterOperatingPoint:
    v_bus_V: float
    i_ph_pk_A: float
    m_index: float                # SPWM-normalised modulation index
    cos_phi: float                # displacement power factor (current vs voltage)
    f_sw_Hz: float
    deadtime_s: float
    tj_C: float = 100.0
    n_parallel: int = 1           # devices per switch position


def switching_times(m: MosfetParams, g: GateDriveParams) -> tuple[float, float]:
    """Voltage/current transition times from gate charge and driver current limits.
    t_on ≈ (Qgs2 + Qgd) / I_on, t_off ≈ (Qgs2 + Qgd) / I_off, where the driver
    current is the lesser of its setting and (V_drive - V_plateau)/R_g on, V_plateau/R_g off."""
    rg = m.rg_internal_ohm + g.rg_external_ohm
    i_on = min(g.i_source_A, (g.v_drive_V - m.v_plateau_V) / rg) if rg > 0 else g.i_source_A
    i_off = min(g.i_sink_A, m.v_plateau_V / rg) if rg > 0 else g.i_sink_A
    q = m.qgs2_C + m.qgd_C
    return q / i_on, q / i_off


def inverter_losses(m: MosfetParams, g: GateDriveParams, op: InverterOperatingPoint) -> dict:
    """Losses for the whole three-phase bridge [W], split by mechanism.

    conduction (per device, synchronous MOSFET bridge):
        the channel conducts in BOTH directions while gated on, so with duty
        d = (1 + M sin(theta))/2 the average of d * i^2 over a period is
        R * I_pk^2 / 4 for each device, independent of M and cos(phi); a leg
        dissipates R * I_rms^2. (The textbook (1/8 +- M cos(phi)/(3 pi)) split
        applies to unidirectional switch + diode pairs such as IGBTs.)
        Dead-time intervals move this current to the body diode (below).
    switching (hard-switched, linear transitions, averaged over a sine period):
        P = (1/pi) * V * I_pk * (t_on + t_off)/2 * f_sw     per phase leg
    output capacitance:  P = Q_oss * V * f_sw / 2 ... per switching device turn-on (approx.)
    gate drive:          P = Q_g * V_drive * f_sw  per device (dissipated mostly in driver/Rg)
    dead time:           P = 2 * Vf * (I_pk / pi) * t_dead * f_sw  per phase leg
    reverse recovery:    P = Q_rr * V * f_sw * (1/pi) per phase leg (crude; often small for these FETs)
    """
    n = max(op.n_parallel, 1)
    r = m.rds_hot(op.tj_C) / n
    p_cond_hi = r * op.i_ph_pk_A ** 2 / 4.0
    p_cond_lo = p_cond_hi
    t_on, t_off = switching_times(m, g)
    # Paralleled devices share current but the driver must charge n gates:
    t_on *= n
    t_off *= n
    p_sw_leg = (1.0 / math.pi) * op.v_bus_V * op.i_ph_pk_A * 0.5 * (t_on + t_off) * op.f_sw_Hz
    p_oss_leg = m.qoss_C * n * op.v_bus_V * op.f_sw_Hz * 0.5
    p_gate_total = 6 * n * m.qg_C * g.v_drive_V * op.f_sw_Hz
    p_dead_leg = 2.0 * m.vf_body_V * (op.i_ph_pk_A / math.pi) * op.deadtime_s * op.f_sw_Hz
    p_rr_leg = m.qrr_C * n * op.v_bus_V * op.f_sw_Hz / math.pi
    parts = {
        "conduction_W": 3 * (p_cond_hi + p_cond_lo),
        "switching_W": 3 * p_sw_leg,
        "coss_W": 3 * p_oss_leg,
        "gate_drive_W": p_gate_total,
        "deadtime_diode_W": 3 * p_dead_leg,
        "reverse_recovery_W": 3 * p_rr_leg,
    }
    parts["total_W"] = sum(parts.values())
    parts["per_device_hottest_W"] = (p_cond_hi + 0.5 * (p_sw_leg + p_oss_leg + p_rr_leg) + 0.5 * p_dead_leg) / n
    parts["t_on_s"], parts["t_off_s"] = t_on, t_off
    return parts


def phase_currents(p_mech_W: float, omega_mech: float, kt_Nm_per_A_pk: float) -> dict:
    """Separate phase quantities from a torque demand (non-salient PMSM, id = 0)."""
    torque = p_mech_W / omega_mech if omega_mech > 0 else 0.0
    i_pk = abs(torque) / kt_Nm_per_A_pk
    return {"torque_Nm": torque, "i_ph_pk_A": i_pk, "i_ph_rms_A": i_pk / math.sqrt(2)}


def battery_current(p_dc_W: float, v_bus_V: float) -> float:
    return p_dc_W / v_bus_V


def dc_link_ripple_rms(i_ph_rms_A: float, m_index: float, cos_phi: float) -> float:
    """DC-link capacitor RMS current for sinusoidal PWM (Kolar & Round form):
        I_C,rms = I_ph,rms * sqrt( 2M [ sqrt(3)/(4 pi) + cos^2(phi) (sqrt(3)/pi - 9M/16) ] )
    with M the SPWM-normalised modulation index. Maximum near M ~ 0.6 for cos(phi)=1."""
    term = 2.0 * m_index * (math.sqrt(3) / (4 * math.pi) + cos_phi ** 2 * (math.sqrt(3) / math.pi - 9.0 * m_index / 16.0))
    return i_ph_rms_A * math.sqrt(max(term, 0.0))


def capacitor_check(i_rms_A: float, esr_ohm: float, n_caps: int, rated_ripple_A_each: float,
                    rated_voltage_V: float, v_max_bus_V: float, derating: float = 0.8) -> dict:
    i_each = i_rms_A / n_caps
    return {"i_rms_each_A": i_each, "p_esr_total_W": i_rms_A ** 2 * esr_ohm / n_caps,
            "ripple_ok": i_each <= rated_ripple_A_each,
            "voltage_ok": v_max_bus_V <= derating * rated_voltage_V}


def bus_voltage_ripple_pp(i_ph_pk_A: float, f_sw_Hz: float, c_F: float) -> float:
    """Upper-bound estimate of switching-frequency DC-link voltage ripple:
    dV ≈ I_ph_pk / (4 * f_sw * C) (worst case, source impedance neglected)."""
    return i_ph_pk_A / (4.0 * f_sw_Hz * c_F)


def max_bus_voltage(v_max_charged_V: float, transient_margin_fraction: float, ringing_V: float = 0.0) -> float:
    """Design bus voltage = max charged battery voltage x (1 + margin) + measured ringing.
    The margin must be justified by measured switching overshoot and any
    back-EMF/regen pumping; it is NOT a substitute for measurement."""
    return v_max_charged_V * (1.0 + transient_margin_fraction) + ringing_V


def precharge(c_F: float, v_V: float, r_ohm: float, final_fraction: float = 0.95) -> dict:
    """RC precharge: time to final_fraction of V, resistor energy (= capacitor
    energy for a full charge), and initial peak power (for pulse rating)."""
    tau = r_ohm * c_F
    return {"tau_s": tau, "t_to_fraction_s": -tau * math.log(1.0 - final_fraction),
            "resistor_energy_J": 0.5 * c_F * v_V ** 2, "peak_power_W": v_V ** 2 / r_ohm,
            "inrush_without_precharge_A_per_mohm": v_V / 1e-3}


def junction_temperature(p_device_W: float, t_amb_C: float, rth_jc: float, rth_cs: float, rth_sa: float) -> float:
    return t_amb_C + p_device_W * (rth_jc + rth_cs + rth_sa)


def solve_tj(m: MosfetParams, g: GateDriveParams, op: InverterOperatingPoint, t_amb_C: float, rth_cs: float,
             rth_sa: float, iters: int = 30) -> tuple[float, dict]:
    """Fixed-point iteration: RDS(on) depends on Tj which depends on losses."""
    tj = t_amb_C + 20.0
    res = {}
    for _ in range(iters):
        res = inverter_losses(m, g, dataclasses.replace(op, tj_C=tj))
        tj_new = junction_temperature(res["per_device_hottest_W"], t_amb_C, m.rth_jc_K_W, rth_cs, rth_sa)
        if abs(tj_new - tj) < 0.01:
            tj = tj_new
            break
        tj = tj_new
    return tj, res


def shunt(r_ohm: float, i_ph_pk_A: float, m_index: float, cos_phi: float, amp_gain: float, adc_vref: float,
          adc_bits: int, amp_offset_input_V: float) -> dict:
    """Low-side shunt in series with the lower switch of one phase leg.

    Dissipation: the shunt carries the phase current (either direction)
    whenever the lower switch or its body diode conducts: P = R * I_pk^2 / 4
    = R * I_rms^2 / 2 per shunt for sinusoidal current (same averaging as the
    synchronous-MOSFET conduction above); R * I_rms^2 bounds it.
    Range/resolution for a mid-biased bidirectional amplifier into an ADC:
        I_fs = (Vref/2) / (G * R),   LSB = 2 * I_fs / 2^bits
    Offset: an input-referred amplifier offset V_os appears as V_os / R amps,
    so a smaller shunt (less loss) makes the same V_os a larger current error.
    """
    del m_index, cos_phi  # no effect on the time-averaged shunt dissipation (see above)
    i_fs = 0.5 * adc_vref / (amp_gain * r_ohm)
    return {"p_each_W": r_ohm * i_ph_pk_A ** 2 / 4.0,
            "p_each_upper_bound_W": r_ohm * (i_ph_pk_A / math.sqrt(2)) ** 2,
            "i_full_scale_A": i_fs,
            "lsb_A": 2.0 * i_fs / (2 ** adc_bits),
            "offset_A": amp_offset_input_V / r_ohm}


def amplifier_settling_ok(settling_s: float, adc_sample_s: float, min_lowside_on_s: float, deadtime_s: float) -> bool:
    """Low-side sampling window must contain dead time + amplifier settling + ADC sampling."""
    return deadtime_s + settling_s + adc_sample_s <= min_lowside_on_s


def conductor_loss(i_rms_A: float, length_m: float, area_mm2: float, rho_ohm_m: float = 1.72e-8,
                   n_conductors: int = 2) -> float:
    return i_rms_A ** 2 * rho_ohm_m * length_m * n_conductors / (area_mm2 * 1e-6)


def fuse_coordination(i_continuous_A: float, i_peak_A: float, peak_s: float, fuse_rating_A: float,
                      wire_ampacity_A: float, battery_short_circuit_A: float, fuse_breaking_A: float) -> dict:
    """First-order coordination checks; the fuse time-current curve must be
    checked against the actual peak profile before selection."""
    return {
        "carries_continuous": fuse_rating_A >= 1.25 * i_continuous_A,
        "protects_wire": fuse_rating_A <= wire_ampacity_A,
        "breaking_capacity_ok": fuse_breaking_A >= battery_short_circuit_A,
        "peak_note": f"peak {i_peak_A:.1f} A for {peak_s:.1f} s must lie below the fuse curve (not checked)",
    }


def aux_energy_per_run(loads_W: dict[str, float], run_time_s: float) -> dict:
    e = {k: v * run_time_s for k, v in loads_W.items()}
    e["total_J"] = sum(e.values())
    return e
