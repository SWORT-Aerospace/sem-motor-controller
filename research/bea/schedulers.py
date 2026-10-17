"""Evidence-acquisition schedulers A to F (research/PROTOCOL.md section 7), on one finite action set.

Every scheduler sees only the View of research/bea/episode.py and uses the same candidate actions:

  edge      2 s of full-rate controller frames around a power edge seen in the summary (tests HT)
  coast     a coast segment of controller frames at 1/10 rate plus its wheel counts (tests HB, HL)
  steady    a steady-driving segment of controller frames at 1/10 rate (tests HB, HL)
  imu       IMU records plus 1/10-rate frames over a segment (grade against drag; only with an IMU)
  capture   the next 6 s of full-rate frames and wheel counts (when the past holds no useful segment)
  clockmeta clock and receipt-path metadata (bounds the timing uncertainty)

A: fixed low rate      the summary only; decides a fixed time after detection
B: fixed high rate     every channel at full rate, continuously
C: event capture       on detection, the last 5 s and the next 20 s of every channel at full rate
D: random bursts       random candidates at random times, total bytes matched to F in the pilot
E: information gain    the candidate with the largest expected information gain per byte
F: ambiguity-directed  the cheapest candidate that separates a pair of hypotheses still open (or tests
                       one the evidence has not been able to test); stops when nothing affordable helps

Predicted separations are noise-free distances (research/bea/identifiability.py) computed on a proxy of
the candidate window rebuilt from the summary; they guide the choice and are not a guarantee.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

import numpy as np

from research.bea.diagnosis import FAULT_PARAM, NOMINAL_SIZE, NOMINAL_SIZE_HT, _complete, calibrate_blocks
from research.bea.episode import FRAME_CHANNELS, Segment, View, _estimate_bytes, frame_rels
from research.bea.harness import Request
from research.bea.identifiability import is_collinear, separation, truth_residual
from research.bea.relations import TIMING, Study, build_window, whiten

ALL_CHANNELS = ("motion", "currents", "cmd", "wheel")
LATENCY_WEIGHT_B_PER_S = 2000.0      # F and E: one second of latency costs as much as this many bytes
AUDIT_PERIOD_S = 15.0
TESTED_VALID_S = 30.0               # a hypothesis a fetched window tested stays tested this long
AUDIT_LOOKBACK_S = 60.0             # audits may fetch any window of the last minute (the log keeps 600 s)
AUDIT_MAX_ACTIONS = 2               # an audit may fetch one window for each untested hypothesis, at most this many
HYPS = ("HB", "HT", "HL")


@dataclasses.dataclass(frozen=True)
class Candidate:
    kind: str
    requests: tuple
    window: tuple
    rels: dict
    bytes: int
    latency_s: float


def _summary_arrays(view: View, t0: float, t1: float):
    rows = [m for m in view.summaries if t0 <= m["t_local_ms"] / 1000.0 <= t1 and m["ctrl"]["coast"] is not None
            and m["ctrl"]["p_batt_W_mean"] is not None]
    rows = sorted({m["seq"]: m for m in rows}.values(), key=lambda m: m["seq"])
    if len(rows) < 4:
        return None
    t = np.array([m["t_local_ms"] / 1000.0 for m in rows])
    coast = np.array([bool(m["ctrl"]["coast"]) for m in rows])
    p = np.array([float(m["ctrl"]["p_batt_W_mean"]) for m in rows])
    return rows, t, coast, p


def _runs(mask: np.ndarray, t: np.ndarray, min_len: float):
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            if t[j] - t[i] >= min_len:
                out.append((t[i], t[j]))
            i = j + 1
        else:
            i += 1
    return out


def _buffer(channels, a, b, decimation=1) -> Request:
    return Request("buffer", tuple(channels), a, b, 0.0, decimation)


def candidates(view: View, since: float, rtt_s: float = 0.6, uplink_Bps: float = 20000.0) -> list[Candidate]:
    """The finite action set at this moment, built from the summary history since `since`."""
    out: list[Candidate] = []
    arr = _summary_arrays(view, since, view.now_local)
    if arr is not None:
        rows, t, coast, p = arr
        edges = [i for i in range(1, len(t)) if coast[i] != coast[i - 1] or abs(p[i] - p[i - 1]) > 40.0]
        for i in edges[-3:]:                                           # the most recent edges
            te = t[i] - 0.25
            out.append(_cand("edge", (_buffer(FRAME_CHANNELS, te - 1.0, te + 1.0),), (te - 1.0, te + 1.0),
                             {"R1": 100.0, "R3": 100.0}, rtt_s, uplink_Bps))
        for a, b in _runs(coast, t, 2.0)[-2:]:
            a, b = a + 0.5, min(b, a + 8.5)
            out.append(_cand("coast", (_buffer(FRAME_CHANNELS, a, b, 10), _buffer(("wheel",), a, b)), (a, b),
                             {"R3": 10.0, "R4": 10.0}, rtt_s, uplink_Bps))
        steady = ~coast & np.concatenate([[False], np.abs(np.diff(p)) < 5.0])
        for a, b in _runs(steady, t, 3.0)[-2:]:
            b = min(b, a + 8.0)
            out.append(_cand("steady", (_buffer(FRAME_CHANNELS, a, b, 10),), (a, b), {"R1": 10.0, "R2": 10.0},
                             rtt_s, uplink_Bps))
        if view.imu_available:
            segs = _runs(np.ones(len(t), bool), t, 4.0)
            if segs:
                a, b = segs[-1][1] - 8.0, segs[-1][1]
                out.append(_cand("imu", (_buffer(("imu",), a, b), _buffer(FRAME_CHANNELS, a, b, 10)), (a, b),
                                 {"R5": 10.0}, rtt_s, uplink_Bps))
    out.append(_cand("capture", (Request("capture", ALL_CHANNELS, 0.0, 0.0, 6.0, 1),),
                     (view.now_local, view.now_local + 6.0), {"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0},
                     rtt_s, uplink_Bps, extra_latency=6.0))
    if view.timing_s > TIMING["known"]:
        out.append(Candidate("clockmeta", (Request("clockmeta"),), (view.now_local, view.now_local), {}, 160, rtt_s))
    return out


def _cand(kind, reqs, window, rels, rtt_s, uplink_Bps, extra_latency=0.0) -> Candidate:
    b = sum(_estimate_bytes(r) for r in reqs)
    return Candidate(kind, reqs, window, rels, b, rtt_s + b / uplink_Bps + extra_latency)


def _fetched(view: View, c: Candidate) -> bool:
    """True if a candidate's window was already requested (no repeats)."""
    if c.kind == "clockmeta":
        return view.timing_s <= TIMING["known"] or any(rq.kind == "clockmeta" for _, rq in view.requested)
    for _, rq in view.requested:
        if rq.kind == "buffer" and c.requests[0].kind == "buffer" and rq.channels == c.requests[0].channels:
            ov = min(rq.t1_local, c.window[1]) - max(rq.t0_local, c.window[0])
            if ov > 0.5 * (c.window[1] - c.window[0]):
                return True
        if rq.kind == "capture" and c.kind == "capture":
            return True
    return False


