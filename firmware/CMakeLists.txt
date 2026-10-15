cmake_minimum_required(VERSION 3.20)
project(semmc_firmware C)

# ---------------------------------------------------------------------------
# Options
#   SEMMC_HARDWARE_BUILD  ON  -> validate SEMMC_VEHICLE_CONFIG in hardware mode at
#                               configure time and FAIL on any missing/invalid
#                               rating or calibration. The STM32G4 platform layer
#                               is not implemented in v0.1, so a hardware build
#                               stops there in any case.
#   SEMMC_SANITIZE        ON  -> ASan + UBSan for host tests.
#   SEMMC_PORTABLE_ONLY   ON  -> build only the portable core library (used for
#                               the arm-none-eabi portability compile check).
# ---------------------------------------------------------------------------
option(SEMMC_HARDWARE_BUILD "Hardware-enabled build (requires a validated hardware config)" OFF)
option(SEMMC_SANITIZE "Build host tests with ASan/UBSan" ON)
option(SEMMC_PORTABLE_ONLY "Build only the portable core library" OFF)
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
  message(FATAL_ERROR
    "Hardware build: configuration validated, but the STM32G4 platform layer is not "
    "implemented in v0.1 (firmware/platform/stm32g4/README.md). No embedded motor "
    "firmware image can be produced from this tree.")
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
  ${SEMMC_PROTO_GEN}/semmc_protocol.c)
target_include_directories(semmc_core PUBLIC include ${SEMMC_PROTO_GEN})
target_compile_options(semmc_core PRIVATE ${SEMMC_WARN})
if(NOT CMAKE_CROSSCOMPILING)
  target_link_libraries(semmc_core PUBLIC m)
endif()

if(SEMMC_PORTABLE_ONLY)
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
set(SEMMC_TESTS test_control test_freshness test_config test_state_machine test_protocol test_core)
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
target_sources(test_core PRIVATE platform/host/sim_plant.c)
