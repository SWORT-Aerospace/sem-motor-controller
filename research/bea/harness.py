"""Causal evaluation harness (HOST SIMULATION): truth, sensors, transport, faults, vehicle log, pit access.

Layers, in the order data flows; each is a separate function with its own inputs:

  1. plant      truth trajectory of one episode: drive cycle, nuisance draws, plant-level faults (HL, grade)
  2. sensors    source-side samples at their true acquisition times: noise, quantisation, calibration
                errors, sensor-level faults (HB, HT, an unmodelled gain error)
  3. transport  controller CAN frames: send jitter, bus latency, burst loss, duplication, reordering,
                receipt stamps in the telemetry unit's clock
  4. vehicle    the local log (every received record, bounded depth per channel) and the 2 Hz summary
                with its uplink delay, outages and backlog
  5. access     what the pit can see at a simulated time, and the costed requests that fetch more

The diagnostic receives only an Access object. Fault labels stay in EpisodeSpec, which only the
scorer reads. The vehicle side does not depend on the diagnostic (the study is diagnostic only), so
layers 1 to 4 are computed once per episode; layer 5 enforces causality: a record is returned only
after it existed on the vehicle, after the request reached the vehicle, and after the transfer time.

All parameters are synthetic assumptions; see research/HARNESS.md for the list and their status.
"""
from __future__ import annotations

import dataclasses
import json
import math
from typing import Optional

import numpy as np

from host.telematics.clocks import LocalClock
from models.vehicle.longitudinal import G, SYNTHETIC_VEHICLE, motor_torque_for_force, resistive_force, tractive_force
from models.vehicle.powertrain import SYNTHETIC_MOTOR, SyntheticPhysicsMap
from research.bea.identifiability import NUISANCE, Study

PLANT_HZ = 500
CTRL_PERIOD = 0.01
REC_BYTES = {"motion": 17, "currents": 17, "energy": 17, "cmd": 17, "validity": 17, "wheel": 11, "imu": 14,
             "gnss": 16}                                    # STLG record sizes [F]: 6-byte header + body
CHANNEL_HZ = {"motion": 100.0, "currents": 100.0, "energy": 10.0, "cmd": 50.0, "validity": 10.0, "wheel": 10.0,
              "imu": 100.0, "gnss": 10.0}
FAULT_KINDS = ("none", "HB", "HT", "HL", "HL_grade", "HU_gain", "HB+HL", "HT+HB")


# ----------------------------------------------------------------------------- specifications
@dataclasses.dataclass(frozen=True)
class FaultSpec:
    kind: str = "none"
    onset_s: float = math.inf
    size: float = 0.0          # A (HB), s (HT), N (HL), rad (HL_grade), relative (HU_gain)
    ht_kind: str = "delay"     # delay | lag | boxcar (HT only)
    size2: float = 0.0         # second fault of a combined kind (HB+HL: N; HT+HB: A)


@dataclasses.dataclass(frozen=True)
class PlantDraw:
    """True deviations from the nominal model, unknown to the diagnostic."""
    d_crr: float = 0.0
    d_cda: float = 0.0
    d_meff_rel: float = 0.0
    d_kt_rel: float = 0.0
    d_rs: float = 0.0
    d_fe_rel: float = 0.0
    d_sw: float = 0.0
    d_tf: float = 0.0
    d_p0: float = 0.0
    grade_rad: float = 0.0
    wind_mps: float = 0.0       # along-track headwind
    ioff_A: float = 0.0
    imu_bias: float = 0.0
    meter_gain_rel: float = 0.0


@dataclasses.dataclass(frozen=True)
class LinkSpec:
    can_loss_p_gb: float = 0.0005   # Gilbert-Elliott: good to bad
    can_loss_p_bg: float = 0.2      # bad to good
    can_loss_bad: float = 0.5       # loss probability in the bad state
    can_dup: float = 0.0005
    can_reorder: float = 0.0005
    clock: LocalClock = dataclasses.field(default_factory=LocalClock)
    uplink_latency_s: float = 0.3
    uplink_outages: tuple = ()      # (t0, t1) true time
    rtt_s: float = 0.6              # pit to vehicle and back, for requests (proposed path)
    uplink_Bps: float = 20000.0     # usable uplink rate for bulk responses [A]


