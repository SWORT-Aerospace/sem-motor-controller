/* Time bases.
 *   TIM2: 32-bit free-running counter at 1 MHz, extended to 64 bits with mc_time_extend() in the
 *         slow step (it wraps every 71.6 minutes; the slow step runs at 1 kHz).
 *   TIM6: 1 kHz update interrupt that runs the slow step (priority below the current interrupt).
 *   DWT cycle counter: the fast step's measured dt and execution time (160 MHz). */
#ifndef SEMMC_STM32G4_TIMEBASE_H
#define SEMMC_STM32G4_TIMEBASE_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_types.h"

void timebase_init(void);
void timebase_start_slow_tick(uint32_t priority);
uint32_t timebase_us32(void);
/* True if the next 1 ms tick is already pending: the slow step took longer than its period. */
bool timebase_slow_tick_pending(void);
mc_time_us_t timebase_now_us(void); /* call from one context only (the slow step) */

#endif
