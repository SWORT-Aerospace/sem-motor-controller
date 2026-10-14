"""Battery-power maps  P_batt = f(speed, torque, V_bus, temperature, mode).

Preferred: a MEASURED loss map near the operating region, because an
efficiency ratio eta = P_out/P_in is ill-conditioned near zero torque (both go
to zero while losses do not). Maps therefore return absolute battery power and
declare which losses they already contain, so the energy model never adds them
twice.

The SyntheticPhysicsMap is a placeholder built from synthetic parameters; it is
for exercising the optimiser, not for predicting the real vehicle.
"""
from __future__ import annotations

import csv
import dataclasses
import math
import pathlib
from typing import Protocol

import numpy as np

from models.inverter.losses import GateDriveParams, InverterOperatingPoint, MosfetParams, inverter_losses
from models.vehicle.longitudinal import VehicleParams

LOSS_COMPONENTS = {"motor_copper", "motor_iron", "motor_friction", "inverter", "drivetrain", "aux"}
MODES = ("drive", "coast_gate_off", "coast_zero_current")


class PowerMap(Protocol):
    includes: frozenset[str]
    label: str

    def p_batt(self, v_mps: float, motor_torque_Nm: float, v_bus: float, temp_C: float, mode: str) -> float: ...


@dataclasses.dataclass(frozen=True)
class MotorParams:
    pole_pairs: int
    rs_ohm: float
    lambda_Wb: float
    k_iron_W_per_rad_s15: float      # iron loss ~ k * w_mech^1.5 (synthetic form)
    friction_Nm: float               # bearing/seal friction torque
    label: str = "SYNTHETIC"

    @property
    def kt(self) -> float:
        return 1.5 * self.pole_pairs * self.lambda_Wb


SYNTHETIC_MOTOR = MotorParams(pole_pairs=4, rs_ohm=0.10, lambda_Wb=0.010, k_iron_W_per_rad_s15=2.0e-3,
                              friction_Nm=0.005)
SYNTHETIC_FET = MosfetParams(rds_on_25_ohm=0.004, rds_tc_per_K=0.006, qg_C=60e-9, qgd_C=12e-9, qgs2_C=8e-9,
                             qoss_C=100e-9, qrr_C=50e-9, vf_body_V=0.8, v_plateau_V=4.5, label="SYNTHETIC-FET")
SYNTHETIC_GATE = GateDriveParams(v_drive_V=10.0, i_source_A=0.3, i_sink_A=0.6, rg_external_ohm=5.0)


@dataclasses.dataclass
class SyntheticPhysicsMap:
    vehicle: VehicleParams
    motor: MotorParams = SYNTHETIC_MOTOR
    fet: MosfetParams = SYNTHETIC_FET
    gate: GateDriveParams = SYNTHETIC_GATE
    f_sw_Hz: float = 20000.0
    deadtime_s: float = 200e-9
    p_aux_W: float = 3.0             # controller logic + sensors + companion share (synthetic)
    tj_C: float = 60.0
    includes: frozenset = frozenset({"motor_copper", "motor_iron", "motor_friction", "inverter", "aux"})
    label: str = "SYNTHETIC physics map (not measured)"

    def p_batt(self, v_mps: float, motor_torque_Nm: float, v_bus: float, temp_C: float = 25.0,
               mode: str = "drive") -> float:
        if mode not in MODES:
            raise ValueError(mode)
        w = max(v_mps, 0.0) * self.vehicle.gear_ratio / self.vehicle.wheel_radius_m
        m = self.motor
        w_e = w * m.pole_pairs
        if mode == "coast_gate_off":
            # Gates off. With back-EMF below the bus no current flows; only
            # electronics consume. (Motor drag is a mechanical load, handled in
            # the vehicle model when the motor stays coupled.)
            e_ll_pk = math.sqrt(3) * m.lambda_Wb * w_e
            if e_ll_pk >= v_bus:
                raise ValueError("gate-off coast with back-EMF above the bus: rectification - not modelled")
            return self.p_aux_W
        t_em = max(motor_torque_Nm, 0.0) + (m.friction_Nm if w > 0 else 0.0)
        iq = t_em / m.kt if mode == "drive" else 0.0
        if mode == "coast_zero_current":
            t_em, iq = 0.0, 0.0
        p_cu = 1.5 * m.rs_ohm * iq * iq
        p_fe = m.k_iron_W_per_rad_s15 * w ** 1.5
        vq = m.rs_ohm * iq + w_e * m.lambda_Wb
        vd = 0.0  # neglect L*w*iq term for the modulation estimate (small at these speeds)
        v_ph_pk = math.hypot(vd, vq)
        m_index = min(v_ph_pk / (0.5 * v_bus), 2.0 / math.sqrt(3))
        cos_phi = vq / v_ph_pk if v_ph_pk > 0 else 1.0
        op = InverterOperatingPoint(v_bus_V=v_bus, i_ph_pk_A=abs(iq), m_index=m_index, cos_phi=cos_phi,
                                    f_sw_Hz=self.f_sw_Hz, deadtime_s=self.deadtime_s, tj_C=self.tj_C)
        p_inv = inverter_losses(self.fet, self.gate, op)["total_W"]
        p_mech = motor_torque_Nm * w if mode == "drive" else 0.0
        # In coast_zero_current the iron/friction losses are supplied by vehicle KE (mechanical), not the battery.
        p_motor_elec = p_cu + (p_fe if mode == "drive" else 0.0)
        return p_mech + p_motor_elec + p_inv + self.p_aux_W


