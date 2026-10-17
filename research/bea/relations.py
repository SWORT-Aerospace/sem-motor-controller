"""Relationships, hypotheses and the bounded fit, shared by the identifiability study and the diagnosis.

One implementation of the mathematics serves two callers:

  * the identifiability study (research/bea/identifiability.py) builds Signals from a synthetic truth
    trajectory and uses the signature columns to compute separation distances;
  * the diagnosis (research/bea/diagnosis.py) builds Signals from received records and fits each
    hypothesis to the measured residuals.

Each relationship on a window yields a Block: the measured residual (measured quantity minus the
nominal model), one signature column per parameter, the exact timing term s(delta) and the noise
covariance. A hypothesis is a set of bounds on the parameters (HYPOTHESES); fit() returns the smallest
whitened squared residual the hypothesis allows.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable, Optional

import numpy as np

from models.vehicle.longitudinal import G, SYNTHETIC_VEHICLE, VehicleParams, tractive_force
from models.vehicle.powertrain import SYNTHETIC_MOTOR, MotorParams

INF = math.inf

# Linear parameters, in column order. Faults: bus-current bias b [A], extra opposing force dF [N]. The rest
# are nuisance: grade [rad], along-track headwind [m/s], loss-model errors (constant P0 [W], winding
# resistance [ohm], iron-loss coefficient (relative), switching loss per phase ampere [W/A], motor friction
# torque [N m]), bus-meter gain (relative), torque constant (relative), rolling resistance, drag area [m^2],
# effective mass (relative), bus-meter zero offset [A], IMU bias after mounting calibration [m/s^2]. Motor
# friction and the torque constant appear in both the power balance and the force balance: one parameter,
# two relationships.
PARAMS = ("b_A", "dF_N", "grade_rad", "wind_mps", "P0_W", "dRs_ohm", "dFe_rel", "dSw_W_per_A", "dTf_Nm", "dGm_rel",
          "dKt_rel", "dCrr", "dCdA_m2", "dmeff_rel", "Ioff_A", "imu_bias_mps2")
FAULTS = ("b_A", "dF_N")


@dataclasses.dataclass(frozen=True)
class Study:
    """Synthetic plant and sensor assumptions (all [A] unless noted)."""
    vehicle: VehicleParams = SYNTHETIC_VEHICLE
    motor: MotorParams = SYNTHETIC_MOTOR
    v_oc_V: float = 48.0              # team-reported nominal pack voltage, used only as an operating point
    r_src_ohm: float = 0.10           # pack and wiring resistance
    torque_slew_Nm_s: float = 20.0    # torque rise rate at a pulse edge
    sigma_ibatt_A: float = 0.02       # bus-meter current noise per 10 ms sample
    sigma_vbus_V: float = 0.01
    sigma_iq_A: float = 0.01          # reported (filtered) iq; small enough that its sharing between blocks is neglected
    sigma_v_rotor_mps: float = 0.002  # rotor-speed noise as vehicle speed
    wheel_circ_m: float = 1.50        # provisional, as host/telematics/sensors.py
    wheel_ppr: int = 32               # provisional, as host/telematics/sensors.py
    wheel_window_s: float = 0.1       # [F] wheel counting window
    sigma_imu_mps2: float = 0.05      # per 100 Hz sample, as host/telematics/sensors.py
    imu_hz: float = 100.0
    guard_s: float = 0.02             # samples this close to a drive/coast change are not used

    @property
    def sigma_x_wheel_m(self) -> float:
        """Distance quantisation of the wheel counts: one count, uniform."""
        return self.wheel_circ_m / self.wheel_ppr / math.sqrt(12.0)


# Nuisance half-widths. "known": after a calibration run; "uncertain": nominal values only.
NUISANCE = {
    "known":     {"grade_rad": 0.001, "wind_mps": 1.0, "P0_W": 2.0, "dRs_ohm": 0.01, "dFe_rel": 0.10,
                  "dSw_W_per_A": 0.05, "dTf_Nm": 0.002, "dGm_rel": 0.005, "dKt_rel": 0.02,
                  "dCrr": 0.0003, "dCdA_m2": 0.003, "dmeff_rel": 0.01, "Ioff_A": 0.005, "imu_bias_mps2": 0.005},
    "uncertain": {"grade_rad": 0.005, "wind_mps": 3.0, "P0_W": 6.0, "dRs_ohm": 0.03, "dFe_rel": 0.30,
                  "dSw_W_per_A": 0.15, "dTf_Nm": 0.005, "dGm_rel": 0.02, "dKt_rel": 0.05,
                  "dCrr": 0.001, "dCdA_m2": 0.010, "dmeff_rel": 0.03, "Ioff_A": 0.03, "imu_bias_mps2": 0.05},
}
TIMING = {"known": 0.005, "uncertain": 0.10}   # |delta| allowed under H0 [s]
DELTA_RANGE_S = 0.5                           # search range for delta under HT

# Hypotheses as bound changes relative to H0. HL is one class; HL_grade (grade beyond its H0 bound) and
# HL_wind are its sub-causes, separated only where the evidence supports it.
HYPOTHESES = {
    "H0": {},
    "HB": {"b_A": (-INF, INF)},
    "HT": {"delta": (-DELTA_RANGE_S, DELTA_RANGE_S)},
    "HL": {"dF_N": (0.0, INF)},
    "HL_grade": {"grade_rad": (0.0, INF)},          # uphill: a downhill slope lowers the opposing force
    "HL_wind": {"wind_mps": (-INF, INF)},
}


# ----------------------------------------------------------------------------- signals on a window
@dataclasses.dataclass
class Signals:
    """Signals on a uniform grid: the synthetic truth (study) or values rebuilt from records (diagnosis).

    v is the speed used by the drive force balance and the resistance model (rotor speed while driving);
    the coast balance uses the wheel windows. P is the bus meter's power as measured, P_model the
    nominal loss model's prediction of it from iq, rotor speed and voltage."""
    t: np.ndarray
    hz: float
    v: np.ndarray
    drive: np.ndarray
    iq: np.ndarray
    w: np.ndarray
    P: np.ndarray
    V: np.ndarray
    I: np.ndarray
    P_model: np.ndarray
    F_trac: np.ndarray
    F_res: np.ndarray
    m_eff: np.ndarray
    f_imu: Optional[np.ndarray] = None       # IMU specific force a + g sin(grade)
    wheel_t: Optional[np.ndarray] = None     # wheel window centres
    wheel_v: Optional[np.ndarray] = None     # wheel window speeds
    kind: str = ""
    valid: Optional[np.ndarray] = None       # False where a sample must not be used (for example a summary
                                             # mean that straddles a drive/coast change)
    predicted: bool = False                  # a proxy rebuilt to predict a window: no interpolation-error term

    def at(self, x: np.ndarray, times: np.ndarray) -> np.ndarray:
        return np.interp(times, self.t, x)

    def grid(self, fs: float) -> np.ndarray:
        return self.t[::max(1, int(round(self.hz / fs)))]