# ----------------------------------------------------------------------------- prediction
def proxy_signals(view: View, c: Candidate, st: Study):
    """The candidate window rebuilt from the summary at the candidate's rate (upsampled snapshots)."""
    a, b = c.window
    if c.kind == "capture":                      # the future is unknown: assume the last 6 s repeat
        a, b = view.now_local - 6.0, view.now_local
    arr = _summary_arrays(view, a - 1.0, b + 1.0)
    if arr is None:
        return None
    rows, ts, coast, p = arr
    hz = max(c.rels.values()) if c.rels else 10.0
    t = np.arange(a, b, 1.0 / hz)
    if len(t) < 5:
        return None
    g = lambda k: np.interp(t, ts, [float(m["ctrl"][k] or 0.0) for m in rows])
    k = np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 1)
    # Between two snapshots the true edge is unknown; ramping it in with the interpolated current keeps the
    # proxy free of a step that real (slewed) records would not have.
    iq_i = g("iq_A")
    drive = ~coast[k] | (np.abs(iq_i) > 0.1)
    wv = [m["wheel"]["speed_mps"]["wheel_drive"] for m in rows]
    wt = np.arange(a, b, st.wheel_window_s)
    wheel_v = np.interp(wt, ts, [x if x is not None else 0.0 for x in wv])
    V = g("vbus_V")
    sig = _complete(t, hz, drive, iq_i, g("speed_mech_rad_s"), V, np.zeros(len(t)), np.zeros(len(t)),
                    wt, wheel_v, None, st)
    sig.predicted = True
    sig.P, sig.I = sig.P_model.copy(), sig.P_model / np.maximum(V, 1.0)
    if "R5" in c.rels:
        sig.f_imu = np.gradient(sig.v, 1.0 / hz)
    return sig