@dataclasses.dataclass
class MeasuredLossMap:
    """Bilinear interpolation of a measured battery-side loss grid
    P_loss(w_mech, T) [W] at a reference bus voltage. File format (CSV):
        speed_rad_s,torque_Nm,p_loss_W     plus a header comment line
        # includes=motor_copper,motor_iron,motor_friction,inverter ; v_bus=... ; provenance=...
    Outside the measured grid the map refuses to extrapolate."""
    speeds: np.ndarray
    torques: np.ndarray
    loss: np.ndarray                 # [len(speeds), len(torques)]
    includes: frozenset
    vehicle: VehicleParams
    p_aux_W: float = 0.0
    label: str = "measured"

    @classmethod
    def from_csv(cls, path: pathlib.Path, vehicle: VehicleParams, p_aux_W: float = 0.0) -> "MeasuredLossMap":
        lines = pathlib.Path(path).read_text().splitlines()
        meta = dict(kv.strip().split("=", 1) for kv in lines[0].lstrip("#").split(";") if "=" in kv)
        includes = frozenset(x.strip() for x in meta.get("includes", "").split(",") if x.strip())
        unknown = includes - LOSS_COMPONENTS
        if unknown:
            raise ValueError(f"unknown loss components {unknown}")
        rows = list(csv.DictReader(lines[1:]))
        sp = sorted({float(r["speed_rad_s"]) for r in rows})
        tq = sorted({float(r["torque_Nm"]) for r in rows})
        grid = np.full((len(sp), len(tq)), np.nan)
        for r in rows:
            grid[sp.index(float(r["speed_rad_s"])), tq.index(float(r["torque_Nm"]))] = float(r["p_loss_W"])
        if np.isnan(grid).any():
            raise ValueError("measured map grid is incomplete")
        return cls(np.array(sp), np.array(tq), grid, includes, vehicle, p_aux_W,
                   f"measured ({meta.get('provenance', 'unknown provenance')})")

    def p_batt(self, v_mps, motor_torque_Nm, v_bus, temp_C=25.0, mode="drive"):
        w = max(v_mps, 0.0) * self.vehicle.gear_ratio / self.vehicle.wheel_radius_m
        if not (self.speeds[0] <= w <= self.speeds[-1] and self.torques[0] <= motor_torque_Nm <= self.torques[-1]):
            raise ValueError(f"operating point ({w:.1f} rad/s, {motor_torque_Nm:.3f} N*m) outside measured map")
        i = min(np.searchsorted(self.speeds, w, side="right") - 1, len(self.speeds) - 2)
        j = min(np.searchsorted(self.torques, motor_torque_Nm, side="right") - 1, len(self.torques) - 2)
        fx = (w - self.speeds[i]) / (self.speeds[i + 1] - self.speeds[i])
        fy = (motor_torque_Nm - self.torques[j]) / (self.torques[j + 1] - self.torques[j])
        L = self.loss
        loss = (L[i, j] * (1 - fx) * (1 - fy) + L[i + 1, j] * fx * (1 - fy) + L[i, j + 1] * (1 - fx) * fy
                + L[i + 1, j + 1] * fx * fy)
        aux = 0.0 if "aux" in self.includes else self.p_aux_W
        return motor_torque_Nm * w + loss + aux


def check_no_double_counting(vehicle: VehicleParams, pmap: PowerMap) -> None:
    """Raise if the vehicle model and the power map would both apply a loss."""
    if "drivetrain" in pmap.includes and (vehicle.drivetrain_eff != 1.0 or vehicle.drivetrain_drag_N != 0.0):
        raise ValueError("power map already includes drivetrain losses; set vehicle drivetrain_eff=1, drag=0")
    if "motor_friction" in pmap.includes and vehicle.motor_drag_Nm != 0.0 and not vehicle.freewheel:
        # Coupled-coast motor drag is a mechanical term; while DRIVING it must not
        # also be inside the map. The vehicle model only applies it when unpowered.
        pass
