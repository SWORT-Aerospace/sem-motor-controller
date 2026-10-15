"""CSIA vehicle adapter - SHADOW MODE.

Wraps the pinned CSIA TrustCore (third_party/csia-trust-layer.lock) with
vehicle-specific relationships. It observes and reports; it never commands.

Separation of concerns (each reported independently, never folded into trust):
  freshness      - did a NEW sample arrive within its window (local receive time)
  evidence       - which relationships were gated in this tick
  observability  - can a disagreement be attributed (observable) or only
                   detected (ambiguous) or not even detected (unobservable)
  trust          - CSIA Beta-belief, which the core HOLDS when evidence is
                   absent; `trust_current` says whether it was updated recently
  monitor health - adapter's own timing/numerics/pin integrity

Rules followed:
  * a derived quantity is never a separate witness: wheel dv/dt is part of the
    wheel node, torque from iq is part of the phase-current node;
  * a reconstructed third phase current is never KCL evidence (kcl_available);
  * the fused output is never fed back as evidence for its inputs;
  * a disagreement with no corroboration is reported AMBIGUOUS, not blamed.
"""
from __future__ import annotations

import dataclasses
import enum
import math
import os
import pathlib
import sys
import time
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[2]
G = 9.80665


def _import_csia():
    path = os.environ.get("SEMMC_CSIA_PATH", str(ROOT / ".deps" / "csia-trust-layer"))
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import csia  # noqa: F401
        from csia.trust_engine.engine import EngineConfig, TrustCore
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise ImportError("pinned CSIA core not found: run `python3 tools/fetch_csia.py` "
                          "(or set SEMMC_CSIA_PATH)") from exc
    import csia
    return TrustCore, EngineConfig, csia.__version__, path


class Explain(enum.IntEnum):
    OK_CONSISTENT = 0
    NO_EVIDENCE = 1
    STALE_INPUTS = 2
    REGIME_GATED = 3
    DISAGREE_AMBIGUOUS = 4
    SUSPECT_ROTOR_SPEED = 5
    SUSPECT_WHEEL_DRIVE = 6
    SUSPECT_WHEEL_L = 7
    SUSPECT_WHEEL_R = 8
    SUSPECT_GNSS = 9
    SUSPECT_IMU = 10
    SUSPECT_PHASE_CURRENT = 11
    SUSPECT_DC_METER = 12
    MONITOR_UNHEALTHY = 15


SUSPECT_CODE = {"rotor": Explain.SUSPECT_ROTOR_SPEED, "wheel_drive": Explain.SUSPECT_WHEEL_DRIVE,
                "wheel_l": Explain.SUSPECT_WHEEL_L, "wheel_r": Explain.SUSPECT_WHEEL_R, "gnss": Explain.SUSPECT_GNSS,
                "imu": Explain.SUSPECT_IMU, "phase_current": Explain.SUSPECT_PHASE_CURRENT,
                "dc_meter": Explain.SUSPECT_DC_METER}
NODES = list(SUSPECT_CODE)
# Auxiliary inputs: nodes that enter a relationship's expectation without
# being endpoints (IMU yaw for E2/E3, rotor speed for E6). A relationship lists
# an auxiliary unless its failure would survive that input being wrong by its
# largest plausible amount. A failure is attributed to an endpoint only if every
# listed auxiliary is corroborated and has not failed recently.
EDGE_BITS = {"E1_rotor_wheeldrive": 0, "E2_wheel_lr_yaw": 1, "E3a_gnss_wheel_l": 2, "E3b_gnss_wheel_r": 3,
             "E4_imu_wheel_l": 4, "E6_power_balance": 5, "E7_gnss_wheeldrive": 6, "P_phase_current": 7}


@dataclasses.dataclass
class Sample:
    value: float
    sigma: float
    src_t: float            # source timestamp, seconds in the source clock domain
    clock: str              # clock-domain identity, e.g. "controller", "imu", "gnss"
    rx_t: float             # LOCAL monotonic receive time [s]
    seq: int
    session: int = 0
    flags: dict = dataclasses.field(default_factory=dict)


