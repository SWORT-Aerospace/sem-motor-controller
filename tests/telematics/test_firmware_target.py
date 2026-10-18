"""The NUCLEO-U575ZI-Q images of the telematics firmware: they link, and their structure is right.

Builds telematics/firmware with arm-none-eabi-gcc (TM_TARGET_U575=ON) into a temporary directory and inspects
the ELF files. Without the toolchain the tests are skipped, unless SEMMC_REQUIRE_ARM=1 (set in CI), which
makes a missing toolchain a failure.

What this shows: the images are complete (startup, vector table, linker script, drivers, portable
application), their vector table matches ST's interrupt list for the STM32U575, nothing is placed in the log
bank, and the code does not depend on the project's controller firmware. What it does not show: that the
images run. Nothing here executes target code; that is the bench procedure, telematics/firmware/BENCH.md.
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FW = ROOT / "telematics" / "firmware"
HEADER = FW / "platform" / "u575" / "vendor" / "cmsis_device_u5" / "Include" / "stm32u575xx.h"
FLASH0, LOG0, LOG1, RAM0, RAM1 = 0x08000000, 0x08100000, 0x08200000, 0x20000000, 0x20030000


@pytest.fixture(scope="module")
def images(tmp_path_factory):
    if shutil.which("arm-none-eabi-gcc") is None:
        if os.environ.get("SEMMC_REQUIRE_ARM") == "1":
            pytest.fail("arm-none-eabi-gcc not found; SEMMC_REQUIRE_ARM=1", pytrace=False)
        pytest.skip("arm-none-eabi-gcc not found")
    b = tmp_path_factory.mktemp("u575")
    gen = ["-G", "Ninja"] if shutil.which("ninja") else []
    subprocess.run(["cmake", "-S", str(FW), "-B", str(b), *gen, f"-DCMAKE_TOOLCHAIN_FILE={FW}/cmake/arm-none-eabi-cortex-m33.cmake",
                    "-DTM_TARGET_U575=ON", "-DCMAKE_BUILD_TYPE=MinSizeRel"], check=True, capture_output=True)
    r = subprocess.run(["cmake", "--build", str(b)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    return b


def _irqs():
    text = HEADER.read_text()
    block = text[text.index("typedef enum"):text.index("} IRQn_Type;")]
    return {int(n): name for name, n in re.findall(r"^\s+(\w+)_IRQn\s*=\s*(-?\d+)", block, re.M) if int(n) >= 0}


def _symbols(elf):
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], capture_output=True, text=True, check=True).stdout
    return {parts[2]: int(parts[0], 16) for parts in (l.split() for l in out.splitlines()) if len(parts) == 3}


def _vectors(elf, n):
    blob = subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "-j", ".isr_vector", str(elf), "/dev/stdout"],
                          capture_output=True, check=True).stdout
    return struct.unpack(f"<{n}I", blob[:4 * n])


@pytest.mark.parametrize("name", ["tm_u575", "tm_u575_can"])
def test_vector_table_matches_st_interrupt_list(images, name):
    irqs = _irqs()
    n = 16 + max(irqs) + 1
    elf = images / f"{name}.elf"
    sym = _symbols(elf)
    v = _vectors(elf, n)
    assert sym["g_vectors"] == FLASH0 and RAM0 < v[0] <= RAM1           # initial stack pointer in SRAM1
    assert v[1] == sym["Reset_Handler"] | 1                               # Thumb bit set
    for pos in range(max(irqs) + 1):
        w = v[16 + pos]
        if pos not in irqs:
            assert w == 0, f"reserved position {pos} is not 0"
            continue
        handler = f"{irqs[pos]}_IRQHandler"
        assert w & 1 and FLASH0 <= w < LOG0, handler
        expected = sym.get(handler, sym["Default_Handler"])
        assert w == expected | 1, handler
    tim2 = [p for p, nm in irqs.items() if nm == "TIM2"][0]
    can = [p for p, nm in irqs.items() if nm == "FDCAN1_IT0"][0]
    assert v[16 + tim2] != sym["Default_Handler"] | 1                     # the capture interrupt is handled
    if name == "tm_u575_can":
        assert v[16 + can] == sym["FDCAN1_IT0_IRQHandler"] | 1
    else:
        assert v[16 + can] == sym["Default_Handler"] | 1                  # no CAN in the basic image


@pytest.mark.parametrize("name", ["tm_u575", "tm_u575_can"])
def test_layout_leaves_the_log_bank_free_and_has_no_controller_code(images, name):
    elf = images / f"{name}.elf"
    hdr = subprocess.run(["arm-none-eabi-objdump", "-h", str(elf)], capture_output=True, text=True, check=True).stdout
    for line in hdr.splitlines():
        p = line.split()
        if len(p) >= 6 and re.fullmatch(r"[0-9a-f]{8}", p[3] or "") and int(p[2], 16) > 0:
            vma, lma = int(p[3], 16), int(p[4], 16)
            assert not LOG0 <= lma < LOG1 and not LOG0 <= vma < LOG1, line
    sym = _symbols(elf)
    assert sym["__log_start"] == LOG0 and sym["__log_size"] == LOG1 - LOG0
    assert not [s for s in sym if s.startswith(("mc_", "semmc_"))]        # nothing from firmware/ (the controller)
    assert (images / f"{name}.bin").stat().st_size < 64 * 1024


def test_sources_have_no_transmit_path():
    src = "\n".join(p.read_text() for p in (FW / "platform" / "u575").glob("*.c"))
    src += "\n".join(p.read_text() for p in (FW / "src").glob("*.c"))
    for word in ("TXBAR", "TXFQS", "TXBC", "can_tx"):
        assert word not in src, word
    can = (FW / "platform" / "u575" / "can_u575.c").read_text()
    assert "FDCAN_CCCR_MON" in can                                       # bus-monitoring mode
    assert not re.search(r"firmware/(src|include|platform/stm32g4)", (FW / "CMakeLists.txt").read_text())
