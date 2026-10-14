"""Load config/parameters.yaml (the parameter registry).

The registry is the single source of truth for configuration parameters. Both
the JSON schema and the C parameter table are generated from it, and both the
Python validator (tools/config_tool.py) and the C validator
(firmware/src/calibration/mc_config.c) consume those generated artefacts.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "config" / "parameters.yaml"


@dataclass(frozen=True)
class Param:
    id: int              # blob id of element 0 (arrays occupy id .. id+array-1)
    path: str
    kind: str            # real | int | bool | enum
    req_sim: bool
    req_hw: bool
    min: float | None = None
    max: float | None = None
    enum: str | None = None
    array: int = 0       # 0 = scalar

    @property
    def c_name(self) -> str:
        return "MC_P_" + self.path.replace(".", "_").upper()

    def element_ids(self) -> list[int]:
        return [self.id + k for k in range(self.array)] if self.array else [self.id]


@dataclass(frozen=True)
class StringField:
    path: str
    req_sim: bool
    req_hw: bool
    max_len: int | None = None


@dataclass
class Registry:
    enums: dict[str, dict[str, int]]
    params: list[Param]
    strings: list[StringField]
    by_path: dict[str, Param] = field(default_factory=dict)

    def __post_init__(self):
        self.by_path = {p.path: p for p in self.params}
        seen: dict[int, str] = {}
        for p in self.params:
            for eid in p.element_ids():
                if eid in seen:
                    raise ValueError(f"registry id {eid} reused by {p.path} and {seen[eid]}")
                if not 0 < eid < 256:
                    raise ValueError(f"registry id {eid} out of 1..255")
                seen[eid] = p.path
            if p.kind == "enum" and p.enum not in self.enums:
                raise ValueError(f"{p.path}: unknown enum {p.enum}")
            if p.kind in ("real", "int") and (p.min is None or p.max is None):
                raise ValueError(f"{p.path}: numeric parameter needs min/max")
            for bound in (p.min, p.max):
                # YAML 1.1 reads e.g. 1.0e5 (no exponent sign) as a string.
                if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float))):
                    raise ValueError(f"{p.path}: bound {bound!r} is not numeric (write 1.0e+5, not 1.0e5)")

    def element_paths(self):
        """Yield (blob_id, param, element_index_or_None)."""
        for p in self.params:
            if p.array:
                for k in range(p.array):
                    yield p.id + k, p, k
            else:
                yield p.id, p, None

    @property
    def max_id(self) -> int:
        return max(eid for eid, _, _ in self.element_paths())


def load_registry(path: pathlib.Path = REGISTRY_PATH) -> Registry:
    data = yaml.safe_load(path.read_text())
    params = [Param(**p) for p in data["params"]]
    strings = [StringField(**s) for s in data.get("strings", [])]
    return Registry(enums=data["enums"], params=params, strings=strings)