@dataclasses.dataclass(frozen=True)
class EpisodeSpec:
    seed: int
    split: str
    cycle: str                      # pulse_coast | speed_hold | mixed
    duration_s: float
    v_lo: float
    v_hi: float
    a_pulse: float
    draw: PlantDraw
    fault: FaultSpec
    link: LinkSpec
    nuisance_level: str = "known"   # which bounds the draws respect


def draw_episode(seed: int, split: str, fault_kind: str, level: str = "known",
                 cycle: Optional[str] = None, size_scale: float = 1.0) -> EpisodeSpec:
    """Draw every random element of one episode from its seed. Fault sizes are drawn around the
    study's nominal sizes; the onset is uniform in the middle of the run."""
    rng = np.random.default_rng(seed)
    nb = NUISANCE[level]
    u = lambda k, f=0.9: float(rng.uniform(-f, f) * nb[k])      # stay inside the bound
    draw = PlantDraw(d_crr=u("dCrr"), d_cda=u("dCdA_m2"), d_meff_rel=u("dmeff_rel"), d_kt_rel=u("dKt_rel"),
                     d_rs=u("dRs_ohm"), d_fe_rel=u("dFe_rel"), d_sw=u("dSw_W_per_A"), d_tf=u("dTf_Nm"),
                     d_p0=u("P0_W"), grade_rad=u("grade_rad"), wind_mps=u("wind_mps"), ioff_A=u("Ioff_A"),
                     imu_bias=u("imu_bias_mps2"), meter_gain_rel=u("dGm_rel") if "dGm_rel" in nb else 0.0)
    cycle = cycle or str(rng.choice(["pulse_coast", "speed_hold", "mixed"]))
    duration = 90.0
    onset = float(rng.uniform(25.0, 45.0)) if fault_kind != "none" else math.inf
    s = size_scale * float(rng.uniform(0.6, 2.0))
    sizes = {"none": 0.0, "HB": 0.2, "HT": 0.1, "HL": 3.0, "HL_grade": 0.01, "HU_gain": 0.08, "HB+HL": 0.2,
             "HT+HB": 0.1}
    one_sided = ("HL", "HL_grade", "HT", "HT+HB", "HB+HL")      # HL and its grade sub-cause increase the opposing force
    size = sizes[fault_kind] * s * (1 if rng.random() < 0.5 or fault_kind in one_sided else -1)
    size2 = {"HB+HL": 3.0 * s, "HT+HB": 0.2 * s}.get(fault_kind, 0.0)
    ht_kind = "delay" if split != "robust" else str(rng.choice(["delay", "lag", "boxcar"]))
    fault = FaultSpec(fault_kind, onset, size, ht_kind, size2)
    outages = ()
    if rng.random() < 0.2:
        t0 = float(rng.uniform(10, 70))
        outages = ((t0, t0 + float(rng.uniform(2, 10))),)
    link = LinkSpec(clock=LocalClock(offset_s=float(rng.uniform(0.5, 3.0)), drift_ppm=float(rng.uniform(-50, 50))),
                    uplink_outages=outages)
    v_lo = float(rng.uniform(4.5, 6.0))
    return EpisodeSpec(seed, split, cycle, duration, v_lo, v_lo + float(rng.uniform(1.5, 3.0)),
                       float(rng.uniform(0.3, 0.6)), draw, fault, link, level)


# ----------------------------------------------------------------------------- 1. plant
@dataclasses.dataclass
class Plant:
    t: np.ndarray
    v: np.ndarray
    a: np.ndarray
    drive: np.ndarray
    torque: np.ndarray          # shaft torque command after slew [N m]
    iq: np.ndarray              # true q current
    w: np.ndarray               # rotor speed [rad/s]
    P: np.ndarray               # inverter-input power
    V: np.ndarray
    I: np.ndarray
    grade: np.ndarray
    x: np.ndarray               # distance [m]


