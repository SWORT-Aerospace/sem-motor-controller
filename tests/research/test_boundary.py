"""The research code is diagnostic only: it reads models and records, and nothing in it can reach the
vehicle (no CAN, MQTT, serial or socket access, no controller command path, no firmware code beyond the
CRC routine the recorder shares)."""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ALLOWED = ("__future__", "typing", "argparse", "dataclasses", "hashlib", "json", "math", "multiprocessing", "numpy",
           "os", "pathlib", "subprocess", "sys", "time", "types", "research", "models.vehicle", "models.inverter",
           "host.csia_adapter", "host.telematics.clocks")


def _imports(path: pathlib.Path) -> set:
    out = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_research_python_imports_nothing_that_reaches_the_vehicle():
    bad = {}
    for p in sorted((ROOT / "research").rglob("*.py")):
        mods = {m for m in _imports(p) if not any(m == a or m.startswith(a + ".") for a in ALLOWED)}
        if mods:
            bad[str(p.relative_to(ROOT))] = sorted(mods)
    assert bad == {}, f"imports outside the diagnostic boundary: {bad}"


def test_recorder_uses_only_the_shared_crc_from_the_firmware():
    for p in (ROOT / "research" / "recorder").rglob("*.[ch]"):
        if "tests" in p.parts:
            continue
        local = re.findall(r'#include\s+"([^"]+)"', p.read_text())
        assert set(local) <= {"bea_recorder.h", "semmc/mc_crc.h"}, (p, local)
