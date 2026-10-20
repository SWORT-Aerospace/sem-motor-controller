#!/usr/bin/env python3
"""The telematics bench package: one procedure, one parts list, one set of images, one blank results form.

    python3 tools/telematics_bench.py render            # writes BENCH.md and BENCH_MINIMAL.md from bench.yaml
    python3 tools/telematics_bench.py render --check    # exit 1 if either page is stale or bench.yaml fails a check
    python3 tools/telematics_bench.py package --images build-u575 --out build/telematics_bench [--rebuild]
    python3 tools/telematics_bench.py package --minimal --images build-u575 --host-build build-telematics \
        --out build/telematics_bench_minimal [--rebuild]

The single source is telematics/bench/bench.yaml. Its connection rows name the firmware line that sets each pin
up, its steps quote console text that the firmware prints, and its parts are the `bench` lines of
hardware/telematics/bom.yaml; `render --check` fails when any of those no longer holds, so the procedure cannot
drift from the code or the parts list. Recording durations come from docs/generated/telematics_storage.json.

`package` copies the target images and writes MANIFEST.json (SHA-256 and size of every file, the source
revision, the revision string inside each image, the compiler), BENCH.md, CONNECTIONS.csv, PARTS.csv, a blank
RESULTS_FORM.md and results.yaml, and tools/uart_capture.py. It refuses images built from another revision or
from a modified tree (--allow-dirty marks the package as not valid for a recorded bench run). --rebuild builds
the images again in a new directory and records whether every hash is equal. Nothing here flashes or runs the
board: every connection stays unverified until a filled results form says otherwise.

`package --minimal` is the first physical chain only (bench.yaml, section minimal): tm_u575 alone, the six
connection rows it uses, its parts and equipment, the document checks to answer before flashing with the request for
the PDFs this environment cannot download, a blank results form for steps M0 to M4, and a SIMULATED rehearsal: the
minimal procedure run on the host simulator and read back through the same chain command the bench uses
(tools/run_bench_chain.py --rehearse-minimal), so the operator sees what each check prints before the board does.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import telematics_bom as tb  # noqa: E402

SRC = ROOT / "telematics" / "bench" / "bench.yaml"
DOC = ROOT / "telematics" / "firmware" / "BENCH.md"
DOC_MIN = ROOT / "telematics" / "firmware" / "BENCH_MINIMAL.md"
STORAGE = ROOT / "docs" / "generated" / "telematics_storage.json"
FW = ROOT / "telematics" / "firmware"
STEP_IDS = [f"B{k}" for k in range(14)]
MIN_STEP_IDS = [f"M{k}" for k in range(5)]
IMAGE_EXT = (".elf", ".bin", ".hex", ".map")
COMPARED = (".elf", ".bin", ".hex")       # the map names the build directory's object paths


def load() -> dict:
    return yaml.safe_load(SRC.read_text())


def values() -> dict:
    """The numbers the steps quote, from the measured recording durations."""
    st = json.loads(STORAGE.read_text())
    mix = {m["id"]: m for m in st["mixes"]}
    w, i = mix["wheel"]["storages"], mix["wheel_imu_temp"]["storages"]
    return {"overflow_s": f"{2 ** 32 / 1e6:.3f}",
            "wheel_sps": f"{mix['wheel']['seconds_per_slot']:.2f}",
            "wheel_internal_full_min": f"{w['internal flash bank 2']['full_rate_s'] / 60:.1f}",
            "imu_internal_full_min": f"{i['internal flash bank 2']['full_rate_s'] / 60:.1f}",
            "wheel_nor_full_s": f"{w['W25Q128JV NOR']['full_rate_s']}",
            "imu_nor_full_s": f"{i['W25Q128JV NOR']['full_rate_s']}",
            "sparse_period_s": f"{st['config']['sparse_period_s']:.0f}"}


def fill(text: str, vals: dict) -> str:
    def sub(m):
        if m.group(1) not in vals:
            raise KeyError(f"unknown value [[{m.group(1)}]]")
        return vals[m.group(1)]
    return re.sub(r"\[\[(\w+)\]\]", sub, text)


def _bench_lines(bom: dict, config: str) -> dict:
    return {l["id"]: l for l in bom["lines"] if l["config"] == config}


def validate(d: dict, bom: dict) -> list[str]:
    err = []
    steps = [s["id"] for s in d["steps"]]
    if steps != STEP_IDS:
        err.append(f"steps must be {STEP_IDS[0]} to {STEP_IDS[-1]} in order, got {steps}")
    vals = values()
    for s in d["steps"]:
        for k in ("title", "do", "expect", "record"):
            if not s.get(k):
                err.append(f"{s['id']}: no {k}")
        for k in ("do", "expect"):
            try:
                fill(s.get(k, ""), vals)
            except KeyError as e:
                err.append(f"{s['id']}: {e}")
        for ref in re.findall(r"commands\.(\w+)", f"{s.get('do', '')} {s.get('expect', '')}"):
            if ref.rstrip("_") not in d["commands"] and not any(c.startswith(ref.rstrip("_")) for c in d["commands"]):
                err.append(f"{s['id']}: commands.{ref} is not in commands")
        for c in s.get("firmware_text") or []:
            p = ROOT / c["file"]
            if not p.exists() or c["contains"] not in p.read_text():
                err.append(f"{s['id']}: {c['file']} does not contain {c['contains']!r}")
    bench = _bench_lines(bom, "bench")
    equip = _bench_lines(bom, "equipment")
    ids = [c["id"] for c in d["connections"]]
    if len(ids) != len(set(ids)):
        err.append("connection ids repeat")
    used = set()
    for c in d["connections"]:
        if c.get("part"):
            used.add(c["part"])
            if c["part"] not in bench:
                err.append(f"connection {c['id']}: part {c['part']} is not a bench line of the BOM")
        chk = c.get("check")
        if chk:
            p = ROOT / chk["file"]
            if not p.exists() or chk["contains"] not in p.read_text():
                err.append(f"connection {c['id']}: {chk['file']} does not contain {chk['contains']!r}")
        elif c["mcu"] not in ("-", ""):
            err.append(f"connection {c['id']}: MCU pin {c['mcu']} without the firmware line that sets it up")
    other = d.get("parts_without_a_row") or {}
    for k in other:
        if k not in bench:
            err.append(f"parts_without_a_row: {k} is not a bench line of the BOM")
        if k in used:
            err.append(f"parts_without_a_row: {k} is already the part of a connection row")
    missing = set(bench) - used - set(other)
    if missing:
        err.append(f"bench BOM lines used nowhere in the procedure: {sorted(missing)}")
    if d["parts_config"] != "bench":
        err.append("parts_config must be the BOM's bench configuration")
    for e in d["equipment"]:
        if e not in equip:
            err.append(f"equipment {e} is not an equipment line of the BOM")
    cm = (FW / "CMakeLists.txt").read_text()
    for im in d["images"]:
        if im["name"] not in cm:
            err.append(f"image {im['name']} is not built by telematics/firmware/CMakeLists.txt")
    for e in d["electrical"]["checks"]:
        if not (e.get("method") and e.get("pass")):
            err.append(f"{e['id']}: method and pass criterion needed")
    return err + validate_minimal(d, bom)


def _contains(c: dict) -> bool:
    p = ROOT / c["file"]
    return p.exists() and c["contains"] in p.read_text()


def validate_minimal(d: dict, bom: dict) -> list[str]:
    """The minimal bench (section minimal), the documents and the document checks."""
    err, m = [], d["minimal"]
    bench, equip = _bench_lines(bom, "bench"), _bench_lines(bom, "equipment")
    conns = {c["id"]: c for c in d["connections"]}
    if m["image"] not in [im["name"] for im in d["images"]]:
        err.append(f"minimal: image {m['image']} is not one of the bench images")
    for c in m["connections"]:
        if c not in conns:
            err.append(f"minimal: connection {c} is not a row of the connection table")
        elif conns[c].get("part") and conns[c]["part"] not in m["parts"]:
            err.append(f"minimal: connection {c} needs part {conns[c]['part']}, not in the minimal parts")
    for c in m.get("open") or []:
        if c not in m["connections"]:
            err.append(f"minimal: open row {c} is not one of its connections")
    for k in m["parts"]:
        if k not in bench:
            err.append(f"minimal: part {k} is not a bench line of the BOM")
    for e in m["equipment"]:
        if e not in equip:
            err.append(f"minimal: equipment {e} is not an equipment line of the BOM")
        if not (m.get("equipment_use") or {}).get(e):
            err.append(f"minimal: equipment {e} without its use on this bench")
    steps = [s["id"] for s in m["steps"]]
    if steps != MIN_STEP_IDS:
        err.append(f"minimal: steps must be {MIN_STEP_IDS[0]} to {MIN_STEP_IDS[-1]} in order, got {steps}")
    for s in m["steps"]:
        for k in ("title", "do", "expect", "record"):
            if not s.get(k):
                err.append(f"minimal {s['id']}: no {k}")
        text = f"{s.get('do', '')} {s.get('expect', '')}"
        for ref in re.findall(r"\bcommands\.(\w+)", text):
            if ref not in d["commands"]:
                err.append(f"minimal {s['id']}: commands.{ref} is not in commands")
        for ref in re.findall(r"\bminimal\.(\w+)", text):
            if ref not in m["commands"]:
                err.append(f"minimal {s['id']}: minimal.{ref} is not in the minimal commands")
        for c in s.get("firmware_text") or []:
            if not _contains(c):
                err.append(f"minimal {s['id']}: {c['file']} does not contain {c['contains']!r}")
    if not m.get("needs_a_board"):
        err.append("minimal: the list of what needs a real board is empty")
    docs = {x["id"]: x for x in d["documents"]}
    if len(docs) != len(d["documents"]):
        err.append("documents: ids repeat")
    for x in d["documents"]:
        for k in ("file", "title", "part", "maker", "page"):
            if not x.get(k):
                err.append(f"document {x.get('id')}: no {k}")
    ids = [c["id"] for c in d["document_checks"]]
    if len(ids) != len(set(ids)):
        err.append("document checks: ids repeat")
    allowed = set(MIN_STEP_IDS) | set(STEP_IDS)
    used = set()
    for c in d["document_checks"]:
        used.add(c["doc"])
        if c["doc"] not in docs:
            err.append(f"{c['id']}: document {c['doc']} is not in documents")
        if c["before"] not in allowed:
            err.append(f"{c['id']}: before {c['before']} is not a step")
        if not c.get("question"):
            err.append(f"{c['id']}: no question")
        if not _contains(c["code"]):
            err.append(f"{c['id']}: {c['code']['file']} does not contain {c['code']['contains']!r}")
    for k in set(docs) - used:
        err.append(f"document {k} is asked for but no check needs it")
    return err


def _md_cell(x) -> str:
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ")


def render(d: dict, bom: dict) -> str:
    vals = values()
    bench, equip = _bench_lines(bom, "bench"), _bench_lines(bom, "equipment")
    L = [f"# {d['title']}", "",
         "Generated by `tools/telematics_bench.py` from `telematics/bench/bench.yaml`; do not edit. "
         "`render --check` in CI fails if this page no longer matches the firmware, the BOM or the measured recording "
         "durations.", "",
         "**Status: built and host-tested, never run on hardware.** No connection below has been made or measured; "
         "every row is unverified until a filled results form (from the bench package) says otherwise. Host tests "
         "run the portable C code and model the storage; they do not exercise the U575's peripherals.", "",
         f"**Power.** {d['power']}", "",
         "Start with the minimal bench ([`BENCH_MINIMAL.md`](BENCH_MINIMAL.md)): one wheel input through the whole "
         "chain to a plot, and the document checks due before each step of either bench.", "",
         "## 1. Images", "",
         "| Image | Files | Steps | What it does |", "|---|---|---|---|"]
    for im in d["images"]:
        L.append(f"| `{im['name']}` | {', '.join(f'`{f}`' for f in im['files'])} | {im['steps']} | {_md_cell(im['what'])} |")
    c = d["commands"]
    L += ["", "## 2. Build and package", "", "```", "# portable library, unit tests and host simulator",
          c["build_host"], "", "# target images (arm-none-eabi-gcc 13.2, Ubuntu 24.04 package gcc-arm-none-eabi)",
          c["build_target"], "", "# the bench package: images, SHA-256 manifest, this procedure, parts, blank results form",
          c["package"], "```", "",
          "The revision printed in the banner is `git describe --always --dirty` at configure time; the package refuses "
          "images whose revision differs from the tree or ends in `-dirty` (unless `--allow-dirty`, which marks it not "
          "valid for a recorded run). `--rebuild` builds the images again in a new directory and records whether every "
          "hash is equal.", "",
          "## 3. Parts", "",
          f"Exactly the `{d['parts_config']}` lines of `hardware/telematics/bom.yaml` (docs/TELEMATICS_BOM.md), with the "
          "firmware driver each sensor or storage part needs. Nothing has been ordered.", "",
          "| Line | Qty | Item | Part | Used for | Driver |", "|---|---|---|---|---|---|"]
    rows_for = {}
    for cn in d["connections"]:
        if cn.get("part"):
            rows_for.setdefault(cn["part"], []).append(cn["id"])
    other = d.get("parts_without_a_row") or {}
    for k, l in bench.items():
        use = other.get(k) or "rows " + ", ".join(rows_for.get(k, []))
        drv = f"`{l['driver']}`" if l.get("driver") else ""
        L.append(f"| `{k}` | {l['qty']} | {_md_cell(l['item'])} | {_md_cell(l.get('part'))} | {_md_cell(use)} | {drv} |")
    L += ["", "Equipment (not bought for the unit): " + "; ".join(
        f"{equip[e]['qty']} x {equip[e]['item']} (`{e}`)" for e in d["equipment"]) + ".", "",
        "## 4. Connections", "", d["sources"].strip(), "",
        "| Row | Signal | MCU pin | NUCLEO position | Connect to | Part | Firmware line | Notes |",
        "|---|---|---|---|---|---|---|---|"]
    for cn in d["connections"]:
        chk = cn.get("check")
        fl = f"`{pathlib.Path(chk['file']).name}`: `{chk['contains']}`" if chk else ""
        L.append(f"| `{cn['id']}` | {_md_cell(cn['signal'])} | {_md_cell(cn['mcu'])} | {_md_cell(cn['nucleo'])} | "
                 f"{_md_cell(cn['to'])} | {_md_cell(cn.get('part'))} | {_md_cell(fl)} | {_md_cell(cn.get('note'))} |")
    L += [""] + [f"- {n}" for n in d.get("board_notes", [])]
    L += ["", "## 5. Commands", "", "| Use | Command |", "|---|---|"]
    for k in ("verify", "flash_cubeprogrammer", "flash_openocd", "console", "export_uart", "export_programmer",
              "import", "status"):
        L.append(f"| {k.replace('_', ' ')} | `{_md_cell(c[k])}` |")
    L += ["", f"**{c['never']}**", "",
          "## 6. Procedure", "",
          "Steps in order; each step's capture file is named `capture_B<n>.txt`. Write every measured value on the "
          "results form, including the ones that pass.", ""]
    for s in d["steps"]:
        L += [f"### {s['id']}. {s['title']}", "", f"- **Do.** {fill(s['do'], vals).strip()}",
              f"- **Expect.** {fill(s['expect'], vals).strip()}",
              "- **Record.** " + "; ".join(s["record"]) + "."]
        if s.get("firmware_text"):
            L.append("- **Firmware text checked.** " + "; ".join(
                f"`{pathlib.Path(x['file']).name}`: \"{x['contains']}\"" for x in s["firmware_text"]))
        L.append("")
    el = d["electrical"]
    L += ["## 7. Electrical checks before any vehicle bus", "", el["intro"].strip(), "",
          "| Check | Method | Pass |", "|---|---|---|"]
    for e in el["checks"]:
        L.append(f"| {e['id']} {_md_cell(e['title'])} | {_md_cell(e['method'].strip())} | {_md_cell(e['pass'].strip())} |")
    L += ["", "Step B11 shows receive-only behaviour at the protocol level; E1 to E6 are about the hardware.", "",
          "## 8. Not covered yet", "",
          "GNSS with PPS capture, the LTE modem, the live uplink from the target (the host model is "
          "`host/telematics/node.py`), a watchdog test, interrupt latency and the NOR's real erase and program times "
          "(the host model uses typical-class values, docs/generated/telematics_storage.md). The vehicle supply is "
          "blocked (docs/TELEMATICS_BOM.md). Each is a later step in docs/TELEMETRY_EMBEDDED_PORT.md.", ""]
    return "\n".join(L)


LEVEL_NOTE = {"M0": "the minimal bench, before wiring", "M1": "the minimal bench, before flashing"}


def _min_rows(d: dict) -> list[dict]:
    m = d["minimal"]
    conns = {c["id"]: c for c in d["connections"]}
    out = []
    for cid in m["connections"]:
        c = dict(conns[cid])
        if cid in (m.get("open") or []):
            c["to"] = "nothing (open)"
            c["note"] = ("Unconnected on this bench: reads as suspect inactive (I) while wheel_0 turns, as a "
                         "disconnected sensor must")
        out.append(c)
    return out


def _before_minimal(c: dict) -> bool:
    return c["before"] in MIN_STEP_IDS


def document_checks_md(d: dict, heading: str = "#", number: str = "") -> list[str]:
    docs = {x["id"]: x for x in d["documents"]}
    L = [f"{heading} {number}Document checks before flashing", "",
         "Each question is about the silicon or the board and is answered only by the document named; ST's HAL and board "
         "files, which the firmware follows, do not settle it (docs/U575_REGISTER_CHECK.md). Write the answer with the "
         "document's revision and page. An answer that contradicts the firmware line named stops the bench before the "
         "step in the last column.", "",
         "| Check | Document | Question | Firmware line that depends on it | Answer before |", "|---|---|---|---|---|"]
    for c in sorted(d["document_checks"], key=lambda c: (not _before_minimal(c), c["id"])):
        code = f"`{pathlib.Path(c['code']['file']).name}`: `{_md_cell(c['code']['contains'])}`"
        when = f"{c['before']} ({LEVEL_NOTE[c['before']]})" if c["before"] in LEVEL_NOTE else f"{c['before']} (full bench)"
        L.append(f"| {c['id']} | {docs[c['doc']]['id']} | {_md_cell(c['question'])} | {code} | {when} |")
    n_min = sum(1 for c in d["document_checks"] if _before_minimal(c))
    L += ["", f"{n_min} checks come before the minimal bench (M0, M1); the other "
          f"{len(d['document_checks']) - n_min} only before the full bench steps named (the NOR in B0 and B7, the "
          "watchdog in B2, CAN in B11, I2C in B12, GNSS in B13).", "",
          f"{heading}# {number.rstrip('. ') + '.1 ' if number else ''}The documents", "",
          "Read so far, from copies the team provided (not committed to the repository): " + "; ".join(
              f"{x['id']} {x['received']}" for x in d["documents"] if x.get("received")) + ". "
          "The others are not in the repository, and this environment cannot fetch them: www.st.com, "
          "www.winbond.com, www.u-blox.com, content.u-blox.com, www.sparkfun.com and cdn.sparkfun.com are refused by "
          "its network policy (the proxy answers 403 to the connection). Please "
          "download each from the manufacturer and commit it under the exact file name to "
          "`docs/reference/datasheets/`; the checks are then answered from them with page references.", "",
          "| # | Document | Part (exact) | Manufacturer | Status | Official page | Needed by |",
          "|---|---|---|---|---|---|---|"]
    for i, x in enumerate(d["documents"], 1):
        need = ", ".join(c["id"] for c in d["document_checks"] if c["doc"] == x["id"])
        status = (f"read: {x['received']}" if x.get("received") else
                  f"needed: commit as `docs/reference/datasheets/{x['file']}`")
        L.append(f"| {i} | {_md_cell(x['title'])} | {_md_cell(x['part'])} | {x['maker']} | {_md_cell(status)} | "
                 f"{_md_cell(x['page'])} | {need} |")
    return L


def render_minimal(d: dict, bom: dict) -> str:
    m, c = d["minimal"], d["commands"]
    mc = m["commands"]
    bench, equip = _bench_lines(bom, "bench"), _bench_lines(bom, "equipment")
    image = next(im for im in d["images"] if im["name"] == m["image"])
    L = [f"# {m['title']}", "",
         "Generated by `tools/telematics_bench.py` from `telematics/bench/bench.yaml` (section `minimal`); do not edit. "
         "`render --check` in CI fails if this page no longer matches the firmware, the BOM or the chain's checks.", "",
         "**Status: never run on a board.** Built and host-tested only. The rehearsal in the package is a host "
         "simulation (SIMULATED); nothing below is a bench result until a filled results form says so.", "",
         f"**Chain.** {m['chain'].strip()}.", "",
         f"**Power.** {d['power'].strip()}", "",
         "The full first bench (NOR, IMU, TMP117, CAN, GNSS; steps B0 to B13) is [`BENCH.md`](BENCH.md). This page is the "
         "smallest bench that exercises the whole evidence chain once on real hardware.", "",
         "## 1. Still needs a real board", ""]
    L += [f"- {x}" for x in m["needs_a_board"]]
    L += ["", "## 2. Build, package, rehearse", "",
          "The commands CI runs on every push (job firmware-build); the package records the hashes it produced.", "",
          "```", "# portable library, unit tests and the host simulator", c["build_host"], "",
          "# target image (arm-none-eabi-gcc 13.2, Ubuntu 24.04 package gcc-arm-none-eabi)", c["build_target"], "",
          "# the minimal package: image and SHA-256 manifest, this procedure, connections, parts, document checks,",
          "# blank results form, and the SIMULATED rehearsal of M0 to M4",
          "python3 tools/telematics_bench.py package --minimal --images build-u575 --host-build build-telematics \\",
          "        --out build/telematics_bench_minimal --rebuild", "",
          "# the rehearsal alone", mc["rehearse"], "```", "",
          f"Image: `{m['image']}` ({', '.join(f'`{f}`' for f in image['files'])}). "
          "Its SHA-256 is in the package's `MANIFEST.json`, not on this page: the image carries the revision it was "
          "built from, so its hash changes with every commit.", "",
          "## 3. Parts and equipment", "",
          "| Line | Qty | Item | Part |", "|---|---|---|---|"]
    for k in m["parts"]:
        l = bench[k]
        L.append(f"| `{k}` | {l['qty']} | {_md_cell(l['item'])} | {_md_cell(l.get('part'))} |")
    L += ["", "| Equipment | Qty | Item | Used for here |", "|---|---|---|---|"]
    for k in m["equipment"]:
        L.append(f"| `{k}` | {equip[k]['qty']} | {_md_cell(equip[k]['item'])} | {_md_cell(m['equipment_use'][k])} |")
    L += ["", "The generator's own output lead (BNC to clips or to a 0.1 in pin) connects it to the jumper wires. "
          "Nothing has been ordered.", "",
          "## 4. Connections", "",
          "| Row | Signal | MCU pin | NUCLEO position | Connect to | Firmware line | Notes |", "|---|---|---|---|---|---|---|"]
    for cn in _min_rows(d):
        chk = cn.get("check")
        fl = f"`{pathlib.Path(chk['file']).name}`: `{chk['contains']}`" if chk else ""
        L.append(f"| `{cn['id']}` | {_md_cell(cn['signal'])} | {_md_cell(cn['mcu'])} | {_md_cell(cn['nucleo'])} | "
                 f"{_md_cell(cn['to'])} | {_md_cell(fl)} | {_md_cell(cn.get('note'))} |")
    L += ["", "Every row is unverified: positions come from ST's board files (Zephyr's NUCLEO-U575ZI-Q description), "
          "not from UM2861, which could not be read here (DC01).", ""]
    L += document_checks_md(d, "##", "5. ")
    L += ["", "## 6. Commands", "", "| Use | Command |", "|---|---|"]
    for k in ("flash_cubeprogrammer", "flash_openocd"):
        L.append(f"| {k.replace('_', ' ')} | `{_md_cell(c[k])}` |")
    for k, v in mc.items():
        L.append(f"| {k.replace('_', ' ')} | `{_md_cell(v)}` |")
    L += ["", f"**{c['never']}**", "", "## 7. Procedure", "",
          "Steps in order. Write every value on the results form, including the ones that pass.", ""]
    for st in m["steps"]:
        L += [f"### {st['id']}. {st['title']}", "", f"- **Do.** {st['do'].strip()}",
              f"- **Expect.** {st['expect'].strip()}", "- **Record.** " + "; ".join(st["record"]) + "."]
        if st.get("firmware_text"):
            L.append("- **Text checked against the code.** " + "; ".join(
                f"`{pathlib.Path(x['file']).name}`: \"{x['contains']}\"" for x in st["firmware_text"]))
        L.append("")
    L += ["## 8. Then", "",
          "The full bench ([`BENCH.md`](BENCH.md), B0 to B13), and the bench stage of the first physical protocol, "
          "EXP-01 ([`../../research/vehicle_validation/EXP-01_wheel_speed_corruption.md`]"
          "(../../research/vehicle_validation/EXP-01_wheel_speed_corruption.md)): this wiring plus a second generator "
          "channel on wheel_1 (Arduino A1, PA2) at a known ratio to wheel_0.", ""]
    return "\n".join(L)


def results_form_minimal(d: dict, manifest: dict) -> str:
    m = d["minimal"]
    L = ["# Results form: minimal bench (M0 to M4)", "",
         "Blank. Fill one copy per session, by hand or in `results.yaml`. A row counts as verified only when this form "
         "records it, with who and when; an empty cell means not done.", "",
         f"Package: commit `{manifest['commit']}`, revision `{manifest['source_revision']}`.", "",
         "| Field | Value |", "|---|---|"]
    for f in ("Date", "Operator(s)", "NUCLEO-U575ZI-Q serial (sticker)", "Unit id (banner, run_id prefix)",
              "ST-LINK firmware version", "PC, OS, uart_capture.py or terminal", "Signal generator model",
              "Generator frequency accuracy (its data sheet)", "Scope model", "Multimeter model"):
        L.append(f"| {f} | |")
    for im in manifest["images"]:
        L.append(f"| SHA-256 of `{im['name']}.bin` as flashed (MANIFEST: `{im['sha256_bin'][:16]}...`) | |")
    docs = {x["id"]: x for x in d["documents"]}
    L += ["", "## Document checks", "",
          "| Check | Document | Revision and page | Answer | Agrees with the firmware (yes, no) |", "|---|---|---|---|---|"]
    for c in d["document_checks"]:
        if _before_minimal(c):
            L.append(f"| {c['id']} | {docs[c['doc']]['id']} | | | |")
    L += ["", "## Connections", "",
          "| Row | Signal | MCU pin | Planned position | Position found | Continuity | Verified on board (by, date) |",
          "|---|---|---|---|---|---|---|"]
    for cn in _min_rows(d):
        L.append(f"| `{cn['id']}` | {_md_cell(cn['signal'])} | {_md_cell(cn['mcu'])} | {_md_cell(cn['nucleo'])} | | | |")
    L += ["", "## Steps", ""]
    for st in m["steps"]:
        L += [f"### {st['id']}. {st['title']}", "", f"Expect: {st['expect'].strip()}", "",
              "| Record | Value |", "|---|---|"]
        L += [f"| {_md_cell(r)} | |" for r in st["record"]]
        L += ["| Capture file | |", "| Result (pass, fail, not run) | |", "| Deviation from the procedure | |", ""]
    L += ["## Notes", "", "", ""]
    return "\n".join(L)


def results_template_minimal(d: dict, manifest: dict) -> dict:
    return {"package": {"commit": manifest["commit"], "source_revision": manifest["source_revision"],
                        "profile": "minimal"},
            "session": {"date": None, "operators": None, "board_serial": None, "unit_id": None, "generator": None,
                        "generator_accuracy": None, "scope": None, "flashed_sha256": {}},
            "document_checks": {c["id"]: {"revision": None, "page": None, "answer": None, "agrees": None}
                                for c in d["document_checks"] if _before_minimal(c)},
            "connections": {c["id"]: {"position_found": None, "continuity": None, "verified_by": None,
                                      "verified_date": None} for c in _min_rows(d)},
            "steps": {s["id"]: {"result": None, "capture": None, "deviation": None,
                                "record": {r: None for r in s["record"]}} for s in d["minimal"]["steps"]}}


# ------------------------------------------------------------------------------------------------ package
def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def image_revision(name: str, data: bytes) -> str | None:
    """The revision compiled into the image: the banner's firmware string '<name> <revision>'."""
    m = re.search(re.escape(name.encode()) + rb" ([0-9A-Za-z][0-9A-Za-z._+-]*)\x00", data)
    return m.group(1).decode() if m else None


