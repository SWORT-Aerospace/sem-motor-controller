"""The STM32G474 target image: it links, and its structure matches ST's device definition.

Builds firmware/ with the arm-none-eabi toolchain (SEMMC_TARGET_STM32G474=ON) into a temporary
directory and inspects the ELF. Without arm-none-eabi-gcc the tests are skipped, unless
SEMMC_REQUIRE_ARM=1 (set in CI), which makes a missing toolchain a failure.

What this shows: the image is complete (startup, vector table, linker script, drivers, core) and its
layout is right. What it does not show: that the image runs. Nothing here executes target code;
bring-up on the board is docs/BENCH_ACCEPTANCE.md stage 2 onwards.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEVICE_H = ROOT / "firmware/platform/stm32g4/vendor/cmsis_device_g4/Include/stm32g474xx.h"
FLASH_START, CAL_START, RAM_START, RAM_END = 0x08000000, 0x0807F000, 0x20000000, 0x20018000
HANDLED = {"ADC1_2", "TIM1_BRK_TIM15", "TIM6_DAC"}
DOUBLE_HELPERS = re.compile(r"^__aeabi_(d\w+|[fiul]+2d|[ui]?l2d)$|^__(adddf3|subdf3|muldf3|divdf3|extendsfdf2|truncdfsf2)$|"
                            r"^(sin|cos|tan|exp|log|log10|pow|sqrt|fmod|ceil|floor|lround|round|atan2)$")


def _tool(name):
    path = shutil.which(name)
    if path is None:
        msg = f"no {name} (install gcc-arm-none-eabi and libnewlib-arm-none-eabi)"
        if os.environ.get("SEMMC_REQUIRE_ARM") == "1":
            pytest.fail(msg + "; SEMMC_REQUIRE_ARM=1", pytrace=False)
        pytest.skip(msg)
    return path


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    _tool("arm-none-eabi-gcc")
    if shutil.which("cmake") is None or shutil.which("ninja") is None:
        pytest.skip("cmake and ninja are needed to build the target image")
    build = tmp_path_factory.mktemp("build-g4")
    subprocess.run(["cmake", "-S", str(ROOT / "firmware"), "-B", str(build), "-G", "Ninja",
                    f"-DCMAKE_TOOLCHAIN_FILE={ROOT / 'firmware/cmake/arm-none-eabi-cortex-m4f.cmake'}",
                    "-DSEMMC_TARGET_STM32G474=ON", "-DSEMMC_SANITIZE=OFF", "-DCMAKE_BUILD_TYPE=MinSizeRel"],
                   check=True, capture_output=True, text=True)
    r = subprocess.run(["cmake", "--build", str(build)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    elf = build / "semmc_stm32g474.elf"
    assert elf.exists() and (build / "semmc_stm32g474.bin").exists() and (build / "semmc_stm32g474.hex").exists()
    return elf


def _symbols(elf):
    out = subprocess.run(["arm-none-eabi-nm", str(elf)], check=True, capture_output=True, text=True).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def _irqs():
    h = DEVICE_H.read_text()
    enum = h[h.index("typedef enum"):h.index("} IRQn_Type;")]
    return {int(n): name for name, n in re.findall(r"^\s*([A-Za-z0-9_]+)_IRQn\s*=\s*(\d+)", enum, re.M)}


def test_vector_table_matches_st_interrupt_list(image, tmp_path):
    raw = tmp_path / "vec.bin"
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", "--only-section=.isr_vector", str(image), str(raw)],
                   check=True)
    data = raw.read_bytes()
    words = [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]
    irqs = _irqs()
    assert len(words) == 16 + max(irqs) + 1 == 118
    s = _symbols(image)
    assert words[0] == s["_estack"] == RAM_END
    assert words[1] == s["Reset_Handler"] | 1
    default = s["Default_Handler"] | 1
    for n in range(max(irqs) + 1):
        entry = words[16 + n]
        if n not in irqs:
            assert entry == 0, f"reserved vector {n} not zero"
            continue
        name = irqs[n] + "_IRQHandler"
        assert entry == s[name] | 1, name
        if irqs[n] in HANDLED:
            assert entry != default, f"{name} is not implemented"
        else:
            assert entry == default, f"{name} unexpectedly implemented"
    assert s["g_vectors"] == FLASH_START


def test_memory_layout_and_reserved_calibration_area(image):
    out = subprocess.run(["arm-none-eabi-objdump", "-h", str(image)], check=True, capture_output=True,
                         text=True).stdout
    sections = {}
    for m in re.finditer(r"^\s*\d+\s+(\S+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", out, re.M):
        sections[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16))
    for name in (".isr_vector", ".text"):
        size, vma, _ = sections[name]
        assert FLASH_START <= vma and vma + size <= CAL_START, name
    for name in (".data", ".bss", ".noinit"):
        size, vma, _ = sections[name]
        assert RAM_START <= vma and vma + size <= RAM_END, name
    _, _, data_lma = sections[".data"]
    assert data_lma + sections[".data"][0] <= CAL_START
    s = _symbols(image)
    assert s["__cal_start"] == CAL_START
    # The image never contains calibration: the binary ends before the reserved area.
    assert image.with_suffix(".bin").stat().st_size <= CAL_START - FLASH_START


def _call_graph(elf):
    dis = subprocess.run(["arm-none-eabi-objdump", "-d", str(elf)], check=True, capture_output=True,
                         text=True).stdout
    graph, cur = {}, None
    for line in dis.splitlines():
        m = re.match(r"^[0-9a-f]+ <([^>]+)>:$", line)
        if m:
            cur = m.group(1)
            graph[cur] = set()
            continue
        m = re.search(r"\b(?:bl|b|b\.w|bl\.w|blx)\s+[0-9a-f]+ <([^>+]+)", line)
        if cur and m and m.group(1) != cur:
            graph[cur].add(m.group(1))
    return graph


def test_no_double_precision_on_the_current_interrupt_path(image):
    """The Cortex-M4F FPU is single precision; a double operation in the current interrupt is a
    software routine of hundreds of cycles. None may be reachable from ADC1_2_IRQHandler."""
    graph = _call_graph(image)
    seen, todo = set(), ["ADC1_2_IRQHandler"]
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        todo.extend(graph.get(f, ()))
    assert "mc_core_fast_step" in seen
    bad = sorted(f for f in seen if DOUBLE_HELPERS.match(f))
    assert not bad, f"double-precision routines reachable from the current interrupt: {bad}"


def test_fault_handlers_force_the_safe_state(image):
    graph = _call_graph(image)
    for h in ("HardFault_Handler", "MemManage_Handler", "BusFault_Handler", "UsageFault_Handler", "NMI_Handler",
              "Default_Handler"):
        reach, todo = set(), [h]
        while todo:
            f = todo.pop()
            if f in reach:
                continue
            reach.add(f)
            todo.extend(graph.get(f, ()))
        assert "board_force_safe" in reach, h


def test_startup_comment_names_this_test():
    src = (ROOT / "firmware/platform/stm32g4/src/startup_stm32g474.c").read_text()
    assert "tests/integration/test_target_firmware.py" in src


def test_emulated_fast_step_instruction_count_regression(image):
    """Exploratory regression guard, not a timing proof: on the target build the core reaches current
    control, and its fast step's emulated instruction count stays below the cycle count of half a PWM
    period of the synthetic configuration. Instructions are not cycles (IT folding, stalls); the deadline
    is checked on the board (g_bench.fast_margin_min_ticks, fast_late_writes)."""
    pytest.importorskip("unicorn")
    import yaml

    from tools import emulate_core_timing as emu

    blob_path = image.parent / "synthetic_for_emulation.bin"
    subprocess.run([sys.executable, str(ROOT / "tools/config_tool.py"), "blob", str(ROOT / "config/vehicle.synthetic.yaml"),
                    "--mode", "sim", "-o", str(blob_path)], check=True, capture_output=True)
    blob = blob_path.read_bytes()
    res = emu.run(image.parent / "semmc_core_timing.elf", blob, 160, image.parent)
    assert res["final_state"] == 4, res["final_state"]  # MANUAL
    assert len(res["fast_pwm"]) > 900
    f_pwm = yaml.safe_load((ROOT / "config/vehicle.synthetic.yaml").read_text())["inverter"]["pwm_frequency_Hz"]
    assert max(res["fast_pwm"]) / emu.SYSCLK_HZ < 0.5 / f_pwm


def test_bench_reader_layout_matches_the_firmware():
    from tools import bench_read

    src = (ROOT / "firmware/platform/stm32g4/src/main.c").read_text()
    m = re.search(r"_Static_assert\(sizeof\(bench_view_t\) == (\d+)u", src)
    assert m and int(m.group(1)) == bench_read.struct.calcsize(bench_read.FORMAT)
    assert bench_read.FORMAT in src
    d = bench_read.decode(bytes(bench_read.SIZE))
    assert d["state_name"] == "BOOT" and d["platform_faults_named"] == []
    assert d["startup_state"] == "INHIBITED" and d["drv_state"] == d["ina_state"] == "UNVERIFIED"
    # The decoder's name lists follow the C enums, in order.
    inc = ROOT / "firmware/include/semmc"
    for header, typedef, prefix, names in [
            ("mc_startup.h", "mc_su_state_t", "MC_SU_", bench_read.STARTUP),
            ("mc_startup.h", "mc_su_fault_t", "MC_SU_F_", bench_read.STARTUP_FAULTS),
            ("mc_precharge.h", "mc_pc_fault_t", "MC_PCF_", bench_read.PRECHARGE_FAULTS),
            ("mc_drv835x.h", "mc_drv_state_t", "MC_DRV_", bench_read.DRV_STATES),
            ("mc_drv835x.h", "mc_drv_error_t", "MC_DRV_ERR_", bench_read.DRV_ERRORS),
            ("mc_ina228.h", "mc_ina_state_t", "MC_INA_", bench_read.INA_STATES),
            ("mc_ina228.h", "mc_ina_error_t", "MC_INA_ERR_", bench_read.INA_ERRORS)]:
        body = re.search(r"typedef enum \{([^{}]*)\} " + typedef + ";", (inc / header).read_text()).group(1)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        members = [m.split("=")[0].strip() for m in body.split(",") if m.strip()]
        assert all(m.startswith(prefix) for m in members), typedef
        assert [m[len(prefix):] for m in members] == names, typedef


def test_target_image_keeps_the_gate_driver_and_meter_inhibited():
    """Until the data sheets are read, the image passes no device description, and DRV_ENABLE is also
    behind the compile-time GATE_DRIVER_CONFIGURED (docs/reference/datasheets/README.md)."""
    src = (ROOT / "firmware/platform/stm32g4/src/main.c").read_text()
    assert re.search(r"#define GATE_DRIVER_CONFIGURED false", src)
    assert "mc_drv835x_init(&g_drv, NULL, NULL, NULL, NULL, 0u);" in src
    assert "mc_ina228_init(&g_ina, NULL, NULL, NULL, NULL, NULL, 0u, 0u);" in src
    calls = re.findall(r"board_set_drv_enable\(([^;]*)\);", src)
    assert calls == ["GATE_DRIVER_CONFIGURED && g_drv.enable_pin"]
    assert "si.gate_driver_ready = GATE_DRIVER_CONFIGURED && g_su.gate_driver_ready" in src


def test_bench_pwm_image_is_separate_and_marked(image):
    """The stage-4 bench image switches the gate signals; it must never be mistaken for the controller image."""
    def strings(p):
        return subprocess.run(["arm-none-eabi-strings", str(p)], check=True, capture_output=True, text=True).stdout
    bench = image.parent / "semmc_stm32g474_pwmtest.elf"
    assert bench.exists()
    assert "semmc stm32g474 BENCH PWM TEST " in strings(bench)
    assert "BENCH PWM TEST" not in strings(image)


def _function_disassembly(elf, name):
    dis = subprocess.run(["arm-none-eabi-objdump", "-d", "--no-show-raw-insn", str(elf)], check=True,
                         capture_output=True, text=True).stdout
    m = re.search(rf"^[0-9a-f]+ <{name}>:\n(.*?)(?:\n\n|\Z)", dis, re.M | re.S)
    assert m, name
    return m.group(1)


def test_fast_slow_handoff_compiles_to_ordered_atomics(image):
    """mc_core.h "Shared state": the release stores (command index, event acknowledgments) and the acquire
    loads compile to DMB-fenced accesses on the target; plain volatile would not order the buffer writes."""
    slow = _function_disassembly(image, "mc_core_slow_step")
    fast = _function_disassembly(image, "mc_core_fast_step")
    assert len(re.findall(r"\bdmb\b", slow)) >= 3      # index store, two acknowledgments (and the acquire loads)
    assert len(re.findall(r"\bdmb\b", fast)) >= 1      # index load (acquire) and the event stores (release)
    src = (ROOT / "firmware/platform/stm32g4/src/main.c").read_text()
    assert "_Static_assert(PRIO_FAST < PRIO_BREAK && PRIO_BREAK < PRIO_SLOW" in src
    assert "NVIC_SetPriorityGrouping(NVIC_GROUP_ALL_PREEMPT)" in src


def test_timing_marker_image_is_separate_and_marked(image):
    def strings(p):
        return subprocess.run(["arm-none-eabi-strings", str(p)], check=True, capture_output=True, text=True).stdout
    timing = image.parent / "semmc_stm32g474_timing.elf"
    assert timing.exists()
    assert "semmc stm32g474 TIMING MARKER " in strings(timing)
    assert "TIMING MARKER" not in strings(image)
