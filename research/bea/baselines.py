"""Diagnostic baselines on identical records (research/PROTOCOL.md section 7).

  aligned residual   fixed fault-signature table on the means of the aligned residuals: each
                     residual fires against a threshold set on fault-free calibration windows; a cause
                     is consistent when every firing residual is sensitive to it
  MHT                multiple-hypothesis likelihood: Gaussian priors on the nuisance terms (the
                     variance of a uniform over the bound) and broad priors on the fault sizes;
                     marginal likelihood per hypothesis, maximum a posteriori, abstain below a
                     posterior threshold
  R3v, CSIA2         the frozen monitors of host/csia_adapter, run unchanged on the same records
                     converted to their stream format; the CSIA2 power model is refitted with the
                     frozen calibrate_e6 and the R3v threshold set by the frozen calibrate(), both on
                     fault-free calibration episodes of this harness

Outcomes use the same names as the reference diagnosis. The frozen monitors know sensor nodes, not
causes: a suspected DC meter maps to HB, any other node to "other", AMBIGUOUS to unresolved.
"""
from __future__ import annotations

import dataclasses
import math
import types
from typing import Optional

import numpy as np

from host.csia_adapter import evaluation as EV
from host.csia_adapter import evaluation_v2 as EV2
from host.csia_adapter.adapter import Sample
from host.csia_adapter.adapter_v2 import E6Model, calibrate_e6
from research.bea.relations import NUISANCE, TIMING, FAULTS, Whitened, bounds_for, whiten

# ----------------------------------------------------------------------------- aligned residual monitor
SENSITIVE = {             # residuals each fault can move (structured residuals, binary fault-signature table)
    "HB": {"R1", "R3"},
    "HT": {"R1dyn", "R3"},   # the current that a late meter carries into a coast shows in R3
    "HL": {"R2", "R4", "R5"},
}


def residual_statistics(blocks: list, noise_scale: float = 1.0) -> dict:
    """Standardised mean of each relationship's residual, and for R1 the correlation-like statistic of its
    residual with the model's power rate (a timing error shows there)."""
    out = {}
    for b in blocks:
        sd = np.sqrt(np.diag(b.cov)) * noise_scale
        if b.n < 3:
            continue
        name = "R1" if b.name in ("R1", "R1s") else "R2" if b.name in ("R2", "R2s") else b.name
        out[name] = float(np.sum(b.resid / sd ** 2) / math.sqrt(np.sum(1.0 / sd ** 2)))
        if b.shift is not None and name == "R1":
            g = b.shift(0.01) / 0.01                         # -dP/dt of the model
            if np.any(g):
                w = g / sd ** 2
                out["R1dyn"] = float(np.sum(w * b.resid) / math.sqrt(np.sum(w * g)))
    return out


def aligned_residual(blocks: list, thresholds: dict, noise_scale: float = 1.0) -> dict:
    stat = residual_statistics(blocks, noise_scale)
    if not stat:
        return {"outcome": "insufficient", "hypotheses": (), "stat": stat}
    fired = {k for k, v in stat.items() if abs(v) > thresholds.get(k, 6.0)}
    if not fired:
        return {"outcome": "consistent", "hypotheses": ("H0",), "stat": stat}
    # A cause is consistent with the pattern when every firing residual is sensitive to it; a sensitive
    # residual that does not fire does not exonerate (it may be below its threshold).
    match = tuple(h for h, sens in SENSITIVE.items() if fired <= sens)
    if not match:
        return {"outcome": "no_fit", "hypotheses": (), "stat": stat}
    return {"outcome": "supported" if len(match) == 1 else "unresolved", "hypotheses": match, "stat": stat}


def calibrate_aligned(stats: list) -> dict:
    """Per-residual threshold: 1.1 times the largest |statistic| (residual_statistics) on fault-free
    calibration windows, and at least 4."""
    mx: dict = {}
    for st in stats:
        for k, v in st.items():
            mx[k] = max(mx.get(k, 0.0), abs(v))
    return {k: round(max(4.0, 1.1 * v), 2) for k, v in mx.items()}


# ----------------------------------------------------------------------------- multiple-hypothesis baseline
FAULT_PRIOR_SD = {"b_A": 0.5, "dF_N": 10.0}
MHT_HYPS = {"H0": (), "HB": ("b_A",), "HT": (), "HL": ("dF_N",)}