def _compiler(build: pathlib.Path) -> str:
    """The C compiler CMake used (the toolchain file sets it, so it is in CMakeCCompiler.cmake, not the cache)."""
    found = sorted(build.glob("CMakeFiles/*/CMakeCCompiler.cmake"))
    m = re.search(r'^set\(CMAKE_C_COMPILER "([^"]+)"\)', found[-1].read_text(), re.M) if found else None
    if not m:
        return "unknown"
    r = subprocess.run([m.group(1), "--version"], capture_output=True, text=True)
    return r.stdout.splitlines()[0] if r.returncode == 0 and r.stdout else m.group(1)


def _build_type(build: pathlib.Path) -> str:
    cache = build / "CMakeCache.txt"
    m = re.search(r"^CMAKE_BUILD_TYPE:\w+=(.*)$", cache.read_text(), re.M) if cache.exists() else None
    return m.group(1) if m else "unknown"


def rebuild(into: pathlib.Path) -> None:
    subprocess.run(["cmake", "-S", str(FW), "-B", str(into), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=MinSizeRel",
                    f"-DCMAKE_TOOLCHAIN_FILE={FW / 'cmake' / 'arm-none-eabi-cortex-m33.cmake'}", "-DTM_TARGET_U575=ON"],
                   check=True, capture_output=True, text=True)
    subprocess.run(["cmake", "--build", str(into)], check=True, capture_output=True, text=True)


