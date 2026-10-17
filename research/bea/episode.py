"""Episode runner: one scheduler and one diagnostic engine on one episode, in simulated time.

Loop at the summary period:

  1. advance the pit clock; take the summaries and responses that have arrived (Access enforces that
     nothing arrives early);
  2. run the summary monitor on the last monitor_window_s of summaries; a fault is detected when it
     rejects normal operation on `debounce` consecutive evaluations;
  3. after detection, let the scheduler request records, wait, or stop;
  4. at the stop (or the deadline), make the final decision on all evidence received for the decision
     window, which starts at detection (or with the fetched records that detected the fault); when no
     modelled cause fits the whole window, a change point inside it is tested (decide_final).

Evidence is assembled without double counting: where full-rate records were fetched, they replace the
summary for that time, because both measure the same quantities. Ground truth is not visible here; the
scorer (research/bea/scoring.py) compares the result with the episode's label afterwards.
"""
from __future__ import annotations

import dataclasses
import math
import time
from typing import Optional

import numpy as np

from research.bea.diagnosis import (Diagnosis, EngineConfig, calibrate_blocks, diagnose_blocks, signals_from_frames,
                                    signals_from_summaries)
from research.bea.harness import Access, Episode, Request, SUMMARY_PERIOD
from research.bea.relations import TIMING, Study, build_window

FRAME_CHANNELS = ("motion", "currents", "cmd")
SUMMARY_RELS = {"R1s": 2.0, "R2s": 2.0, "R3": 2.0, "R4": 2.0}


@dataclasses.dataclass(frozen=True)
class RunConfig:
    engine: EngineConfig = EngineConfig()
    monitor_window_s: float = 20.0
    monitor_every_s: float = 1.0
    debounce: int = 2
    decide_after_s: float = 20.0      # fixed-recipe schedulers decide this long after detection
    deadline_s: float = 40.0          # every scheduler decides by detection + deadline_s
    byte_budget: int = 200_000        # hard limit per episode on requested bytes
    imu_available: bool = False       # the IMU is proposed, not built
    default_timing: str = "uncertain" # until clock metadata bounds the receipt path
    double_count: bool = False        # ablation switch: also use the summary where frames cover the same time


@dataclasses.dataclass
class Segment:
    t0: float
    t1: float
    channels: tuple
    decimation: int
    records: dict


@dataclasses.dataclass
class View:
    """Everything a scheduler may use. No labels, no truth."""
    now_local: float
    summaries: list
    segments: list
    pending: int
    detected_at: Optional[float]
    monitor: Optional[Diagnosis]
    current: Optional[Diagnosis]
    timing_s: float
    bytes_used: int
    byte_budget: int
    imu_available: bool
    requested: list
    deadline_local: Optional[float]
    engine: EngineConfig = EngineConfig()
    tested: dict = dataclasses.field(default_factory=dict)   # hypothesis -> end of the latest fetched window that tested it
    window_start: Optional[float] = None     # start of the decision window (detected_at unless fetched records detected)

    def decision_start(self) -> Optional[float]:
        return self.window_start if self.window_start is not None else self.detected_at


def frame_rels(seg: Segment, imu: bool) -> dict:
    hz = 100.0 / max(1, seg.decimation)
    rels = {"R1": hz, "R2": min(10.0, hz), "R3": hz}
    if "wheel" in seg.channels:
        rels["R4"] = 10.0
    if imu and "imu" in seg.channels:
        rels["R5"] = 10.0
    return rels


