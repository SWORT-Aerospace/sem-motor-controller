/* CRC helpers.
 *
 * CRC-8/SAE-J1850: poly 0x1D, init 0xFF, xorout 0xFF, no reflection
 *   (check value for "123456789" = 0x4B). Used as the application integrity
 *   check on CAN payloads, seeded with a per-message 16-bit Data ID so a frame
 *   decoded under the wrong ID or wrong protocol major version fails.
 * CRC-32/ISO-HDLC (zlib crc32): poly 0x04C11DB7 reflected, init/xorout
 *   0xFFFFFFFF (check 0xCBF43926). Used for the calibration blob.
 */
#ifndef SEMMC_MC_CRC_H
#define SEMMC_MC_CRC_H

#include <stddef.h>
#include <stdint.h>

uint8_t mc_crc8_j1850_update(uint8_t crc, const uint8_t *data, size_t len);
uint8_t mc_crc8_j1850(const uint8_t *data, size_t len);
/* CRC over [data_id LE (2 bytes)] ++ data. */
uint8_t mc_crc8_with_data_id(uint16_t data_id, const uint8_t *data, size_t len);
uint32_t mc_crc32(const uint8_t *data, size_t len);

#endif
