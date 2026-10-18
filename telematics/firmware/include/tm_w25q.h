/* Winbond W25Q-series SPI NOR flash (W25Q128JV, 16 MiB, in the telematics bill of materials) as log
 * storage behind tm_flash_if_t: 4 KiB sector erase, 256-byte page program, chip erase, read, status
 * polling. Command codes are the common SPI NOR set (0x9F JEDEC id, 0x06 write enable, 0x05 status, 0x20
 * sector erase, 0x02 page program, 0xC7 chip erase, 0x03 read) with 3-byte addresses, so parts of 1 to 16 MiB
 * only; the W25Q128JV data sheet has not been read in this environment, so codes, pinout and timings are to be
 * confirmed against it (bench step B1 shows the JEDEC id). The device timings are not assumed: busy() polls the
 * status register. Standard SPI only: /WP and /HOLD must be tied high on the board. Not run on hardware. */
#ifndef TM_W25Q_H
#define TM_W25Q_H

#include <stdint.h>

#include "tm_bus.h"
#include "tm_flashlog.h"

typedef struct {
    const tm_spi_t *spi;
    uint8_t jedec[3];
    uint32_t capacity;
    tm_flash_if_t io;
} tm_w25q_t;

/* Read the JEDEC id; 0 if a Winbond device of 1 to 16 MiB answers, <0 otherwise (absent, another maker, a
 * larger part that needs 4-byte addresses, bus error). On success `io` covers `slots` slots from `base` (both within the device; slots 0: to the end). */
int tm_w25q_init(tm_w25q_t *d, const tm_spi_t *spi, uint32_t base, uint32_t slots);

#endif
