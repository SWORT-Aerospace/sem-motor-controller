#ifndef SEMMC_STM32G4_SYSTEM_CLOCK_H
#define SEMMC_STM32G4_SYSTEM_CLOCK_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool ok;            /* SYSCLK is 160 MHz from the PLL */
    bool hse;           /* the PLL runs from the crystal */
    uint32_t sysclk_hz;
} clock_status_t;

clock_status_t system_clock_init(void);

#define SYSCLK_HZ 160000000u
#define TIMCLK_HZ 160000000u  /* APB1 and APB2 prescalers are 1 */

#endif
