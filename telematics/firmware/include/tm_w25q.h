/* Winbond W25Q-series SPI NOR flash (W25Q128JV, 16 MiB, in the telematics bill of materials) as log
 * storage behind tm_flash_if_t: 4 KiB sector erase, 256-byte page program, read, status polling. Command
 * codes are the JEDEC-common ones of the W25Q128JV data sheet (0x9F, 0x06, 0x05, 0x20, 0x02, 0x03); the
 * device timings are not assumed: busy() polls the status register. Not run on hardware. */
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

/* Read the JEDEC id; 0 if a Winbond device of known capacity answers, <0 otherwise (absent, wrong part, bus
 * error). On success `io` covers `slots` slots from `base` (both within the device). */
int tm_w25q_init(tm_w25q_t *d, const tm_spi_t *spi, uint32_t base, uint32_t slots);

#endif
