/* Little-endian stores (the STLG format is little-endian; so is the Cortex-M33, but byte order is not
 * assumed). */
#ifndef TM_LE_H
#define TM_LE_H

#include <stdint.h>

static inline void tm_le16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static inline void tm_le32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4u; i++) p[i] = (uint8_t)(v >> (8u * i));
}

static inline void tm_le64(uint8_t *p, uint64_t v)
{
    for (unsigned i = 0; i < 8u; i++) p[i] = (uint8_t)(v >> (8u * i));
}

static inline uint16_t tm_rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }

static inline uint32_t tm_rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

#endif