class SignalTracker:
    """Freshness per signal: renewed only by a NEW sample (sequence advanced AND
    source time advanced, same session). Re-sent cached samples do not renew."""

    def __init__(self, window_s: float):
        self.window = window_s
        self.last: Optional[Sample] = None
        self.last_new_rx = -math.inf
        self.rejected = 0

    def update(self, s: Sample) -> bool:
        if not math.isfinite(s.value):
            self.rejected += 1
            return False
        p = self.last
        if p is not None and s.session == p.session and s.clock == p.clock:
            dseq = (s.seq - p.seq) & 0xFFFF
            if dseq == 0 or dseq >= 0x8000 or s.src_t <= p.src_t:
                self.rejected += 1
                return False
        self.last = s
        self.last_new_rx = s.rx_t
        return True

    def fresh(self, now: float) -> bool:
        return self.last is not None and (now - self.last_new_rx) <= self.window

    def value(self) -> float:
        return self.last.value if self.last else math.nan

    def sigma(self) -> float:
        return self.last.sigma if self.last else math.inf


@dataclasses.dataclass
class AdapterParams:
    wheel_radius_m: float
    gear_ratio: float
    track_width_m: float = 0.5
    freewheel: bool = True
    kt_Nm_per_A: float = 0.06
    p_aux_W: float = 3.0
    loss_rel: float = 0.08           # power-balance model uncertainty (relative)
    loss_abs_W: float = 4.0
    i_engaged_A: float = 1.0         # |iq| above which the freewheel is assumed engaged
    i_slip_A: float = 12.0           # |iq| above which driven-wheel slip is possible
    gz_max: float = 0.8              # rad/s, max yaw for the L/R relationship
    gz_phys_max: float = 1.0         # rad/s, largest yaw this vehicle can physically reach
    rotor_phys_max: float = 600.0    # rad/s mech, largest plausible rotor speed
    v_min_gnss: float = 1.5
    v_min_wheels: float = 0.8
    gnss_sacc_max: float = 0.5
    gnss_min_sv: int = 6
    lam_fail: float = 9.0            # 3-sigma
    lam_ok: float = 4.0
    trust_hold_s: float = 2.0        # trust not updated for longer than this => not current
    engage_settle_s: float = 0.5     # freewheel re-engagement transient excluded from E1
    corroboration_s: float = 3.0     # a pass this recent (with no failure since) corroborates a node
    accel_window_s: float = 1.0      # least-squares slope window for wheel acceleration
    tick_s: float = 0.1
    windows: dict = dataclasses.field(default_factory=lambda: {
        "rotor": 0.1, "iq_ref": 0.1, "iq": 0.1, "kcl": 0.1, "wheel_l": 0.25, "wheel_r": 0.25, "wheel_drive": 0.25,
        "gnss": 0.3, "imu_ax": 0.05, "imu_gz": 0.05, "p_dc": 0.25, "grade": 1e9})


@dataclasses.dataclass
class AdvisoryState:
    t: float
    trust: dict
    trust_current: dict
    fresh: dict
    evidence: dict             # node -> number of active relationships
    evidence_mask: int
    lambdas: dict              # relationship -> lambda (nan if gated)
    suspects: list
    ambiguous: list
    observability: int         # 0 unknown 1 observable 2 ambiguous 3 unobservable
    explanation: Explain
    monitor_ok: bool
    monitor_notes: list
    aggregate_trust: float
    elapsed_s: float


