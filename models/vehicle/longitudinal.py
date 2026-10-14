"""Longitudinal vehicle model and coast-down identification.

    m_eff * dv/dt = F_drive - F_roll - F_aero - F_grade - F_cornering - F_drivetrain

Sign conventions (SI):
  v        > 0 forward ground speed [m/s]
  wind     component of wind velocity ALONG the direction of travel [m/s]
           (> 0 tailwind). Air-relative speed v_air = v - wind.
  grade    road angle theta [rad], > 0 uphill
  curvature kappa = 1/R [1/m] (0 on straights)
  F_drive  tractive force at the tyre contact patch [N] (after drivetrain)

All defaults in SYNTHETIC_VEHICLE are synthetic placeholders.
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

G = 9.80665


@dataclasses.dataclass(frozen=True)
class VehicleParams:
    mass_kg: float                  # vehicle + driver
    wheel_radius_m: float
    gear_ratio: float               # motor speed / wheel speed
    crr: float                      # rolling resistance coefficient
    cda_m2: float
    rho_air: float = 1.20
    j_wheels_kg_m2: float = 0.0     # all wheels, about their axles
    j_motor_kg_m2: float = 0.0
    drivetrain_eff: float = 1.0     # forward (motoring) efficiency of the reduction
    drivetrain_drag_N: float = 0.0  # constant bearing/chain drag at the wheel
    cornering_stiffness_N_rad: float = math.inf  # total; inf => no cornering resistance
    freewheel: bool = True          # motor decouples when not driving
    motor_drag_Nm: float = 0.0      # motor spin-down torque when coupled and unpowered
    motor_drag_Nm_per_rad_s: float = 0.0
    label: str = "SYNTHETIC"

    def m_eff(self, coupled: bool) -> float:
        """Effective translating mass incl. rotating inertia (motor only if coupled)."""
        r = self.wheel_radius_m
        m = self.mass_kg + self.j_wheels_kg_m2 / r**2
        if coupled:
            m += self.j_motor_kg_m2 * self.gear_ratio**2 / r**2
        return m

    def motor_speed(self, v: float) -> float:
        return v * self.gear_ratio / self.wheel_radius_m


SYNTHETIC_VEHICLE = VehicleParams(
    mass_kg=100.0, wheel_radius_m=1.50 / (2 * math.pi), gear_ratio=10.0, crr=0.0025, cda_m2=0.035,
    j_wheels_kg_m2=0.06, j_motor_kg_m2=2.0e-4, drivetrain_eff=0.95, drivetrain_drag_N=0.3,
    cornering_stiffness_N_rad=4000.0, freewheel=True, motor_drag_Nm=0.01, motor_drag_Nm_per_rad_s=2.0e-5)


def resistive_force(p: VehicleParams, v: float, grade: float = 0.0, wind: float = 0.0,
                    curvature: float = 0.0, motor_coupled_unpowered: bool = False) -> float:
    """Sum of resisting forces [N] for v >= 0 (rolling acts only while moving)."""
    v_air = v - wind
    f_aero = 0.5 * p.rho_air * p.cda_m2 * v_air * abs(v_air)
    f_roll = p.crr * p.mass_kg * G * math.cos(grade) if v > 1e-6 else 0.0
    f_grade = p.mass_kg * G * math.sin(grade)
    f_corner = 0.0
    if curvature and math.isfinite(p.cornering_stiffness_N_rad):
        f_y = p.mass_kg * v * v * abs(curvature)          # lateral force
        f_corner = f_y * f_y / p.cornering_stiffness_N_rad  # induced drag ~ Fy * slip angle
    f_dt = p.drivetrain_drag_N if v > 1e-6 else 0.0
    f_motor = 0.0
    if motor_coupled_unpowered and v > 1e-6:
        w = p.motor_speed(v)
        f_motor = (p.motor_drag_Nm + p.motor_drag_Nm_per_rad_s * w) * p.gear_ratio / p.wheel_radius_m
    return f_aero + f_roll + f_grade + f_corner + f_dt + f_motor


def resistive_force_np(p: VehicleParams, v: np.ndarray, grade: float = 0.0, wind: float = 0.0,
                       curvature: float = 0.0, motor_coupled_unpowered: bool = False) -> np.ndarray:
    """Vectorised resistive_force (identical terms; tested for equality)."""
    v = np.asarray(v, float)
    moving = v > 1e-6
    v_air = v - wind
    f = 0.5 * p.rho_air * p.cda_m2 * v_air * np.abs(v_air)
    f = f + np.where(moving, p.crr * p.mass_kg * G * math.cos(grade) + p.drivetrain_drag_N, 0.0)
    f = f + p.mass_kg * G * math.sin(grade)
    if curvature and math.isfinite(p.cornering_stiffness_N_rad):
        f_y = p.mass_kg * v * v * abs(curvature)
        f = f + f_y * f_y / p.cornering_stiffness_N_rad
    if motor_coupled_unpowered:
        w = v * p.gear_ratio / p.wheel_radius_m
        f = f + np.where(moving, (p.motor_drag_Nm + p.motor_drag_Nm_per_rad_s * w) * p.gear_ratio / p.wheel_radius_m,
                         0.0)
    return f


def tractive_force(p: VehicleParams, motor_torque_Nm: float) -> float:
    """Wheel force from motor shaft torque (motoring only; regen not modelled)."""
    return max(motor_torque_Nm, 0.0) * p.gear_ratio * p.drivetrain_eff / p.wheel_radius_m


def motor_torque_for_force(p: VehicleParams, f_wheel: float) -> float:
    return max(f_wheel, 0.0) * p.wheel_radius_m / (p.gear_ratio * p.drivetrain_eff)


# --------------------------------------------------------------------- coast-down
@dataclasses.dataclass
class CoastdownFit:
    """Fit of  -m_eff*a - m*g*sin(theta) = A + C*v_air^2  (B*v optional).

    A ~ Crr*m*g + constant drags, C = 0.5*rho*CdA. Reports covariance and an
    explicit identifiability verdict: if the A and C estimates are strongly
    correlated or poorly determined, only their combined effect over the
    tested speed range is supported by the data."""
    A_N: float
    B_N_s_m: float
    C_N_s2_m2: float
    cov: np.ndarray
    corr_AC: float
    rel_std_A: float
    rel_std_C: float
    cond: float
    v_range: tuple[float, float]
    n: int
    identifiable: bool
    verdict: str

    def crr(self, mass_kg: float, const_drag_N: float = 0.0) -> float:
        return (self.A_N - const_drag_N) / (mass_kg * G)

    def cda(self, rho: float = 1.2) -> float:
        return 2.0 * self.C_N_s2_m2 / rho


def fit_coastdown(t: np.ndarray, v: np.ndarray, m_eff: float, mass_kg: float, grade: np.ndarray | float = 0.0,
                  wind: np.ndarray | float = 0.0, with_linear: bool = False, max_corr: float = 0.95,
                  max_rel_std: float = 0.25) -> CoastdownFit:
    t = np.asarray(t, float)
    v = np.asarray(v, float)
    grade = np.broadcast_to(np.asarray(grade, float), v.shape)
    wind = np.broadcast_to(np.asarray(wind, float), v.shape)
    # central-difference acceleration (interior points)
    a = np.gradient(v, t)
    sl = slice(2, -2)
    y = -(m_eff * a[sl]) - mass_kg * G * np.sin(grade[sl])
    v_air = v[sl] - wind[sl]
    cols = [np.ones_like(v_air)]
    if with_linear:
        cols.append(v[sl])
    cols.append(v_air * np.abs(v_air))
    X = np.column_stack(cols)
    beta, res, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    dof = max(len(y) - X.shape[1], 1)
    resid = y - X @ beta
    s2 = float(resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    iA, iC = 0, X.shape[1] - 1
    corr = cov[iA, iC] / math.sqrt(cov[iA, iA] * cov[iC, iC])
    rsA = math.sqrt(cov[iA, iA]) / abs(beta[iA]) if beta[iA] else math.inf
    rsC = math.sqrt(cov[iC, iC]) / abs(beta[iC]) if beta[iC] else math.inf
    cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else math.inf
    ok = abs(corr) <= max_corr and rsA <= max_rel_std and rsC <= max_rel_std and beta[iA] > 0 and beta[iC] > 0
    verdict = ("A (rolling + constant drag) and C (aero) separately identified within the stated uncertainty"
               if ok else
               f"NOT separately identifiable from this data (corr(A,C)={corr:+.2f}, rel.std A={rsA:.0%}, "
               f"C={rsC:.0%}); only the combined resistance over {v.min():.1f}-{v.max():.1f} m/s is supported")
    return CoastdownFit(float(beta[iA]), float(beta[1]) if with_linear else 0.0, float(beta[iC]), cov, float(corr),
                        rsA, rsC, cond, (float(v.min()), float(v.max())), len(y), ok, verdict)


def simulate_coastdown(p: VehicleParams, v0: float, v_end: float, dt: float = 0.05, grade: float = 0.0,
                       wind: float = 0.0, noise_mps: float = 0.0, rng: np.random.Generator | None = None):
    """Synthetic coast-down (freewheel => motor decoupled) for testing the fit."""
    rng = rng or np.random.default_rng(1)
    m_eff = p.m_eff(coupled=not p.freewheel)
    ts, vs = [0.0], [v0]
    v, t = v0, 0.0
    while v > v_end and t < 3600:
        f = resistive_force(p, v, grade, wind, 0.0, motor_coupled_unpowered=not p.freewheel)
        # RK2 on dv/dt = -f/m_eff
        k1 = -f / m_eff
        vm = v + 0.5 * dt * k1
        k2 = -resistive_force(p, vm, grade, wind, 0.0, motor_coupled_unpowered=not p.freewheel) / m_eff
        v += dt * k2
        t += dt
        ts.append(t)
        vs.append(v)
    vs = np.array(vs) + (rng.normal(0, noise_mps, len(vs)) if noise_mps else 0.0)
    return np.array(ts), vs, m_eff
