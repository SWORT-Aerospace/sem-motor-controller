"""CSIA v2 evaluation harness (SHADOW MODE, synthetic). Protocol: docs/csia/EVALUATION_PROTOCOL_v2.md.

Every monitor produces raw per-tick output; one shared persistence filter
(Debounce, 3 ticks, node level) is applied to every monitor, so differences
between monitors are not differences in debounce (the v1 post-hoc finding).

Monitors:
  B1       range / NaN / freshness
  R3       calibrated residuals (v2 relationship set) + the adapter's gates, detection only
  R3v      R3 + majority-vote attribution (a node in >= 2 failing relationships, unique)
  CSIA1    frozen v1 adapter: v1 relationships + corroboration attribution
  CSIA2    v2 adapter: v2 power balance + the same corroboration attribution
  TRUST2   the v2 adapter's TrustCore beliefs, thresholded per node
  B1+CSIA2 union
The residual threshold of R3/R3v and the TRUST2 thresholds are calibrated on
the v2 development nominal scenarios only.
"""
from __future__ import annotations

import collections
import time
import tracemalloc

from host.csia_adapter import evaluation as EV
from host.csia_adapter.adapter import NODES
from host.csia_adapter.adapter_v2 import E6Model, VehicleCsiaAdapterV2
from host.csia_adapter.synthetic import params

TICK = EV.TICK
DEBOUNCE = 3
MONITOR_ORDER = ["B1", "R3", "R3v", "CSIA1", "CSIA2", "TRUST2", "B1+CSIA2"]
DESCR = {"B1": "range / NaN / freshness", "R3": "calibrated residuals (v2 set) + gates, detection only",
         "R3v": "R3 + majority-vote attribution", "CSIA1": "frozen v1 adapter (corroboration attribution)",
         "CSIA2": "v2 adapter: v2 power balance + corroboration attribution",
         "TRUST2": "TrustCore belief threshold (v2 adapter)", "B1+CSIA2": "B1 + CSIA2"}


class Debounce:
    """A node is reported (implicated / suspected) only after DEBOUNCE consecutive ticks."""

    def __init__(self, inner, n: int = DEBOUNCE):
        self.inner, self.n, self.name = inner, n, inner.name
        self.ci: collections.Counter = collections.Counter()
        self.cs: collections.Counter = collections.Counter()

    def ingest(self, name, s):
        self.inner.ingest(name, s)

    def tick(self, t):
        o = self.inner.tick(t)
        for c, cur in ((self.ci, o.implicated), (self.cs, o.suspects)):
            for k in list(c):
                if k not in cur:
                    del c[k]
            for k in cur:
                c[k] += 1
        imp = frozenset(k for k, v in self.ci.items() if v >= self.n)
        sus = frozenset(k for k, v in self.cs.items() if v >= self.n)
        return EV.Out(sus, imp | sus, o.eligible)


class ResidualV2(EV.Residual):
    """v1's residual monitor on the v2 relationship set (raw: debounce 1, filtered by Debounce)."""

    def __init__(self, name, attribution, lam_thr, e6: E6Model):
        super().__init__(name, "calibrated", True, attribution, lam_thr, debounce=1)
        self.ad = VehicleCsiaAdapterV2(params(), e6)


class Csia1(EV.Csia):
    name = "CSIA1"


class Csia2(EV.Csia):
    name = "CSIA2"

    def __init__(self, e6: E6Model):
        self.ad = VehicleCsiaAdapterV2(params(), e6)
        self.last = None


class Trust2(EV.Trust):
    name = "TRUST2"

    def __init__(self, thr: dict, e6: E6Model):
        self.ad = VehicleCsiaAdapterV2(params(), e6)
        self.thr = thr


class UnionV2:
    name = "B1+CSIA2"

    def __init__(self, e6: E6Model):
        self.b1, self.c = Debounce(EV.B1()), Debounce(Csia2(e6))

    def ingest(self, n, s):
        self.b1.ingest(n, s)
        self.c.ingest(n, s)

    def tick(self, t):
        a, b = self.b1.tick(t), self.c.tick(t)
        return EV.Out(a.suspects | b.suspects, a.implicated | b.implicated, b.eligible)


def make_monitors(lam: float, trust_thr: dict, e6: E6Model) -> list:
    return [Debounce(EV.B1()), Debounce(ResidualV2("R3", "none", lam, e6)), Debounce(ResidualV2("R3v", "vote", lam, e6)),
            Debounce(Csia1()), Debounce(Csia2(e6)), Debounce(Trust2(trust_thr, e6)), UnionV2(e6)]


def run_stream_timed(data, duration_s, monitors):
    """EV.run_stream, plus accumulated host CPU time per monitor (ingest + tick)."""
    k = 0
    outs = {m.name: [] for m in monitors}
    cpu = {m.name: 0.0 for m in monitors}
    ticks = 0
    for j in range(1, int(round(duration_s / TICK))):
        t = j * TICK
        batch = []
        while k < len(data) and data[k][0] <= t:
            batch.append(data[k])
            k += 1
        for m in monitors:
            c0 = time.perf_counter()
            for _t, name, s in batch:
                m.ingest(name, s)
            o = m.tick(t)
            cpu[m.name] += time.perf_counter() - c0
            outs[m.name].append((t, o))
        ticks += 1
    return outs, cpu, ticks


def peak_memory_kib(factory, data, duration_s) -> float:
    """Peak traced Python allocation of one monitor over one stream (host CPython figure)."""
    tracemalloc.start()
    m = factory()
    EV.run_stream(data, duration_s, [m])
    _c, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024.0


def residual_alarms(args) -> int:
    scn, data, thr, e6 = args
    o = EV.run_stream(data, scn.duration_s, [Debounce(ResidualV2("R3", "none", thr, E6Model(**e6)))])["R3"]
    return sum(1 for _t, x in o if x.alarm)


def calibrate(dev_nominal: list, e6: E6Model, pmap=map) -> tuple[float, dict, dict]:
    """Residual threshold (smallest grid value with zero debounced alarms on the
    dev nominal scenarios) and per-node TrustCore thresholds (0.02 below the dev
    nominal minimum after a 10 s burn-in)."""
    chosen = None
    for thr in EV.LAM_GRID:
        n = sum(pmap(residual_alarms, [(scn, data, thr, e6.__dict__) for scn, data in dev_nominal]))
        if chosen is None or n < chosen[1]:
            chosen = (thr, n)
        if n == 0:
            break
    trust_min = {n: 1.0 for n in NODES}
    for scn, data in dev_nominal:
        probe = VehicleCsiaAdapterV2(params(), e6)
        k = 0
        for j in range(1, int(round(scn.duration_s / TICK))):
            t = j * TICK
            while k < len(data) and data[k][0] <= t:
                probe.ingest(data[k][1], data[k][2])
                k += 1
            st = probe.tick(t)
            if t > 10.0:
                for n in NODES:
                    trust_min[n] = min(trust_min[n], st.trust[n])
    trust_thr = {n: max(trust_min[n] - 0.02, 0.0) for n in NODES}
    return chosen[0], {"dev_alarms_at_threshold": chosen[1]}, trust_thr