class VehicleCsiaAdapter:
    MODE_SHADOW = 0

    def __init__(self, params: AdapterParams):
        TrustCore, EngineConfig, ver, path = _import_csia()
        self.csia_version, self.csia_path = ver, path
        self.p = params
        self.core = TrustCore(NODES, EngineConfig())
        self.sig = {k: SignalTracker(w) for k, w in params.windows.items()}
        self.last_evidence_t = {n: -math.inf for n in NODES}
        self.last_tick = None
        self.wheel_l_hist: list[tuple[float, float]] = []
        self.imu_ax_hist: list[tuple[float, float]] = []
        self.rotor_hist: list[tuple[float, float]] = []
        self.last_fail_edge = {n: {} for n in NODES}
        self.engaged_since = math.inf
        self.last_pass_t = {n: -math.inf for n in NODES}
        self.last_fail_t = {n: -math.inf for n in NODES}
        self.mode = self.MODE_SHADOW
        # Ablation switches (host/csia_adapter/evaluation.py). Defaults are the
        # frozen adapter; nothing in the vehicle path changes them.
        self.ablate_gates = False        # True: every relationship eligible whenever its inputs are fresh
        self.residual_design = "calibrated"  # "naive": no yaw/centreline/time-alignment/loss/grade terms
        self.monitor_notes: list[str] = []
        if ver != "0.8.0":
            self.monitor_notes.append(f"CSIA version {ver} != pinned 0.8.0")

    # ---------------------------------------------------------------- inputs
    def ingest(self, name: str, s: Sample) -> bool:
        ok = self.sig[name].update(s)
        if ok and name == "wheel_l":
            self.wheel_l_hist.append((s.rx_t, s.value))
            self.wheel_l_hist = self.wheel_l_hist[-40:]
        if ok and name == "rotor":
            self.rotor_hist.append((s.rx_t, s.value))
            self.rotor_hist = self.rotor_hist[-60:]
        if ok and name == "imu_ax":
            self.imu_ax_hist.append((s.rx_t, s.value))
            self.imu_ax_hist = self.imu_ax_hist[-400:]
        return ok

    # ---------------------------------------------------------------- relationships
    def _rel(self, now: float):
        p, S = self.p, self.sig
        fr = {k: S[k].fresh(now) for k in S}
        val = {k: S[k].value() for k in S}
        sg = {k: S[k].sigma() for k in S}
        k_rot = p.wheel_radius_m / p.gear_ratio
        edges, phys = {}, {}
        iq = val["iq"] if fr["iq"] else math.nan
        engaged_now = (not p.freewheel) or (math.isfinite(iq) and abs(iq) > p.i_engaged_A)
        if engaged_now:
            self.engaged_since = min(self.engaged_since, now)
        else:
            self.engaged_since = math.inf
        engaged = engaged_now and (now - self.engaged_since) >= (p.engage_settle_s if p.freewheel else 0.0)
        slip_possible = math.isfinite(iq) and abs(iq) > p.i_slip_A
        gnss_ok = fr["gnss"] and S["gnss"].last.flags.get("sacc", 9) <= p.gnss_sacc_max and \
            S["gnss"].last.flags.get("num_sv", 0) >= p.gnss_min_sv and val["gnss"] >= p.v_min_gnss
        gz = val["imu_gz"] if fr["imu_gz"] else math.nan

        def lam(r, var):
            return (r * r) / var if var > 0 else math.inf

        def aux_if_needed(node, r, var, max_effect):
            """An auxiliary input is NOT needed for attribution only if the
            residual would still exceed the failure threshold with that input
            wrong by its largest physically plausible amount. Significance is
            never judged from the (possibly faulty) auxiliary value itself."""
            if not math.isfinite(r):
                return (node,)
            return () if abs(r) - max_effect > math.sqrt(p.lam_fail * var) else (node,)

        # E1 rotor <-> driven wheel (only while the freewheel transmits torque)
        g = fr["rotor"] and fr["wheel_drive"] and engaged and val["wheel_drive"] >= p.v_min_wheels
        # Time alignment: wheel speed is an edge count over the window ending at
        # its sample time, so compare with the rotor MEAN over the same window.
        wd = S["wheel_drive"].last
        rot_avg = val["rotor"]
        if wd is not None:
            win = [v for t, v in self.rotor_hist if wd.rx_t - 0.1 - 1e-6 <= t <= wd.rx_t]
            if win:
                rot_avg = sum(win) / len(win)
        r = rot_avg * k_rot - val["wheel_drive"]
        edges["E1_rotor_wheeldrive"] = ("rotor", "wheel_drive", lam(r, (sg["rotor"] * k_rot) ** 2 + sg["wheel_drive"] ** 2), float(g), ())
        # E2 front wheels with yaw-rate correction (cornering is a normal event)
        # Gate on the FASTER wheel: a dead sensor reading zero must not gate out
        # the very relationships that would expose it.
        g = fr["wheel_l"] and fr["wheel_r"] and math.isfinite(gz) and abs(gz) <= p.gz_max and \
            max(val["wheel_l"], val["wheel_r"]) >= p.v_min_wheels
        r = (val["wheel_r"] - val["wheel_l"]) - gz * p.track_width_m if math.isfinite(gz) else math.nan
        var = sg["wheel_l"] ** 2 + sg["wheel_r"] ** 2 + (p.track_width_m * (S["imu_gz"].sigma() if fr["imu_gz"] else 1)) ** 2
        aux = aux_if_needed("imu", r, var, 2 * p.gz_phys_max * p.track_width_m)
        edges["E2_wheel_lr_yaw"] = ("wheel_l", "wheel_r", lam(r, var), float(g), aux)
        # E3 GNSS Doppler <-> each front wheel, corrected to the centreline
        for key, w, sgn in (("E3a_gnss_wheel_l", "wheel_l", +1), ("E3b_gnss_wheel_r", "wheel_r", -1)):
            g = gnss_ok and fr[w] and math.isfinite(gz)
            vc = val[w] + sgn * gz * p.track_width_m / 2 if math.isfinite(gz) else math.nan
            var3 = sg[w] ** 2 + sg["gnss"] ** 2
            aux = aux_if_needed("imu", vc - val["gnss"], var3, p.gz_phys_max * p.track_width_m)
            edges[key] = ("gnss", w, lam(vc - val["gnss"], var3), float(g), aux)
        # E7 GNSS <-> driven wheel, only when slip is not expected
        g = gnss_ok and fr["wheel_drive"] and not slip_possible
        edges["E7_gnss_wheeldrive"] = ("gnss", "wheel_drive", lam(val["wheel_drive"] - val["gnss"],
                                                                  sg["wheel_drive"] ** 2 + sg["gnss"] ** 2), float(g), ())
        # E4 IMU longitudinal specific force <-> front-wheel acceleration + g sin(grade).
        # Wheel acceleration is a least-squares slope over accel_window_s (the
        # wheel node's own derived quantity, not a separate witness), compared
        # with the IMU mean over the same window.
        g4, r4, var4 = False, math.nan, math.inf
        w0 = now - p.accel_window_s
        h = [(t, v) for t, v in self.wheel_l_hist if t >= w0]
        hi = [a for t, a in self.imu_ax_hist if t >= w0]
        v_regime = max(val["wheel_l"] if fr["wheel_l"] else 0.0, val["wheel_r"] if fr["wheel_r"] else 0.0)
        if fr["imu_ax"] and fr["wheel_l"] and fr["grade"] and len(h) >= 8 and len(hi) >= 20 and \
                v_regime >= p.v_min_wheels:
            ts = [t for t, _ in h]
            vs = [v for _, v in h]
            tm = sum(ts) / len(ts)
            vm = sum(vs) / len(vs)
            stt = sum((t - tm) ** 2 for t in ts)
            if stt > 0:
                slope = sum((t - tm) * (v - vm) for t, v in zip(ts, vs)) / stt
                sig_slope = sg["wheel_l"] / math.sqrt(stt)
                a_imu = sum(hi) / len(hi)
                r4 = a_imu - (slope + G * math.sin(val["grade"]))
                var4 = (sg["imu_ax"] ** 2) / len(hi) + sig_slope ** 2 + (G * sg["grade"]) ** 2 + 0.03 ** 2
                g4 = abs(a_imu) < 3.0
        edges["E4_imu_wheel_l"] = ("imu", "wheel_l", lam(r4, var4), float(g4), ())
        # E6 power balance: DC meter vs (torque x speed + modelled losses + aux)
        g6 = fr["p_dc"] and fr["iq"] and fr["rotor"]
        if g6:
            p_mech = p.kt_Nm_per_A * iq * val["rotor"]
            expected = p_mech + p.loss_rel * abs(p_mech) + p.p_aux_W
            var6 = (p.loss_rel * abs(p_mech) + p.loss_abs_W) ** 2 + sg["p_dc"] ** 2
            aux = aux_if_needed("rotor", val["p_dc"] - expected, var6,
                                (1 + p.loss_rel) * p.kt_Nm_per_A * abs(iq) * p.rotor_phys_max)
            edges["E6_power_balance"] = ("dc_meter", "phase_current", lam(val["p_dc"] - expected, var6), 1.0, aux)
        else:
            edges["E6_power_balance"] = ("dc_meter", "phase_current", math.nan, 0.0, ())
        # Phase-current self-consistency: KCL only with THREE measured phases;
        # current tracking only when not saturated/slewing.
        lams = []
        if fr["kcl"] and S["kcl"].last.flags.get("kcl_available", False):
            lams.append(lam(val["kcl"], sg["kcl"] ** 2))
        if fr["iq"] and fr["iq_ref"] and not S["iq_ref"].last.flags.get("saturated_or_slewing", True):
            lams.append(lam(val["iq"] - val["iq_ref"], sg["iq"] ** 2 + 0.3 ** 2))
        phys["phase_current"] = ((sum(lams) / len(lams)) if lams else 0.0, 1.0 if lams else 0.0)
        if self.residual_design == "naive":
            edges, phys = self._naive(edges, phys, fr, val, sg, iq)
        if self.ablate_gates:
            edges = {k: (a, b, l, 1.0 if math.isfinite(l) else 0.0, aux) for k, (a, b, l, g, aux) in edges.items()}
            lams = []
            if fr["kcl"] and S["kcl"].last.flags.get("kcl_available", False):
                lams.append(lam(val["kcl"], sg["kcl"] ** 2))
            if fr["iq"] and fr["iq_ref"]:
                lams.append(lam(val["iq"] - val["iq_ref"], sg["iq"] ** 2 + 0.3 ** 2))
            phys["phase_current"] = ((sum(lams) / len(lams)) if lams else 0.0, 1.0 if lams else 0.0)
        return edges, phys, fr

    def _naive(self, edges, phys, fr, val, sg, iq):
        """Ablation: the same relationships with the textbook residuals of
        baseline B2: instantaneous rotor speed, no yaw or centreline
        correction, no grade term, no loss model. Gates are kept as computed
        (switch them off separately with ablate_gates)."""
        p = self.p
        k_rot = p.wheel_radius_m / p.gear_ratio

        def lam(r, var):
            return (r * r) / var if var > 0 else math.inf
        out = dict(edges)
        a, b, _l, g, _x = edges["E1_rotor_wheeldrive"]
        out["E1_rotor_wheeldrive"] = (a, b, lam(val["rotor"] * k_rot - val["wheel_drive"],
                                                (sg["rotor"] * k_rot) ** 2 + sg["wheel_drive"] ** 2), g, ())
        a, b, _l, g, _x = edges["E2_wheel_lr_yaw"]
        out["E2_wheel_lr_yaw"] = (a, b, lam(val["wheel_r"] - val["wheel_l"], sg["wheel_l"] ** 2 + sg["wheel_r"] ** 2),
                                  g, ())
        for key, w in (("E3a_gnss_wheel_l", "wheel_l"), ("E3b_gnss_wheel_r", "wheel_r")):
            a, b, _l, g, _x = edges[key]
            out[key] = (a, b, lam(val[w] - val["gnss"], sg[w] ** 2 + sg["gnss"] ** 2), g, ())
        a, b, l4, g, _x = edges["E4_imu_wheel_l"]
        if math.isfinite(l4) and fr["grade"]:
            # remove the grade term the calibrated design adds: recompute without it
            w0 = self.last_tick if self.last_tick is not None else 0.0
            h = [(t, v) for t, v in self.wheel_l_hist if t >= w0 - p.accel_window_s + p.tick_s]
            hi = [x for t, x in self.imu_ax_hist if t >= w0 - p.accel_window_s + p.tick_s]
            if len(h) >= 2 and hi:
                slope = (h[-1][1] - h[0][1]) / max(h[-1][0] - h[0][0], 1e-6)
                out["E4_imu_wheel_l"] = (a, b, lam(sum(hi) / len(hi) - slope, sg["imu_ax"] ** 2 + 0.03 ** 2), g, ())
        a, b, _l, g, _x = edges["E6_power_balance"]
        if g > 0:
            out["E6_power_balance"] = (a, b, lam(val["p_dc"] - (p.kt_Nm_per_A * iq * val["rotor"] + p.p_aux_W),
                                                 sg["p_dc"] ** 2 + p.loss_abs_W ** 2), g, ())
        return out, phys

    # ---------------------------------------------------------------- tick
    def tick(self, now: float) -> AdvisoryState:
        t_start = time.perf_counter()
        notes = list(self.monitor_notes)
        if self.last_tick is not None:
            dt = now - self.last_tick
            if not (0.5 * self.p.tick_s <= dt <= 2.0 * self.p.tick_s):
                notes.append(f"tick interval {dt:.3f}s outside [{0.5*self.p.tick_s:.2f},{2*self.p.tick_s:.2f}]")
        self.last_tick = now
        edges, phys, fr = self._rel(now)
        node_inputs = {"rotor": ["rotor"], "wheel_drive": ["wheel_drive"], "wheel_l": ["wheel_l"],
                       "wheel_r": ["wheel_r"], "gnss": ["gnss"], "imu": ["imu_ax", "imu_gz"],
                       "phase_current": ["iq"], "dc_meter": ["p_dc"]}
        fresh = {n: all(fr[s] for s in ins) for n, ins in node_inputs.items()}
        active = {k: e for k, e in edges.items() if e[3] > 0 and math.isfinite(e[2]) and fresh[e[0]] and fresh[e[1]]}
        core_edges = {k: (a, b, min(lam, 1e6), g) for k, (a, b, lam, g, _aux) in active.items()}
        core_phys = {n: (min(l, 1e6), g) for n, (l, g) in phys.items() if g > 0}
        out = self.core.step(core_edges, core_phys, {n: None for n in NODES}, {n: None for n in NODES},
                             {n: fresh[n] for n in NODES})
        evidence = {n: sum(1 for e in active.values() if n in (e[0], e[1])) + (1 if n in core_phys else 0)
                    for n in NODES}
        for n in NODES:
            if evidence[n] > 0 and fresh[n]:
                self.last_evidence_t[n] = now
        trust_current = {n: (now - self.last_evidence_t[n]) <= self.p.trust_hold_s for n in NODES}
        # ---- attribution (never forced) ----
        fail = {k: e for k, e in active.items() if e[2] > self.p.lam_fail}
        passing = {k: e for k, e in active.items() if e[2] <= self.p.lam_ok}
        F = {n: sum(1 for e in fail.values() if n in (e[0], e[1])) for n in NODES}
        Pn_now = {n: sum(1 for e in passing.values() if n in (e[0], e[1])) +
                  (1 if n in core_phys and core_phys[n][0] <= self.p.lam_ok else 0) for n in NODES}
        for n in NODES:
            if Pn_now[n] > 0:
                self.last_pass_t[n] = now
        for k, (a, b, _l, _g, _aux) in fail.items():
            self.last_fail_edge[a][k] = now
            self.last_fail_edge[b][k] = now
        for n, (lam_p, _g) in core_phys.items():
            if lam_p > self.p.lam_fail:
                self.last_fail_edge[n]["phys"] = now

        def corroborated(n, excluding=None):
            """Passing now on another relationship, or passed recently with no
            failure SINCE on any relationship other than the one being judged.
            (Relationships are often regime-exclusive, e.g. E1 only while driving
            and E7 only while not, so same-tick corroboration alone is too strict;
            and the failure under judgement must not discredit its own witness.)"""
            now_pass = sum(1 for kk, e in passing.items() if n in (e[0], e[1]) and kk != excluding) + \
                (1 if n in core_phys and core_phys[n][0] <= self.p.lam_ok else 0)
            if now_pass:
                return True
            other_fail = max((tt for kk, tt in self.last_fail_edge[n].items() if kk != excluding), default=-math.inf)
            return (now - self.last_pass_t[n]) <= self.p.corroboration_s and other_fail < self.last_pass_t[n]

        def recently_failed(n):
            """Any failure within the corroboration window. A sensor that is stuck
            agrees by coincidence now and then; such a node may not vouch, as an
            auxiliary input, for attributing someone else's failure."""
            last = max(self.last_fail_edge[n].values(), default=-math.inf)
            return (now - last) <= self.p.corroboration_s

        Pn = {n: int(corroborated(n)) for n in NODES}
        suspects, ambiguous = [], []
        for n, (lam_p, g) in core_phys.items():
            if lam_p > self.p.lam_fail and n not in suspects:
                suspects.append(n)
        for k, (a, b, lam, g, aux) in fail.items():
            if a in suspects or b in suspects:
                continue
            if any(not corroborated(x) or F[x] > 0 or recently_failed(x) for x in aux):
                ambiguous.append((a, b, k))
                continue
            ca, cb = corroborated(a, k), corroborated(b, k)
            if ca and not cb:
                suspects.append(b)
            elif cb and not ca:
                suspects.append(a)
            elif F[a] >= 2 and F[b] == 1:
                suspects.append(a)
            elif F[b] >= 2 and F[a] == 1:
                suspects.append(b)
            else:
                ambiguous.append((a, b, k))
        mask = 0
        for k in active:
            mask |= 1 << EDGE_BITS[k]
        if "phase_current" in core_phys:
            mask |= 1 << EDGE_BITS["P_phase_current"]
        if suspects:
            obs = 1
        elif ambiguous:
            obs = 2
        elif not active and not core_phys:
            obs = 3
        else:
            obs = 1
        elapsed = time.perf_counter() - t_start
        if elapsed > 0.02:
            notes.append(f"tick took {elapsed*1e3:.1f} ms (> 20 ms budget)")
        trust = {n: out[n]["trust"] for n in NODES}
        if any(not math.isfinite(v) for v in trust.values()):
            notes.append("non-finite trust")
        monitor_ok = not notes
        if not monitor_ok:
            code = Explain.MONITOR_UNHEALTHY
        elif suspects:
            code = SUSPECT_CODE[suspects[0]]
        elif ambiguous:
            code = Explain.DISAGREE_AMBIGUOUS
        elif not any(fresh.values()):
            code = Explain.STALE_INPUTS
        elif not active and not core_phys:
            code = Explain.NO_EVIDENCE
        elif len(active) < 3:
            code = Explain.REGIME_GATED
        else:
            code = Explain.OK_CONSISTENT
        speed_nodes = ["rotor", "wheel_drive", "gnss"]
        agg = min(trust[n] for n in speed_nodes)
        return AdvisoryState(now, trust, trust_current, fresh, evidence, mask,
                             {k: (e[2] if e[3] > 0 else math.nan) for k, e in edges.items()},
                             suspects, ambiguous, obs, code, monitor_ok, notes, agg, elapsed)

    def restriction_permitted(self) -> bool:
        """ADR-0008: shadow mode until the evidence gate in VALIDATION_PLAN.md is met."""
        return False

    def advisory_values(self, st: AdvisoryState) -> dict:
        """Field values for the csia_advisory CAN message (protocol.yaml)."""
        return {"trust": st.aggregate_trust if all(st.trust_current[n] for n in ("rotor", "wheel_drive")) else
                float("nan"),
                "mode": self.mode, "observability": st.observability, "monitor_ok": st.monitor_ok,
                "evidence_fresh": any(st.trust_current.values()), "reserved": 0,
                "evidence_mask": st.evidence_mask & 0xFF, "explanation": int(st.explanation),
                "src_time_ms": int(round(st.t * 1000)) & 0xFFFF}