@dataclasses.dataclass
class Block:
    """One relationship on one window."""
    name: str
    cols: dict[str, np.ndarray]
    shift: Optional[Callable[[float], np.ndarray]]
    cov: np.ndarray            # full covariance (diagonal, or banded from differencing)
    times: np.ndarray
    resid: np.ndarray          # measured residual (zero for a nominal truth)
    cols_at: Optional[Callable[[float], dict]] = None   # columns when the measured side is offset by delta

    @property
    def n(self) -> int:
        return len(self.times)


def _steady_mask(sig: Signals, times: np.ndarray, mode_drive: bool, guard: float, span: float = 0.0) -> np.ndarray:
    """True where [t - guard, t + span + guard] lies inside one mode and a sample exists at t + span (an
    interval must not bridge a gap in the records, such as summary messages replaced by fetched frames)."""
    ok = np.ones(len(times), bool)
    lo = np.searchsorted(sig.t, times - guard)
    hi = np.searchsorted(sig.t, times + span + guard, side="right")
    end = np.searchsorted(sig.t, times + span - guard)
    tol = max(guard, 0.25 / sig.hz)
    for i, (a, b, e) in enumerate(zip(lo, hi, end)):
        if e >= len(sig.t) or sig.t[e] > times[i] + span + tol:
            ok[i] = False
            continue
        sl = slice(max(a, 0), min(max(b, e + 1), len(sig.t)))
        seg = sig.drive[sl]
        ok[i] = len(seg) > 0 and bool(np.all(seg == mode_drive)) and (sig.valid is None or bool(np.all(sig.valid[sl])))
    return ok


