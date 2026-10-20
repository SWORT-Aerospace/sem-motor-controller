/* RAM model of a flash device for host tests: erase sets 0xFF, programming a unit that is not erased is
 * an error (the STM32U5 internal flash forbids it: its ECC covers each quad-word), operations take
 * simulated time and a stall window keeps the device busy. */
#ifndef TM_FAKEFLASH_H
#define TM_FAKEFLASH_H

#include <stdint.h>

#include "tm_flashlog.h"

typedef struct {
    uint8_t *mem;
    uint32_t size;
    uint64_t (*now_us)(void);
    uint64_t busy_until;
    uint32_t erase_us, program_us;
    uint64_t stall_t0, stall_t1;          /* busy throughout [t0, t1) */
    uint32_t erases, programs, violations;
    int fail_next_program;                 /* inject one program error */
    tm_flash_if_t io;
} tm_fakeflash_t;

void tm_fakeflash_init(tm_fakeflash_t *ff, uint8_t *mem, uint32_t size, uint32_t page_bytes, uint32_t prog_bytes,
                       uint64_t (*now_us)(void));

#endif
