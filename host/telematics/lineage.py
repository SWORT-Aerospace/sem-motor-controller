"""Lineage: which raw sources and shared paths a value, or a conclusion, depends on.

The schema (telematics/schema/telemetry_schema.yaml) gives every registry signal and every derived quantity its
raw source items (`controller:rotor_position_sensor`, `wheel:<channel>.edges`, ...) and the parameters a derivation
needs; every source lists the shared paths a common-cause event could take (`depends_on`: power, ground, bus,
clock), and `shared_paths` says which paths feed which.

Two answers are needed, and they differ:

  same_raw_source(a, b)    the two values come from the same sensor or estimate: not two witnesses at all
                           (vehicle speed from motor speed and from the controller's own odometer are one witness)
  shared_paths(a, b)       the values come from different sensors that share a path (the IMU and the TMP117 on
                           I2C1 and the 3.3 V rail): independent for a fault of one sensor, not for a fault of the
                           shared path

This is deliberately small: lists, not a graph engine.
"""
from __future__ import annotations

import functools
from typing import Iterable

from host.telematics import evidence


@functools.lru_cache(maxsize=1)
def _doc() -> dict:
    return evidence.schema()


def raw_sources(item: str) -> frozenset[str]:
    """Raw source items of a registry signal (channel-specific) or of a derived quantity in the schema."""
    lin = evidence.lineage(item)
    if lin:
        return frozenset(lin)
    for d in _doc()["derived"]:
        if d["id"] == item:
            return frozenset(d["lineage"]["raw"])
    raise KeyError(f"no lineage for {item!r}")


def parameters(item: str) -> frozenset[str]:
    for d in list(_doc()["derived"]) + list(_doc()["signals"]):
        if d["id"] == item or (evidence._signal_entry(item) is d):
            return frozenset(d["lineage"].get("parameters", ()))
    return frozenset()


def source_of(raw_item: str) -> str:
    return raw_item.split(":", 1)[0]


def _ancestors(path: str) -> set[str]:
    out, todo = set(), [path]
    feeds = _doc()["shared_paths"]
    while todo:
        p = todo.pop()
        if p in out:
            continue
        out.add(p)
        todo += [q for q, e in feeds.items() if p in e.get("feeds", ())]
    return out


def paths_of(item: str) -> frozenset[str]:
    """Shared paths of every source an item depends on, with the paths that feed them (a sensor supply fed by
    the 3.3 V rail depends on the unit supply too)."""
    out: set[str] = set()
    for r in raw_sources(item):
        for p in _doc()["sources"][source_of(r)]["depends_on"]:
            out |= _ancestors(p)
    return frozenset(out)


def same_raw_source(a: str, b: str) -> frozenset[str]:
    return raw_sources(a) & raw_sources(b)


def shared_paths(a: str, b: str) -> frozenset[str]:
    return paths_of(a) & paths_of(b)


def contributors(items: Iterable[str]) -> dict:
    """For a conclusion drawn from `items`: every raw source, every parameter and every shared path behind it."""
    items = list(items)
    return {"items": items,
            "raw_sources": sorted(set().union(*(raw_sources(i) for i in items))) if items else [],
            "parameters": sorted(set().union(*(parameters(i) for i in items))) if items else [],
            "shared_paths": sorted(set().union(*(paths_of(i) for i in items))) if items else []}


def independent_witnesses(a: str, b: str) -> tuple[bool, list[str]]:
    """Whether `b` can witness `a` against a fault of `a`'s own sensor: no raw source in common. Shared paths are
    returned as caveats: a fault on one of them can move both."""
    same = same_raw_source(a, b)
    caveats = [f"shares raw source {s}" for s in sorted(same)] + \
              [f"shares path {p}" for p in sorted(shared_paths(a, b))]
    return (not same), caveats
