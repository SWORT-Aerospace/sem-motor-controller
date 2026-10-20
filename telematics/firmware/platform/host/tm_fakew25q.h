/* RAM model of a W25Q-series SPI NOR flash on the tm_spi_t transport, for host tests and the host
 * simulator. It implements what tm_w25q.c relies on: JEDEC id (0x9F), write enable (0x06) and the WEL bit,
 * status register 1 (0x05) with BUSY, 4 KiB sector erase (0x20), chip erase (0xC7), 256-byte page program
 * (0x02, wrapping within the page, clearing bits only) and read (0x03). Operations take simulated time;
 * any command but a status read while busy is ignored, as the part does, and counted as a violation, as
 * is a program or erase without WEL. The timings are parameters, not the part's (tests run both a typical
 * and a slow setting). The memory may be smaller than the capacity the id reports; addresses beyond it are
 * violations. */
#ifndef TM_FAKEW25Q_H
#define TM_FAKEW25Q_H

#include <stdbool.h>
#include <stdint.h>

#include "tm_bus.h"

typedef struct {
    uint8_t *mem;
    uint32_t size;
    uint8_t jedec[3];                      /* manufacturer, type, capacity code (2^code bytes) */
    bool present;                          /* false: the bus reads 0xFF (no device) */
    uint64_t (*now_us)(void);
    uint64_t busy_until;
    bool wel;
    uint32_t sector_erase_us, page_program_us, chip_erase_us;
    uint32_t erases, programs, chip_erases, violations;
    tm_spi_t spi;
} tm_fakew25q_t;

/* capacity_code 0x18 = 16 MiB (W25Q128JV). now_us may be 0: then every operation completes at once. */
void tm_fakew25q_init(tm_fakew25q_t *f, uint8_t *mem, uint32_t size, uint8_t capacity_code, uint64_t (*now_us)(void));

#endif