def _interval_mean(sig: Signals, x: np.ndarray, t0: np.ndarray, t1: np.ndarray) -> np.ndarray:
    c = np.concatenate([[0.0], np.cumsum(0.5 * (x[1:] + x[:-1]) / sig.hz)])
    return (np.interp(t1, sig.t, c) - np.interp(t0, sig.t, c)) / (t1 - t0)


def _timed_grid(sig: Signals, fs: float) -> np.ndarray:
    """Sample times of a relationship with a timing term: the window less DELTA_RANGE_S at each end, so
    that the value at t - delta is inside the window for every delta tested."""
    t = sig.grid(fs)
    return t[(t >= sig.t[0] + DELTA_RANGE_S) & (t <= sig.t[-1] - DELTA_RANGE_S)]


def _alignment_var(x: np.ndarray, sigma: np.ndarray, c: float = 0.25) -> np.ndarray:
    """Variance of the error made by interpolating the model between samples near a corner.

    A slope change of the signal inside a sample interval cannot be placed by linear interpolation;
    the error is at most about a quarter of the second difference at the nearest sample. It is taken
    from the measured samples, so it marks the samples where the measured signal has its edges and is
    the same under every hypothesis. Second differences within three noise levels are treated as noise."""
    d2 = np.zeros(len(x))
    if len(x) >= 3:
        d2[1:-1] = np.abs(x[2:] - 2.0 * x[1:-1] + x[:-2])
    excess = np.maximum(d2 - 3.0 * math.sqrt(6.0) * sigma, 0.0)
    return (c * excess) ** 2


def _blockwise_diff_cov(t0: np.ndarray, dt: float, order: int, scale, white_var) -> np.ndarray:
    """Covariance of scale_k * (difference of order `order` of iid unit noise) plus white noise.

    Differences share samples with their neighbours inside a run of contiguous
    intervals; a gap in t0 starts a new, independent run."""
    n = len(t0)
    cov = np.diag(np.broadcast_to(np.asarray(white_var, float), (n,))).copy()
    scale = np.broadcast_to(np.asarray(scale, float), (n,))
    breaks = np.flatnonzero(np.diff(t0) > dt * 1.5) + 1
    for idx in np.split(np.arange(n), breaks):
        D = np.eye(len(idx) + order)
        for _ in range(order):
            D = D[1:] - D[:-1]
        S = np.diag(scale[idx])
        cov[np.ix_(idx, idx)] += S @ (D @ D.T) @ S
    return cov