def evidence_blocks(view: View, t0: float, t1: float, st: Study, double_count: bool = False) -> tuple[list, list]:
    """Blocks for [t0, t1]: fetched frame segments first (highest rate first, no overlaps), the summary
    for the rest. Returns (blocks, description)."""
    covered: list[tuple[float, float]] = []
    blocks, desc = [], []
    for seg in sorted(view.segments, key=lambda s: s.decimation):
        if not all(c in seg.channels for c in FRAME_CHANNELS):
            continue
        a, b = max(seg.t0, t0), min(seg.t1, t1)
        for c0, c1 in covered:                       # trim against what is already covered
            if c0 <= a < c1:
                a = c1
            if c0 < b <= c1:
                b = c0
        if b - a < 1.2:                              # R1 and R3 keep 0.5 s margins at both ends
            continue
        sig = signals_from_frames(seg.records, a, b, st, period=0.01 * max(1, seg.decimation))
        if sig is None:
            continue
        got = calibrate_blocks(build_window(sig, st, frame_rels(seg, view.imu_available)), view.engine, "frames")
        if got:
            blocks += got
            covered.append((a, b))
            desc.append(f"frames {a - t0:.1f} to {b - t0:.1f} s, 1/{seg.decimation}")
    rest = [m for m in view.summaries if t0 <= m["t_local_ms"] / 1000.0 <= t1
            and (double_count or not any(c0 - SUMMARY_PERIOD <= m["t_local_ms"] / 1000.0 <= c1 + SUMMARY_PERIOD
                                         for c0, c1 in covered))]
    sig = signals_from_summaries(rest, st)
    if sig is not None:
        got = calibrate_blocks(build_window(sig, st, SUMMARY_RELS), view.engine, "summary")
        if got:
            blocks += got
            desc.append(f"summary ({len(rest)} messages)")
    return blocks, desc


def decide(view: View, t0: float, t1: float, rc: RunConfig, st: Study) -> Diagnosis:
    blocks, desc = evidence_blocks(view, t0, t1, st, rc.double_count)
    source = "frames" if any(d.startswith("frames") for d in desc) else "summary"
    d = diagnose_blocks(blocks, rc.engine, view.timing_s, (t0, t1), source)
    d.reason += " [" + "; ".join(desc) + "]"
    return d


CHANGE_MIN_AFTER_S = 8.0       # a change point leaves at least this much of the window after it
CHANGE_STEP_S = 2.0            # candidate change points: every 2 s of the window
CHANGE_MAX_CANDIDATES = 16


def decide_final(view: View, t0: float, t1: float, rc: RunConfig, st: Study) -> Diagnosis:
    """The final decision. Every hypothesis has a constant size over the window, so a fault that began
    inside the window can leave no modelled cause fitting. When the whole window gives "no modelled
    cause fits", candidate change points are tried in time order (every 2 s): the first one before
    which normal operation is not rejected and after which a modelled cause fits is reported, with the
    change point in the reason. Otherwise "no fit" stands."""
    d = decide(view, t0, t1, rc, st)
    if d.outcome != "no_fit":
        return d
    cands = [t0 + CHANGE_STEP_S * k for k in range(1, int((t1 - t0) / CHANGE_STEP_S) + 1)]
    cands = [c for c in cands if c <= t1 - CHANGE_MIN_AFTER_S]
    if len(cands) > CHANGE_MAX_CANDIDATES:
        cands = [cands[int(round(i * (len(cands) - 1) / (CHANGE_MAX_CANDIDATES - 1)))] for i in range(CHANGE_MAX_CANDIDATES)]
    for c in cands:
        if decide(view, t0, c, rc, st).outcome not in ("consistent", "insufficient"):
            continue
        post = decide(view, c, t1, rc, st)
        if post.outcome in ("supported", "unresolved"):
            post.reason = (f"normal operation is not rejected before {c - t0:.1f} s and a modelled cause fits after it "
                           f"(a fault that began inside the window); " + post.reason)
            return post
    return d


