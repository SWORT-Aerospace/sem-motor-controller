"""Signal registry: identity, unit, role and plausible range of every quantity the telematics unit reports.

The registry is read from the canonical schema, telematics/schema/telemetry_schema.yaml, which also holds each
signal's source, encoding, rate, timestamp, freshness, invalid and missing semantics and lineage.

A measurement (measurement.py) names one of these signals. The registry is the single list that the node,
the controller adapters, the pit validation and the energy analysis share, so a unit or a range is defined
once. Signals that come from the external motor controller are `origin: controller`; the controller team
decides what they broadcast (docs/CONTROLLER_INTERFACE_REQUEST.md), so every one of them may be absent.

Roles:
  energy_essential     needed for controller input energy (DC voltage and DC current at the controller input)
  energy_total         needed for total battery energy (battery-side voltage and current: our own monitor,
                       which also sees the telematics unit and every auxiliary load)
  diagnostic_optional  useful for diagnostics and the shadow-mode monitors; nothing depends on them
  motion               speed, distance and attitude from the unit's own sensors
  environment          temperatures from the unit's own probes

The unit's own health (queue high water, drops, restarts) is not a measurement: it is in the counters
(stlg COUNTERS2) and the live message's `counters` block.

`stale_s` is how old a value may be before a live summary reports it as stale (value null). The values for
controller signals assume the broadcast periods of the simulation fixture and are PROVISIONAL until the
controller team states its periods.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import pathlib

import yaml

ROLES = ("energy_essential", "energy_total", "diagnostic_optional", "motion", "environment")


@dataclasses.dataclass(frozen=True)
class Signal:
    id: str                 # may contain one "*" for a channel name, e.g. "wheel.*.speed"
    unit: str
    origin: str             # "controller" (external, through an adapter) or "telematics" (our own sensor)
    role: str
    lo: float
    hi: float
    stale_s: float
    description: str


SCHEMA_PATH = pathlib.Path(__file__).resolve().parents[2] / "telematics" / "schema" / "telemetry_schema.yaml"


def _load() -> tuple[Signal, ...]:
    """The registry is the `signals` list of the canonical schema (telematics/schema/telemetry_schema.yaml)."""
    doc = yaml.safe_load(SCHEMA_PATH.read_text())
    out = []
    for e in doc["signals"]:
        lo, hi = e["range"]
        out.append(Signal(e["id"], str(e["unit"]), e["origin"], e["role"], float(lo), float(hi), float(e["stale_s"]),
                          e["description"]))
    return tuple(out)


REGISTRY: tuple[Signal, ...] = _load()


def _registry_id() -> str:
    import hashlib
    h = hashlib.sha256("|".join(f"{s.id}:{s.unit}:{s.lo!r}:{s.hi!r}" for s in REGISTRY).encode()).hexdigest()
    return "reg-" + h[:12]


# Named in every live message: the units and ranges a live value refers to. The pit refuses a message whose
# registry differs from its own (it would not know the units).
REGISTRY_ID = _registry_id()


def lookup(signal_id: str) -> Signal | None:
    for s in REGISTRY:
        if s.id == signal_id or ("*" in s.id and fnmatch.fnmatchcase(signal_id, s.id) and "." in signal_id):
            return s
    return None


def in_range(signal_id: str, value: float) -> bool:
    s = lookup(signal_id)
    return s is not None and s.lo <= value <= s.hi


def by_role(role: str) -> list[Signal]:
    return [s for s in REGISTRY if s.role == role]