# ----------------------------------------------------------------------------- relationships
def r1_power(sig: Signals, st: Study, fs: float, steady_only: bool = False) -> Optional[Block]:
    """R1: bus-meter power against the loss model driven by iq and rotor speed (drive samples)."""
    times = _timed_grid(sig, fs)
    keep = _steady_mask(sig, times, True, st.guard_s)
    if steady_only:
        dP = np.gradient(sig.P_model, 1.0 / sig.hz)
        keep &= np.abs(sig.at(dP, times)) < 5.0
    times = times[keep]
    if len(times) < 3:
        return None
    V, I, iq, w, P = (sig.at(x, times) for x in (sig.V, sig.I, sig.iq, sig.w, sig.P))
    kt = st.motor.kt
    Pm = sig.at(sig.P_model, times)
    var = (V * st.sigma_ibatt_A) ** 2 + (I * st.sigma_vbus_V) ** 2 + (kt * w * st.sigma_iq_A) ** 2
    if not sig.predicted:
        var = var + _alignment_var(P, np.sqrt(var))

    def cols_at(d: float) -> dict:
        """Under a timing offset the bus meter reports its whole quantity late, the loss terms included,
        so every column is the term evaluated at t - delta."""
        Vd, iqd, wd, Pd = (sig.at(x, times - d) for x in (sig.V, sig.iq, sig.w, sig.P_model))
        # Signs matter for parameters shared with other relationships (Ioff with R3, dKt with R2 and R5):
        # each column is the change of this residual for a positive change of the parameter. Motor friction
        # does not enter: with iq measured, the electrical power does not depend on how the torque splits.
        return {"b_A": Vd, "Ioff_A": Vd, "P0_W": np.ones_like(Vd), "dRs_ohm": 1.5 * iqd ** 2,
                "dFe_rel": st.motor.k_iron_W_per_rad_s15 * np.maximum(wd, 0.0) ** 1.5, "dSw_W_per_A": np.abs(iqd),
                "dGm_rel": Pd, "dKt_rel": kt * iqd * wd}

    return Block("R1", cols_at(0.0), lambda d: sig.at(sig.P_model, times - d) - Pm, np.diag(var), times, P - Pm,
                 cols_at)


def r3_coast_current(sig: Signals, st: Study, fs: float) -> Optional[Block]:
    """R3: bus-meter current during coast with the gates off, where the true inverter input is 0."""
    times = _timed_grid(sig, fs)
    times = times[_steady_mask(sig, times, False, st.guard_s)]
    if len(times) < 3:
        return None
    one = np.ones(len(times))
    I_model = sig.P_model / sig.V
    I = sig.at(sig.I, times)
    var = st.sigma_ibatt_A ** 2 + (np.zeros(len(times)) if sig.predicted else _alignment_var(I, np.full(len(times), st.sigma_ibatt_A)))
    kt = st.motor.kt

    def cols_at(d: float) -> dict:
        """Offset by delta, a coast sample can carry current from the drive that preceded it; that
        current carries the loss-model terms of R1, divided by the voltage."""
        if d == 0.0:
            return {"b_A": one, "Ioff_A": one}
        td = times - d
        on = (sig.at(sig.drive.astype(float), td) > 0.5) / np.maximum(sig.at(sig.V, td), 1.0)
        iqd, wd, Pd = (sig.at(x, td) for x in (sig.iq, sig.w, sig.P_model))
        return {"b_A": one, "Ioff_A": one, "P0_W": on, "dRs_ohm": on * 1.5 * iqd ** 2,
                "dFe_rel": on * st.motor.k_iron_W_per_rad_s15 * np.maximum(wd, 0.0) ** 1.5,
                "dSw_W_per_A": on * np.abs(iqd), "dGm_rel": on * Pd, "dKt_rel": on * kt * iqd * wd}

    return Block("R3", cols_at(0.0), lambda d: sig.at(I_model, times - d), np.diag(var), times, I, cols_at)


def _force_cols(sig: Signals, st: Study, t0, t1, accel, m_eff, grade_coef) -> dict[str, np.ndarray]:
    veh = st.vehicle
    v_air = _interval_mean(sig, sig.v, t0, t1)
    v2 = _interval_mean(sig, sig.v ** 2, t0, t1)
    one = np.ones(len(t0))
    return {"dF_N": one, "grade_rad": grade_coef * one, "wind_mps": veh.rho_air * veh.cda_m2 * v_air,
            "dCrr": veh.mass_kg * G * one, "dCdA_m2": 0.5 * veh.rho_air * v2, "dmeff_rel": m_eff * accel}


