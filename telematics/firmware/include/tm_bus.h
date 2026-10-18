/* Bus transports of the telematics unit's own peripherals (not the vehicle bus): SPI1 for the external NOR
 * flash, I2C1 for the IMU and the temperature sensors. Every call finishes or fails within a bound the
 * platform states (bytes x byte time + a fixed timeout); none waits on a device indefinitely, so a
 * missing or stuck device costs at most that bound and is reported as an error. */
#ifndef TM_BUS_H
#define TM_BUS_H

#include <stdbool.h>
#include <stdint.h>

enum { TM_BUS_OK = 0, TM_BUS_NACK = -1, TM_BUS_TIMEOUT = -2, TM_BUS_ERROR = -3 };

typedef struct {
    /* full-duplex transfer of n bytes with chip select held low; tx or rx may be 0 */
    int (*xfer)(void *ctx, const uint8_t *tx, uint8_t *rx, uint32_t n);
    /* two-phase transfer (command then data) under one chip select */
    int (*xfer2)(void *ctx, const uint8_t *cmd, uint32_t ncmd, const uint8_t *tx, uint8_t *rx, uint32_t n);
    void *ctx;
} tm_spi_t;

typedef struct {
    /* write nw bytes, then (repeated start) read nr bytes from the 7-bit address; nr or nw may be 0 */
    int (*write_read)(void *ctx, uint8_t addr7, const uint8_t *w, uint32_t nw, uint8_t *r, uint32_t nr);
    void *ctx;
} tm_i2c_t;

#endif
