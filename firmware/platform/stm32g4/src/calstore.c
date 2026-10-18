#include "calstore.h"

extern const uint8_t __cal_start[];
extern const uint8_t __cal_size[];

size_t calstore_find(const uint8_t **blob)
{
    const uint8_t *p = __cal_start;
    const size_t cap = (size_t)(uintptr_t)__cal_size;
    *blob = p;
    if (p[0] != 'S' || p[1] != 'M' || p[2] != 'C' || p[3] != 'B') return 0u;
    const size_t n = (size_t)p[10] | ((size_t)p[11] << 8u); /* n_entries, mc_config.h header layout */
    const size_t len = 32u + 8u * n + 4u;
    return len <= cap ? len : 0u;
}