def r2_torque_motion(sig: Signals, st: Study, fs: float, torque_source: str = "iq",
                     steady_only: bool = False) -> Optional[Block]:
    """R2: tractive force from iq against resistance plus inertia from rotor speed (drive intervals).

    torque_source="ibatt" is the dependency case: torque computed from the bus
    meter's power, so the bus-current bias enters this relationship too."""
    dt = 1.0 / fs
    t0 = sig.grid(fs)[:-1]
    keep = _steady_mask(sig, t0, True, st.guard_s, span=dt)
    if steady_only:     # 2 Hz snapshots give an interval's force only while the torque is steady
        dF = np.abs(np.gradient(sig.F_trac, 1.0 / sig.hz))
        c = np.concatenate([[0.0], np.cumsum(dF[1:] / sig.hz)])
        keep &= (np.interp(t0 + dt, sig.t, c) - np.interp(t0, sig.t, c)) < 0.5
    t0 = t0[keep]
    if len(t0) < 3:
        return None
    t1 = t0 + dt
    m = sig.at(sig.m_eff, t0)
    accel = (sig.at(sig.v, t1) - sig.at(sig.v, t0)) / dt
    cols = _force_cols(sig, st, t0, t1, accel, m, st.vehicle.mass_kg * G)
    f_trac = _interval_mean(sig, sig.F_trac, t0, t1)
    f_res = _interval_mean(sig, sig.F_res, t0, t1)
    # A larger torque constant than nominal: the model under-estimates the force (column -F_trac), while R1
    # sees more electrical power (+Kt iq w). More friction than nominal: the model over-estimates the
    # shaft torque, so the residual rises (+G eta / r per N m).
    cols["dKt_rel"] = -f_trac
    cols["dTf_Nm"] = np.full(len(t0), tractive_force(st.vehicle, 1.0))
    if torque_source == "ibatt":
        veh = st.vehicle
        cols["b_A"] = veh.drivetrain_eff * _interval_mean(sig, sig.V, t0, t1) / np.maximum(
            _interval_mean(sig, sig.v, t0, t1), 0.5)
    elif torque_source != "iq":
        raise ValueError(torque_source)
    # Speed differencing: every interval shares its end speeds with its neighbours (banded covariance).
    a_white = (tractive_force(st.vehicle, st.motor.kt * st.sigma_iq_A) / math.sqrt(max(1.0, 100.0 / fs))) ** 2
    cov = _blockwise_diff_cov(t0, dt, 1, m * st.sigma_v_rotor_mps / dt, a_white)
    return Block("R2", cols, None, cov, t0, f_trac - f_res - m * accel)


def r4_coast_decel(sig: Signals, st: Study, fs: float) -> Optional[Block]:
    """R4: coast deceleration from the wheel count windows against resistance (coast intervals).

    At 10 Hz consecutive windows are used, so their speeds share the quantised
    distance at each window boundary (second difference). At lower rates single
    windows are taken fs apart, as the live summary reports them (first difference
    of independent window speeds). The spacing of the windows comes from their
    times: the summary carries one 0.1 s window per message, 0.5 s apart."""
    if sig.wheel_t is None or len(sig.wheel_t) < 4 or fs > 1.0 / st.wheel_window_s + 1e-9:
        return None
    spacing = float(np.median(np.diff(sig.wheel_t)))
    k = max(1, int(round(1.0 / (fs * spacing))))
    dt = k * spacing
    adjacent = k == 1 and abs(spacing - st.wheel_window_s) < 0.25 * st.wheel_window_s
    idx = np.arange(0, len(sig.wheel_t) - k, k)
    t0, t1 = sig.wheel_t[idx], sig.wheel_t[idx + k]
    keep = _steady_mask(sig, t0, False, st.guard_s, span=dt) & (np.abs(t1 - t0 - dt) < 0.25 * spacing)
    idx, t0, t1 = idx[keep], t0[keep], t1[keep]
    if len(t0) < 3:
        return None
    m = sig.at(sig.m_eff, t0)
    accel = (sig.wheel_v[idx + k] - sig.wheel_v[idx]) / dt
    cols = _force_cols(sig, st, t0, t1, accel, m, st.vehicle.mass_kg * G)
    if adjacent:
        cov = _blockwise_diff_cov(t0, dt, 2, m * st.sigma_x_wheel_m / dt ** 2, np.zeros(len(t0)))
    else:
        sv = math.sqrt(2.0) * st.sigma_x_wheel_m / st.wheel_window_s
        cov = _blockwise_diff_cov(t0, dt, 1, m * sv / dt, np.zeros(len(t0)))
    return Block("R4", cols, None, cov, t0, -_interval_mean(sig, sig.F_res, t0, t1) - m * accel)


