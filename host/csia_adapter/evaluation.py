"""Held-out evaluation and ablation of the CSIA vehicle adapter (SHADOW MODE).

Monitors compared on identical sample streams:
  B1        range / NaN / freshness checks (host/csia_adapter/baselines.py)
  V0        naive residuals, no regime gates, residual alarms only
  V1        naive residuals + the adapter's regime gates
  V2        calibrated residuals (yaw, centreline, time alignment, grade, loss model), no gates
  V3        calibrated residuals + gates; residual alarms only (detection, no attribution)
  V3v       V3 + majority-vote attribution (a node in >= 2 failing relationships, unique)
  CSIA      the frozen adapter: V3's relationships + corroboration / auxiliary-input attribution
  TRUST     the frozen adapter's TrustCore beliefs, thresholded per node (attribution = the low node)
  B1+CSIA   union: B1 for freshness/range, CSIA for everything else

Residual thresholds of V0-V3v and TRUST thresholds are calibrated on the FROZEN
development nominal run only (smallest threshold with zero alarms there),
which is the same data the adapter was tuned on.

Metrics per monitor (docs/csia/EVALUATION_PROTOCOL.md): false-alarm episodes
per operating hour (all alarms, and false attributions), missed detections,
misattribution, ambiguity, onset->detection latency, eligible-evidence
latency, unobservable intervals.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable

from host.csia_adapter.adapter import NODES, VehicleCsiaAdapter
from host.csia_adapter.baselines import SimpleChecks
from host.csia_adapter.synthetic import params

TICK = 0.1
GRACE_S = 5.0
SIGNAL_NODE = {"rotor": "rotor", "wheel_l": "wheel_l", "wheel_r": "wheel_r", "wheel_drive": "wheel_drive",
               "gnss": "gnss", "imu_ax": "imu", "imu_gz": "imu", "iq": "phase_current", "iq_ref": "phase_current",
               "kcl": "phase_current", "p_dc": "dc_meter"}
NODE_INPUTS = {"rotor": ["rotor"], "wheel_drive": ["wheel_drive"], "wheel_l": ["wheel_l"], "wheel_r": ["wheel_r"],
               "gnss": ["gnss"], "imu": ["imu_ax", "imu_gz"], "phase_current": ["iq"], "dc_meter": ["p_dc"]}


@dataclasses.dataclass
class Out:
    suspects: frozenset      # attributed nodes
    implicated: frozenset    # every node involved in an alarm (suspected or not)
    eligible: dict | None = None   # node -> eligible relationships (frozen adapter only)

    @property
    def alarm(self) -> bool:
        return bool(self.implicated)


class B1:
    name = "B1"

    def __init__(self):
        self.m = SimpleChecks(params())

    def ingest(self, n, s):
        self.m.ingest(n, s)

    def tick(self, t):
        nodes = frozenset(SIGNAL_NODE[a] for a in self.m.tick(t) if a in SIGNAL_NODE)
        return Out(nodes, nodes)


class Residual:
    """Residual monitor on the adapter's relationship set with ablation switches."""

    def __init__(self, name, design, gates, attribution, lam_thr, debounce=3):
        self.name = name
        self.ad = VehicleCsiaAdapter(params())
        self.ad.residual_design = design
        self.ad.ablate_gates = not gates
        self.attr = attribution
        self.thr, self.deb = lam_thr, debounce
        self.count: dict = {}

    def ingest(self, n, s):
        self.ad.ingest(n, s)

    def tick(self, t):
        edges, phys, fr = self.ad._rel(t)
        self.ad.last_tick = t
        fresh = {n: all(fr[s] for s in ins) for n, ins in NODE_INPUTS.items()}
        failing = []
        for k, (a, b, lam, g, _aux) in edges.items():
            act = g > 0 and math.isfinite(lam) and fresh[a] and fresh[b]
            c = self.count.get(k, 0) + 1 if (act and lam > self.thr) else 0
            self.count[k] = c
            if c >= self.deb:
                failing.append((a, b))
        lp, gp = phys.get("phase_current", (0.0, 0.0))
        c = self.count.get("phys", 0) + 1 if (gp > 0 and fresh["phase_current"] and lp > self.thr) else 0
        self.count["phys"] = c
        phys_fail = c >= self.deb
        implicated = {x for e in failing for x in e} | ({"phase_current"} if phys_fail else set())
        suspects = set()
        if self.attr == "vote":
            if phys_fail:
                suspects.add("phase_current")
            cnt = {}
            for a, b in failing:
                cnt[a] = cnt.get(a, 0) + 1
                cnt[b] = cnt.get(b, 0) + 1
            if cnt:
                top = max(cnt.values())
                best = [n for n, v in cnt.items() if v == top]
                if top >= 2 and len(best) == 1:
                    suspects.add(best[0])
        return Out(frozenset(suspects), frozenset(implicated))


