/* Calibration blob in the reserved last 4 KB of flash (linker symbols __cal_start, __cal_size).
 *
 * The blob is written by the flashing procedure (FLASHING.md), never by this firmware. calstore_find()
 * returns its length from the header (36 + 8 x n_entries bytes) or 0 when the area is erased or the
 * header is not a blob; mc_config_parse_blob() then checks the format, CRC and every entry. */
#ifndef SEMMC_STM32G4_CALSTORE_H
#define SEMMC_STM32G4_CALSTORE_H

#include <stddef.h>
#include <stdint.h>

size_t calstore_find(const uint8_t **blob);

#endif
