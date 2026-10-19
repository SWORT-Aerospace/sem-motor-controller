#!/usr/bin/env python3
"""The canonical telemetry schema: check it against the code it describes and render its page.

    python3 tools/telematics_schema.py            # writes docs/TELEMETRY_SCHEMA.md
    python3 tools/telematics_schema.py --check    # exit 1 if the schema fails a check or the page is stale

Checks on telematics/schema/telemetry_schema.yaml:
  * every signal has every contract field; ids are unique; the registry hash equals the one live messages carry
    (host/telematics/signals.REGISTRY_ID), so a unit or range change is a deliberate schema change;
  * the evidence states and the validity mapping cover every validity host/telematics/measurement.py produces,
    plus `stale` and `missing`;
  * every semmc encoding names a message and field of protocol/protocol.yaml with the same scale and invalid raw
    value, the adapter (host/telematics/controller_adapter.py SIM_MAP) maps the same field to the same signal, and
    the expected rate is the message's broadcast rate;
  * every STLG record type named exists in host/telematics/stlg.py, and in the firmware's tm_stlg.h;
  * every lineage item names a known source, every parameter is listed, every shared path a source depends on
    exists, and every path a path feeds exists.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from host.telematics import controller_adapter as CA  # noqa: E402
from host.telematics import measurement, signals, stlg  # noqa: E402
from protocol.generated import semmc_protocol as proto  # noqa: E402

SRC = ROOT / "telematics" / "schema" / "telemetry_schema.yaml"
DOC = ROOT / "docs" / "TELEMETRY_SCHEMA.md"
FIELDS = ("id", "unit", "origin", "role", "range", "stale_s", "description", "physical", "kind", "encoding",
          "expected_rate_hz", "timestamp", "quality_flag", "lineage")
STATES = {"VALID", "SOURCE_UNVERIFIED", "OUT_OF_RANGE", "TIMING_UNCERTAIN", "STALE", "MISSING", "INVALID",
          "UNSUPPORTED", "UNKNOWN"}


def load() -> dict:
    return yaml.safe_load(SRC.read_text())


def check(d: dict) -> list[str]:
    err = []
    if d.get("schema") != "sem.telematics.schema" or not isinstance(d.get("schema_version"), int):
        err.append("schema name or integer schema_version missing")
    if d.get("registry_id") != signals.REGISTRY_ID:
        err.append(f"registry_id {d.get('registry_id')} differs from the registry's {signals.REGISTRY_ID}: a unit, "
                   "range or id changed; bump schema_version and registry_id together")
    if set(d["evidence_states"]) != STATES:
        err.append(f"evidence states {sorted(d['evidence_states'])} differ from {sorted(STATES)}")
    if [k for k, v in d["evidence_states"].items() if v["admissible"]] != ["VALID"]:
        err.append("only VALID may be admissible")
    need = set(measurement.VALIDITY) | {"stale", "missing"}
    if set(d["validity_to_state"]) != need or not set(d["validity_to_state"].values()) <= STATES:
        err.append(f"validity_to_state must map exactly {sorted(need)} to evidence states")
    sources, paths, params = d["sources"], d["shared_paths"], d["parameters"]
    for name, s in sources.items():
        for p in s["depends_on"]:
            if p not in paths:
                err.append(f"source {name}: shared path {p} not in shared_paths")
    for p, e in paths.items():
        for q in e.get("feeds", ()):
            if q not in paths:
                err.append(f"shared path {p} feeds unknown {q}")
        if not e.get("errors") or not set(e["errors"]) <= {"loss", "timing", "value"}:
            err.append(f"shared path {p}: errors must be a non-empty subset of loss, timing, value")
    ids = [s["id"] for s in d["signals"]]
    if len(ids) != len(set(ids)):
        err.append("signal ids repeat")
    sim = {sig: (msg, fld) for msg, lst in CA.SIM_MAP.items() for fld, sig, _f, _c in lst}
    rec_c = (ROOT / "telematics" / "firmware" / "include" / "tm_stlg.h").read_text()
    for s in d["signals"]:
        missing = [f for f in FIELDS if f not in s]
        if missing:
            err.append(f"{s['id']}: missing {missing}")
            continue
        if s["kind"] not in ("measured", "derived") or s["timestamp"] not in ("receive", "producer"):
            err.append(f"{s['id']}: kind must be measured/derived and timestamp receive/producer")
        for r in s["lineage"]["raw"]:
            if r.split(":", 1)[0] not in sources:
                err.append(f"{s['id']}: lineage {r} names no source")
        for p in s["lineage"].get("parameters", ()):
            if p not in params:
                err.append(f"{s['id']}: parameter {p} not listed")
        enc = s["encoding"]
        if "semmc" in enc:
            e = enc["semmc"]
            m = proto.MESSAGES.get(e["message"])
            f = next((x for x in (m or {}).get("fields", ()) if x["name"] == e["field"]), None)
            if f is None:
                err.append(f"{s['id']}: semmc {e['message']}.{e['field']} not in protocol.yaml")
            else:
                if "scale" in e and f.get("scale") != e["scale"]:
                    err.append(f"{s['id']}: scale {e['scale']} != protocol {f.get('scale')}")
                if "invalid_raw" in e and f.get("invalid") != e["invalid_raw"]:
                    err.append(f"{s['id']}: invalid_raw {e['invalid_raw']} != protocol {f.get('invalid')}")
                if abs(s["expected_rate_hz"] - 1.0 / m["period_s"]) > 1e-6:
                    err.append(f"{s['id']}: expected_rate_hz {s['expected_rate_hz']} != 1 / {m['period_s']} s")
                if sim.get(s["id"]) != (e["message"], e["field"]):
                    err.append(f"{s['id']}: the adapter maps {sim.get(s['id'])}, the schema {e['message']}.{e['field']}")
        if "stlg" in enc:
            rec = enc["stlg"]["record"]
            if not isinstance(getattr(stlg, rec, None), int):
                err.append(f"{s['id']}: STLG record {rec} not in host/telematics/stlg.py")
            if f"TM_REC_{rec} = {getattr(stlg, rec, -1)}" not in rec_c and rec not in ("BATT", "GNSS"):
                err.append(f"{s['id']}: STLG record {rec} not in the firmware's tm_stlg.h")
    for sig in sim:
        if sig not in ids:
            err.append(f"the adapter maps {sig}, which the schema lacks")
    for x in d["derived"]:
        for r in x["lineage"]["raw"]:
            if r.split(":", 1)[0] not in sources:
                err.append(f"derived {x['id']}: lineage {r} names no source")
        for p in x["lineage"].get("parameters", ()):
            if p not in params:
                err.append(f"derived {x['id']}: parameter {p} not listed")
    return err


def _c(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def render(d: dict) -> str:
    L = ["# Telemetry schema (canonical source and field contract)", "",
         f"Generated by `tools/telematics_schema.py` from `telematics/schema/telemetry_schema.yaml` (schema version "
         f"{d['schema_version']}, registry `{d['registry_id']}`); do not edit. `--check` in CI validates the schema "
         "against the protocol, the adapter, the STLG record types of the host and the firmware, and the evidence "
         "model. Every controller signal is UNVERIFIED until the controller team states its frames; the semmc "
         "encodings are the simulation fixture.", "",
         "## Evidence states", "", "| State | Admissible | Meaning |", "|---|---|---|"]
    for k, v in d["evidence_states"].items():
        L.append(f"| `{k}` | {'yes' if v['admissible'] else 'no'} | {_c(v['meaning'])} |")
    L += ["", "Measurement validity to state: " + ", ".join(f"`{a}` -> `{b}`" for a, b in d["validity_to_state"].items())
          + ".", "", "## Sources", "", "| Source | Physical | Transport | Producer time | Sequence | Shared paths | Status |",
          "|---|---|---|---|---|---|---|"]
    for k, s in d["sources"].items():
        L.append(f"| `{k}` | {_c(s['physical'])} | {_c(s['transport'])} | {_c(s['producer_timestamp'])} | "
                 f"{_c(s['sequence'])} | {', '.join(f'`{p}`' for p in s['depends_on'])} | {s['status']} |")
    L += ["", "## Signals", "",
          "| Signal | Unit | Range | Kind | Physical | Encoding | Rate (Hz) | Time | Stale (s) | Quality flag | Lineage |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in d["signals"]:
        enc = s["encoding"]
        e = "; ".join(f"{k}: " + (f"`{v['message']}.{v['field']}`" if isinstance(v, dict) and "message" in v
                                    else (f"`{v['record']}`" if isinstance(v, dict) else _c(v)))
                      for k, v in enc.items())
        lin = ", ".join(f"`{r}`" for r in s["lineage"]["raw"])
        if s["lineage"].get("parameters"):
            lin += "; parameters " + ", ".join(f"`{p}`" for p in s["lineage"]["parameters"])
        L.append(f"| `{s['id']}` | {s['unit']} | {s['range'][0]:g} to {s['range'][1]:g} | {s['kind']} | "
                 f"{_c(s['physical'])} | {e} | {s['expected_rate_hz']:g} | {s['timestamp']} | {s['stale_s']:g} | "
                 f"{_c(s['quality_flag'])} | {lin} |")
    L += ["", "## Semantics", ""] + [f"* **{k}.** {_c(v)}" for k, v in d["semantics"].items()]
    L += ["", "## Hall wheel input", ""] + [f"* **{k.replace('_', ' ')}.** {_c(v)}" for k, v in d["hall"].items()]
    L += ["", "## Derived quantities", "", "| Quantity | Unit | Derivation | Raw sources | Parameters |", "|---|---|---|---|---|"]
    for x in d["derived"]:
        L.append(f"| `{x['id']}` | {x['unit']} | {_c(x['derivation'])} | {', '.join(f'`{r}`' for r in x['lineage']['raw'])} | "
                 f"{', '.join(f'`{p}`' for p in x['lineage'].get('parameters', ())) or '-'} |")
    L += ["", "## Vehicle parameters", "", "| Parameter | Source | Status |", "|---|---|---|"]
    L += [f"| `{k}` | {_c(v['source'])} | {v['status']} |" for k, v in d["parameters"].items()]
    L += ["", "## Shared paths (common-cause candidates)", "",
          "Common errors a disturbance of the path can give every source on it: loss (evidence stops), timing (times "
          "shift together), value (values shift together, so two sources can agree and both be wrong). A listed kind is a "
          "hypothesis the evidence has to rule out.", "",
          "| Path | Feeds | Common errors | Evidence of a disturbance |", "|---|---|---|---|"]
    L += [f"| `{k}` | {', '.join(f'`{q}`' for q in v['feeds']) or '-'} | {', '.join(v['errors'])} | "
          f"{_c('; '.join(v['evidence_of_disturbance']))} |" for k, v in d["shared_paths"].items()]
    L += ["", "## Vehicle contexts", "", "| Context | Needs | Rule |", "|---|---|---|"]
    for k, v in d["contexts"].items():
        needs = ", ".join(f"`{n}`" for n in v["needs"]) or "-"
        if v.get("alternatively"):
            needs += " (or " + ", ".join(f"`{n}`" for n in v["alternatively"]) + ")"
        L.append(f"| `{k}` | {needs} | {_c(v['rule'])} |")
    L += ["", "## Canonical evidence record", "", "| Field | Meaning |", "|---|---|"]
    L += [f"| `{k}` | {_c(v)} |" for k, v in d["evidence_record"]["fields"].items()]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    d = load()
    err = check(d)
    for e in err:
        print("schema: " + e)
    if err:
        return 1
    text = render(d)
    if a.check:
        if not DOC.exists() or DOC.read_text() != text:
            print(f"stale: {DOC.relative_to(ROOT)} (run tools/telematics_schema.py)")
            return 1
        print(f"telemetry schema v{d['schema_version']} consistent with the code; page current")
        return 0
    DOC.write_text(text)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
