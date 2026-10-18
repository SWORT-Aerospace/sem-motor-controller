"""Wheel speed and distance from Hall-switch edge timestamps (reference for the firmware, telematics/firmware).

The firmware captures the time of every edge with a timer (1 us resolution, extended to 64 bits across
timer overflow) and, every `record_period_us`, writes one WHEEL_EDGES record per channel (stlg.py):
the number of edges since the previous record, the time of the last edge (the record time), the span from
the first to the last of those edges, the line level, a per-channel record counter and a count of edges
lost to capture overrun. A channel without edges still gets a record (a heartbeat, n = 0) at the
evaluation time, so silence is recorded, not inferred.

From those records:

  distance   pitch x total edges since start, pitch = circumference / pulses per revolution; uncertainty one
             pitch. The total is in every record, so a lost record loses no distance; edges lost to capture
             overrun make it a lower bound (validity unverified)
  speed      over complete edge intervals only: from the last edge of the previous record to the last edge
             of this one there are n intervals, so v = n x pitch / (t_last - t_prev_last). The window starts
             and ends on an edge, so there is no counting-window quantisation (the old fixed-window
             estimate, counts x C / (ppr x window), is +-1 count per window). The sample time is the middle
             of the interval and its uncertainty half the interval. After a break in the chain (a lost
             record, capture overrun, the first record) only the record's own edges are used, n >= 2:
             v = (n - 1) x pitch / span.
  no edge    when the time since the last edge exceeds `stale_factor` x the last edge period (or there was
             never an edge), the speed is not known: `no_evidence`, never 0. If the sensor works, the wheel has
             moved less than one pitch since that edge, so the result carries the bound v < pitch / dt; the
             bound is only as good as that assumption, and the provenance says so.
  standstill never inferred from this channel alone. The line level cannot prove it: a magnet under the
             sensor, a signal shorted to ground and a failed sensor all hold the line at its active level; a
             wheel stopped between magnets, an open wire, an unpowered sensor and a line shorted high all leave
             it inactive. A stopped vehicle needs an independent source (another sensor that can measure zero).
  suspect    classify() compares the channels (the same rule as tm_wheel_classify() in the firmware): a
             channel silent for at least 8 periods of a channel that is moving, and at least 1 s, is suspect.
             Its line level names the fault that fits: active, stuck active (short to ground, failed sensor);
             inactive, stuck inactive or disconnected. A suspect channel's speed is `invalid` with no bound,
             and its distance from then on is a lower bound (`unverified`): edges may have been missed.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from host.telematics import signals
from host.telematics.measurement import Measurement

FLAG_LINE_HIGH = 0x01        # line level at the record time
FLAG_OVERRUN = 0x02          # an edge was captured before the previous one was read: edges lost
FLAG_HEARTBEAT = 0x04        # no edge since the previous record


@dataclasses.dataclass(frozen=True)
class WheelConfig:
    circumference_m: float
    ppr: int                                  # edges counted per revolution (one edge per magnet pass)
    active_high: bool = False                 # open-collector Hall switch with pull-up: low when a magnet is near
    stale_factor: float = 3.0
    max_period_us: int = 2_000_000            # a longer edge period than this is not a speed sample

    @property
    def pitch_m(self) -> float:
        return self.circumference_m / self.ppr


@dataclasses.dataclass(frozen=True)
class EdgeRecord:
    t_us: int                # time of the last edge (n > 0) or of the evaluation (heartbeat)
    channel: int
    n: int
    span_us: int             # last edge - first edge in this record
    total: int               # edges since start, wraps at 2**32
    flags: int
    rec_seq: int             # per-channel, wraps at 65536
    lost: int                # edges lost to capture overrun since the previous record


class EdgeAccumulator:
    """One channel's edge accumulator: what the capture interrupt updates and the record task drains.
    The firmware (tm_wheel.c) does the same in C; tests compare the two on the same edges."""

    def __init__(self, channel: int):
        self.channel = channel
        self.n = 0
        self.t_first = None
        self.t_last = None
        self.lost = 0
        self.overrun = False
        self.rec_seq = 0
        self.total = 0

    def edge(self, t_us: int) -> None:
        if self.n == 0:
            self.t_first = t_us
        self.t_last = t_us
        self.n += 1
        self.total = (self.total + 1) & 0xFFFFFFFF

    def overrun_edge(self) -> None:
        self.lost += 1
        self.overrun = True

    def take(self, t_now_us: int, line_high: bool) -> EdgeRecord:
        flags = (FLAG_LINE_HIGH if line_high else 0) | (FLAG_OVERRUN if self.overrun else 0)
        if self.n:
            r = EdgeRecord(self.t_last, self.channel, self.n, self.t_last - self.t_first, self.total, flags,
                           self.rec_seq, self.lost)
        else:
            r = EdgeRecord(t_now_us, self.channel, 0, 0, self.total, flags | FLAG_HEARTBEAT, self.rec_seq, self.lost)
        self.n, self.t_first, self.t_last, self.lost, self.overrun = 0, None, None, 0, False
        self.rec_seq = (self.rec_seq + 1) & 0xFFFF
        return r


MOVING_PERIODS = 3                # the same constants as tm_wheel.h
MOVING_MIN_US = 250_000
SUSPECT_PERIODS = 8
SUSPECT_MIN_US = 1_000_000
MAX_PERIOD_US = 2_000_000
STATE_TEXT = {"N": "never produced an edge", "M": "moving", "S": "silent (stopped or failed: unknown)",
              "A": "suspect: line held at the active level while another channel moves (stuck active: short to "
                   "ground, failed sensor or magnet stuck)",
              "I": "suspect: line held at the inactive level while another channel moves (stuck inactive or "
                   "disconnected: open wire, no supply, shorted high)"}


@dataclasses.dataclass
class WheelTrack:
    """What the plausibility rule keeps per channel (tm_wheel_track_t)."""
    since_us: int = 0                 # latest edge, or the start of tracking before the first edge
    period_us: int = 0                # latest edge period; 0: none
    ever: bool = False
    line_high: bool = True

    def update(self, r: EdgeRecord) -> None:
        self.line_high = bool(r.flags & FLAG_LINE_HIGH)
        if r.n == 0:
            return
        p = 0
        if r.n >= 2 and r.span_us > 0:
            p = r.span_us // (r.n - 1)
        elif self.ever and r.t_us > self.since_us:
            p = r.t_us - self.since_us
        self.period_us = 0 if p > MAX_PERIOD_US else p
        self.since_us = r.t_us
        self.ever = True

    def moving(self, now_us: int) -> bool:
        if not self.ever or self.period_us == 0:
            return False
        if now_us <= self.since_us:
            return True
        return now_us - self.since_us <= max(MOVING_PERIODS * self.period_us, MOVING_MIN_US)


def classify(tracks, ch: int, now_us: int, active_high: bool) -> tuple[str, Optional[int]]:
    """State of channel `ch` at `now_us` (N M S A I, see tm_wheel.h) and the moving channel that makes it
    suspect. `tracks` maps channel -> WheelTrack."""
    c = tracks[ch]
    if c.moving(now_us):
        return "M", None
    silence = max(0, now_us - c.since_us)
    for k in sorted(tracks):
        o = tracks[k]
        if k == ch or not o.moving(now_us) or o.period_us == 0:
            continue
        if silence >= SUSPECT_PERIODS * o.period_us and silence >= SUSPECT_MIN_US:
            return ("A" if c.line_high == active_high else "I"), k
    return ("S" if c.ever else "N"), None


class WheelEstimator:
    """Records of one channel in, measurements out (speed and distance)."""

    def __init__(self, cfg: WheelConfig, name: str, record_id=None, t_unc_capture_us: int = 2):
        self.cfg = cfg
        self.name = name
        self.rid = record_id or (lambda: 0)
        self.t_unc_capture_us = t_unc_capture_us
        self.edges = 0
        self.total0: Optional[int] = None         # the first record's total minus its edges (a restart begins at 0)
        self.last_edge: Optional[int] = None      # time of the latest edge seen
        self.last_period: Optional[int] = None
        self.chain_ok = False                     # the previous record's last edge is the edge before this one
        self.expect_seq: Optional[int] = None
        self.ever_edge = False
        self.suspect_since: Optional[int] = None  # first time the channel was found suspect
        self.lost_edges = 0
        self.lost_records = 0

    def _m(self, signal: str, value, t_rx: int, t_sample, t_unc, validity: str, prov: str, upper=None):
        return Measurement(self.rid(), "wheel", f"wheel.{self.name}.{signal}", value,
                           "m/s" if signal == "speed" else "m", t_rx, t_sample, t_unc, None, validity, prov, upper)

    def feed(self, r: EdgeRecord, state: str = "", ref: Optional[str] = None) -> list[Measurement]:
        """One record of this channel. `state` and `ref` come from classify() (WheelGroup passes them); a
        suspect state (A, I) makes a silent channel's speed invalid and its later distances lower bounds."""
        cfg, out = self.cfg, []
        if state in ("A", "I") and self.suspect_since is None:
            self.suspect_since = r.t_us
        if self.expect_seq is not None and r.rec_seq != self.expect_seq:
            self.lost_records += (r.rec_seq - self.expect_seq) & 0xFFFF
            self.chain_ok = False
        self.expect_seq = (r.rec_seq + 1) & 0xFFFF
        if r.lost or r.flags & FLAG_OVERRUN:
            self.lost_edges += r.lost
            self.chain_ok = False
        line_active = bool(r.flags & FLAG_LINE_HIGH) == cfg.active_high
        prov = f"wheel-edges:ch{r.channel}"
        if r.n > 0:
            t_first = r.t_us - r.span_us
            v = None
            if self.chain_ok and self.last_edge is not None and r.t_us - self.last_edge <= cfg.max_period_us * r.n:
                dt = r.t_us - self.last_edge
                v, t_mid, half = r.n * cfg.pitch_m * 1e6 / dt, self.last_edge + dt // 2, dt // 2
            elif r.n >= 2 and r.span_us > 0:
                v, t_mid, half = (r.n - 1) * cfg.pitch_m * 1e6 / r.span_us, t_first + r.span_us // 2, r.span_us // 2
            if v is not None:
                ok = signals.in_range(f"wheel.{self.name}.speed", v)
                out.append(self._m("speed", v if ok else None, r.t_us, t_mid, half + self.t_unc_capture_us,
                                   "valid" if ok else "out_of_range", prov))
            if r.n >= 2:
                self.last_period = r.span_us // (r.n - 1)
            elif self.last_edge is not None and self.chain_ok:
                self.last_period = r.t_us - self.last_edge
            if self.total0 is None:
                self.total0 = (r.total - r.n) & 0xFFFFFFFF
            self.edges = (r.total - self.total0) & 0xFFFFFFFF
            self.last_edge = r.t_us
            self.ever_edge = True
            self.chain_ok = True
            # after an edge lost to capture overrun, or while the channel was suspect, the count is a lower
            # bound: unverified, not valid
            why = [w for w, c in (("edges lost to overrun", self.lost_edges), ("channel was suspect",
                                                                            self.suspect_since is not None)) if c]
            out.append(self._m("distance", self.edges * cfg.pitch_m, r.t_us, r.t_us, self.t_unc_capture_us,
                               "unverified" if why else "valid",
                               prov + (" lower bound: " + ", ".join(why) if why else "")))
            return out
        # heartbeat: no edge since the previous record. The line level is recorded for diagnosis only: it
        # cannot show whether the wheel stands still or the sensor has failed.
        level = "active" if line_active else "inactive"
        if state in ("A", "I"):
            out.append(self._m("speed", None, r.t_us, None, None, "invalid",
                               f"{prov} {STATE_TEXT[state]}" + (f" ({ref})" if ref else "")))
            return out
        since = None if self.last_edge is None else r.t_us - self.last_edge
        expected = None if self.last_period is None else cfg.stale_factor * self.last_period
        if since is not None and expected is not None and since <= expected:
            return out                                       # between edges: the latest speed still stands
        upper = cfg.pitch_m * 1e6 / since if since else None
        out.append(self._m("speed", None, r.t_us, None, None, "no_evidence",
                           f"{prov} no edge, line {level}; bound v < pitch/dt holds only for a working sensor",
                           upper))
        return out