def r5_imu_force(sig: Signals, st: Study, fs: float) -> Optional[Block]:
    """R5: force balance with the IMU's specific force (a + g sin(grade)) in place of the wheel acceleration.

    Grade cancels except for the rotating-inertia share, so R5 sees the extra
    force but almost no grade. Needs the IMU records from the local log."""
    if sig.f_imu is None:
        return None
    dt = 1.0 / fs
    t0 = sig.grid(fs)[:-1]
    t0 = t0[_steady_mask(sig, t0, True, st.guard_s, span=dt) | _steady_mask(sig, t0, False, st.guard_s, span=dt)]
    if len(t0) < 3:
        return None
    t1 = t0 + dt
    m = sig.at(sig.m_eff, t0)
    f_mean = _interval_mean(sig, sig.f_imu, t0, t1)
    cols = _force_cols(sig, st, t0, t1, f_mean, m, (st.vehicle.mass_kg - m) * G)
    f_trac = _interval_mean(sig, sig.F_trac, t0, t1)
    cols["dKt_rel"] = -f_trac
    drive_frac = _interval_mean(sig, sig.drive.astype(float), t0, t1)
    cols["dTf_Nm"] = tractive_force(st.vehicle, 1.0) * drive_frac
    cols["imu_bias_mps2"] = m
    n_avg = max(1.0, st.imu_hz * dt)
    var = (m * st.sigma_imu_mps2) ** 2 / n_avg
    return Block("R5", cols, None, np.diag(var), t0, f_trac - _interval_mean(sig, sig.F_res, t0, t1) - m * f_mean)


BUILDERS = {
    "R1": lambda s, st, fs, ts: r1_power(s, st, fs) if ts == "iq" else None,   # circular with bus-current torque
    "R1s": lambda s, st, fs, ts: r1_power(s, st, fs, steady_only=True) if ts == "iq" else None,
    "R2": lambda s, st, fs, ts: r2_torque_motion(s, st, fs, ts),
    "R2s": lambda s, st, fs, ts: r2_torque_motion(s, st, fs, ts, steady_only=True),
    "R3": lambda s, st, fs, ts: r3_coast_current(s, st, fs),
    "R4": lambda s, st, fs, ts: r4_coast_decel(s, st, fs),
    "R5": lambda s, st, fs, ts: r5_imu_force(s, st, fs),
}


def build_window(sig: Signals, st: Study, rels: dict[str, float], torque_source: str = "iq") -> list[Block]:
    """The blocks of the named relationships at their rates; a relationship without usable samples is left out."""
    return [b for b in (BUILDERS[name](sig, st, fs, torque_source) for name, fs in rels.items()) if b is not None]


# ----------------------------------------------------------------------------- whitening and stacking
@dataclasses.dataclass
class Whitened:
    """Stacked, whitened problem: columns C (n x p), timing term, measured residual y, parameter names.
    C_at(delta) gives the columns when the measured side of the timed relationships is offset by delta."""
    C: np.ndarray
    names: list[str]
    shift: Callable[[float], np.ndarray]
    n: int
    blocks: list[str]
    y: np.ndarray
    C_at: Callable[[float], np.ndarray] = None


