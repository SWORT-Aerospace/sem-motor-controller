# Vendored headers (STM32U575)

Copied unchanged from the manufacturers' public repositories at pinned commits (fetched from
raw.githubusercontent.com on 2026-10-18). Do not edit; update by copying a newer release and recording its commit
and SHA-256 here. `tests/telematics/test_firmware_target.py` checks the image's vector table against the
interrupt list in `stm32u575xx.h`.

| File | Source | Commit | SHA-256 | License |
|---|---|---|---|---|
| `cmsis_device_u5/Include/stm32u575xx.h` | STMicroelectronics/cmsis-device-u5 v1.4.3 | `624374fa1e21ca195d6f2102ac0caaa50d0ea4c8` | `854b9a7b5534b1bce610ece61cd975e5380010bb398ce3c4b6d1768c00232c77` | Apache-2.0 (`cmsis_device_u5/LICENSE.md`) |
| `cmsis_device_u5/Include/stm32u5xx.h` | same | same | `e14c30935b33e903dd293e84632f5b3c374bf5b6554182f188dba3a798ee7bc5` | Apache-2.0 |
| `cmsis_device_u5/Include/system_stm32u5xx.h` | same | same | `73675e7a1dfd4a6378f08f6dce3ec072d6244f70365276ef52704144559b289e` | Apache-2.0 |
| `cmsis_core/Include/core_cm33.h` | ARM-software/CMSIS_5 5.9.0 | `2b7495b8535bdcb306dac29b9ded4cfb679d7e5c` | `225c47c36230edaa314f1e7a45b38279f6ab4d58faeb132226db35f7007d58aa` | Apache-2.0 (`cmsis_core/LICENSE.md`) |
| `cmsis_core/Include/cmsis_compiler.h` | same | same | `b51963d271c1571ca3463654c76aa7ea50c4eac5d0a2710df10414ac64d9e0f8` | Apache-2.0 |
| `cmsis_core/Include/cmsis_gcc.h` | same | same | `43bfd1fe69fbbc2ca70aaf7d43cc3e20f16e0c7f66e1bdef9b51af6dc14b2617` | Apache-2.0 |
| `cmsis_core/Include/cmsis_version.h` | same | same | `184c19fd3ee73632edf35a0b4d49cd48be75fbf49e6ccb19d9db05fa83bea4b3` | Apache-2.0 |
| `cmsis_core/Include/mpu_armv8.h` | same | same | `2c7d22a344cedcc1e35380d1f76f0e6c55da5e3101e6a41fd85497d1841fe8c9` | Apache-2.0 |

CMSIS 5.9.0 and cmsis-device-u5 v1.4.3 are the versions STM32CubeU5 v1.9.0 ships (its release notes; the copies are
byte-identical). `cmsis_core/LICENSE.md` is the Apache-2.0 text as ST distributes it with CMSIS-Core.

Register sequences in `platform/u575/` (flash erase and programming, reset flags, LSE and MSI PLL mode, PLL1, the
peripheral clock enables) follow ST's HAL, `STMicroelectronics/stm32u5xx-hal-driver` v1.6.3
(`2552682ee5a0d6f826a6435750fc9267be65868b`), and the board pins follow ST's NUCLEO-U575ZI-Q BSP v1.2.3
(`STMicroelectronics/stm32u5xx-nucleo-bsp@ed50f1d2d4940e4efe23104027b8008ce79037f5`), Zephyr v4.4.2
(`zephyrproject-rtos/zephyr@dccb09599635bdff17633fa7e9dab014b91dce90`, `boards/st/nucleo_u575zi_q`) and ST's open pin
data (`STMicroelectronics/STM32_open_pin_data@7d1f1514ed5583ec5007ad91236b4e1d377295b1`); these are referenced, not
vendored. RM0456, DS13737 and UM2861 were not readable from this environment; the items that depend on them are listed
in `telematics/firmware/BENCH.md`.