def size_of(view: View, h: str) -> float:
    """Size to predict with: the current estimate under h when there is one, else the reference size."""
    nominal = NOMINAL_SIZE.get(h, NOMINAL_SIZE_HT)
    cur = view.current
    if cur is not None and isinstance(cur.estimates.get(h), dict):
        e = cur.estimates[h]
        v = abs(e.get("delta_s", 0.0)) if h == "HT" else abs(e.get(FAULT_PARAM.get(h, ""), 0.0))
        return max(v, 0.5 * nominal)
    return nominal


def predicted_pairs(view: View, c: Candidate, pairs: list, st: Study, level: str, timing_s: float) -> dict:
    """Noise-free separation in both directions for each pair, on the candidate's proxy window."""
    if c.kind == "clockmeta":
        return {}
    sig = proxy_signals(view, c, st)
    if sig is None:
        return {}
    W = whiten(calibrate_blocks(build_window(sig, st, c.rels), view.engine, "frames"), view.engine.noise_scale)
    if W.n == 0:
        return {}
    out = {}
    for h, g in pairs:
        d1 = separation(W, h, size_of(view, h), g, level) if np.any(truth_residual(W, h, size_of(view, h))) else 0.0
        if g == "H0":                                 # detectability: one direction
            out[(h, g)] = d1
            continue
        d2 = separation(W, g, size_of(view, g), h, level) if np.any(truth_residual(W, g, size_of(view, g))) else 0.0
        out[(h, g)] = min(d1, d2)
    return out


def open_hypotheses(view: View) -> tuple:
    """Hypotheses the evidence has not excluded. Before detection: those the monitor cannot test.
    After detection: the retained set of the current decision, or every fault if it has none."""
    if view.detected_at is None:
        m = view.monitor
        power = m.estimates.get("_power", {}) if m is not None else {}
        recent = {h for h, t in view.tested.items() if view.now_local - t < TESTED_VALID_S}
        return tuple(h for h in HYPS if power.get(h, 0.0) < 4.0 and h not in recent)
    cur = view.current
    if cur is None or cur.outcome in ("insufficient", "consistent"):
        return HYPS
    if cur.outcome == "no_fit":
        return HYPS
    return tuple(h for h in cur.hypotheses if h in HYPS) or HYPS


# ----------------------------------------------------------------------------- schedulers
class FixedLow:
    name = "A_fixed_low"

    def __init__(self, rc):
        self.rc = rc

    def step(self, view: View):
        if view.detected_at is not None and view.now_local >= view.detected_at + self.rc.decide_after_s:
            return "stop"
        return None


class FixedHigh:
    name = "B_fixed_high"

    def __init__(self, rc, period_s: float = 5.0):
        self.rc, self.period = rc, period_s
        self.next_t = None

    def reset(self):
        self.next_t = None

    def step(self, view: View):
        out = []
        if self.next_t is None:
            self.next_t = view.now_local + self.period
            out.append(Request("clockmeta"))
        if view.now_local >= self.next_t:
            out.append(_buffer(ALL_CHANNELS + (("imu",) if view.imu_available else ()), self.next_t - self.period,
                               self.next_t))
            self.next_t += self.period
        if view.detected_at is not None and view.now_local >= view.detected_at + self.rc.decide_after_s:
            return "stop"
        return out


class EventCapture:
    name = "C_event_capture"

    def __init__(self, rc):
        self.rc = rc
        self.sent = False

    def reset(self):
        self.sent = False

    def step(self, view: View):
        if view.detected_at is None:
            return None
        if not self.sent:
            self.sent = True
            ch = ALL_CHANNELS + (("imu",) if view.imu_available else ())
            return [Request("clockmeta"), _buffer(ch, view.detected_at - 5.0, view.now_local),
                    Request("capture", ch, 0.0, 0.0, 20.0, 1)]
        return "stop" if view.pending == 0 else None


class RandomBursts:
    name = "D_random"

    def __init__(self, rc, budget_bytes: int, seed: int = 0, rate_per_s: float = 0.1):
        self.rc, self.budget, self.seed, self.rate = rc, budget_bytes, seed, rate_per_s
        self.rng = None

    def reset(self):
        self.rng = None

    def step(self, view: View):
        if self.rng is None:
            self.rng = np.random.default_rng(self.seed + int(view.now_local * 1000) % 100000)
        if view.detected_at is not None and view.now_local >= view.detected_at + self.rc.decide_after_s:
            return "stop"
        if self.rng.random() > self.rate * 0.5:
            return None
        cands = [c for c in candidates(view, view.now_local - 30.0) if view.bytes_used + c.bytes <= self.budget]
        if not cands:
            return None
        c = cands[int(self.rng.integers(len(cands)))]
        return list(c.requests)


