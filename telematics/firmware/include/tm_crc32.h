#ifndef TM_CRC32_H
#define TM_CRC32_H

#include <stddef.h>
#include <stdint.h>

/* CRC-32 as zlib computes it (reflected polynomial 0xEDB88320, initial and final XOR 0xFFFFFFFF), so the
 * host reader (Python zlib.crc32) checks what the firmware writes. `crc` is the running value, 0 to start. */
uint32_t tm_crc32(uint32_t crc, const uint8_t *p, size_t n);

#endif
