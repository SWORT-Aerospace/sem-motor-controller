# Vendored headers

Copied unchanged from the manufacturers' public repositories. Do not edit; update by copying a newer
release and recording its commit here.

| Directory | Source | Commit | Files | License |
|---|---|---|---|---|
| `cmsis_device_g4/Include/` | https://github.com/STMicroelectronics/cmsis-device-g4 | `626ee412334a5ed2e5b320af5a8d77d69f03a558` | `stm32g4xx.h`, `stm32g474xx.h`, `system_stm32g4xx.h` | Apache-2.0 (`cmsis_device_g4/LICENSE.md`) |
| `cmsis_core/Include/` | https://github.com/STMicroelectronics/cmsis-core (CMSIS-Core(M) 6.1) | `01d18147527e30ed69ace1cb03b818de78bc7062` | the six headers `core_cm4.h` needs with GCC | Apache-2.0 (`cmsis_core/LICENSE.md`) |

The device header is ST's register and bit definition for the STM32G474: every register access in
`firmware/platform/stm32g4/src/` uses its names, not hand-written addresses. Sequences (clock switch,
ADC enable and calibration, FDCAN initialisation) follow ST's HAL driver,
`STMicroelectronics/stm32g4xx-hal-driver@a6001282dfacfff57e9710250f15e4333b578865`, which is
referenced in the source comments and not vendored.