def _log_marginal(W: Whitened, y: np.ndarray, C: np.ndarray, prior_var: np.ndarray) -> float:
    """log N(y; 0, I + C diag(v) C^T) by the matrix determinant lemma and Woodbury."""
    keep = prior_var > 0
    C, v = C[:, keep], prior_var[keep]
    if C.shape[1] == 0:
        return -0.5 * float(y @ y)
    A = C * np.sqrt(v)
    M = np.eye(A.shape[1]) + A.T @ A
    sign, logdet = np.linalg.slogdet(M)
    u = A.T @ y
    quad = float(y @ y - u @ np.linalg.solve(M, u))
    return -0.5 * quad - 0.5 * logdet


def mht(blocks: list, level: str = "known", timing_s: Optional[float] = None, noise_scale: float = 1.0,
        p_accept: float = 0.95, prior_h0: float = 0.25) -> dict:
    """Multiple-hypothesis baseline: Gaussian marginal likelihood of each hypothesis (nuisance and fault
    parameters integrated, the timing offset averaged over a uniform prior), prior prior_h0 for normal
    operation and the rest shared equally by the faults. Decision: normal operation if it has the
    largest posterior; else the best fault if its posterior reaches p_accept; else unresolved, with the
    faults of posterior at least 0.05. "posterior_equal" is the posterior under equal priors (calibration)."""
    if not blocks:
        return {"outcome": "insufficient", "hypotheses": (), "posterior": {}}
    W = whiten(blocks, noise_scale)
    nb = NUISANCE[level]
    t0 = TIMING[level] if timing_s is None else timing_s
    logm = {}
    for h, free in MHT_HYPS.items():
        var = np.array([FAULT_PRIOR_SD[p] ** 2 if p in free else 0.0 if p in FAULTS else nb[p] ** 2 / 3.0
                        for p in W.names])
        grid = np.linspace(-0.5, 0.5, 41) if h == "HT" else np.linspace(-t0, t0, 3)
        vals = [_log_marginal(W, W.y - W.shift(d), W.C_at(d), var) for d in grid]
        m = max(vals)
        logm[h] = m + math.log(np.mean(np.exp(np.array(vals) - m)))     # uniform prior on the offset
    m = max(logm.values())
    lik = {h: math.exp(v - m) for h, v in logm.items()}
    equal = {h: v / sum(lik.values()) for h, v in lik.items()}
    nf = len(lik) - 1
    post = {h: v * (prior_h0 if h == "H0" else (1.0 - prior_h0) / nf) for h, v in lik.items()}
    z = sum(post.values())
    post = {h: p / z for h, p in post.items()}
    best = max(post, key=post.get)
    if best == "H0":
        return {"outcome": "consistent", "hypotheses": ("H0",), "posterior": post, "posterior_equal": equal}
    if post[best] >= p_accept:
        return {"outcome": "supported", "hypotheses": (best,), "posterior": post, "posterior_equal": equal}
    keep = tuple(h for h, p in sorted(post.items(), key=lambda kv: -kv[1]) if p >= 0.05 and h != "H0")
    return {"outcome": "unresolved", "hypotheses": keep, "posterior": post, "posterior_equal": equal}


def calibrate_mht_prior(equal_posteriors: list, n_faults: int = 3) -> float:
    """Prior probability of normal operation: the smallest that makes normal operation the most probable
    hypothesis on every fault-free calibration window, with the prior odds raised by 1.1 (the rule used
    for the reference diagnosis's margins), and at least the equal share."""
    need = max((max(v for h, v in p.items() if h != "H0") / max(p["H0"], 1e-300) for p in equal_posteriors), default=0.0)
    odds = 1.1 * need / n_faults            # prior_h0 / ((1 - prior_h0) / n_faults) must exceed need
    return round(max(1.0 / (n_faults + 1), odds / (1.0 + odds)), 6)


