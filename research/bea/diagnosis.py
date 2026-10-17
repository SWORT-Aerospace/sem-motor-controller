"""Reference set-valued diagnosis (pit side, host research code).

Input: records received by the pit (the live summary, and records returned by requests). Output: a
structured outcome with everything needed to audit it:

  consistent      no fault hypothesis improves on normal operation within the tested model. This is
                  not a statement that every component is healthy.
  unresolved      a fault is detected; more than one modelled cause remains (the set is reported)
  supported       a fault is detected and exactly one modelled cause remains
  no_fit          a fault is detected and no modelled cause, alone, fits (HU). Never read as healthy.
  insufficient    the records cannot test the hypotheses (too few samples, or no relationship that
                  would show a fault of the reference size)

Every hypothesis is fitted with bounded nuisance (research/bea/relations.py). A hypothesis is
retained when its fit is consistent with the noise (z score of the whitened residual) and within a
likelihood-ratio margin of the best fit. The thresholds are set in the development pilot and frozen.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np

from models.vehicle.longitudinal import SYNTHETIC_VEHICLE, resistive_force_np, tractive_force
from models.vehicle.powertrain import SYNTHETIC_MOTOR, SyntheticPhysicsMap
from research.bea.relations import Signals, Study, build_window, fit, whiten

NOMINAL_SIZE = {"HB": 0.2, "HL": 3.0}           # reference sizes for the insufficient-evidence test
DRIVE_IQ_A = 0.1                                # |iq| above this while the command trace says driving [A]
FAULT_PARAM = {"HB": "b_A", "HL": "dF_N"}


@dataclasses.dataclass(frozen=True)
class EngineConfig:
    # Whitened residual z score above which a hypothesis is inconsistent with the records, per evidence
    # source (full-rate frames, or the 2 Hz summary alone); set on the calibration split.
    z_frames: float = 3.0
    z_summary: float = 3.0
    set_margin: float = 9.0        # a fault hypothesis stays in the set when J_h - J_best_fault <= this
    # Normal operation is rejected when a fault hypothesis improves the fit by more than kappa_h. The
    # values depend on the evidence (the timing search has more freedom on full-rate records) and are
    # set on the calibration split; these defaults are placeholders before calibration.
    kappa_summary: tuple = (("HB", 9.0), ("HT", 9.0), ("HL", 9.0), ("HL_grade", 9.0))
    kappa_frames: tuple = (("HB", 9.0), ("HT", 9.0), ("HL", 9.0), ("HL_grade", 9.0))
    noise_scale: float = 1.0       # multiplies every modelled standard deviation
    # Per evidence source and relationship: (source, relationship, factor) multiplying that relationship's
    # modelled standard deviations, set on the calibration split (calibrate_blocks applies them).
    rel_scale: tuple = ()
    level: str = "known"
    timing: bool = True            # ablation switch: False drops the timing hypothesis and every timing allowance
    n_min: int = 20
    detect_sigma: float = 4.0      # insufficient when no fault of reference size would reach this separation


RECORD: Optional[list] = None      # calibration: when a list, every diagnosis appends its fit statistics


@dataclasses.dataclass
class Diagnosis:
    outcome: str
    hypotheses: tuple
    J: dict
    z: dict
    n: int
    blocks: tuple
    estimates: dict
    timing_bound_s: Optional[float]
    window_local: tuple
    reason: str
    accepted: dict = dataclasses.field(default_factory=dict)


# ----------------------------------------------------------------------------- signals from records
def _slots(t_rx: np.ndarray, vals: dict, t_ref: float, period: float, n: int) -> dict:
    """Place each record in its controller cycle (receipt jitter is far below the period), keeping the
    last record per cycle; cycles without a record are filled by linear interpolation. No averaging of
    neighbouring records, so the measurement noise stays independent between samples."""
    k = np.round((t_rx - t_ref) / period).astype(int)
    ok = (k >= 0) & (k < n)
    out = {}
    for name, v in vals.items():
        a = np.full(n, np.nan)
        a[k[ok]] = v[ok]
        good = np.isfinite(a)
        if good.sum() < 2:
            return {}
        idx = np.arange(n)
        a[~good] = np.interp(idx[~good], idx[good], a[good])
        out[name] = a
    return out


def _refine_edges(drive: np.ndarray, iq: np.ndarray, reach: int = 3) -> np.ndarray:
    """The command trace (50 Hz) says whether the gates are on. Near each of its transitions, the q current
    of the 100 Hz motion frame places the gate change to the cycle: the first cycle with |iq| below
    DRIVE_IQ_A after a drive-to-coast change (or above it after coast-to-drive). Elsewhere the trace
    decides, because the gates can be on at zero torque."""
    out = drive.copy()
    for e in np.flatnonzero(np.diff(drive.astype(int))) + 1:
        lo, hi = max(e - reach, 1), min(e + reach, len(drive) - 1)
        on = np.abs(iq[lo - 1:hi + 1]) > DRIVE_IQ_A
        if drive[e]:                                   # coast -> drive: first cycle with current
            j = np.flatnonzero(on)
            if len(j):
                k = lo - 1 + j[0]
                out[min(k, e):max(k, e)] = k <= e
        else:                                          # drive -> coast: first cycle without current
            j = np.flatnonzero(~on)
            if len(j):
                k = lo - 1 + j[0]
                out[min(k, e):max(k, e)] = k > e
    return out


def signals_from_frames(recs: dict, t0: float, t1: float, st: Study = Study(), period: float = 0.01) -> Optional[Signals]:
    """Rebuild signals on the controller's 10 ms cycle from full-rate records (telemetry-unit clock).

    The grid is anchored on the battery-current frames' receipt stamps. The drive or coast state comes
    from the command trace; speed is rotor speed while driving and wheel speed while coasting."""
    need = ("motion", "currents", "cmd")
    if any(k not in recs or len(recs[k]["t_rx"]) < 5 for k in need):
        return None
    c = recs["currents"]
    inwin = (c["t_rx"] >= t0) & (c["t_rx"] <= t1)
    if inwin.sum() < 10:
        return None
    t_ref = float(np.min(c["t_rx"][inwin]))
    n = int(np.floor((t1 - t_ref) / period)) + 1
    t = t_ref + np.arange(n) * period
    m, cm = recs["motion"], recs["cmd"]
    sm = _slots(m["t_rx"], {"iq": m["iq_A"], "w": m["speed_mech_rad_s"], "V": m["vbus_V"]}, t_ref, period, n)
    sc = _slots(c["t_rx"], {"I": c["ibatt_A"]}, t_ref, period, n)
    if not sm or not sc:
        return None
    k = np.clip(np.searchsorted(cm["t_rx"], t + 0.5 * period, side="right") - 1, 0, len(cm["t_rx"]) - 1)
    drive = _refine_edges(cm["coast"][k] < 0.5, sm["iq"])
    wheel_t = wheel_v = None
    if "wheel" in recs and len(recs["wheel"]["t_rx"]) > 3:
        wr = recs["wheel"]
        wheel_t = wr["t_rx"] - st.wheel_window_s / 2           # a window is stamped when it closes
        wheel_v = wr["counts"] * st.wheel_circ_m / (st.wheel_ppr * st.wheel_window_s)
    f_imu = None
    if "imu" in recs and len(recs["imu"]["t_rx"]) > 10:
        f_imu = np.interp(t, recs["imu"]["t_rx"], recs["imu"]["ax"])
    V, I = sm["V"], sc["I"]
    return _complete(t, 1.0 / period, drive, sm["iq"], sm["w"], V, I, V * I, wheel_t, wheel_v, f_imu, st)


def signals_from_summaries(msgs: list[dict], st: Study = Study()) -> Optional[Signals]:
    """Signals on the 2 Hz summary grid: instantaneous iq, speed and voltage, mean power since the
    previous message, the latest wheel window."""
    rows = [m for m in msgs if m["ctrl"]["iq_A"] is not None and m["ctrl"]["p_batt_W_mean"] is not None
            and m["ctrl"]["coast"] is not None]
    if len(rows) < 6:
        return None
    rows = sorted({m["seq"]: m for m in rows}.values(), key=lambda m: m["seq"])
    t = np.array([m["t_local_ms"] / 1000.0 for m in rows])
    if np.any(np.diff(t) <= 0):
        return None
    g = lambda k: np.array([float(m["ctrl"][k]) for m in rows])
    iq, w, V, P = g("iq_A"), g("speed_mech_rad_s"), g("vbus_V"), g("p_batt_W_mean")
    drive = np.array([not m["ctrl"]["coast"] for m in rows])
    wv = [m["wheel"]["speed_mps"]["wheel_drive"] for m in rows]
    ok = np.array([x is not None for x in wv])
    wheel_t = t[ok] - st.wheel_window_s / 2 if ok.sum() > 3 else None
    wheel_v = np.array([x for x in wv if x is not None]) if ok.sum() > 3 else None
    sig = _complete(t, 2.0, drive, iq, w, V, P / np.maximum(V, 1.0), P, wheel_t, wheel_v, None, st)
    # A message's mean power covers the time since the previous message: usable only if both were in one
    # mode and no message is missing in between. The model is compared over the same interval: the mean
    # of its values at the two ends (the snapshots), not its value at the end.
    gap_ok = np.concatenate([[False], np.diff([m["seq"] for m in rows]) == 1])
    sig.valid = gap_ok & np.concatenate([[False], drive[1:] == drive[:-1]])
    pm = sig.P_model.copy()
    pm[1:] = np.where(sig.valid[1:], 0.5 * (sig.P_model[1:] + sig.P_model[:-1]), sig.P_model[1:])
    sig.P_model = pm
    return sig


def _complete(t, hz, drive, iq, w, V, I, P, wheel_t, wheel_v, f_imu, st: Study) -> Signals:
    veh, mot = st.vehicle, st.motor
    v_rotor = w * veh.wheel_radius_m / veh.gear_ratio
    v = v_rotor.copy()
    if wheel_t is not None:
        v = np.where(drive, v_rotor, np.interp(t, wheel_t, wheel_v))
    shaft = np.where(drive, mot.kt * iq - mot.friction_Nm, 0.0)
    pmap = SyntheticPhysicsMap(veh, motor=mot, p_aux_W=0.0)
    P_model = np.zeros(len(t))
    for i in np.flatnonzero(drive):
        P_model[i] = pmap.p_batt(max(v_rotor[i], 0.0), max(shaft[i], 0.0), max(V[i], 1.0), 25.0, "drive")
    F_trac = np.array([tractive_force(veh, x) for x in shaft]) * drive
    F_res = resistive_force_np(veh, np.maximum(v, 0.0))
    m_eff = np.where(drive, veh.m_eff(True), veh.m_eff(False))
    return Signals(t, hz, v, drive, iq, w, P, V, I, P_model, F_trac, F_res, m_eff, f_imu, wheel_t, wheel_v, "records")


# ----------------------------------------------------------------------------- the engine
def scale_blocks(blocks: list, s: float) -> list:
    """Copies of the blocks with every standard deviation multiplied by s."""
    return [dataclasses.replace(b, cov=b.cov * s * s) for b in blocks] if s != 1.0 else blocks


def calibrate_blocks(blocks: list, cfg: "EngineConfig", source: str) -> list:
    """Blocks from one evidence source ("frames" or "summary") with each relationship's standard
    deviations multiplied by its calibrated factor."""
    f = {name: k for src, name, k in cfg.rel_scale if src == source}
    return [dataclasses.replace(b, cov=b.cov * f[b.name] ** 2) if f.get(b.name, 1.0) != 1.0 else b for b in blocks]


def engine_from_calibration(c: dict) -> "EngineConfig":
    """EngineConfig from the "engine" section of a calibration file or of the pre-registration manifest."""
    return EngineConfig(noise_scale=c.get("noise_scale", 1.0), z_frames=c.get("z_frames", 3.0),
                        z_summary=c.get("z_summary", 3.0),
                        rel_scale=tuple((src, name, k) for src, by in sorted(c.get("rel_scale", {}).items())
                                        for name, k in sorted(by.items())),
                        kappa_summary=tuple(sorted(c["kappa_summary"].items())),
                        kappa_frames=tuple(sorted(c["kappa_frames"].items())))


def _block_fit_stats(W, blocks: list, est: dict) -> dict:
    """Each relationship's share of the normal-operation fit statistic: name -> [J, n] (calibration)."""
    x = np.array([est[n] for n in W.names])
    d = est.get("delta_s", 0.0)
    r = W.y - W.C_at(d) @ x - W.shift(d)
    out, off = {}, 0
    for b in blocks:
        rb = r[off:off + b.n]
        off += b.n
        acc = out.setdefault(b.name, [0.0, 0])
        acc[0] += float(rb @ rb)
        acc[1] += b.n
    return out