def results_form(d: dict, manifest: dict) -> str:
    L = ["# Results form: first telematics bench", "",
         "Blank. Fill one copy per bench session, by hand or in `results.yaml`. A connection or step counts as "
         "verified only when this form records it, with who and when; an empty cell means not done.", "",
         f"Package: commit `{manifest['commit']}`, revision `{manifest['source_revision']}`.", "",
         "| Field | Value |", "|---|---|"]
    for f in ("Date", "Operator(s)", "NUCLEO-U575ZI-Q serial (sticker)", "Unit id (banner, run_id prefix)",
              "ST-LINK firmware version", "PC, OS, terminal or uart_capture.py", "Signal generator model",
              "Generator frequency accuracy (its data sheet)", "Multimeter model", "USB-CAN adapters (model, firmware)"):
        L.append(f"| {f} | |")
    for im in manifest["images"]:
        L.append(f"| SHA-256 of `{im['name']}.bin` as flashed (MANIFEST: `{im['sha256_bin'][:16]}...`) | |")
    L += ["", "## Connections", "",
          "| Row | Signal | MCU pin | Planned position | Position found | Continuity | Verified on board (by, date) |",
          "|---|---|---|---|---|---|---|"]
    for c in d["connections"]:
        L.append(f"| `{c['id']}` | {_md_cell(c['signal'])} | {_md_cell(c['mcu'])} | {_md_cell(c['nucleo'])} | | | |")
    vals = values()
    L += ["", "## Steps", ""]
    for s in d["steps"]:
        L += [f"### {s['id']}. {s['title']}", "", f"Expect: {fill(s['expect'], vals).strip()}", "",
              "| Record | Value |", "|---|---|"]
        L += [f"| {_md_cell(r)} | |" for r in s["record"]]
        L += ["| Capture file | |", "| Result (pass, fail, not run) | |", "| Deviation from the procedure | |", ""]
    L += ["## Electrical checks", "", "| Check | Pass criterion | Measured | Result | By, date |", "|---|---|---|---|---|"]
    for e in d["electrical"]["checks"]:
        L.append(f"| {e['id']} {_md_cell(e['title'])} | {_md_cell(e['pass'].strip())} | | | |")
    L += ["", "## Notes", "", "", ""]
    return "\n".join(L)


