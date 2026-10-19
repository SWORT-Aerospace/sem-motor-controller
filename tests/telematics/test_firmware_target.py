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


def _body(src: str, signature: str) -> str:
    start = src.index(signature)
    return src[start:src.index("\n}\n", start)]


def test_register_sequences_follow_st_hal():
    """The orderings that the audit against ST's HAL v1.6.3 corrected (docs/U575_REGISTER_CHECK.md): what ST's own
    driver does, kept from regressing. Text checks of the source; they do not show the registers behave so on the
    part (RM0456 and the data sheet remain unread: T-U5-DOCS; ES0499 is covered by the test below)."""
    u5 = FW / "platform" / "u575"
    board = (u5 / "board_u575.c").read_text()
    gpio = _body(board, "static void gpio_mode(")
    assert gpio.index("AFR[") < gpio.index("g->MODER =")                # alternate function before mode
    init = _body(board, "void board_init(void)")
    order = [init.index(k) for k in ("PWR_DBPR_DBP, 10000u", "RCC->BDCR |= RCC_BDCR_LSEON;",
                                     "RCC->BDCR |= RCC_BDCR_LSESYSEN;", "RCC_BDCR_LSESYSRDY", "RCC_CR_MSIPLLSEL",
                                     "RCC_CR_MSIPLLEN")]
    assert order == sorted(order)                                       # LSE for RCC, then MSI PLL mode
    cap = _body(board, "void board_capture_start(void)")
    assert cap.index("TIM2->CR1 = TIM_CR1_URS;") < cap.index("TIM_EGR_UG") < cap.index("__DSB()") < cap.index(
        "TIM2->SR = 0u") < cap.index("TIM_CR1_URS | TIM_CR1_CEN")
    pll = _body(board, "bool board_pll1q_20mhz(void)")
    assert pll.index("PWR_VOSR_VOSRDY") < pll.index("PWR_SVMSR_ACTVOSRDY") < pll.index("RCC_CR_PLL1ON")
    flash = (u5 / "flash_u575.c").read_text()
    for fn in ("static int f_erase(", "static int f_program("):
        assert "swapped()" in _body(flash, fn)                          # no erase or program with SWAP_BANK set
    i2c = _body((u5 / "i2c_u575.c").read_text(), "static void recover(void)")
    assert "I2C_CR2_STOP" in i2c and "TXDR" in i2c
    assert "USART_ISR_TEACK" in (u5 / "uart_u575.c").read_text()
    assert "SPI1->CFG1 & SPI_CFG1_CRCSIZE" in (u5 / "spi_u575.c").read_text()
    can = _body((u5 / "can_u575.c").read_text(), "const char *can_monitor_init(")
    assert can.index("bitrate == 0u") < can.index("KERNEL_HZ / bitrate")


def test_es0499_workarounds_in_the_source():
    """The workarounds that ES0499 Rev 12 (read with UM2861 Rev 10, docs/U575_REGISTER_CHECK.md section 5) calls
    for, kept from regressing. Text checks of the source; the bench shows whether the LSE starts and locks."""
    u5 = FW / "platform" / "u575"
    init = _body((u5 / "board_u575.c").read_text(), "void board_init(void)")
    # 2.2.3, 2.2.16: never the low or medium-low LSE drive; the drive is raised only with the LSE off (HAL rcc.h)
    off, byp, rdy, drv, lsco, on = (init.index(k) for k in (
        "RCC->BDCR &= ~(RCC_BDCR_LSEON | RCC_BDCR_LSESYSEN);", "RCC->BDCR &= ~RCC_BDCR_LSEBYP;",
        "wait_clear_kick(&RCC->BDCR, RCC_BDCR_LSERDY", "(RCC->BDCR & ~RCC_BDCR_LSEDRV) | RCC_BDCR_LSEDRV_1",
        "RCC->BDCR &= ~RCC_BDCR_LSCOEN;", "RCC->BDCR |= RCC_BDCR_LSEON;"))
    assert off < byp < rdy < drv < on and lsco < on                     # 2.2.9: LSCO off before the LSE starts
    assert "(RCC->BDCR & RCC_BDCR_LSEDRV) < RCC_BDCR_LSEDRV_1" in init and "LSEDRV_0" not in init
    # 2.20.2: a bus error in controller mode is cleared and the transfer goes on; arbitration loss still ends it
    wait = _body((u5 / "i2c_u575.c").read_text(), "static int wait_flag(uint32_t mask)")
    assert "if (isr & I2C_ISR_BERR) I2C1->ICR = I2C_ICR_BERRCF;" in wait
    arlo = wait[wait.index("if (isr & I2C_ISR_ARLO)"):]
    assert arlo.index("return TM_BUS_ERROR") < arlo.index("if (isr & mask)")
    assert "I2C_ISR_BERR | I2C_ISR_ARLO" not in wait
