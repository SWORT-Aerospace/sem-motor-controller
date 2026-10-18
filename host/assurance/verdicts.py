"""Advisory conclusions from witness observations, and the receipts that let anyone check them.

Verdicts (advisory, never a command):

  SUPPORTED    the claim agrees with admissible, independent evidence in a context where it applies
  AMBIGUOUS    an inconsistency was observed and the evidence does not isolate its cause; the open candidates
               are listed
  UNSUPPORTED  no conclusion: the claim is not applicable now, or the evidence is not admissible

No conclusion names a fault ("sensor fault", "motor fault", "battery fault"). The strongest statement is that an
inconsistency is localized to one evidence path: the subject disagrees with two witnesses that are independent of
it and of each other and that agree with each other. Even then the cause on that path (sensor, wiring, parameter,
a real local effect) stays open.

Common cause (family C): simultaneous loss of admissible evidence in several sources is reported with the shared
paths those sources have in common (host/telematics/lineage.py). A shared path stays a candidate only if no source
that also depends on it kept admissible evidence through the event (that source exonerates it). A shared-path event
is SUPPORTED only with direct evidence of a disturbance on a remaining candidate path (a brown-out reset cause, a bus
error status, a session that ended without its final record); otherwise it is AMBIGUOUS: a common cause and
independent causes both remain possible.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Iterable, Optional

from host.assurance.witnesses import Observation
from host.telematics import lineage

VERDICTS = ("SUPPORTED", "AMBIGUOUS", "UNSUPPORTED")
FORBIDDEN_LABELS = ("sensor fault", "motor fault", "battery fault", "controller fault", "faulty", "has failed")

PATH_CANDIDATES = {
    "wheel": ("the Hall sensor, magnet or wiring of that wheel", "the circumference or pulses per revolution set for it",
              "slip or lock at that wheel", "edges lost or extra on that channel"),
    "ctrl": ("the controller's own sensor or estimate", "the adapter mapping or scaling", "a drivetrain parameter"),
    "gnss": ("the receiver's fix quality, multipath or antenna", "time alignment of the GNSS stream"),
    "imu": ("the IMU mounting, axis or offset", "the sensor", "the bus read"),
    "temp": ("the temperature sensor or its contact", "the bus read"),
    "batt": ("the battery-side monitor or its shunt",),
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

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["candidates"], d["basis"] = list(self.candidates), list(self.basis)
        return d


def from_observation(o: Observation) -> Conclusion:
    if o.result == "CONSISTENT":
        return Conclusion("relation", o.relation, "SUPPORTED", f"supported: {o.claim} ({o.detail})", (), (o.relation,))
    if o.result == "INCONSISTENT":
        return Conclusion("relation", o.relation, "AMBIGUOUS",
                          f"observed inconsistency: {o.claim} does not hold now ({o.detail}); cause not isolated",
                          o.causes_if_inconsistent, (o.relation,))
    return Conclusion("relation", o.relation, "UNSUPPORTED", f"no conclusion on '{o.claim}': {o.detail}", (),
                      (o.relation,))


# relations that compare two estimates of the same quantity (vehicle speed): only these can localize
SAME_QUANTITY = ("B1:", "B2:", "B3:")


def _edges(observations: Iterable[Observation]) -> list[tuple[str, str, str, str]]:
    """(subject, primary witness, result, relation) for every same-quantity comparison that gave a result."""
    return [(o.subject, o.witnesses[0], o.result, o.relation) for o in observations
            if o.relation.startswith(SAME_QUANTITY) and o.result in ("CONSISTENT", "INCONSISTENT")]


def _indep(a: str, b: str) -> bool:
    try:
        return lineage.independent_witnesses(a, b)[0]
    except KeyError:
        return False


def localize(observations: list[Observation]) -> list[Conclusion]:
    edges = _edges(observations)
    agree = {frozenset((a, b)) for a, b, r, _ in edges if r == "CONSISTENT"}
    out = []
    nodes = {x for a, b, _r, _ in edges for x in (a, b)}
    for x in sorted(nodes):
        against = sorted({(b if a == x else a, rel) for a, b, r, rel in edges if r == "INCONSISTENT" and x in (a, b)})
        others = sorted({y for y, _ in against})
        for i, y in enumerate(others):
            for z in others[i + 1:]:
                if frozenset((y, z)) in agree and _indep(x, y) and _indep(x, z) and _indep(y, z):
                    src = x.split(".")[0] if not x.startswith("wheel.") else "wheel"
                    out.append(Conclusion(
                        "localization", x, "AMBIGUOUS",
                        f"inconsistency localized to the evidence path of {x}: it disagrees with {y} and {z}, which "
                        f"are independent of it and of each other and agree with each other; the cause on that path "
                        f"is not isolated",
                        PATH_CANDIDATES.get(src, ("the evidence path of " + x,)),
                        tuple(rel for _y, rel in against if _y in (y, z))))
                    break
            else:
                continue
            break
    return out


def common_cause(onsets: list[tuple[int, str, str, Optional[str]]], window_us: int,
                 disturbances: list[tuple[int, str, str]],
                 still_admissible: Optional[Callable[[int, int], set[str]]] = None) -> list[Conclusion]:
    """`onsets`: (t_us, source, signal, reason) where a signal stopped being admissible. `disturbances`:
    (t_us, path, description) of direct evidence on a shared path (a brown-out reset cause, a bus error status).
    `still_admissible(a, b)`: the signals with fresh admissible evidence received in (a, b], asked for the window
    after the event. Onsets within `window_us` of each other from two or more sources form one event."""
    out = []
    onsets = sorted(onsets)
    i = 0
    while i < len(onsets):
        j = i
        while j + 1 < len(onsets) and onsets[j + 1][0] - onsets[j][0] <= window_us:
            j += 1
        grp = onsets[i:j + 1]
        i = j + 1
        srcs = sorted({s for _t, s, _g, _r in grp})
        if len(srcs) < 2:
            continue
        t0, t1 = grp[0][0], grp[-1][0]
        sigs = sorted({g for _t, _s, g, _r in grp})
        try:
            shared = set.intersection(*(set(lineage.paths_of(g)) for g in sigs))
        except KeyError:
            shared = set()
        kept = sorted(still_admissible(t1, t1 + window_us)) if still_admissible else []
        disturbed = {d[1] for d in disturbances if t0 - window_us <= d[0] <= t1 + window_us}
        exonerated: dict[str, str] = {}
        for k in kept:
            try:
                for pth in (lineage.paths_of(k) & shared) - disturbed:
                    exonerated.setdefault(pth, k)
            except KeyError:
                pass
        shared -= set(exonerated)
        support = [d for d in disturbances if t0 - window_us <= d[0] <= t1 + window_us and d[1] in shared]
        basis = tuple(f"{g} {r or ''}".strip() for _t, _s, g, r in grp)
        exo = "; ".join(f"{pth} exonerated by {k}, still admissible" for pth, k in sorted(exonerated.items()))
        if shared and support:
            paths = sorted({d[1] for d in support})
            out.append(Conclusion("common_cause", ",".join(srcs), "SUPPORTED",
                                  f"a shared-path event on {', '.join(paths)} is supported by "
                                  f"{'; '.join(d[2] for d in support)}: sources {', '.join(srcs)} lost admissible "
                                  f"evidence together", tuple(f"disturbance on {p}" for p in paths), basis, t0))
        elif shared:
            out.append(Conclusion("common_cause", ",".join(srcs), "AMBIGUOUS",
                                  f"sources {', '.join(srcs)} lost admissible evidence within "
                                  f"{(t1 - t0) / 1000:.0f} ms; they share {', '.join(sorted(shared))}; no direct "
                                  "evidence of a disturbance there, so a common cause and independent causes both "
                                  "remain possible",
                                  tuple(f"event on {p}" for p in sorted(shared)) + ("independent causes",), basis,
                                  t0))
        else:
            out.append(Conclusion("common_cause", ",".join(srcs), "AMBIGUOUS",
                                  f"sources {', '.join(srcs)} lost admissible evidence together but no shared path of "
                                  f"the model remains a candidate{' (' + exo + ')' if exo else ''}: independent causes, "
                                  "or a path the model does not contain",
                                  ("independent causes", "a shared path not in the schema"), basis, t0))
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
        "evidence": {s: {k: e[k] for k in ("state", "value", "reason", "t_ref_us", "age_us", "source", "lineage")}
                     for s, e in evidence.items()},
        "admissible": sorted(s for s, e in evidence.items() if e["state"] == "VALID"),
        "rejected": {s: [e["state"], e["reason"]] for s, e in sorted(evidence.items()) if e["state"] != "VALID"},
        "observations": [o.as_dict() for o in observations],
        "conclusions": [c.as_dict() for c in conclusions],
        "reason": "; ".join(c.statement for c in conclusions if c.verdict != "UNSUPPORTED") or
                  "no supported or ambiguous conclusion at this time",
    }


RECEIPT_KEYS = ("advisory_only", "t_us", "schema_version", "relation_set", "data_class", "run_id", "context",
                "evidence", "admissible", "rejected", "observations", "conclusions", "reason")


def receipt_problems(r: dict) -> list[str]:
    """What a receipt lacks to be reconstructible: every key, every observation's inputs accounted for (admitted
    or rejected with a state), every conclusion's basis among the observations or events."""
    out = [f"missing {k}" for k in RECEIPT_KEYS if k not in r]
    if out:
        return out
    if r["advisory_only"] is not True:
        out.append("not marked advisory")
    rel_ids = {o["relation"] for o in r["observations"]}
    for o in r["observations"]:
        for s in [o["subject"]] + o["witnesses"]:
            if s not in o["admitted"] and s not in o["rejected"]:
                out.append(f"{o['relation']}: input {s} neither admitted nor rejected")
    for c in r["conclusions"]:
        if c["kind"] in ("relation", "localization") and not set(c["basis"]) <= rel_ids:
            out.append(f"conclusion on {c['subject']} cites relations not in the receipt")
        if any(w in c["statement"].lower() for w in FORBIDDEN_LABELS):
            out.append(f"conclusion on {c['subject']} names a fault")
    return out