class WheelGroup:
    """All wheel channels of one unit: an estimator per channel plus the plausibility rule across them.
    Records go in one at a time (in log order); each is classified against the latest state of the other
    channels, as the firmware does every record period."""

    def __init__(self, cfg: WheelConfig, names: dict, record_id=None, t0_us: int = 0):
        self.cfg = cfg
        self.names = dict(names)
        self.est = {ch: WheelEstimator(cfg, n, record_id) for ch, n in self.names.items()}
        self.tracks = {ch: WheelTrack(since_us=t0_us) for ch in self.names}
        self.state = {ch: "N" for ch in self.names}
        self.episodes = {"A": 0, "I": 0}

    def set_record_id(self, record_id) -> None:
        for e in self.est.values():
            e.rid = record_id

    def _ensure(self, ch: int, t_us: int) -> None:
        if ch not in self.est:
            self.names[ch] = f"wheel_{ch}"
            self.est[ch] = WheelEstimator(self.cfg, self.names[ch], next(iter(self.est.values())).rid
                                          if self.est else None)
            self.tracks[ch] = WheelTrack(since_us=t_us)
            self.state[ch] = "N"

    def update(self, r: EdgeRecord) -> None:
        self._ensure(r.channel, r.t_us)
        self.tracks[r.channel].update(r)

    def classify(self, ch: int, now_us: int) -> tuple[str, Optional[str]]:
        s, k = classify(self.tracks, ch, now_us, self.cfg.active_high)
        if s != self.state[ch] and s in self.episodes:
            self.episodes[s] += 1
        self.state[ch] = s
        return s, (self.names[k] if k is not None else None)

    def estimate(self, r: EdgeRecord, state: str, ref: Optional[str]) -> list[Measurement]:
        return self.est[r.channel].feed(r, state, ref)

    def feed(self, r: EdgeRecord) -> list[Measurement]:
        """Update, classify and estimate one record (the pit import's order)."""
        self.update(r)
        s, ref = self.classify(r.channel, r.t_us)
        return self.estimate(r, s, ref)
