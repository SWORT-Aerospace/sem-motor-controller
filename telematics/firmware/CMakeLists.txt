# Telematics firmware for the NUCLEO-U575ZI-Q (STM32U575ZITxQ, Cortex-M33).
#
#   host build (default): the portable library, its unit tests and the host simulator
#     cmake -S telematics/firmware -B build-telematics && cmake --build build-telematics && ctest --test-dir build-telematics
#   target build: the linked image for the board (needs arm-none-eabi-gcc)
#     cmake -S telematics/firmware -B build-u575 -DCMAKE_TOOLCHAIN_FILE=$PWD/telematics/firmware/cmake/arm-none-eabi-cortex-m33.cmake -DTM_TARGET_U575=ON
#     cmake --build build-u575
# Nothing here depends on the controller firmware in firmware/.
cmake_minimum_required(VERSION 3.20)
project(telematics_firmware C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
option(TM_TARGET_U575 "Build the NUCLEO-U575ZI-Q image" OFF)

set(TM_PORTABLE src/tm_crc32.c src/tm_wheel.c src/tm_queue.c src/tm_stlg.c src/tm_flashlog.c src/tm_reset.c
                src/tm_app.c src/tm_w25q.c src/tm_imu.c)
set(TM_GNSS src/tm_gnss.c)                     # GNSS and PPS: the vehicle image and the host build
set(TM_WARN -Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion)

execute_process(COMMAND git describe --always --dirty --abbrev=12 WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                OUTPUT_VARIABLE TM_GIT_REV OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT TM_GIT_REV)
  set(TM_GIT_REV "unknown")
endif()

if(NOT TM_TARGET_U575)
  add_library(tm_portable STATIC ${TM_PORTABLE} ${TM_GNSS} platform/host/tm_fakeflash.c platform/host/tm_fakew25q.c)
  target_include_directories(tm_portable PUBLIC include platform/host)
  target_compile_options(tm_portable PRIVATE ${TM_WARN} -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(tm_portable PUBLIC -fsanitize=address,undefined)
  add_executable(tm_tests tests/test_tm.c tests/test_drivers.c)
  target_link_libraries(tm_tests tm_portable)
  target_compile_options(tm_tests PRIVATE -Wall -Wextra -Werror)
  add_executable(tm_hostsim platform/host/tm_hostsim.c)
  target_link_libraries(tm_hostsim tm_portable)
  target_compile_options(tm_hostsim PRIVATE -Wall -Wextra -Werror)
  enable_testing()
  add_test(NAME tm_tests COMMAND tm_tests)
else()
  set(U5 platform/u575)
  set(TM_TARGET_SRC ${U5}/startup_stm32u575.c ${U5}/system_u575.c ${U5}/board_u575.c ${U5}/flash_u575.c
                    ${U5}/uart_u575.c ${U5}/spi_u575.c ${U5}/i2c_u575.c ${U5}/main_u575.c)
  # tm_u575: wheel capture to the log (first milestone); tm_u575_can: the same plus FDCAN1 in bus-monitoring
  # mode (the controller receive fixture); tm_u575_vehicle: tm_u575_can plus the GNSS receiver and its PPS
  # (configuration A)
  foreach(variant IN ITEMS tm_u575 tm_u575_can tm_u575_vehicle)
    if(variant STREQUAL "tm_u575_can")
      add_executable(${variant}.elf ${TM_PORTABLE} ${TM_TARGET_SRC} ${U5}/can_u575.c)
    elseif(variant STREQUAL "tm_u575_vehicle")
      add_executable(${variant}.elf ${TM_PORTABLE} ${TM_GNSS} ${TM_TARGET_SRC} ${U5}/can_u575.c ${U5}/gnss_u575.c)
    else()
      add_executable(${variant}.elf ${TM_PORTABLE} ${TM_TARGET_SRC})
    endif()
    target_include_directories(${variant}.elf PRIVATE include ${U5} ${U5}/vendor/cmsis_device_u5/Include
                               ${U5}/vendor/cmsis_core/Include)
    target_compile_definitions(${variant}.elf PRIVATE STM32U575xx TM_GIT_REV="${TM_GIT_REV}")
    target_compile_options(${variant}.elf PRIVATE ${TM_WARN} -ffunction-sections -fdata-sections)
    target_link_options(${variant}.elf PRIVATE -T${CMAKE_CURRENT_SOURCE_DIR}/${U5}/stm32u575zi_flash.ld
                        -Wl,--gc-sections -Wl,-Map=${variant}.map -Wl,--print-memory-usage --specs=nano.specs
                        --specs=nosys.specs)
    add_custom_command(TARGET ${variant}.elf POST_BUILD
                       COMMAND ${CMAKE_OBJCOPY} -O binary ${variant}.elf ${variant}.bin
                       COMMAND ${CMAKE_OBJCOPY} -O ihex ${variant}.elf ${variant}.hex
                       COMMAND ${CMAKE_SIZE_UTIL} ${variant}.elf)
  endforeach()
  target_compile_definitions(tm_u575_can.elf PRIVATE TM_ENABLE_CAN=1)
  target_compile_definitions(tm_u575_vehicle.elf PRIVATE TM_ENABLE_CAN=1 TM_ENABLE_GNSS=1)
endif()
