# Portability check ONLY: compiles the portable core for Cortex-M4F (STM32G4
# class) to prove it has no host dependencies and to measure code size. It does
# NOT produce a firmware image: there is no startup code, linker script, HAL,
# PWM/ADC driver or motor-control integration for the target in v0.1.
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_C_FLAGS_INIT "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard -ffunction-sections -fdata-sections")