class _Directed:
    """Shared machinery of E and F: audits before detection, choice after detection."""

    def __init__(self, rc, st: Study = Study(), audit_budget_frac: float = 0.3):
        self.rc, self.st, self.audit_frac = rc, st, audit_budget_frac
        self.next_audit = None
        self.stopped = False

    def reset(self):
        self.next_audit, self.stopped = None, False

    def open_set(self, view: View) -> tuple:
        return open_hypotheses(view)

    def step(self, view: View):
        if self.stopped:
            return "stop" if view.pending == 0 else None
        if view.pending:
            return None
        if view.detected_at is None:
            if self.next_audit is None:
                self.next_audit = view.now_local + AUDIT_PERIOD_S
            if view.now_local < self.next_audit or view.bytes_used > self.audit_frac * self.rc.byte_budget:
                return None
            self.next_audit = view.now_local + AUDIT_PERIOD_S
            untested = self.open_set(view)
            if not untested:
                return None
            pairs = [(h, "H0") for h in untested]
            since = view.now_local - AUDIT_LOOKBACK_S
        else:
            hyps = self.open_set(view)
            if len(hyps) <= 1:                                   # one cause left: nothing to separate
                self.stopped = True
                return "stop"
            pairs = [(h, g) for i, h in enumerate(hyps) for g in hyps[i + 1:]] or [(h, "H0") for h in hyps]
            since = view.detected_at
        cands = [c for c in candidates(view, since) if not _fetched(view, c)
                 and view.bytes_used + c.bytes <= self.rc.byte_budget]
        if view.detected_at is None:
            return self.audit(view, cands, pairs)
        choice = self.choose(view, cands, pairs)
        if choice is None:
            if view.detected_at is not None:
                if view.now_local >= view.detected_at + self.rc.deadline_s - 6.0:
                    self.stopped = True
                    return "stop"
            return None                                          # wait for an informative condition
        return list(choice.requests)


    def audit(self, view: View, cands: list, pairs: list):
        """Before detection: one choice per untested hypothesis, up to AUDIT_MAX_ACTIONS. Only windows
        later than the last one that tested the hypothesis are considered: an audit asks whether a
        fault is present now, and an earlier window cannot show a fault that began after it."""
        out, spent = [], 0
        for pair in pairs:
            after = view.tested.get(pair[0], -math.inf)
            c = self.choose(view, [c for c in cands if c not in out and c.window[0] >= after], [pair])
            if c is not None and view.bytes_used + spent + c.bytes <= self.audit_frac * self.rc.byte_budget:
                out.append(c)
                spent += c.bytes
            if len(out) >= AUDIT_MAX_ACTIONS:
                break
        return [rq for c in out for rq in c.requests] or None


class InformationGain(_Directed):
    name = "E_info_gain"

    def choose(self, view, cands, pairs):
        best, best_v = None, 0.0
        w = 1.0 / max(1, len(pairs))
        for c in sorted(cands, key=lambda c: -c.window[1]):     # ties go to the most recent window
            if c.kind == "clockmeta":
                v = w * 0.5 if any("HT" in p for p in pairs) else 0.0
            else:
                pred = predicted_pairs(view, c, pairs, self.st, self.rc.engine.level, view.timing_s)
                v = sum(w * (1.0 - math.exp(-d * d / 8.0)) for d in pred.values())
            v /= (c.bytes + LATENCY_WEIGHT_B_PER_S * c.latency_s)
            if v > best_v:
                best, best_v = c, v
        return best if best_v > 1e-7 else None


class AmbiguityDirected(_Directed):
    name = "F_ambiguity"

    def choose(self, view, cands, pairs):
        best, best_v = None, 0.0
        for c in sorted(cands, key=lambda c: (c.bytes, -c.window[1])):   # ties: cheapest, then most recent
            if c.kind == "clockmeta":
                # cheap: worth it when a timing hypothesis is open and the timing bound is the reason
                n = 1 if any("HT" in p for p in pairs) else 0
            else:
                pred = predicted_pairs(view, c, pairs, self.st, self.rc.engine.level, view.timing_s)
                n = sum(1 for d in pred.values() if d >= 4.0)
            v = n / (c.bytes + LATENCY_WEIGHT_B_PER_S * c.latency_s)
            if v > best_v:
                best, best_v = c, v
        return best


class AmbiguityDirectedNoAmbiguity(AmbiguityDirected):
    """Ablation of F: the same actions and costs, without the engine's relationship and ambiguity
    information. Every fault hypothesis counts as open at every step, so the scheduler neither knows
    which pairs are already separated nor stops when one cause remains."""
    name = "F_noamb"

    def open_set(self, view: View) -> tuple:
        return HYPS
