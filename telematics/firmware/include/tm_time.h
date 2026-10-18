/* 64-bit microsecond time from a 32-bit timer and a software overflow count. */
#ifndef TM_TIME_H
#define TM_TIME_H

#include <stdbool.h>
#include <stdint.h>

/* `hi` is the number of overflows the update interrupt has counted, `count` a value read from the timer
 * (counter or capture register) and `overflow_pending` whether the timer's update flag was set when it
 * was read, i.e. the counter has wrapped but the update interrupt has not yet incremented `hi`. A value in
 * the lower half of the range was then taken after the wrap and belongs to hi + 1; a value in the upper
 * half was taken before it. This is exact as long as the reading happens less than half a period
 * (2147 s at 1 MHz) after the event, which the capture interrupt guarantees. */
static inline uint64_t tm_time_extend(uint32_t hi, uint32_t count, bool overflow_pending)
{
    if (overflow_pending && count < 0x80000000u) hi += 1u;
    return ((uint64_t)hi << 32) | count;
}

#endif
