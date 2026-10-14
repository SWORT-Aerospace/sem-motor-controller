#include "semmc/mc_crc.h"

uint8_t mc_crc8_j1850_update(uint8_t crc, const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            const unsigned c = crc;
            crc = (uint8_t)((c & 0x80u) ? ((c << 1) ^ 0x1Du) : (c << 1));
        }
    }
    return crc;
}

uint8_t mc_crc8_j1850(const uint8_t *data, size_t len)
{
    return (uint8_t)(mc_crc8_j1850_update(0xFFu, data, len) ^ 0xFFu);
}

uint8_t mc_crc8_with_data_id(uint16_t data_id, const uint8_t *data, size_t len)
{
    const uint8_t id[2] = {(uint8_t)(data_id & 0xFFu), (uint8_t)(data_id >> 8)};
    uint8_t crc = mc_crc8_j1850_update(0xFFu, id, 2);
    crc = mc_crc8_j1850_update(crc, data, len);
    return (uint8_t)(crc ^ 0xFFu);
}

uint32_t mc_crc32(const uint8_t *data, size_t len)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : (crc >> 1);
        }
    }
    return crc ^ 0xFFFFFFFFu;
}
