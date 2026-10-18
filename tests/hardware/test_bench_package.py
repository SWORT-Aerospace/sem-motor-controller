"""Bench package (tools/bench_package.py): the committed page is current and a built package is complete."""
import json
import subprocess
import sys

from tools import bench_package as bp


def test_page_is_current_and_names_each_image_with_its_stages():
    r = subprocess.run([sys.executable, str(bp.ROOT / "tools" / "bench_package.py"), "--doc", "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = bp.DOC.read_text()
    assert "| `semmc_stm32g474_pwmtest.elf` | PWM bench | S4 |" in text
    assert "BP3" in text and "BP5 | OPEN" in text.replace("BP5 the gate driver keeps its gates low when disabled or "
                                                           "unpowered, and tolerates driven inputs unpowered", "BP5")


def test_built_package_has_every_part_and_a_manifest(tmp_path):
    img = tmp_path / "build-g4"
    img.mkdir()
    for name, _r, _w in bp.IMAGES:
        (img / f"{name}.elf").write_bytes(b"\x7fELF...semmc stm32g474 TEST abc123\x00...")  # stand-in images
        (img / f"{name}.bin").write_bytes(b"bin")
    out = tmp_path / "pkg"
    assert bp.build(img, "BOARD-T", out) == 0
    m = json.loads((out / "MANIFEST.json").read_text())
    assert m["board"] == "BOARD-T" and "hardware-valid" in m["calibration"]
    assert set(m["image_revisions"]) == {n for n, _r, _w in bp.IMAGES}
    assert all(v.startswith("semmc stm32g474 ") for v in m["image_revisions"].values())
    for f in ("images/semmc_stm32g474_pwmtest.elf", "procedures/BENCH_ACCEPTANCE.md", "scripts/bench_read.py",
              "templates/S4_BOARD-T.json", "checks/CONSISTENCY_CHECK.md", "drawings/semmc_schematic_DRAFT.pdf"):
        assert f in m["files"], f
    assert len([f for f in m["files"] if f.startswith("templates/")]) == 11


def test_missing_image_is_refused(tmp_path):
    assert bp.build(tmp_path, "B", tmp_path / "out") == 1