def results_template(d: dict, manifest: dict) -> dict:
    return {"package": {"commit": manifest["commit"], "source_revision": manifest["source_revision"]},
            "session": {"date": None, "operators": None, "board_serial": None, "unit_id": None,
                        "generator": None, "generator_accuracy": None, "flashed_sha256": {}},
            "connections": {c["id"]: {"position_found": None, "continuity": None, "verified_by": None,
                                      "verified_date": None} for c in d["connections"]},
            "steps": {s["id"]: {"result": None, "capture": None, "deviation": None,
                                "record": {r: None for r in s["record"]}} for s in d["steps"]},
            "electrical": {e["id"]: {"measured": None, "result": None, "by": None, "date": None}
                           for e in d["electrical"]["checks"]}}


def _csv(rows: list[list]) -> str:
    b = io.StringIO()
    csv.writer(b, lineterminator="\n").writerows(rows)
    return b.getvalue()


def rehearse(out: pathlib.Path, host_build: pathlib.Path) -> dict:
    """The minimal procedure on the host simulator through the bench chain command (SIMULATED), kept in `out`."""
    from tools import run_bench_chain
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_bench_chain.main(["--rehearse-minimal", "--out", str(out), "--build", str(host_build)])
    for p in [out / "flash.bin", out / "pit.sqlite", *out.glob("import/*.stlg")]:
        p.unlink(missing_ok=True)
    res = json.loads((out / "chain.json").read_text())
    (out / "chain_output.txt").write_text(buf.getvalue())
    return {"pass": rc == 0 and res["pass"], "data_class": res["data_class"], "run_id": res["run_id"],
            "checks": [{"id": c["id"], "pass": c["pass"]} for c in res["checks"]],
            "command": "python3 tools/run_bench_chain.py --rehearse-minimal --out rehearsal"}