def _true_models(spec: EpisodeSpec):
    d = spec.draw
    veh = dataclasses.replace(SYNTHETIC_VEHICLE, crr=SYNTHETIC_VEHICLE.crr + d.d_crr,
                              cda_m2=SYNTHETIC_VEHICLE.cda_m2 + d.d_cda,
                              mass_kg=SYNTHETIC_VEHICLE.mass_kg * (1 + d.d_meff_rel))
    mot = dataclasses.replace(SYNTHETIC_MOTOR, rs_ohm=SYNTHETIC_MOTOR.rs_ohm + d.d_rs,
                              lambda_Wb=SYNTHETIC_MOTOR.lambda_Wb * (1 + d.d_kt_rel),
                              k_iron_W_per_rad_s15=SYNTHETIC_MOTOR.k_iron_W_per_rad_s15 * (1 + d.d_fe_rel),
                              friction_Nm=SYNTHETIC_MOTOR.friction_Nm + d.d_tf)
    return veh, mot


def simulate_plant(spec: EpisodeSpec, st: Study = Study()) -> Plant:
    veh, mot = _true_models(spec)
    nom = SYNTHETIC_VEHICLE
    pmap = SyntheticPhysicsMap(veh, motor=mot, p_aux_W=0.0)
    f = spec.fault
    rng = np.random.default_rng(spec.seed + 1)
    n = int(round(spec.duration_s * PLANT_HZ)) + 1
    dt = 1.0 / PLANT_HZ
    t = np.arange(n) * dt
    v, a, drive, tq, grade, x = (np.zeros(n) for _ in range(6))
    drive = drive.astype(bool)
    v[0] = 0.5 * (spec.v_lo + spec.v_hi)
    t_eq = lambda vv: motor_torque_for_force(nom, resistive_force(nom, vv))      # the controller knows nominal only
    t_acc = lambda aa: motor_torque_for_force(nom, nom.m_eff(True) * aa)
    pulse, v_set, next_set, prev = True, v[0], 15.0, t_eq(v[0])
    hold_until = 45.0 if spec.cycle == "mixed" else (math.inf if spec.cycle == "speed_hold" else -1.0)
    for k in range(n):
        tk = t[k]
        g_k = spec.draw.grade_rad + (f.size if f.kind == "HL_grade" and tk >= f.onset_s else 0.0)
        extra = (f.size if f.kind == "HL" else f.size2 if f.kind == "HB+HL" else 0.0) if tk >= f.onset_s else 0.0
        if tk < hold_until:                                         # speed hold with set-point changes
            if tk >= next_set:
                v_set = float(rng.uniform(spec.v_lo, spec.v_hi))
                next_set = tk + float(rng.uniform(12.0, 25.0))
            d, cmd = True, max(t_eq(v[k]) + 0.8 * (v_set - v[k]), 0.0)
        else:                                                       # pulse and coast
            if pulse and v[k] >= spec.v_hi:
                pulse = False
            elif not pulse and v[k] <= spec.v_lo:
                pulse = True
            d, cmd = pulse, (t_eq(v[k]) + t_acc(spec.a_pulse)) if pulse else 0.0
        step = st.torque_slew_Nm_s * dt
        tq_k = min(max(cmd, prev - step), prev + step) if d else 0.0
        prev = tq_k if d else 0.0
        drive[k], tq[k], grade[k] = d, tq_k, g_k
        force = tractive_force(veh, tq_k) if d else 0.0
        res = resistive_force(veh, v[k], grade=g_k, wind=-spec.draw.wind_mps) + extra
        a[k] = (force - res) / veh.m_eff(d)
        if k + 1 < n:
            v[k + 1] = max(v[k] + a[k] * dt, 0.0)
            x[k + 1] = x[k] + v[k] * dt
    w = v * veh.gear_ratio / veh.wheel_radius_m
    iq = np.where(drive, (tq + mot.friction_Nm) / mot.kt, 0.0)
    P, V = np.zeros(n), np.full(n, st.v_oc_V)
    d = spec.draw
    for k in np.flatnonzero(drive):
        p = pmap.p_batt(v[k], tq[k], st.v_oc_V, 25.0, "drive") + d.d_p0 + d.d_sw * abs(iq[k])
        vb = 0.5 * (st.v_oc_V + math.sqrt(st.v_oc_V ** 2 - 4.0 * st.r_src_ohm * p))
        P[k] = pmap.p_batt(v[k], tq[k], vb, 25.0, "drive") + d.d_p0 + d.d_sw * abs(iq[k])
        V[k] = 0.5 * (st.v_oc_V + math.sqrt(st.v_oc_V ** 2 - 4.0 * st.r_src_ohm * P[k]))
    return Plant(t, v, a, drive, tq, iq, w, P, V, P / V, grade, x)


