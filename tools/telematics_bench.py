#!/usr/bin/env python3
"""The telematics bench package: one procedure, one parts list, one set of images, one blank results form.

    python3 tools/telematics_bench.py render            # writes telematics/firmware/BENCH.md from bench.yaml
    python3 tools/telematics_bench.py render --check    # exit 1 if BENCH.md is stale or bench.yaml fails a check
    python3 tools/telematics_bench.py package --images build-u575 --out build/telematics_bench [--rebuild]

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
"""
from __future__ import annotations

import argparse
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
STORAGE = ROOT / "docs" / "generated" / "telematics_storage.json"
FW = ROOT / "telematics" / "firmware"
STEP_IDS = [f"B{k}" for k in range(13)]
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


def package(d: dict, bom: dict, images: pathlib.Path, out: pathlib.Path, allow_dirty: bool, do_rebuild: bool) -> dict:
    err = validate(d, bom)
    if err:
        raise SystemExit("bench.yaml fails its checks:\n  " + "\n  ".join(err))
    rev = _git("describe", "--always", "--dirty", "--abbrev=12")
    commit = _git("rev-parse", "HEAD")
    dirty = rev.endswith("-dirty") or not rev
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    (out / "tools").mkdir()
    ims, problems = [], []
    for im in d["images"]:
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
                          for im in d["images"] for e in COMPARED}
    shutil.copy2(ROOT / "tools" / "uart_capture.py", out / "tools" / "uart_capture.py")
    (out / "BENCH.md").write_text(render(d, bom))
    cn = [["id", "signal", "mcu_pin", "nucleo_position", "connect_to", "part", "firmware_file", "firmware_line", "note",
           "verified_on_board"]]
    for c in d["connections"]:
        chk = c.get("check") or {}
        cn.append([c["id"], c["signal"], c["mcu"], c["nucleo"], c["to"], c.get("part") or "", chk.get("file", ""),
                   chk.get("contains", ""), c.get("note") or "", ""])
    (out / "CONNECTIONS.csv").write_text(_csv(cn))
    pr = [["id", "kind", "qty", "item", "part", "price_low_usd", "price_high_usd", "evidence", "source", "driver"]]
    for k, l in _bench_lines(bom, "bench").items():
        pr.append([k, "part", l["qty"], l["item"], l.get("part") or "", l.get("low"), l.get("high"), l["evidence"],
                   l["source"], l.get("driver") or ""])
    eq = _bench_lines(bom, "equipment")
    for k in d["equipment"]:
        l = eq[k]
        pr.append([k, "equipment", l["qty"], l["item"], l.get("part") or "", l.get("low"), l.get("high"),
                   l["evidence"], l["source"], ""])
    (out / "PARTS.csv").write_text(_csv(pr))
    manifest = {"package": "telematics first bench (NUCLEO-U575ZI-Q)", "commit": commit, "source_revision": rev,
                "commit_date": _git("show", "-s", "--format=%cI", "HEAD"),
                "valid_for_recorded_run": not (dirty or problems), "problems": problems,
                "compiler": _compiler(images), "build_type": _build_type(images), "images": ims,
                "reproduced_in_a_new_build_directory": reproduced,
                "bench_parts_total_usd": tb.totals(bom)["bench"], "verified_on_board": "nothing"}
    (out / "RESULTS_FORM.md").write_text(results_form(d, manifest))
    (out / "results.yaml").write_text("# Blank: fill after the bench session (null = not done)\n" +
                                      yaml.safe_dump(results_template(d, manifest), sort_keys=False, width=120))
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
    a = ap.parse_args()
    d, bom = load(), tb.load()
    if a.cmd == "render":
        err = validate(d, bom)
        for e in err:
            print("bench.yaml: " + e)
        if err:
            return 1
        text = render(d, bom)
        if a.check:
            stale = not DOC.exists() or DOC.read_text() != text
            if stale:
                print(f"stale: {DOC.relative_to(ROOT)} (run tools/telematics_bench.py render)")
            if not stale:
                print("telematics bench procedure current and consistent with the firmware and the BOM")
            return 1 if stale else 0
        DOC.write_text(text)
        print(f"wrote {DOC.relative_to(ROOT)}")
        return 0
    m = package(d, bom, a.images, a.out, a.allow_dirty, a.rebuild)
    print(f"wrote {a.out}: {len(m['files'])} files, revision {m['source_revision']}, "
          f"valid for a recorded run: {m['valid_for_recorded_run']}"
          + (f", reproduced: {all(m['reproduced_in_a_new_build_directory'].values())}"
             if m["reproduced_in_a_new_build_directory"] else ""))
    for im in m["images"]:
        print(f"  {im['name']}.bin {im['sha256_bin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