class Csia:
    name = "CSIA"

    def __init__(self):
        self.ad = VehicleCsiaAdapter(params())
        self.last = None

    def ingest(self, n, s):
        self.ad.ingest(n, s)

    def tick(self, t):
        st = self.ad.tick(t)
        self.last = st
        imp = set(st.suspects) | {x for a, b, _k in st.ambiguous for x in (a, b)}
        elig = {n: st.evidence[n] if st.fresh[n] else 0 for n in NODES}
        return Out(frozenset(st.suspects), frozenset(imp), elig)


class Trust:
    name = "TRUST"

    def __init__(self, thr: dict):
        self.ad = VehicleCsiaAdapter(params())
        self.thr = thr

    def ingest(self, n, s):
        self.ad.ingest(n, s)

    def tick(self, t):
        st = self.ad.tick(t)
        low = {n for n in NODES if st.trust_current[n] and st.trust[n] < self.thr[n]}
        return Out(frozenset(low) if len(low) == 1 else frozenset(), frozenset(low))


class Union:
    name = "B1+CSIA"

    def __init__(self):
        self.b1, self.c = B1(), Csia()

    def ingest(self, n, s):
        self.b1.ingest(n, s)
        self.c.ingest(n, s)

    def tick(self, t):
        a, b = self.b1.tick(t), self.c.tick(t)
        return Out(a.suspects | b.suspects, a.implicated | b.implicated, b.eligible)


def run_stream(data, duration_s, monitors):
    k = 0
    outs = {m.name: [] for m in monitors}
    for j in range(1, int(round(duration_s / TICK))):
        t = j * TICK
        while k < len(data) and data[k][0] <= t:
            _, name, s = data[k]
            for m in monitors:
                m.ingest(name, s)
            k += 1
        for m in monitors:
            outs[m.name].append((t, m.tick(t)))
    return outs


# --------------------------------------------------------------------- monitors
RESIDUAL_VARIANTS = [("V0", "naive", False, "none"), ("V1", "naive", True, "none"),
                     ("V2", "calibrated", False, "none"), ("V3", "calibrated", True, "none"),
                     ("V3v", "calibrated", True, "vote")]
LAM_GRID = (9.0, 16.0, 25.0, 36.0, 64.0, 100.0, 225.0, 400.0, 900.0)


def calibrate_on_dev(dev_data, dev_duration):
    """Smallest residual threshold with zero alarms on the frozen development
    nominal run, per residual variant; per-node trust thresholds below the
    dev-nominal minimum. Returns (lam per variant, dev alarms at that lam,
    trust thresholds)."""
    lam, dev_alarms = {}, {}
    for name, design, gates, attr in RESIDUAL_VARIANTS:
        chosen = None
        for thr in LAM_GRID:
            o = run_stream(dev_data, dev_duration, [Residual(name, design, gates, attr, thr)])[name]
            n = sum(1 for _t, x in o if x.alarm)
            if chosen is None or n < chosen[1]:
                chosen = (thr, n)
            if n == 0:
                break
        lam[name], dev_alarms[name] = chosen
    c = run_stream(dev_data, dev_duration, [Csia()])["CSIA"]
    ad_trust = {n: 1.0 for n in NODES}
    probe = VehicleCsiaAdapter(params())
    k = 0
    for j in range(1, int(round(dev_duration / TICK))):
        t = j * TICK
        while k < len(dev_data) and dev_data[k][0] <= t:
            probe.ingest(dev_data[k][1], dev_data[k][2])
            k += 1
        st = probe.tick(t)
        if t > 10.0:  # skip prior burn-in
            for n in NODES:
                ad_trust[n] = min(ad_trust[n], st.trust[n])
    trust_thr = {n: max(ad_trust[n] - 0.02, 0.0) for n in NODES}
    dev_alarms["CSIA"] = sum(1 for _t, x in c if x.alarm)
    return lam, dev_alarms, trust_thr


