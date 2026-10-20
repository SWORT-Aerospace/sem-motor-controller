"""Advisory conclusions from witness observations, and the receipts that let anyone check them.

Verdicts (advisory, never a command):

  SUPPORTED    the claim agrees with admissible evidence in a context where it applies
  AMBIGUOUS    an inconsistency was observed and the evidence does not isolate its cause; the open candidates
               are listed
  UNSUPPORTED  no conclusion: the claim is not applicable now, or the evidence is not admissible

Every conclusion also has a level, which says how far it goes:

  observed     a relation's result: the values agree or disagree; nothing about why
  conditional  a localization or a common cause that holds only under the assumptions it lists; the
               alternatives those assumptions leave out stay among its candidates
  established  a cause confirmed by independent ground truth in a run record (research/vehicle_validation/records);
               never produced by this software

No conclusion names a fault ("sensor fault", "motor fault", "battery fault"). Distinct sensors are not independent
against every fault: two witnesses that share a path or a parameter (host/telematics/lineage.py `independence`) can
agree because they share an error. A localization therefore states, as assumptions, that the agreeing witnesses have
no common timing or value error through each dependency they share, and keeps "a common error of the witnesses, the
subject correct" among its candidates. When they share a parameter (one scaling for both), that alternative comes
first: the pattern is exactly what a wrong parameter gives.

Common cause (family C): simultaneous loss of admissible evidence in several sources is reported with the shared
paths those sources have in common, and each path is judged under two fault models (`common_cause`): a complete
loss of the path, which predicts that every source on it loses evidence, and a partial or brief disturbance, which
predicts only that some do (different reset thresholds, buffering, a dip shorter than one source's period). A source
on the path that delivered admissible evidence continuously through the event excludes the complete-loss model only;
the partial model stays a candidate unless direct evidence excludes it. A shared-path event is SUPPORTED only with
direct evidence of a disturbance on that path (a brown-out reset cause, a bus error status, counted log drops, a
session that ended without its final record); otherwise it is AMBIGUOUS. Onsets form one event only within one
window of the first onset: a chain of onsets is never merged into one "simultaneous" event longer than the window.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Iterable, Optional

from host.assurance.witnesses import Observation
from host.telematics import lineage

VERDICTS = ("SUPPORTED", "AMBIGUOUS", "UNSUPPORTED")
LEVELS = ("observed", "conditional", "established")
FORBIDDEN_LABELS = ("sensor fault", "motor fault", "battery fault", "controller fault", "faulty", "has failed")

PATH_CANDIDATES = {
    "wheel": ("the Hall sensor, magnet or wiring of that wheel", "the circumference or pulses per revolution set for it",
              "slip or lock at that wheel", "edges lost or extra on that channel"),
    "ctrl": ("the controller's own sensor or estimate", "the adapter mapping or scaling", "a drivetrain parameter"),
    "gnss": ("the receiver's fix quality, multipath or antenna", "time alignment of the GNSS stream"),
    "imu": ("the IMU mounting, axis or offset", "the sensor", "the bus read"),
    "temp": ("the temperature sensor or its contact", "the bus read"),
    "batt": ("the battery-side monitor or its shunt",),
    "speed": ("the controller's speed estimate", "the gear ratio or circumference parameter", "freewheel or slip",
              "the adapter mapping or scaling"),
}


@dataclasses.dataclass(frozen=True)
class Conclusion:
    kind: str                       # relation | localization | common_cause
    subject: str
    verdict: str
    statement: str
    candidates: tuple[str, ...]
    basis: tuple[str, ...]          # relation ids or event descriptions
    t_us: Optional[int] = None      # for events (common cause): when the first source lost admissible evidence
    level: str = "observed"         # LEVELS
    assumptions: tuple[str, ...] = ()   # what a conditional conclusion holds under
    shared: dict = dataclasses.field(default_factory=dict)   # shared dependencies behind it (lineage.independence)

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["candidates"], d["basis"], d["assumptions"] = list(self.candidates), list(self.basis), list(self.assumptions)
        return d


def from_observation(o: Observation) -> Conclusion:
    if o.result == "CONSISTENT":
        return Conclusion("relation", o.relation, "SUPPORTED", f"supported: {o.claim} ({o.detail})", (), (o.relation,))
    if o.result == "INCONSISTENT":
        return Conclusion("relation", o.relation, "AMBIGUOUS",
                          f"disagreement observed: {o.claim} does not hold now ({o.detail}); cause not isolated",
                          o.causes_if_inconsistent, (o.relation,))
    return Conclusion("relation", o.relation, "UNSUPPORTED", f"no conclusion on '{o.claim}': {o.detail}", (),
                      (o.relation,))


# relations that compare two estimates of the same quantity (vehicle speed): only these can localize
SAME_QUANTITY = ("B1:", "B2:", "B3:")


def _edges(observations: Iterable[Observation]) -> list[tuple[str, str, str, str]]:
    """(subject, primary witness, result, relation) for every same-quantity comparison that gave a result."""
    return [(o.compared or o.subject, o.witnesses[0], o.result, o.relation) for o in observations
            if o.relation.startswith(SAME_QUANTITY) and o.result in ("CONSISTENT", "INCONSISTENT")]


def _independence(a: str, b: str):
    try:
        return lineage.independence(a, b)
    except KeyError:
        return None


def _conditional(x: str, y: str, z: str, rels: tuple[str, ...]) -> Optional[Conclusion]:
    """A localization to `x`'s path, conditional on `y` and `z` sharing no error; None if any pair shares a sensor
    (then there are not three witnesses) or a lineage is unknown."""
    inds = {k: _independence(*k) for k in ((x, y), (x, z), (y, z))}
    if any(i is None or not i.distinct_sensors for i in inds.values()):
        return None
    iyz = inds[(y, z)]
    common = iyz.common_errors(("timing", "value"))
    params = [d for d, _k in common if d in iyz.shared_parameters]
    common = [c for c in common if c[0] in params] + [c for c in common if c[0] not in params]
    alternatives = tuple(f"a common {k} error of {y} and {z} through {d}, with {x} correct" for d, k in common)
    assumptions = tuple(f"{y} and {z} have no common {k} error through {d}" for d, k in common) + \
        (f"{y} and {z} agree because both are right, not by coincidence within the tolerance",
         "the relations' PROVISIONAL tolerances and contexts hold")
    src = "wheel" if x.startswith("wheel.") else x.split(".")[0]
    own = PATH_CANDIDATES.get(src, ("the evidence path of " + x,))
    if params:
        statement = (f"disagreement observed between {x} and {y}, {z}, which agree with each other; {y} and {z} share "
                     f"{', '.join(params)}: a wrong value moves both together, which gives this same pattern with {x} "
                     f"correct; the evidence does not separate that from an error on the evidence path of {x}")
        candidates = alternatives + own
    else:
        statement = (f"conditional localization: {x} disagrees with {y} and {z}, which agree with each other; if they "
                     f"share no error ({len(common)} shared dependencies could give one: "
                     f"{', '.join(sorted({d for d, _k in common})) or 'none'}), the inconsistency is on the evidence path "
                     f"of {x}; the cause on that path is not established")
        candidates = own + alternatives
    return Conclusion("localization", x, "AMBIGUOUS", statement, candidates, rels, level="conditional",
                      assumptions=assumptions, shared={f"{a}|{b}": i.as_dict() for (a, b), i in inds.items()})


def localize(observations: list[Observation]) -> list[Conclusion]:
    """Conditional localizations from same-quantity relations: a subject that disagrees with two witnesses that agree
    with each other (each pair from distinct sensors). The shared dependencies of the agreeing witnesses stay in the
    conclusion as assumptions and alternatives; nothing here establishes a cause."""
    edges = _edges(observations)
    agree = {frozenset((a, b)) for a, b, r, _ in edges if r == "CONSISTENT"}
    out = []
    nodes = {x for a, b, _r, _ in edges for x in (a, b)}
    for x in sorted(nodes):
        against = sorted({(b if a == x else a, rel) for a, b, r, rel in edges if r == "INCONSISTENT" and x in (a, b)})
        others = sorted({y for y, _ in against})
        found = []
        for i, y in enumerate(others):
            for z in others[i + 1:]:
                if frozenset((y, z)) in agree:
                    c = _conditional(x, y, z, tuple(rel for _y, rel in against if _y in (y, z)))
                    if c:
                        found.append(c)
        if found:
            # the witness pair that shares the least: no shared parameter first, then the fewest shared error paths
            out.append(min(found, key=lambda c: (c.candidates[0].startswith("a common"), len(c.assumptions),
                                                 c.statement)))
    return out


FAULT_MODELS = {
    "complete": "a complete loss of the path for the event: predicts that every source on it loses admissible evidence",
    "partial": "a partial or brief disturbance of the path (different reset or brown-out thresholds, buffering, a dip "
               "shorter than a source's sample period): predicts that some sources on it lose evidence and others not",
}


def _events(onsets: list, window_us: int) -> list[list]:
    """Onsets grouped into events: each event holds the onsets within `window_us` of its FIRST onset, so a chain of
    onsets a little less than a window apart is never merged into one long 'simultaneous' event."""
    out, cur = [], []
    for o in sorted(onsets):
        if cur and o[0] - cur[0][0] > window_us:
            out.append(cur)
            cur = []
        cur.append(o)
    if cur:
        out.append(cur)
    return out


def common_cause(onsets: list[tuple[int, str, str, Optional[str]]], window_us: int,
                 disturbances: list[tuple[int, str, str]],
                 continuity: Optional[Callable[[str, int, int], bool]] = None,
                 others: Iterable[str] = ()) -> list[Conclusion]:
    """Family C. `onsets`: (t_us, source, signal, reason) where a signal stopped being admissible. `disturbances`:
    (t_us, path, description) of direct evidence on a path (a brown-out reset cause, a bus error status, counted drops).
    `continuity(signal, a, b)`: the signal delivered admissible evidence throughout [a, b] (no break longer than its
    own tolerance); asked only for `others`, the run's signals that are not part of the event (a source that lost
    evidence and recovered is in the event and never counts as unaffected).

    Each shared path is judged under FAULT_MODELS: a continuous source on the path excludes the complete-loss model;
    nothing in the loss pattern excludes the partial model, so it stays a candidate unless a disturbance is supported."""
    out = []
    for grp in _events(onsets, window_us):
        srcs = sorted({s for _t, s, _g, _r in grp})
        if len(srcs) < 2:
            continue
        t0, t1 = grp[0][0], grp[-1][0]
        sigs = sorted({g for _t, _s, g, _r in grp})
        try:
            shared = set.intersection(*(set(lineage.paths_of(g)) for g in sigs))
        except KeyError:
            shared = set()
        a, b = t0 - window_us, t1 + window_us
        unaffected: dict[str, list[str]] = {}
        for k in sorted(set(others) - set(sigs)):
            try:
                kp = lineage.paths_of(k) & shared
            except KeyError:
                continue
            if kp and continuity is not None and continuity(k, a, b):
                for pth in kp:
                    unaffected.setdefault(pth, []).append(k)
        support = [d for d in disturbances if a <= d[0] <= b and d[1] in shared]
        basis = tuple(f"{g} {r or ''}".strip() for _t, _s, g, r in grp)
        span = f"within {(t1 - t0) / 1000:.0f} ms"
        models = {pth: {"complete": ("excluded: " + ", ".join(unaffected[pth]) + " delivered admissible evidence "
                                     "throughout") if pth in unaffected else "not excluded",
                        "partial": "not excluded"} for pth in sorted(shared)}
        shared_d = {"paths": sorted(shared), "fault_models": models, "window_us": window_us,
                    "event_span_us": t1 - t0}
        assumptions = (f"onsets within {window_us / 1000:.0f} ms of the first onset are one event",
                       "the schema lists every path the sources share",
                       "a source counts as unaffected only if its admissible evidence had no break over the event")
        if support:
            paths = sorted({d[1] for d in support})
            out.append(Conclusion(
                "common_cause", ",".join(srcs), "SUPPORTED",
                f"a disturbance on {', '.join(paths)} is supported by {'; '.join(d[2] for d in support)}: sources "
                f"{', '.join(srcs)} lost admissible evidence {span}",
                tuple(f"disturbance on {p}" for p in paths) + ("independent causes coinciding with it",), basis, t0,
                level="conditional",
                assumptions=assumptions + ("the logged disturbance evidence belongs to this event",), shared=shared_d))
            continue
        cands: list[str] = []
        for pth in sorted(shared):
            if pth not in unaffected:
                cands.append(f"complete loss on {pth}")
            cands.append(f"partial or brief disturbance on {pth}")
        cands += ["independent causes"] + ([] if shared else ["a shared path not in the schema"])
        excl = "; ".join(f"complete loss on {pth} excluded ({', '.join(ks)} unaffected), a partial or brief "
                         f"disturbance there is not" for pth, ks in sorted(unaffected.items()))
        statement = (f"sources {', '.join(srcs)} lost admissible evidence {span}; "
                     + (f"they share {', '.join(sorted(shared))}; " if shared else "they share no path of the model; ")
                     + (excl + "; " if excl else "")
                     + "no direct evidence of a disturbance, so a common cause and independent causes both remain "
                       "possible")
        out.append(Conclusion("common_cause", ",".join(srcs), "AMBIGUOUS", statement, tuple(cands), basis, t0,
                              level="conditional", assumptions=assumptions, shared=shared_d))
    return out


def receipt(t_us: int, context: dict, evidence: dict, observations: list[Observation], conclusions: list[Conclusion],
            meta: dict) -> dict:
    """Everything needed to answer "why did the system say this?" from the logged evidence."""
    return {
        "advisory_only": True,
        "t_us": t_us,
        "schema_version": meta["schema_version"],
        "relation_set": meta["relation_set"],
        "data_class": meta["data_class"],
        "run_id": meta["run_id"],
        "context": context,
        "timing_policy": meta.get("timing_policy", "not stated"),
        "evidence": {s: {k: e.get(k) for k in ("state", "value", "reason", "t_ref_us", "t_unc_us", "t_unc_basis",
                                               "sample_age_known", "age_us", "source", "lineage")}
                     for s, e in evidence.items()},
        "admissible": sorted(s for s, e in evidence.items() if e["state"] == "VALID"),
        "rejected": {s: [e["state"], e["reason"]] for s, e in sorted(evidence.items()) if e["state"] != "VALID"},
        "observations": [o.as_dict() for o in observations],
        "conclusions": [c.as_dict() for c in conclusions],
        "reason": "; ".join(c.statement for c in conclusions if c.verdict != "UNSUPPORTED") or
                  "no supported or ambiguous conclusion at this time",
    }


RECEIPT_KEYS = ("advisory_only", "t_us", "schema_version", "relation_set", "data_class", "run_id", "timing_policy",
                "context", "evidence", "admissible", "rejected", "observations", "conclusions", "reason")


def receipt_problems(r: dict) -> list[str]:
    """What a receipt lacks to be reconstructible: every key, every observation's inputs accounted for (admitted
    or rejected with a state), every conclusion's basis among the observations or events."""
    out = [f"missing {k}" for k in RECEIPT_KEYS if k not in r]
    if out:
        return out
    if r["advisory_only"] is not True:
        out.append("not marked advisory")
    rel_ids = {o["relation"] for o in r["observations"]}
    for sig, e in r["evidence"].items():
        if "t_unc_basis" not in e or "sample_age_known" not in e:
            out.append(f"evidence {sig} lacks its timing basis")
            break
        if e.get("t_unc_us") is not None and e.get("t_unc_basis") is None:
            out.append(f"evidence {sig} has a timestamp bound without its basis")
    if r["data_class"] != "SIMULATED":
        for o in r["observations"]:
            used = [s for s in o["admitted"] if (r["evidence"].get(s) or {}).get("t_unc_basis") == "assumed"]
            if used:
                out.append(f"{o['relation']}: an assumed timestamp bound admitted for {r['data_class']} data")
    for o in r["observations"]:
        for s in [o["subject"]] + o["witnesses"]:
            if s not in o["admitted"] and s not in o["rejected"]:
                out.append(f"{o['relation']}: input {s} neither admitted nor rejected")
    for c in r["conclusions"]:
        if c["kind"] in ("relation", "localization") and not set(c["basis"]) <= rel_ids:
            out.append(f"conclusion on {c['subject']} cites relations not in the receipt")
        if any(w in c["statement"].lower() for w in FORBIDDEN_LABELS):
            out.append(f"conclusion on {c['subject']} names a fault")
        lvl = c.get("level")
        if lvl not in LEVELS:
            out.append(f"conclusion on {c['subject']} has no level")
        elif lvl == "established" and not c.get("record"):
            out.append(f"conclusion on {c['subject']} is established without a run record")
        elif lvl == "conditional" and not c.get("assumptions"):
            out.append(f"conditional conclusion on {c['subject']} states no assumptions")
        if c["kind"] == "localization" and lvl != "conditional":
            out.append(f"localization of {c['subject']} is not marked conditional")
    return out
