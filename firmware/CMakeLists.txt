cmake_minimum_required(VERSION 3.20)
project(semmc_firmware C)

# ---------------------------------------------------------------------------
# Options
#   SEMMC_TARGET_STM32G474 ON -> (with the arm-none-eabi toolchain file) link the
#                               target image semmc_stm32g474.elf/.bin/.hex. The
#                               image carries no calibration: it reads the blob
#                               from the last 4 KB of flash and refuses physical
#                               output unless that blob is hardware-valid.
#   SEMMC_HARDWARE_BUILD  ON  -> also validate SEMMC_VEHICLE_CONFIG in hardware mode
#                               and encode it as cal_hw.bin for flashing. FAILS at
#                               configure time on any missing/invalid rating or
#                               calibration: no hardware blob exists without one.
#   SEMMC_HSE_HZ              -> board crystal frequency (16000000 or empty). Empty:
#                               the target runs from its internal RC and keeps CAN off.
#   SEMMC_SANITIZE        ON  -> ASan + UBSan for host tests.
#   SEMMC_PORTABLE_ONLY   ON  -> build only the portable core library (used for
#                               the arm-none-eabi portability compile check).
# ---------------------------------------------------------------------------
option(SEMMC_TARGET_STM32G474 "Link the STM32G474 target image" OFF)
option(SEMMC_HARDWARE_BUILD "Encode a validated hardware calibration blob (requires a hardware-valid config)" OFF)
option(SEMMC_SANITIZE "Build host tests with ASan/UBSan" ON)
option(SEMMC_PORTABLE_ONLY "Build only the portable core library" OFF)
set(SEMMC_HSE_HZ "" CACHE STRING "Board crystal frequency in Hz (16000000), empty if none is fitted")
set(SEMMC_VEHICLE_CONFIG "${CMAKE_CURRENT_SOURCE_DIR}/../config/vehicle.unconfigured.yaml"
    CACHE FILEPATH "Vehicle configuration validated for a hardware build")

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(SEMMC_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(SEMMC_PROTO_GEN ${SEMMC_ROOT}/protocol/generated)

if(SEMMC_HARDWARE_BUILD)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  execute_process(
    COMMAND ${Python3_EXECUTABLE} ${SEMMC_ROOT}/tools/config_tool.py validate ${SEMMC_VEHICLE_CONFIG} --mode hw
    RESULT_VARIABLE semmc_cfg_rc
    OUTPUT_VARIABLE semmc_cfg_out
    ERROR_VARIABLE semmc_cfg_err)
  if(NOT semmc_cfg_rc EQUAL 0)
    message(FATAL_ERROR
      "Hardware build refused: ${SEMMC_VEHICLE_CONFIG} is not valid for hardware.\n"
      "${semmc_cfg_out}${semmc_cfg_err}\n"
      "Replace every null with a measured/verified value (docs/OPEN_PARAMETERS.md); "
      "unknowns are never defaulted.")
  endif()
  set(SEMMC_HW_BLOB ${CMAKE_BINARY_DIR}/cal_hw.bin)
  execute_process(
    COMMAND ${Python3_EXECUTABLE} ${SEMMC_ROOT}/tools/config_tool.py blob ${SEMMC_VEHICLE_CONFIG} --mode hw
            -o ${SEMMC_HW_BLOB}
    RESULT_VARIABLE semmc_blob_rc)
  if(NOT semmc_blob_rc EQUAL 0)
    message(FATAL_ERROR "Hardware build: encoding ${SEMMC_VEHICLE_CONFIG} failed")
  endif()
  message(STATUS "Hardware calibration blob: ${SEMMC_HW_BLOB} (flash at 0x0807F000, FLASHING.md)")
endif()

set(SEMMC_WARN
  -Wall -Wextra -Wpedantic -Werror -Wdouble-promotion -Wshadow -Wcast-qual
  -Wstrict-prototypes -Wmissing-prototypes -Wfloat-conversion -Wsign-conversion)

# ---- portable core: no I/O, no allocation ---------------------------------
add_library(semmc_core STATIC
  src/calibration/mc_crc.c
  src/calibration/mc_config.c
  src/control/mc_pi.c
  src/control/mc_transforms.c
  src/control/mc_foc.c
  src/control/mc_hall.c
  src/telemetry/mc_freshness.c
  src/protection/mc_protection.c
  src/state_machine/mc_state_machine.c
  src/state_machine/mc_arbiter.c
  src/csia_adapter/mc_csia_shadow.c
  src/core/mc_core.c
  src/transport/mc_can_binding.c
  src/io/mc_io.c
  src/io/mc_precharge.c
  src/io/mc_periph_timing.c
  src/io/mc_ina228.c
  src/io/mc_drv835x.c
  src/io/mc_startup.c
  ${SEMMC_PROTO_GEN}/semmc_protocol.c)
target_include_directories(semmc_core PUBLIC include ${SEMMC_PROTO_GEN})
target_compile_options(semmc_core PRIVATE ${SEMMC_WARN})
if(NOT CMAKE_CROSSCOMPILING)
  target_link_libraries(semmc_core PUBLIC m)
endif()

if(SEMMC_PORTABLE_ONLY)
  return()
endif()

# ---- STM32G474 target image -------------------------------------------------
if(SEMMC_TARGET_STM32G474)
  if(NOT CMAKE_CROSSCOMPILING)
    message(FATAL_ERROR "SEMMC_TARGET_STM32G474 needs -DCMAKE_TOOLCHAIN_FILE=firmware/cmake/arm-none-eabi-cortex-m4f.cmake")
  endif()
  set(G4 ${CMAKE_CURRENT_SOURCE_DIR}/platform/stm32g4)
  find_package(Git QUIET)
  set(SEMMC_GIT_REV "unknown")
  if(GIT_FOUND)
    execute_process(COMMAND ${GIT_EXECUTABLE} -C ${SEMMC_ROOT} rev-parse --short=12 HEAD
                    OUTPUT_VARIABLE SEMMC_GIT_REV OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    execute_process(COMMAND ${GIT_EXECUTABLE} -C ${SEMMC_ROOT} status --porcelain --untracked-files=no
                    OUTPUT_VARIABLE semmc_dirty OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    if(semmc_dirty)
      set(SEMMC_GIT_REV "${SEMMC_GIT_REV}-modified")
    endif()
  endif()
  set(SEMMC_G4_SOURCES
    ${G4}/src/startup_stm32g474.c
    ${G4}/src/system_clock.c
    ${G4}/src/board.c
    ${G4}/src/event_log.c
    ${G4}/src/timebase.c
    ${G4}/src/watchdog.c
    ${G4}/src/calstore.c
    ${G4}/src/pwm.c
    ${G4}/src/adc.c
    ${G4}/src/can.c
    ${G4}/src/uart.c
    ${G4}/src/main.c)
  # semmc_stm32g474: the controller image. semmc_stm32g474_pwmtest: the stage-4 bench image (main.c header).
  # semmc_stm32g474_timing: the controller image with a scope marker on the status-LED pin (main.c).
  foreach(img semmc_stm32g474 semmc_stm32g474_pwmtest semmc_stm32g474_timing)
    add_executable(${img} ${SEMMC_G4_SOURCES})
    set_target_properties(${img} PROPERTIES SUFFIX ".elf")
    target_include_directories(${img} PRIVATE ${G4}/src)
    target_include_directories(${img} SYSTEM PRIVATE ${G4}/vendor/cmsis_device_g4/Include ${G4}/vendor/cmsis_core/Include)
    target_compile_definitions(${img} PRIVATE STM32G474xx SEMMC_GIT_REV="${SEMMC_GIT_REV}")
    if(SEMMC_HSE_HZ)
      target_compile_definitions(${img} PRIVATE SEMMC_HSE_HZ=${SEMMC_HSE_HZ})
    endif()
    target_compile_options(${img} PRIVATE -Wall -Wextra -Werror -Wdouble-promotion -Wshadow -Wstrict-prototypes)
    target_link_libraries(${img} PRIVATE semmc_core m)
    target_link_options(${img} PRIVATE
      -T${G4}/stm32g474xe_flash.ld -nostartfiles --specs=nano.specs -Wl,--gc-sections
      -Wl,-Map=${CMAKE_BINARY_DIR}/${img}.map -Wl,--print-memory-usage)
    set_target_properties(${img} PROPERTIES LINK_DEPENDS ${G4}/stm32g474xe_flash.ld)
    add_custom_command(TARGET ${img} POST_BUILD
      COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${img}> ${CMAKE_BINARY_DIR}/${img}.bin
      COMMAND ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE:${img}> ${CMAKE_BINARY_DIR}/${img}.hex
      COMMAND ${CMAKE_SIZE} $<TARGET_FILE:${img}>
      COMMENT "Target image: ${img}.elf / .bin / .hex (revision ${SEMMC_GIT_REV})")
  endforeach()
  target_compile_definitions(semmc_stm32g474_pwmtest PRIVATE SEMMC_BENCH_PWM_TEST=1)
  target_compile_definitions(semmc_stm32g474_timing PRIVATE SEMMC_TIMING_MARKER=1)
  # Emulation-only harness: the core and the host plant model with the target compiler and libraries,
  # for instruction counts (tools/emulate_core_timing.py). Not a flashable image.
  add_executable(semmc_core_timing ${G4}/timing/core_timing_harness.c platform/host/sim_plant.c)
  set_target_properties(semmc_core_timing PROPERTIES SUFFIX ".elf")
  target_include_directories(semmc_core_timing PRIVATE platform/host)
  target_link_libraries(semmc_core_timing PRIVATE semmc_core m)
  target_link_options(semmc_core_timing PRIVATE -T${G4}/timing/core_timing_harness.ld -nostartfiles --specs=nano.specs
                      -Wl,--gc-sections)
  set_target_properties(semmc_core_timing PROPERTIES LINK_DEPENDS ${G4}/timing/core_timing_harness.ld)
  return()
endif()

if(SEMMC_SANITIZE)
  set(SEMMC_SAN -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
  target_compile_options(semmc_core PRIVATE ${SEMMC_SAN})
  target_link_options(semmc_core PUBLIC ${SEMMC_SAN})
endif()

# ---- host tools ---------------------------------------------------------------
add_executable(semmc_host platform/host/host_main.c platform/host/sim_plant.c)
target_link_libraries(semmc_host PRIVATE semmc_core)
target_include_directories(semmc_host PRIVATE platform/host)
target_compile_options(semmc_host PRIVATE -Wall -Wextra -Werror ${SEMMC_SAN})

add_executable(semmc_contract_report platform/host/contract_report_main.c platform/host/sim_plant.c)
target_link_libraries(semmc_contract_report PRIVATE semmc_core)
target_include_directories(semmc_contract_report PRIVATE platform/host)
target_compile_options(semmc_contract_report PRIVATE -Wall -Wextra -Werror ${SEMMC_SAN})

add_executable(semmc_cfgcheck platform/host/cfgcheck_main.c)
target_link_libraries(semmc_cfgcheck PRIVATE semmc_core)
target_compile_options(semmc_cfgcheck PRIVATE -Wall -Wextra -Werror ${SEMMC_SAN})

# ---- calibration blobs for tests (generated from the YAML by the Python tool) --
find_package(Python3 REQUIRED COMPONENTS Interpreter)
set(SEMMC_CAL_DIR ${CMAKE_BINARY_DIR}/cal)
add_custom_command(
  OUTPUT ${SEMMC_CAL_DIR}/synthetic.bin ${SEMMC_CAL_DIR}/unconfigured.bin
  COMMAND ${Python3_EXECUTABLE} ${SEMMC_ROOT}/tools/config_tool.py blob ${SEMMC_ROOT}/config/vehicle.synthetic.yaml
          --mode sim -o ${SEMMC_CAL_DIR}/synthetic.bin
  COMMAND ${Python3_EXECUTABLE} ${SEMMC_ROOT}/tools/config_tool.py blob ${SEMMC_ROOT}/config/vehicle.unconfigured.yaml
          --mode sim --allow-invalid -o ${SEMMC_CAL_DIR}/unconfigured.bin || true
  DEPENDS ${SEMMC_ROOT}/config/vehicle.synthetic.yaml ${SEMMC_ROOT}/config/vehicle.unconfigured.yaml
          ${SEMMC_ROOT}/config/parameters.yaml ${SEMMC_ROOT}/tools/config_tool.py
  COMMENT "Encoding calibration blobs")
add_custom_target(semmc_cal_blobs ALL DEPENDS ${SEMMC_CAL_DIR}/synthetic.bin)

# ---- unit tests ---------------------------------------------------------------
enable_testing()
set(SEMMC_TESTS test_control test_freshness test_config test_state_machine test_protocol test_core test_core_properties
                test_io test_drivers)
foreach(t ${SEMMC_TESTS})
  add_executable(${t} tests/${t}.c)
  add_dependencies(${t} semmc_cal_blobs)
  target_compile_definitions(${t} PRIVATE SEMMC_SYNTH_BLOB="${SEMMC_CAL_DIR}/synthetic.bin"
                                          SEMMC_UNCONF_BLOB="${SEMMC_CAL_DIR}/unconfigured.bin")
  target_link_libraries(${t} PRIVATE semmc_core)
  target_include_directories(${t} PRIVATE tests platform/host)
  target_compile_options(${t} PRIVATE -Wall -Wextra -Werror ${SEMMC_SAN})
  add_test(NAME ${t} COMMAND ${t} WORKING_DIRECTORY ${SEMMC_ROOT})
endforeach()
target_sources(test_protocol PRIVATE ${SEMMC_PROTO_GEN}/semmc_golden_vectors.c)
# Emulated preemption of the slow step by the current interrupt (GNU ld --wrap; see the test's header).
if(CMAKE_C_COMPILER_ID STREQUAL "GNU" OR CMAKE_C_COMPILER_ID STREQUAL "Clang")
  add_executable(test_core_preemption tests/test_core_preemption.c)
  add_dependencies(test_core_preemption semmc_cal_blobs)
  target_compile_definitions(test_core_preemption PRIVATE SEMMC_SYNTH_BLOB="${SEMMC_CAL_DIR}/synthetic.bin")
  target_link_libraries(test_core_preemption PRIVATE semmc_core)
  target_link_options(test_core_preemption PRIVATE -Wl,--wrap=mc_prot_evaluate -Wl,--wrap=mc_arb_step)
  target_include_directories(test_core_preemption PRIVATE tests)
  target_compile_options(test_core_preemption PRIVATE -Wall -Wextra -Werror ${SEMMC_SAN})
  add_test(NAME test_core_preemption COMMAND test_core_preemption WORKING_DIRECTORY ${SEMMC_ROOT})
endif()
target_sources(test_core PRIVATE platform/host/sim_plant.c)
target_sources(test_core_properties PRIVATE platform/host/sim_plant.c)
# 24 seeds x 12 s of simulated driving; at 6 seeds the defects it was written to catch can slip through.
set_tests_properties(test_core_properties PROPERTIES TIMEOUT 600)
add_test(NAME test_core_properties_24x12 COMMAND test_core_properties 24 12 WORKING_DIRECTORY ${SEMMC_ROOT})