def make_monitors(lam: dict, trust_thr: dict) -> list:
    ms = [B1()]
    for name, design, gates, attr in RESIDUAL_VARIANTS:
        ms.append(Residual(name, design, gates, attr, lam[name]))
    ms += [Csia(), Trust(trust_thr), Union()]
    return ms


# --------------------------------------------------------------------- metrics
def episodes(ticks: list, pred: Callable) -> list:
    """Contiguous runs of ticks where pred(out) holds -> [(t_start, t_end)]."""
    eps, start, prev_t = [], None, None
    for t, o in ticks:
        if pred(o):
            if start is None:
                start = t
            prev_t = t
        elif start is not None:
            eps.append((start, prev_t))
            start = None
    if start is not None:
        eps.append((start, prev_t))
    return eps


def _drop_true_outages(ticks, scn):
    """A report that GNSS is not fresh DURING a designed GNSS outage (a normal
    event: no fix, no messages) is correct, not a false alarm. Remove gnss from
    every monitor's output for those ticks (+ the 0.3 s freshness window)."""
    outs = getattr(scn, "gnss_outage", ()) or ()
    if not outs:
        return ticks
    res = []
    for t, o in ticks:
        if any(a <= t <= b + 0.5 for a, b in outs):
            o = Out(o.suspects - {"gnss"}, o.implicated - {"gnss"}, o.eligible)
        res.append((t, o))
    return res


def score(outs: dict, scn, eligibility: list) -> dict:
    """Per-monitor metrics for one scenario."""
    f = scn.fault
    res = {}
    for name, ticks in outs.items():
        ticks = _drop_true_outages(ticks, scn)
        win = (f.t0, f.t1 + GRACE_S) if f else None
        in_win = (lambda t: win[0] <= t <= win[1]) if f else (lambda t: False)
        out_ticks = [(t, o) for t, o in ticks if not in_win(t)]
        fa_eps = episodes(out_ticks, lambda o: o.alarm)
        fa_attr = episodes(out_ticks, lambda o: bool(o.suspects))
        fa_nodes = {}
        for a0, b0 in fa_eps:
            key = ",".join(sorted({x for t, o in out_ticks if a0 <= t <= b0 for x in o.implicated}))
            fa_nodes[key] = fa_nodes.get(key, 0) + 1
        r = {"op_s": len(out_ticks) * TICK, "fa_episodes": len(fa_eps), "fa_attr_episodes": len(fa_attr),
             "fa_by_nodes": fa_nodes}
        if f:
            node = f.node
            w = [(t, o) for t, o in ticks if in_win(t)]
            det = next((t for t, o in w if node in o.implicated), None)
            cor = next((t for t, o in w if node in o.suspects), None)
            wrong = sorted({x for _t, o in w for x in o.suspects if x != node})
            amb = sum(1 for _t, o in w if node in o.implicated and node not in o.suspects)
            dett = sum(1 for _t, o in w if node in o.implicated)
            elig = [(t, e) for t, e in eligibility if f.t0 <= t <= f.t1]
            first_elig = next((t for t, e in elig if e.get(node, 0) > 0), None)
            unobs = sum(1 for _t, e in elig if e.get(node, 0) == 0) * TICK
            r.update({"node": node, "kind": f.kind, "detected": det is not None, "attributed": cor is not None,
                      "misattributed": bool(wrong), "wrong_nodes": wrong,
                      "lat_detect_s": None if det is None else det - f.t0,
                      "lat_attr_s": None if cor is None else cor - f.t0,
                      "first_eligible_s": None if first_elig is None else first_elig - f.t0,
                      "lat_detect_after_eligible_s": None if (det is None or first_elig is None) else det - first_elig,
                      "ambiguous_fraction": (amb / dett) if dett else None,
                      "unobservable_s": unobs, "fault_s": f.t1 - f.t0})
        res[name] = r
    return res