def diagnose(sig: Optional[Signals], rels: dict, cfg: EngineConfig = EngineConfig(), st: Study = Study(),
             timing_s: Optional[float] = None) -> Diagnosis:
    if sig is None:
        return Diagnosis("insufficient", (), {}, {}, 0, (), {}, timing_s, (math.nan, math.nan), "no usable records")
    return diagnose_blocks(build_window(sig, st, rels), cfg, timing_s, (float(sig.t[0]), float(sig.t[-1])))


def diagnose_blocks(blocks: list, cfg: EngineConfig = EngineConfig(), timing_s: Optional[float] = None,
                    win: tuple = (math.nan, math.nan), source: str = "summary") -> Diagnosis:
    """The reference diagnosis on already-built relationship blocks (possibly from several record sources)."""
    if not blocks:
        return Diagnosis("insufficient", (), {}, {}, 0, (), {}, timing_s, win, "no usable records")
    W = whiten(blocks, cfg.noise_scale)
    if W.n < cfg.n_min:
        return Diagnosis("insufficient", (), {}, {}, W.n, tuple(W.blocks), {}, timing_s, win,
                         f"{W.n} usable samples, fewer than {cfg.n_min}")
    hyps = ["H0", "HB"] + (["HT"] if cfg.timing else []) + ["HL"] + (["HL_grade"] if "R5" in W.blocks else [])
    if not cfg.timing:
        timing_s = 0.0
    J, est = {}, {}
    for h in hyps:
        J[h], est[h] = fit(W, W.y, h, cfg.level, timing_s=timing_s)
    n = W.n
    z = {h: (J[h] - n) / math.sqrt(2.0 * n) for h in hyps}
    kappa = dict(cfg.kappa_frames if source == "frames" else cfg.kappa_summary)
    faults = [h for h in hyps if h != "H0"]
    if RECORD is not None:
        RECORD.append({"source": source, "n": n, "blocks": tuple(W.blocks), "z0": z["H0"],
                       "dJ": {h: J["H0"] - J[h] for h in faults}, "by_block": _block_fit_stats(W, blocks, est["H0"])})
    zc = cfg.z_frames if source == "frames" else cfg.z_summary
    h0_rejected = z["H0"] > zc or any(J["H0"] - J[h] > kappa.get(h, 9.0) for h in faults)
    jbest = min(J[h] for h in faults)
    keep = ("H0",) if not h0_rejected else tuple(
        h for h in faults if z[h] <= zc and J[h] - jbest <= cfg.set_margin)
    accepted = {b.name: b.n for b in blocks}
    if "H0" in keep:
        power = reference_power(W, cfg, timing_s)
        blind = sorted(h for h, d in power.items() if d < cfg.detect_sigma)
        est["_power"] = power
        if len(blind) == len(power):
            return Diagnosis("insufficient", keep, J, z, n, tuple(W.blocks), est, timing_s, win,
                             "no fault of reference size would separate from normal operation on these records",
                             accepted)
        note = f"; not testable on these records: {', '.join(blind)}" if blind else ""
        return Diagnosis("consistent", ("H0",), J, z, n, tuple(W.blocks), est, timing_s, win,
                         "normal operation explains the records within the tested model" + note, accepted)
    faults = tuple(keep)
    if not faults:
        return Diagnosis("no_fit", (), J, z, n, tuple(W.blocks), est, timing_s, win,
                         "normal operation rejected and no modelled cause fits alone", accepted)
    if len(faults) == 1:
        return Diagnosis("supported", faults, J, z, n, tuple(W.blocks), est, timing_s, win,
                         f"{faults[0]} is the only modelled cause that fits", accepted)
    return Diagnosis("unresolved", faults, J, z, n, tuple(W.blocks), est, timing_s, win,
                     "fault detected; these causes fit equally well: " + ", ".join(faults), accepted)


def reference_power(W, cfg: EngineConfig, timing_s: Optional[float] = None) -> dict:
    """Separation from H0 that a reference-size fault would reach on this window (bounded nuisance):
    what these records could show, independent of what they do show."""
    out = {}
    for h, p in FAULT_PARAM.items():
        if p in W.names:
            a = W.C[:, W.names.index(p)] * NOMINAL_SIZE[h]
            out[h] = math.sqrt(max(fit(W, a, "H0", cfg.level, timing_s=timing_s)[0], 0.0))
        else:
            out[h] = 0.0
    out["HT"] = math.sqrt(max(fit(W, W.shift(NOMINAL_SIZE_HT), "H0", cfg.level, timing_s=timing_s)[0], 0.0)) if W.n else 0.0
    return out


NOMINAL_SIZE_HT = 0.1