# ----------------------------------------------------------------------------- 2. sensors
def _q(x, step):
    return np.round(np.asarray(x) / step) * step


def _meter_view(pl: Plant, f: FaultSpec, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bus voltage and current as the bus meter's converter sees them (HT acts here, after its onset)."""
    V, I = np.interp(times, pl.t, pl.V), np.interp(times, pl.t, pl.I)
    if "HT" not in f.kind:
        return V, I
    on = times >= f.onset_s
    if f.ht_kind == "delay":
        Vd, Id = np.interp(times - f.size, pl.t, pl.V), np.interp(times - f.size, pl.t, pl.I)
    else:
        def filt(x):
            if f.ht_kind == "lag":
                a = min(1.0, 1.0 / (PLANT_HZ * f.size))
                y = np.empty_like(x)
                y[0] = x[0]
                for k in range(1, len(x)):
                    y[k] = y[k - 1] + a * (x[k] - y[k - 1])
                return y
            n = max(1, int(round(f.size * PLANT_HZ)))
            c = np.concatenate([[0.0], np.cumsum(x)])
            idx = np.arange(len(x))
            lo = np.maximum(idx + 1 - n, 0)
            return (c[idx + 1] - c[lo]) / (idx + 1 - lo)
        Vd, Id = np.interp(times, pl.t, filt(pl.V)), np.interp(times, pl.t, filt(pl.I))
    return np.where(on, Vd, V), np.where(on, Id, I)


def sensor_samples(spec: EpisodeSpec, pl: Plant, st: Study = Study()) -> dict[str, dict[str, np.ndarray]]:
    """Source-side samples per channel: true acquisition time 't' plus named values."""
    rng = np.random.default_rng(spec.seed + 2)
    f, d = spec.fault, spec.draw
    nom = SYNTHETIC_VEHICLE
    tc = np.arange(0.0, spec.duration_s, CTRL_PERIOD) + rng.uniform(0.0, 0.0003, int(spec.duration_s / CTRL_PERIOD))
    tc = tc[tc < spec.duration_s]
    V, I = _meter_view(pl, f, tc)
    on = tc >= f.onset_s
    gain = 1.0 + d.meter_gain_rel + (f.size if f.kind == "HU_gain" else 0.0) * on
    bias = (f.size if f.kind == "HB" else f.size2 if f.kind == "HT+HB" else f.size if f.kind == "HB+HL" else 0.0) * on
    ibatt = _q(I * gain + d.ioff_A + bias + rng.normal(0, st.sigma_ibatt_A, len(tc)), 0.01)
    vbus = _q(V + rng.normal(0, st.sigma_vbus_V, len(tc)), 0.01)
    w_meas = _q(np.interp(tc, pl.t, pl.w) + rng.normal(0, st.sigma_v_rotor_mps * nom.gear_ratio / nom.wheel_radius_m,
                                                       len(tc)), 0.05)
    iq = _q(np.interp(tc, pl.t, pl.iq) + rng.normal(0, st.sigma_iq_A, len(tc)), 0.01)
    drive_c = np.interp(tc, pl.t, pl.drive.astype(float)) > 0.5
    w_meas = np.where(drive_c, w_meas, 0.0)                 # freewheel open: rotor speed not reported as vehicle speed
    out = {"motion": {"t": tc, "speed_mech_rad_s": w_meas, "iq_A": iq, "vbus_V": vbus},
           "currents": {"t": tc, "ibatt_A": ibatt}}
    k10 = np.arange(0, len(tc), 10)
    out["energy"] = {"t": tc[k10], "p_batt_W": np.round(vbus[k10] * ibatt[k10])}
    k50 = np.arange(0, len(tc), 2)
    out["cmd"] = {"t": tc[k50], "accepted_Nm": _q(np.interp(tc[k50], pl.t, pl.torque), 0.002),
                  "coast": (~drive_c[k50]).astype(float)}
    out["validity"] = {"t": tc[k10], "ibatt_stale": np.zeros(len(k10))}
    # telemetry-unit sensors (sampled on its own schedule, here on the controller time base plus jitter)
    ti = np.arange(0.0, spec.duration_s, 1.0 / st.imu_hz) + 0.0037
    ti = ti[ti < spec.duration_s]
    ax = np.interp(ti, pl.t, pl.a) + G * np.sin(np.interp(ti, pl.t, pl.grade)) + d.imu_bias
    out["imu"] = {"t": ti, "ax": ax + rng.normal(0, st.sigma_imu_mps2, len(ti)), "gz": rng.normal(0, 0.005, len(ti))}
    tw = np.arange(st.wheel_window_s, spec.duration_s, st.wheel_window_s)
    edges = np.floor(np.interp(tw, pl.t, pl.x) * st.wheel_ppr / st.wheel_circ_m)
    counts = np.diff(np.concatenate([[0.0], edges]))
    out["wheel"] = {"t": tw, "counts": counts, "window_ms": np.full(len(tw), 1000.0 * st.wheel_window_s)}
    tg = np.arange(0.05, spec.duration_s, 0.1)
    out["gnss"] = {"t": tg, "speed": np.interp(tg, pl.t, pl.v) + rng.normal(0, 0.05, len(tg))}
    return out


# ----------------------------------------------------------------------------- 3. transport
CONTROLLER_CHANNELS = ("motion", "currents", "energy", "cmd", "validity")


def transport(spec: EpisodeSpec, samples: dict) -> dict[str, dict[str, np.ndarray]]:
    """Receipt-stamped records per channel, in receipt order, as the telemetry unit logs them.

    Controller frames carry a per-message 8-bit sequence counter and no source time; they can be lost
    in bursts, duplicated or swapped with a neighbour. Telemetry-unit sensors are stamped at acquisition
    in the unit's own clock. 't_true' (the true acquisition time) is kept for scoring only."""
    rng = np.random.default_rng(spec.seed + 3)
    L = spec.link
    out = {}
    for ch, s in samples.items():
        n = len(s["t"])
        seq = np.arange(n) % 256
        if ch in CONTROLLER_CHANNELS:
            t_rx = s["t"] + rng.uniform(0, 0.0003, n) + 0.00025 + rng.uniform(0, 0.0005, n)
            keep = np.ones(n, bool)
            bad = False
            for i in range(n):
                bad = (rng.random() < L.can_loss_p_gb) if not bad else (rng.random() >= L.can_loss_p_bg)
                if bad and rng.random() < L.can_loss_bad:
                    keep[i] = False
            idx = list(np.flatnonzero(keep))
            for j in range(len(idx) - 1):                      # adjacent swaps
                if rng.random() < L.can_reorder:
                    idx[j], idx[j + 1] = idx[j + 1], idx[j]
            dup = [i for i in idx if rng.random() < L.can_dup]
            idx = sorted(idx + dup, key=lambda i: idx.index(i)) if dup else idx
            idx = np.array(idx, int)
            t_rx = t_rx[idx]
            if len(t_rx) > 1:                                   # a swap or duplicate is received after its neighbour
                t_rx = np.maximum.accumulate(t_rx + 1e-6 * np.arange(len(t_rx)))
        else:
            idx = np.arange(n)
            t_rx = s["t"] + 0.0001
        rec = {k: np.asarray(v)[idx] for k, v in s.items() if k != "t"}
        rec["t_true"] = s["t"][idx]
        rec["t_rx_true"] = t_rx
        rec["t_rx"] = np.array([L.clock.local(x) for x in t_rx])
        rec["seq"] = seq[idx]
        out[ch] = rec
    return out


# ----------------------------------------------------------------------------- 4. vehicle log and summary
SUMMARY_PERIOD = 0.5


def summaries(spec: EpisodeSpec, log: dict, st: Study = Study()) -> list[dict]:
    """The live 2 Hz summary, built as host/telematics/node.py builds sem.telemetry.v2: latest values,
    the mean of the battery-power frames since the previous message, and the latest wheel window."""
    out = []
    L = spec.link
    m, e, c, w, g = (log[k] for k in ("motion", "energy", "cmd", "wheel", "gnss"))
    last_e = 0
    up_seq = 0
    backlog: list = []
    for tt in np.arange(SUMMARY_PERIOD, spec.duration_s, SUMMARY_PERIOD):
        i = np.searchsorted(m["t_rx_true"], tt, side="right") - 1
        j = np.searchsorted(e["t_rx_true"], tt, side="right")
        ic = np.searchsorted(c["t_rx_true"], tt, side="right") - 1
        iw = np.searchsorted(w["t_rx_true"], tt, side="right") - 1
        ig = np.searchsorted(g["t_rx_true"], tt, side="right") - 1
        p_mean = float(np.mean(e["p_batt_W"][last_e:j])) if j > last_e else None
        last_e = j
        wheel = (float(w["counts"][iw]) * st.wheel_circ_m / (st.wheel_ppr * st.wheel_window_s)) if iw >= 0 else None
        msg = {"schema": "sem.telemetry.v2", "seq": up_seq, "t_local_ms": int(round(L.clock.local(tt) * 1000)),
               "ctrl": {"speed_mech_rad_s": float(m["speed_mech_rad_s"][i]) if i >= 0 else None,
                        "iq_A": float(m["iq_A"][i]) if i >= 0 else None,
                        "vbus_V": float(m["vbus_V"][i]) if i >= 0 else None, "p_batt_W_mean": p_mean,
                        "accepted_Nm": float(c["accepted_Nm"][ic]) if ic >= 0 else None,
                        "coast": bool(c["coast"][ic]) if ic >= 0 else None},
               "wheel": {"speed_mps": {"wheel_drive": wheel}},
               "gnss": {"speed_mps": float(g["speed"][ig]) if ig >= 0 else None}, "replayed": False}
        up_seq += 1
        down = any(a <= tt < b for a, b in L.uplink_outages)
        if down:
            backlog.append(msg)
            backlog = backlog[-30:]                          # node.py: 30-message backlog, oldest dropped
            continue
        for old in backlog:
            old = dict(old, replayed=True)
            out.append((tt + L.uplink_latency_s, old))
        backlog = []
        out.append((tt + L.uplink_latency_s, msg))
    return [{"t_arrive_true": ta, "bytes": len(json.dumps(msg)), **msg} for ta, msg in out]


@dataclasses.dataclass
class Episode:
    spec: EpisodeSpec
    plant: Plant
    log: dict
    summaries: list


def run_vehicle(spec: EpisodeSpec, st: Study = Study()) -> Episode:
    pl = simulate_plant(spec, st)
    log = transport(spec, sensor_samples(spec, pl, st))
    return Episode(spec, pl, log, summaries(spec, log, st))


# ----------------------------------------------------------------------------- 5. pit access
@dataclasses.dataclass(frozen=True)
class Request:
    kind: str                      # "buffer" | "capture" | "clockmeta"
    channels: tuple = ()
    t0_local: float = 0.0          # buffer: window start (telemetry-unit clock)
    t1_local: float = 0.0          # buffer: window end
    duration_s: float = 0.0        # capture: length of the future window
    decimation: int = 1            # keep every n-th record of each channel


REQUEST_BYTES = 32                 # request message, pit to vehicle: research/recorder wire format v1.0
CHUNK_BYTES = 512                  # response chunk size of the recorder (max_chunk_bytes)
CHUNK_OVERHEAD_BYTES = 28          # 24-byte chunk header + CRC-32, research/recorder wire format v1.0
FLASH_READ_Bps = 1.0e6             # [A]
LOG_DEPTH_S = 600.0                # retained depth of the local log per channel [A]; 8 MB holds about 20 min


@dataclasses.dataclass
class Response:
    request: Request
    t_issue_true: float
    t_arrive_true: float
    records: dict                  # channel -> dict of arrays, without the scoring-only fields
    status: str                    # complete | partial (part overwritten) | empty
    bytes_down: int
    bytes_up: int


class Access:
    """The pit's only view of an episode. Time advances monotonically; nothing from the future leaks."""

    def __init__(self, ep: Episode):
        self._ep = ep
        self._now = 0.0
        self._pending: list[Response] = []
        self._sum_i = 0
        self.ledger = {"bytes_down": 0, "bytes_up": 0, "requests": 0, "summary_bytes": 0}

    @property
    def now_true(self) -> float:
        return self._now

    def now_local(self) -> float:
        return self._ep.spec.link.clock.local(self._now)

    def advance(self, t_true: float) -> tuple[list[dict], list[Response]]:
        """Move the pit clock to t_true; return the summaries and responses that arrived meanwhile."""
        if t_true < self._now:
            raise ValueError("time runs forward only")
        self._now = t_true
        new = []
        S = self._ep.summaries
        while self._sum_i < len(S) and S[self._sum_i]["t_arrive_true"] <= t_true:
            m = {k: v for k, v in S[self._sum_i].items() if k != "t_arrive_true"}
            self.ledger["summary_bytes"] += m["bytes"]
            new.append(m)
            self._sum_i += 1
        done = [r for r in self._pending if r.t_arrive_true <= t_true]
        self._pending = [r for r in self._pending if r.t_arrive_true > t_true]
        return new, sorted(done, key=lambda r: r.t_arrive_true)

    def request(self, rq: Request) -> float:
        """Issue a request now; returns its expected arrival (true time). The records are fixed when the
        request reaches the vehicle: only what the vehicle had logged by then, within the retained depth."""
        ep, L = self._ep, self._ep.spec.link
        t_vehicle = self._now + L.rtt_s / 2
        clock = L.clock
        recs, n_bytes, status = {}, 0, "complete"
        if rq.kind == "clockmeta":
            recs = {"clockmeta": {"rx_jitter_s": self._rx_jitter(t_vehicle), "clock_drift_ppm_bound": 50.0,
                                  "t_local": clock.local(t_vehicle)}}
            n_bytes, t_ready = 96, t_vehicle
        else:
            if rq.kind == "buffer":
                lo_true, hi_true = clock.true(rq.t0_local), min(clock.true(rq.t1_local), t_vehicle)
                if lo_true < t_vehicle - LOG_DEPTH_S:
                    status, lo_true = "partial", t_vehicle - LOG_DEPTH_S
                t_ready = t_vehicle
            elif rq.kind == "capture":
                lo_true, hi_true = t_vehicle, min(t_vehicle + rq.duration_s, ep.spec.duration_s)
                t_ready = hi_true
            else:
                raise ValueError(rq.kind)
            for ch in rq.channels:
                L_ch = ep.log[ch]
                sel = np.flatnonzero((L_ch["t_rx_true"] >= lo_true) & (L_ch["t_rx_true"] <= hi_true))[::max(1, rq.decimation)]
                recs[ch] = {k: v[sel] for k, v in L_ch.items() if k not in ("t_true", "t_rx_true")}
                n_bytes += len(sel) * REC_BYTES[ch]
            if not any(len(r["t_rx"]) for r in recs.values()):
                status = "empty"
            n_bytes += CHUNK_OVERHEAD_BYTES * max(1, math.ceil(n_bytes / (CHUNK_BYTES - CHUNK_OVERHEAD_BYTES)))
        t_arrive = t_ready + n_bytes / FLASH_READ_Bps + n_bytes / L.uplink_Bps + L.rtt_s / 2
        r = Response(rq, self._now, t_arrive, recs, status, n_bytes, REQUEST_BYTES)
        self._pending.append(r)
        self.ledger["bytes_down"] += n_bytes
        self.ledger["bytes_up"] += REQUEST_BYTES
        self.ledger["requests"] += 1
        return t_arrive

    def _rx_jitter(self, t_vehicle: float) -> float:
        """Receipt-interval jitter of the controller frames over the last 10 s, as the unit can measure it."""
        m = self._ep.log["currents"]
        sel = (m["t_rx_true"] <= t_vehicle) & (m["t_rx_true"] >= t_vehicle - 10.0)
        d = np.diff(m["t_rx"][sel])
        consecutive = np.diff(m["seq"][sel]) % 256 == 1          # a lost frame is a gap, not jitter
        d = d[consecutive]
        return float(np.max(np.abs(d - CTRL_PERIOD))) if len(d) > 2 else math.nan