def _whitener(cov: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    if np.count_nonzero(cov - np.diag(np.diag(cov))) == 0:
        inv_sd = 1.0 / np.sqrt(np.diag(cov))
        return lambda x: x * inv_sd
    L = np.linalg.cholesky(cov)
    return lambda x: np.linalg.solve(L, x)


def whiten(blocks: list[Block], noise_scale: float = 1.0) -> Whitened:
    """Stack the blocks and whiten them; noise_scale multiplies every standard deviation (calibration)."""
    ws = [_whitener(b.cov * noise_scale ** 2) for b in blocks]
    C = np.column_stack([np.concatenate([w(b.cols.get(p, np.zeros(b.n))) for b, w in zip(blocks, ws)])
                         for p in PARAMS]) if blocks else np.zeros((0, len(PARAMS)))
    keep = [i for i in range(len(PARAMS)) if np.any(C[:, i] != 0)]
    pairs = list(zip(blocks, ws))
    timed = any(b.cols_at is not None for b in blocks)
    bounds = np.cumsum([0] + [b.n for b in blocks])
    Ck = C[:, keep]

    def C_at(d: float) -> np.ndarray:
        """Columns with the measured side of the timed blocks offset by d (the other blocks are unchanged)."""
        if d == 0.0 or not timed:
            return Ck
        out = Ck.copy()
        for j, (b, w) in enumerate(pairs):
            if b.cols_at is not None:
                cols = b.cols_at(d)
                out[bounds[j]:bounds[j + 1]] = np.column_stack([w(cols.get(PARAMS[i], np.zeros(b.n))) for i in keep])
        return out

    def shift(d: float) -> np.ndarray:
        return np.concatenate([w(b.shift(d)) if b.shift else np.zeros(b.n) for b, w in pairs]) if pairs else np.zeros(0)

    y = np.concatenate([w(b.resid) for b, w in pairs]) if pairs else np.zeros(0)
    return Whitened(C[:, keep], [PARAMS[i] for i in keep], shift, sum(b.n for b in blocks), [b.name for b in blocks], y,
                    C_at)


# ----------------------------------------------------------------------------- bounded least squares
def bvls(A: np.ndarray, y: np.ndarray, lo: np.ndarray, hi: np.ndarray, max_iter: Optional[int] = None,
         x0: Optional[np.ndarray] = None):
    """min ||A x - y||^2 subject to lo <= x <= hi (bounds may be infinite; lo == hi fixes a variable).

    Active-set method in the form of Stark and Parker's BVLS: solve on the free
    set, step back into the box when the solution leaves it, free the bound
    variable whose gradient points most into the box, stop at a KKT point. A
    freed variable whose solve does not lower the objective is blocked until
    the objective next decreases, which prevents cycling on collinear columns.
    Returns (x, ||A x - y||^2)."""
    n = A.shape[1]
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    if n == 0:
        return np.zeros(0), float(y @ y)
    # Unit-norm columns: the study's columns differ by five orders of magnitude.
    cn = np.linalg.norm(A, axis=0)
    cn[cn == 0] = 1.0
    xs, J = _bvls_scaled(A / cn, y, lo * cn, hi * cn, max_iter, None if x0 is None else np.asarray(x0) * cn)
    return xs / cn, J


def _bvls_scaled(A, y, lo, hi, max_iter, x0=None):
    n = A.shape[1]
    max_iter = max_iter or 20 * n + 20
    tol_g = 1e-10 * (1.0 + np.linalg.norm(A) * (1.0 + np.linalg.norm(y)))
    fixed = lo == hi
    obj = lambda z: float(np.sum((A @ z - y) ** 2))

    def settle(x, free):
        for _ in range(n + 1):
            if not free.any():
                break
            z = np.linalg.lstsq(A[:, free], y - A[:, ~free] @ x[~free], rcond=None)[0]
            xf, lf, hf = x[free], lo[free], hi[free]
            if np.all(z >= lf) and np.all(z <= hf):
                x[free] = z
                break
            step = z - xf
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(z < lf, (lf - xf) / step, np.where(z > hf, (hf - xf) / step, np.inf))
            alpha = float(np.clip(np.nanmin(r), 0.0, 1.0))
            x[free] = np.clip(xf + alpha * step, lf, hf)
            idx = np.flatnonzero(free)
            with np.errstate(invalid="ignore"):
                hit = (r <= alpha * (1 + 1e-9) + 1e-15) & np.isfinite(r)
            hit[int(np.nanargmin(r))] = True            # the variable that limited the step always stops at its bound
            k = idx[hit]
            x[k] = np.where(z[hit] < lf[hit], lo[k], hi[k])
            free[k] = False
        return x, free

    x = np.clip(np.zeros(n) if x0 is None else x0, lo, hi)      # a warm start only changes where the search begins
    x, free = settle(x, (x > lo) & (x < hi) & ~fixed)
    best = obj(x)
    blocked = np.zeros(n, bool)
    unblocked_once = False
    for _ in range(max_iter):
        g = A.T @ (y - A @ x)
        push = np.full(n, -np.inf)
        cand = ~free & ~blocked & ~fixed
        push[cand & (x <= lo)] = g[cand & (x <= lo)]
        push[cand & (x >= hi)] = -g[cand & (x >= hi)]
        j = int(np.argmax(push))
        if push[j] <= tol_g:
            if blocked.any():                        # a blocked variable may still violate KKT: retry it once more
                gb = np.where(~free & blocked & ~fixed & (x <= lo), g, np.where(~free & blocked & ~fixed & (x >= hi), -g, -np.inf))
                if np.max(gb) > tol_g and not unblocked_once:
                    blocked[:] = False
                    unblocked_once = True
                    continue
            return x, obj(x)
        f_try = free.copy()
        f_try[j] = True
        x_try, f_try = settle(x.copy(), f_try)
        cur = obj(x_try)
        if cur < best - 1e-13 * (1.0 + best):
            x, free, best = x_try, f_try, cur
            blocked[:] = False
            unblocked_once = False
        else:
            blocked[j] = True
    raise RuntimeError("bvls did not reach a KKT point")


# ----------------------------------------------------------------------------- hypothesis fits
def bounds_for(hyp: str, names: list[str], level: str, timing_s: Optional[float] = None
               ) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """Bounds of every parameter, and of delta, under hypothesis hyp. timing_s overrides the H0 timing
    bound (for example once clock metadata has shown the receipt path to be tight)."""
    nb = NUISANCE[level]
    lo = np.array([0.0 if p in FAULTS else -nb[p] for p in names])
    hi = np.array([0.0 if p in FAULTS else nb[p] for p in names])
    dt0 = TIMING[level] if timing_s is None else timing_s
    delta = (-dt0, dt0)
    for p, (a, b) in HYPOTHESES[hyp].items():
        if p == "delta":
            delta = (a, b)
        elif p in names:
            i = names.index(p)
            lo[i], hi[i] = a, b
    return lo, hi, delta


def fit(W: Whitened, y: np.ndarray, hyp: str, level: str, n_grid: int = 21,
        timing_s: Optional[float] = None) -> tuple[float, dict]:
    """Smallest whitened squared residual of y under hypothesis hyp; returns (J, estimate).

    The timing offset is searched on a grid and refined by golden section around the best grid point.
    When the timing term has no signature on this window (its whitened norm at the ends of the allowed
    range is below 0.05), the offset cannot matter and only delta = 0 is evaluated."""
    lo, hi, (d_lo, d_hi) = bounds_for(hyp, W.names, level, timing_s)
    warm = [None]

    def J(d):
        x, j = bvls(W.C_at(d), y - W.shift(d), lo, hi, x0=warm[0])
        warm[0] = x
        return j, x

    if d_hi <= d_lo or max(np.linalg.norm(W.shift(d_lo)), np.linalg.norm(W.shift(d_hi))) < 0.05:
        jx, x = J(0.0)
        return jx, {"delta_s": 0.0, **{n: float(v) for n, v in zip(W.names, x)}}
    grid = np.unique(np.concatenate([np.linspace(d_lo, d_hi, n_grid if d_hi - d_lo > 0.05 else 5), [0.0]]))
    grid = grid[(grid >= d_lo) & (grid <= d_hi)]
    vals = [J(d)[0] for d in grid]
    i = int(np.argmin(vals))
    a, b = grid[max(i - 1, 0)], grid[min(i + 1, len(grid) - 1)]
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    fc, fd = J(c)[0], J(d)[0]
    for _ in range(25):
        if b - a < 2e-5:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = J(c)[0]
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = J(d)[0]
    cands = [(vals[i], grid[i]), (fc, c), (fd, d)]
    jbest, dbest = min(cands)
    jx, x = J(dbest)
    return jx, {"delta_s": float(dbest), **{n: float(v) for n, v in zip(W.names, x)}}