# ----------------------------------------------------------------------------- frozen monitors
def adapter_stream(log: dict, kt: float, t_end_local: float) -> list:
    """The harness log converted to the frozen adapters' stream format (receive-stamped, telematics clock).

    Controller frames carry no source time, so the receipt stamp stands in for it, in one clock domain.
    The KCL residual is not simulated by this harness and is reported as available and zero."""
    out = []
    m, c, cm, w, g = (log[k] for k in ("motion", "currents", "cmd", "wheel", "gnss"))

    def emit(t, name, value, sigma, seq, flags=None):
        out.append((t, name, Sample(float(value), sigma, t, "telematics", t, int(seq), 1, flags or {})))

    for i in range(len(m["t_rx"])):
        t = float(m["t_rx"][i])
        if t > t_end_local:
            break
        emit(t, "rotor", m["speed_mech_rad_s"][i], 0.01 * abs(float(m["speed_mech_rad_s"][i])) + 2.0, m["seq"][i])
        emit(t, "iq", m["iq_A"][i], 0.15, m["seq"][i])
        emit(t, "kcl", 0.0, 0.1, m["seq"][i], {"kcl_available": True})
    vb = np.interp(c["t_rx"], m["t_rx"], m["vbus_V"])
    for i in range(0, len(c["t_rx"]), 2):                              # 50 Hz bus power, as the v2 sets used
        t = float(c["t_rx"][i])
        if t <= t_end_local:
            emit(t, "p_dc", vb[i] * c["ibatt_A"][i], 1.0, c["seq"][i])
    for i in range(len(cm["t_rx"])):
        t = float(cm["t_rx"][i])
        if t <= t_end_local:
            emit(t, "iq_ref", cm["accepted_Nm"][i] / kt, 0.0, cm["seq"][i], {"saturated_or_slewing": False})
    q = 1.5 / (32 * 0.1)
    for i in range(len(w["t_rx"])):
        t = float(w["t_rx"][i])
        if t <= t_end_local:
            v = float(w["counts"][i]) * q
            for name in ("wheel_l", "wheel_r", "wheel_drive"):
                emit(t, name, v, q / math.sqrt(12) + 0.01 * v, i)
            emit(t, "grade", 0.0, 0.003, i)
    for i in range(len(g["t_rx"])):
        t = float(g["t_rx"][i])
        if t <= t_end_local:
            emit(t, "gnss", g["speed"][i], 0.08, i, {"sacc": 0.08, "num_sv": 11})
    out.sort(key=lambda x: x[0])
    return out


@dataclasses.dataclass
class FrozenMonitors:
    e6: E6Model
    lam: float
    trust_thr: dict
    report: dict

    @classmethod
    def calibrate(cls, cal_streams: list, kt: float = 0.06) -> "FrozenMonitors":
        """Frozen calibration functions only: E6 refit, then the R3v threshold and TrustCore thresholds."""
        shifted = [_shift(s) for _d, s in cal_streams]
        e6, rep = calibrate_e6(shifted, kt)
        scns = [(types.SimpleNamespace(duration_s=s[-1][0]), s) for s in shifted]
        lam, info, trust = EV2.calibrate(scns, e6)
        return cls(e6, lam, trust, {"e6": rep, "r3v_threshold": lam, **info})

    def run(self, stream: list, t0_local: float, t1_local: float) -> dict:
        """Run R3v and CSIA2 from the start of the stream; report each one's last output in [t0, t1]."""
        mons = [EV2.Debounce(EV2.ResidualV2("R3v", "vote", self.lam, self.e6)), EV2.Debounce(EV2.Csia2(self.e6))]
        off = stream[0][0] - EV.TICK
        outs = EV.run_stream(_shift(stream), t1_local - off, mons)
        res = {}
        for name, seq in outs.items():
            win = [o for t, o in seq if t >= t0_local - off]
            res[name] = _map_node_output(win[-1] if win else None)
        return res


def _shift(stream: list) -> list:
    """The stream moved to start at one tick, every time field together (the frozen runner ticks from 0)."""
    off = stream[0][0] - EV.TICK
    return [(t - off, n, dataclasses.replace(s, src_t=s.src_t - off, rx_t=s.rx_t - off)) for t, n, s in stream]


def _map_node_output(o) -> dict:
    if o is None:
        return {"outcome": "insufficient", "hypotheses": ()}
    sus = sorted(o.suspects)
    if len(sus) == 1:
        return {"outcome": "supported", "hypotheses": ("HB",) if sus[0] == "dc_meter" else ("other:" + sus[0],)}
    if len(sus) > 1 or o.implicated:
        imp = sorted(set(sus) | set(o.implicated))
        return {"outcome": "unresolved", "hypotheses": tuple("HB" if n == "dc_meter" else "other:" + n for n in imp)}
    return {"outcome": "consistent", "hypotheses": ("H0",)}
