#!/usr/bin/env python3
"""Generate config/vehicle.schema.json and the C parameter table from the registry.

Usage:
    python3 tools/gen_config.py            # write generated files
    python3 tools/gen_config.py --check    # exit 1 if generated files are stale
"""
from __future__ import annotations

import argparse
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools.config_registry import ROOT, load_registry  # noqa: E402

SCHEMA_PATH = ROOT / "config" / "vehicle.schema.json"
C_HEADER_PATH = ROOT / "firmware" / "include" / "semmc" / "mc_params_generated.h"

CONVENTIONS = {
    "units": "SI",
    "battery_current_positive": "discharge",
    "phase_current_positive": "into_motor_terminal",
    "torque_positive": "forward_motoring",
    "clarke": "amplitude_invariant",
    "resistance": "line_to_neutral",
    "inductance": "line_to_neutral",
    "flux_linkage": "peak_phase_amplitude_invariant",
    "temperature": "degC",
    "angle": "rad_electrical_from_phase_a_axis",
}

SECTIONS = ["calibration", "motor", "battery", "vehicle", "inverter", "limits", "supervision"]


def _param_schema(p, reg):
    if p.kind == "real":
        item = {"type": ["number", "null"], "minimum": p.min, "maximum": p.max}
    elif p.kind == "int":
        item = {"type": ["integer", "null"], "minimum": int(p.min), "maximum": int(p.max)}
    elif p.kind == "bool":
        item = {"type": ["boolean", "null"]}
    elif p.kind == "enum":
        item = {"enum": sorted(reg.enums[p.enum].keys()) + [None]}
    else:  # pragma: no cover
        raise ValueError(p.kind)
    if p.array:
        return {"type": ["array", "null"], "items": item, "minItems": p.array, "maxItems": p.array}
    return item


def build_schema(reg) -> dict:
    sections: dict[str, dict] = {s: {} for s in SECTIONS}
    for p in reg.params:
        sec, name = p.path.split(".", 1)
        sections[sec][name] = _param_schema(p, reg)
    for s in reg.strings:
        sec, name = s.path.split(".", 1)
        ent = {"type": ["string", "null"]}
        if s.max_len:
            ent["maxLength"] = s.max_len
        sections[sec][name] = ent
    props = {}
    for sec, fields in sections.items():
        fields["notes"] = {"type": ["string", "null"]}
        props[sec] = {
            "type": "object",
            "additionalProperties": False,
            "required": sorted(k for k in fields if k != "notes"),
            "properties": fields,
        }
    props["schema_version"] = {"const": 1}
    props["label"] = {"type": "string"}
    props["conventions"] = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(CONVENTIONS),
        "properties": {k: {"const": v} for k, v in CONVENTIONS.items()},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://swort.net/schemas/sem-motor-controller/vehicle.schema.json",
        "title": "SEM motor controller vehicle/calibration configuration",
        "description": "GENERATED from config/parameters.yaml by tools/gen_config.py - do not edit. "
                       "Every key must be present; unknown values are null. Structural validity "
                       "only: ranges, required-for-build and cross-parameter rules are enforced "
                       "by tools/config_tool.py and firmware/src/calibration/mc_config.c.",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "label", "conventions"] + SECTIONS,
        "properties": props,
    }


def _cfloat(v: float) -> str:
    r = repr(float(v))
    if "e" in r or "E" in r:
        return r + "f" if "." in r.split("e")[0] else r.replace("e", ".0e") + "f"
    return r + "f"


def build_c_header(reg) -> str:
    lines = [
        "/* GENERATED from config/parameters.yaml by tools/gen_config.py - do not edit. */",
        "#ifndef SEMMC_MC_PARAMS_GENERATED_H",
        "#define SEMMC_MC_PARAMS_GENERATED_H",
        "",
        "#include <stdint.h>",
        "",
        "/* Parameter element ids in the calibration blob. */",
        "typedef enum {",
    ]
    for eid, p, k in reg.element_paths():
        name = p.c_name + (f"_{k}" if k is not None else "")
        lines.append(f"    {name} = {eid},")
    lines += [f"    MC_P_MAX_ID = {reg.max_id}", "} mc_param_id_t;", ""]
    lines.append("/* Enumerations (values stored as exact small floats in the blob). */")
    for ename, values in reg.enums.items():
        for vname, v in sorted(values.items(), key=lambda kv: kv[1]):
            lines.append(f"#define MC_{ename.upper()}_{vname.upper()} {v}")
        lines.append(f"#define MC_{ename.upper()}_COUNT {max(values.values()) + 1}")
    lines += [
        "",
        "#define MC_PKIND_REAL 0",
        "#define MC_PKIND_INT  1",
        "#define MC_PKIND_BOOL 2",
        "#define MC_PKIND_ENUM 3",
        "",
        "typedef struct {",
        "    uint8_t id;",
        "    uint8_t kind;",
        "    uint8_t req_sim;",
        "    uint8_t req_hw;",
        "    float min;",
        "    float max;",
        "    const char *path;",
        "} mc_param_info_t;",
        "",
        "#define MC_PARAM_TABLE_INIT { \\",
    ]
    kinds = {"real": 0, "int": 1, "bool": 2, "enum": 3}
    for eid, p, k in reg.element_paths():
        if p.kind in ("real", "int"):
            lo, hi = p.min, p.max
        elif p.kind == "bool":
            lo, hi = 0, 1
        else:
            vals = reg.enums[p.enum].values()
            lo, hi = min(vals), max(vals)
        path = p.path + (f"[{k}]" if k is not None else "")
        lines.append(
            f"    {{{eid}u, {kinds[p.kind]}u, {int(p.req_sim)}u, {int(p.req_hw)}u, "
            f"{_cfloat(lo)}, {_cfloat(hi)}, \"{path}\"}}, \\")
    lines += ["}", "", f"#define MC_PARAM_COUNT {sum(1 for _ in reg.element_paths())}", "",
              "#endif /* SEMMC_MC_PARAMS_GENERATED_H */", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    reg = load_registry()
    outputs = {
        SCHEMA_PATH: json.dumps(build_schema(reg), indent=2) + "\n",
        C_HEADER_PATH: build_c_header(reg),
    }
    stale = []
    for path, text in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        for p in stale:
            print(f"STALE: {p.relative_to(ROOT)} (run tools/gen_config.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