def package(d: dict, bom: dict, images: pathlib.Path, out: pathlib.Path, allow_dirty: bool, do_rebuild: bool,
            minimal: bool = False, host_build: pathlib.Path | None = None) -> dict:
    err = validate(d, bom)
    if err:
        raise SystemExit("bench.yaml fails its checks:\n  " + "\n  ".join(err))
    m = d["minimal"]
    image_defs = [im for im in d["images"] if not minimal or im["name"] == m["image"]]
    rev = _git("describe", "--always", "--dirty", "--abbrev=12")
    commit = _git("rev-parse", "HEAD")
    dirty = rev.endswith("-dirty") or not rev
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    (out / "tools").mkdir()
    ims, problems = [], []
    for im in image_defs:
        bin_ = images / f"{im['name']}.bin"
        if not bin_.exists():
            raise SystemExit(f"{bin_} not found: build the target images first ({d['commands']['build_target'].splitlines()[0]} ...)")
        irev = image_revision(im["name"], bin_.read_bytes())
        if irev != rev:
            problems.append(f"{im['name']}: image revision {irev!r}, tree {rev!r}")
        if irev and irev.endswith("-dirty"):
            problems.append(f"{im['name']}: built from a modified tree")
        for f in im["files"]:
            shutil.copy2(images / f, out / "images" / f)
        ims.append({"name": im["name"], "revision": irev, "steps": im["steps"], "sha256_bin": _sha(bin_)})
    if (dirty or problems) and not allow_dirty:
        raise SystemExit("refused: " + "; ".join(problems + (["the tree is modified"] if dirty else [])) +
                         " (commit, rebuild, or pass --allow-dirty for a package not valid for a recorded run)")
    reproduced = None
    if do_rebuild:
        with tempfile.TemporaryDirectory() as t:
            rb = pathlib.Path(t) / "rebuild"
            rebuild(rb)
            reproduced = {f"{im['name']}{e}": _sha(rb / f"{im['name']}{e}") == _sha(images / f"{im['name']}{e}")
                          for im in image_defs for e in COMPARED}
    shutil.copy2(ROOT / "tools" / "uart_capture.py", out / "tools" / "uart_capture.py")
    rehearsal = None
    if minimal:
        (out / "BENCH_MINIMAL.md").write_text(render_minimal(d, bom))
        (out / "DOCUMENT_CHECKS.md").write_text("\n".join(document_checks_md(d)) + "\n")
        rehearsal = rehearse(out / "rehearsal", host_build or ROOT / "build-telematics")
        if not rehearsal["pass"]:
            raise SystemExit("the SIMULATED rehearsal of the minimal procedure failed: see " +
                             str(out / "rehearsal" / "chain.md"))
    else:
        (out / "BENCH.md").write_text(render(d, bom))
    cn = [["id", "signal", "mcu_pin", "nucleo_position", "connect_to", "part", "firmware_file", "firmware_line", "note",
           "verified_on_board"]]
    for c in (_min_rows(d) if minimal else d["connections"]):
        chk = c.get("check") or {}
        cn.append([c["id"], c["signal"], c["mcu"], c["nucleo"], c["to"], c.get("part") or "", chk.get("file", ""),
                   chk.get("contains", ""), c.get("note") or "", ""])
    (out / "CONNECTIONS.csv").write_text(_csv(cn))
    pr = [["id", "kind", "qty", "item", "part", "price_low_usd", "price_high_usd", "evidence", "source", "driver"]]
    for k, l in _bench_lines(bom, "bench").items():
        if minimal and k not in m["parts"]:
            continue
        pr.append([k, "part", l["qty"], l["item"], l.get("part") or "", l.get("low"), l.get("high"), l["evidence"],
                   l["source"], l.get("driver") or ""])
    eq = _bench_lines(bom, "equipment")
    for k in (m["equipment"] if minimal else d["equipment"]):
        l = eq[k]
        pr.append([k, "equipment", l["qty"], l["item"], l.get("part") or "", l.get("low"), l.get("high"),
                   l["evidence"], l["source"], ""])
    (out / "PARTS.csv").write_text(_csv(pr))
    manifest = {"package": ("telematics minimal bench (NUCLEO-U575ZI-Q, one wheel input to a plot)" if minimal else
                            "telematics first bench (NUCLEO-U575ZI-Q)"),
                "profile": "minimal" if minimal else "full", "commit": commit, "source_revision": rev,
                "commit_date": _git("show", "-s", "--format=%cI", "HEAD"),
                "valid_for_recorded_run": not (dirty or problems), "problems": problems,
                "compiler": _compiler(images), "build_type": _build_type(images), "images": ims,
                "build_commands": [d["commands"]["build_host"], d["commands"]["build_target"]],
                "reproduced_in_a_new_build_directory": reproduced,
                "verified_on_board": "nothing"}
    if minimal:
        lines = _bench_lines(bom, "bench")
        manifest["parts_total_usd"] = {k: round(sum(lines[p][k] * lines[p]["qty"] for p in m["parts"]), 2)
                                       for k in ("low", "high")}
        manifest["document_checks_before_flashing"] = [c["id"] for c in d["document_checks"] if _before_minimal(c)]
        manifest["documents_read"] = {x["id"]: x["received"] for x in d["documents"] if x.get("received")}
        manifest["documents_missing"] = [x["file"] for x in d["documents"] if not x.get("received") and
                                         not (ROOT / "docs" / "reference" / "datasheets" / x["file"]).exists()]
        manifest["rehearsal"] = rehearsal
        manifest["needs_a_board"] = m["needs_a_board"]
    else:
        manifest["bench_parts_total_usd"] = tb.totals(bom)["bench"]
    form = results_form_minimal if minimal else results_form
    tmpl = results_template_minimal if minimal else results_template
    (out / "RESULTS_FORM.md").write_text(form(d, manifest))
    (out / "results.yaml").write_text("# Blank: fill after the bench session (null = not done)\n" +
                                      yaml.safe_dump(tmpl(d, manifest), sort_keys=False, width=120))
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(out))] = {"sha256": _sha(p), "bytes": p.stat().st_size}
    manifest["files"] = files
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--check", action="store_true")
    p = sub.add_parser("package")
    p.add_argument("--images", type=pathlib.Path, default=ROOT / "build-u575")
    p.add_argument("--out", type=pathlib.Path, default=ROOT / "build" / "telematics_bench")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--rebuild", action="store_true", help="build the images again and compare the hashes")
    p.add_argument("--minimal", action="store_true", help="the minimal bench only (bench.yaml, section minimal)")
    p.add_argument("--host-build", type=pathlib.Path, default=ROOT / "build-telematics",
                   help="host build with tm_hostsim, for the minimal package's rehearsal")
    a = ap.parse_args()
    d, bom = load(), tb.load()
    if a.cmd == "render":
        err = validate(d, bom)
        for e in err:
            print("bench.yaml: " + e)
        if err:
            return 1
        pages = {DOC: render(d, bom), DOC_MIN: render_minimal(d, bom)}
        if a.check:
            stale = [p for p, text in pages.items() if not p.exists() or p.read_text() != text]
            for p in stale:
                print(f"stale: {p.relative_to(ROOT)} (run tools/telematics_bench.py render)")
            if not stale:
                print("telematics bench procedures (full and minimal) current and consistent with the firmware and "
                      "the BOM")
            return 1 if stale else 0
        for p, text in pages.items():
            p.write_text(text)
            print(f"wrote {p.relative_to(ROOT)}")
        return 0
    m = package(d, bom, a.images, a.out, a.allow_dirty, a.rebuild, a.minimal, a.host_build)
    print(f"wrote {a.out}: {len(m['files'])} files, revision {m['source_revision']}, "
          f"valid for a recorded run: {m['valid_for_recorded_run']}"
          + (f", reproduced: {all(m['reproduced_in_a_new_build_directory'].values())}"
             if m["reproduced_in_a_new_build_directory"] else ""))
    for im in m["images"]:
        print(f"  {im['name']}.bin {im['sha256_bin']}")
    if m.get("rehearsal"):
        print(f"  rehearsal (SIMULATED): {'PASS' if m['rehearsal']['pass'] else 'FAIL'}, "
              f"{len(m['documents_missing'])} documents still to provide, "
              f"{len(m['document_checks_before_flashing'])} document checks before flashing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
