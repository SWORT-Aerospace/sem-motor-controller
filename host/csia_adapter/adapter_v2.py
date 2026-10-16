"""CSIA vehicle adapter v2 (SHADOW MODE): the v1 adapter with a corrected power balance.

v1 (adapter.py) stays frozen and unchanged; its held-out results stand as
published. v2 changes exactly one relationship, E6 (DC meter <-> phase current):

1. Time alignment. v1 compared the latest p_dc (10 Hz in protocol 1.1) with
   the latest iq and rotor speed (100 Hz) at the tick. v2 interpolates iq and
   rotor speed to the receive time of the p_dc sample. Both come from the
   controller over the same bus, so their receive times share one clock.
2. Loss model. v1: losses = loss_rel |p_mech| + p_aux. v2:
       expected = p_mech + 1.5 R iq^2 + c_sw |iq| + P0
   (copper loss with amplitude-invariant dq scaling, a switching/conduction
   term proportional to current, a fixed term), with R, c_sw, P0 fitted by
   least squares on fault-free development data only (calibrate_e6), and
       var = (u_R 1.5 R iq^2)^2 + (u_rel p_mech)^2 + s0^2 + sigma_pdc^2
   where u_R covers the winding-temperature change of R, u_rel the
   torque-constant and gear-efficiency uncertainty, and s0 is the residual
   scatter left by the fit.

3. Gate inputs are auxiliary inputs. With a freewheel, E1 (rotor <-> driven
   wheel) is evaluated only while the freewheel is judged engaged, and that
   judgement uses |iq|. A drifting current sensor therefore opens E1 while
   the freewheel is open and the rotor spins down; v1 then blamed the rotor
   (current drift misattributed to the rotor in 4 of 5 v1 held-out cases).
   v2 lists phase_current as an auxiliary input of E1 when a freewheel is
   fitted, so an E1 failure is not attributed while the current node is
   itself failing or uncorroborated (the v1 auxiliary-input rule).

Everything else (other gates and relationships, attribution rules,
TrustCore) is the v1 code path.
"""
from __future__ import annotations

import bisect
import dataclasses
import math

import numpy as np

from host.csia_adapter.adapter import AdapterParams, VehicleCsiaAdapter


@dataclasses.dataclass
class E6Model:
    R_ohm: float
    c_sw_W_per_A: float
    p0_W: float
    s0_W: float
    u_R: float = 0.15          # winding temperature: R changes ~0.4 %/K, 40 K -> 16 %
    u_rel: float = 0.03        # Kt and gear-efficiency uncertainty on p_mech
    align_max_gap_s: float = 0.03   # no iq/rotor sample within this of the p_dc time: E6 not evaluated


def _interp(hist: list[tuple[float, float]], t: float, max_gap: float) -> float:
    if not hist:
        return math.nan
    ts = [x for x, _ in hist]
    k = bisect.bisect_left(ts, t)
    if k == 0:
        return hist[0][1] if ts[0] - t <= max_gap else math.nan
    if k == len(ts):
        return hist[-1][1] if t - ts[-1] <= max_gap else math.nan
    (t0, v0), (t1, v1) = hist[k - 1], hist[k]
    if t1 - t0 > 2 * max_gap:
        return math.nan
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


class VehicleCsiaAdapterV2(VehicleCsiaAdapter):
    VERSION = "adapter-v2"

    def __init__(self, params: AdapterParams, e6: E6Model):
        super().__init__(params)
        self.e6 = e6
        self.iq_hist: list[tuple[float, float]] = []

    def ingest(self, name, s):
        ok = super().ingest(name, s)
        if ok and name == "iq":
            self.iq_hist.append((s.rx_t, s.value))
            self.iq_hist = self.iq_hist[-60:]
        return ok

    def _e6(self, fr):
        p, S, m = self.p, self.sig, self.e6
        if not (fr["p_dc"] and fr["iq"] and fr["rotor"]):
            return ("dc_meter", "phase_current", math.nan, 0.0, ())
        pd = S["p_dc"].last
        iq = _interp(self.iq_hist, pd.rx_t, m.align_max_gap_s)
        w = _interp(self.rotor_hist, pd.rx_t, m.align_max_gap_s)
        if not (math.isfinite(iq) and math.isfinite(w)):
            return ("dc_meter", "phase_current", math.nan, 0.0, ())
        p_mech = p.kt_Nm_per_A * iq * w
        cu = 1.5 * m.R_ohm * iq * iq
        expected = p_mech + cu + m.c_sw_W_per_A * abs(iq) + m.p0_W
        var = (m.u_R * cu) ** 2 + (m.u_rel * p_mech) ** 2 + m.s0_W ** 2 + pd.sigma ** 2
        r = pd.value - expected
        # auxiliary input: rotor speed enters the expectation; same rule as v1
        max_effect = (1 + m.u_rel) * p.kt_Nm_per_A * abs(iq) * p.rotor_phys_max
        aux = () if abs(r) - max_effect > math.sqrt(p.lam_fail * var) else ("rotor",)
        return ("dc_meter", "phase_current", (r * r) / var if var > 0 else math.inf, 1.0, aux)

    def _rel(self, now: float):
        edges, phys, fr = super()._rel(now)
        edges["E6_power_balance"] = self._e6(fr)
        if self.p.freewheel:
            a, b, lam, g, aux = edges["E1_rotor_wheeldrive"]
            edges["E1_rotor_wheeldrive"] = (a, b, lam, g, tuple(aux) + ("phase_current",))
        return edges, phys, fr


def calibrate_e6(streams, kt: float) -> tuple[E6Model, dict]:
    """Least-squares fit of p_dc - kt iq w = 1.5 R iq^2 + c_sw |iq| + P0 on
    fault-free streams [(t, name, Sample), ...], with iq and rotor speed
    interpolated to each p_dc sample's receive time. Returns the model and a
    fit report. Use development data only."""
    X, y = [], []
    for data in streams:
        iq_h = [(s.rx_t, s.value) for _t, n, s in data if n == "iq"]
        w_h = [(s.rx_t, s.value) for _t, n, s in data if n == "rotor"]
        for _t, n, s in data:
            if n != "p_dc":
                continue
            iq = _interp(iq_h, s.rx_t, 0.03)
            w = _interp(w_h, s.rx_t, 0.03)
            if math.isfinite(iq) and math.isfinite(w):
                X.append([1.5 * iq * iq, abs(iq), 1.0])
                y.append(s.value - kt * iq * w)
    X, y = np.asarray(X), np.asarray(y)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    model = E6Model(R_ohm=float(coef[0]), c_sw_W_per_A=float(coef[1]), p0_W=float(coef[2]),
                    s0_W=float(np.std(res)))
    return model, {"samples": int(len(y)), "R_ohm": model.R_ohm, "c_sw_W_per_A": model.c_sw_W_per_A,
                   "p0_W": model.p0_W, "residual_sd_W": model.s0_W}