def run_episode(ep: Episode, scheduler, rc: RunConfig = RunConfig(), st: Study = Study()) -> dict:
    acc = Access(ep)
    view = View(acc.now_local(), [], [], 0, None, None, None, TIMING[rc.default_timing], 0, rc.byte_budget,
                rc.imu_available, [], None, rc.engine)
    timeline, streak, cpu, last_decide, last_state, cleared, by_key = [], 0, 0.0, -math.inf, None, [], {}
    t_true, next_monitor = 0.0, rc.monitor_every_s
    final, t_final = None, None
    getattr(scheduler, "reset", lambda: None)()
    while t_true < ep.spec.duration_s + 30.0:
        t_true += SUMMARY_PERIOD
        new_s, new_r = acc.advance(t_true)
        view.now_local = acc.now_local()
        view.summaries += new_s
        for r in new_r:
            view.pending -= 1
            if r.request.kind == "clockmeta":
                jit = r.records["clockmeta"]["rx_jitter_s"]
                if math.isfinite(jit) and jit < TIMING["known"]:
                    view.timing_s = TIMING["known"]
                timeline.append((view.now_local, "clockmeta", f"receipt jitter {jit * 1000:.2f} ms"))
                continue
            if r.status != "empty":
                lo = min(float(np.min(v["t_rx"])) for v in r.records.values() if len(v["t_rx"]))
                hi = max(float(np.max(v["t_rx"])) for v in r.records.values() if len(v["t_rx"]))
                rq = r.request
                key = (rq.kind, round(rq.t0_local, 3), round(rq.t1_local, 3), rq.duration_s, round(r.t_issue_true, 3))
                seg = by_key.get(key)
                if seg is None:                        # requests for the same window form one segment
                    seg = by_key[key] = Segment(lo, hi, rq.channels, rq.decimation, dict(r.records))
                    view.segments.append(seg)
                else:
                    seg.records.update(r.records)
                    seg.channels = tuple(dict.fromkeys(seg.channels + rq.channels))
                    seg.t0, seg.t1 = min(seg.t0, lo), max(seg.t1, hi)
                    if any(c in FRAME_CHANNELS for c in rq.channels):
                        seg.decimation = rq.decimation
                if view.detected_at is None and all(c in seg.channels for c in FRAME_CHANNELS):
                    # records fetched before any alarm are checked on their own: they can detect what the
                    # summary cannot show (a timing error, for example)
                    c0 = time.process_time()
                    sig = signals_from_frames(seg.records, lo, hi, st, period=0.01 * max(1, seg.decimation))
                    d = diagnose_blocks(calibrate_blocks(build_window(sig, st, frame_rels(seg, rc.imu_available)), rc.engine,
                                                         "frames") if sig is not None else [],
                                        rc.engine, view.timing_s, (lo, hi), "frames")
                    cpu += time.process_time() - c0
                    if d.outcome in ("supported", "unresolved", "no_fit"):
                        # detected now, when the records arrived; the decision window starts with them
                        view.detected_at, view.window_start = view.now_local, lo
                        view.deadline_local = view.now_local + rc.deadline_s
                        timeline.append((view.now_local, "detected", "fetched records: " + d.outcome + " "
                                         + ",".join(d.hypotheses)))
                    elif d.outcome == "consistent":
                        for h, pw in d.estimates.get("_power", {}).items():
                            if pw >= rc.engine.detect_sigma:      # this window could have shown h, and did not
                                view.tested[h] = max(view.tested.get(h, -math.inf), hi)
            timeline.append((view.now_local, "response", f"{r.request.kind} {r.bytes_down} B {r.status}"))
        if t_true < ep.spec.duration_s and t_true >= next_monitor:
            next_monitor += rc.monitor_every_s
            c0 = time.process_time()
            msgs = [m for m in view.summaries if m["t_local_ms"] / 1000.0 >= view.now_local - rc.monitor_window_s]
            sig = signals_from_summaries(msgs, st)
            view.monitor = diagnose_blocks(calibrate_blocks(build_window(sig, st, SUMMARY_RELS), rc.engine, "summary")
                                           if sig is not None else [],
                                           rc.engine, view.timing_s, (view.now_local - rc.monitor_window_s, view.now_local))
            cpu += time.process_time() - c0
            alarm = view.monitor.outcome in ("supported", "unresolved", "no_fit")
            streak = streak + 1 if alarm else 0
            if view.detected_at is None and streak >= rc.debounce:
                view.detected_at = view.now_local
                view.deadline_local = view.now_local + rc.deadline_s
                timeline.append((view.now_local, "detected", view.monitor.outcome + " " + ",".join(view.monitor.hypotheses)))
        # the scheduler acts on every step (fixed-rate schedulers also before detection)
        c0 = time.process_time()
        if view.detected_at is not None and (new_r or view.current is None or view.now_local >= last_decide + 2.0):
            view.current = decide(view, view.decision_start(), view.now_local, rc, st)
            last_decide = view.now_local
            state = (view.current.outcome, view.current.hypotheses)
            if state != last_state:                    # the assessment changed: record it
                timeline.append((view.now_local, "assessment", f"{state[0]} {{{', '.join(state[1])}}}"))
                last_state = state
        action = scheduler.step(view)
        cpu += time.process_time() - c0
        if isinstance(action, list):
            for rq in action:
                est = _estimate_bytes(rq)
                if view.bytes_used + est > rc.byte_budget:
                    timeline.append((view.now_local, "refused", f"{rq.kind}: budget"))
                    continue
                acc.request(rq)
                view.pending += 1
                view.bytes_used = acc.ledger["bytes_down"] + acc.ledger["bytes_up"]
                view.requested.append((view.now_local, rq))
                timeline.append((view.now_local, "request", _describe(rq)))
        stop = action == "stop" or (view.deadline_local is not None and view.now_local >= view.deadline_local)
        if view.detected_at is not None and stop and view.pending == 0:
            c0 = time.process_time()
            d = decide_final(view, view.decision_start(), view.now_local, rc, st)
            cpu += time.process_time() - c0
            if d.outcome in ("consistent", "insufficient"):
                # the alarm is cleared: record it, re-arm the monitor and keep watching
                cleared.append((view.decision_start(), view.now_local))
                timeline.append((view.now_local, "cleared", d.outcome + "; monitoring resumes"))
                view.detected_at = view.window_start = view.deadline_local = view.current = None
                last_state, streak = None, 0
                getattr(scheduler, "reset", lambda: None)()
                if t_true >= ep.spec.duration_s:
                    break
                continue
            final, t_final = d, view.now_local
            timeline.append((view.now_local, "decision", final.outcome + " " + ",".join(final.hypotheses)))
            break
        if view.detected_at is None and t_true >= ep.spec.duration_s:
            break
    clock = ep.spec.link.clock
    return {"scheduler": scheduler.name, "seed": ep.spec.seed, "label": ep.spec.fault.kind,
            "cleared_alarms": [(clock.true(a), clock.true(b)) for a, b in cleared],
            "outcome": final.outcome if final else ("consistent" if view.detected_at is None else "undecided"),
            "hypotheses": final.hypotheses if final else (), "reason": final.reason if final else "",
            "t_detect_true": clock.true(view.detected_at) if view.detected_at is not None else None,
            "t_decide_true": clock.true(t_final) if t_final is not None else None,
            "bytes": acc.ledger["bytes_down"] + acc.ledger["bytes_up"], "requests": acc.ledger["requests"],
            "summary_bytes": acc.ledger["summary_bytes"], "cpu_s": cpu, "timeline": timeline,
            "J": {h: round(float(v), 3) for h, v in final.J.items()} if final else {},
            "estimates": {h: {k: v for k, v in e.items() if not k.startswith("_")} for h, e in (final.estimates.items() if final else [])
                          if isinstance(e, dict)}}


def _estimate_bytes(rq: Request) -> int:
    from research.bea.harness import CHANNEL_HZ, REC_BYTES
    if rq.kind == "clockmeta":
        return 160
    span = (rq.t1_local - rq.t0_local) if rq.kind == "buffer" else rq.duration_s
    payload = sum(CHANNEL_HZ[c] * span / max(1, rq.decimation) * REC_BYTES[c] for c in rq.channels)
    return int(payload * 512 / 484) + 60                          # chunk framing and the request


def _describe(rq: Request) -> str:
    if rq.kind == "clockmeta":
        return "clock metadata"
    what = "+".join(rq.channels) + (f" 1/{rq.decimation}" if rq.decimation > 1 else "")
    if rq.kind == "buffer":
        return f"buffer {rq.t1_local - rq.t0_local:.1f} s of {what}"
    return f"capture next {rq.duration_s:.1f} s of {what}"
