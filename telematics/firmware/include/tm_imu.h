/* Sensors on I2C1: an ST LSM6DSOX or ISM330DHCX inertial unit and a TI TMP117 temperature sensor.
 *
 * Register addresses and codes as the data sheets give them (LSM6DSOX DS12814, ISM330DHCX DS13012, TMP117
 * SNOSD82): WHO_AM_I 0x0F = 0x6C / 0x6B, CTRL1_XL 0x10, CTRL2_G 0x11, CTRL3_C 0x12, STATUS_REG 0x1E,
 * OUTX_L_G 0x22, OUTX_L_A 0x28; TMP117 temperature 0x00 (7.8125 m degC per LSB), device id 0x0F = 0x0117.
 * They are to be checked against the copies in docs/reference/datasheets before the bench; nothing here has
 * run on hardware. Each read is one bounded I2C transaction. */
#ifndef TM_IMU_H
#define TM_IMU_H

#include <stdbool.h>
#include <stdint.h>

#include "tm_bus.h"

typedef struct {
    const tm_i2c_t *bus;
    uint8_t addr;           /* 0x6A or 0x6B (SA0) */
    uint8_t who;
    uint32_t errors;
} tm_imu_t;

/* Identify the device and set 104 Hz, +-4 g, 500 dps, block data update, address auto-increment. */
int tm_imu_init(tm_imu_t *m, const tm_i2c_t *bus, uint8_t addr);
/* One sample if both accelerometer and gyroscope have new data: 1; nothing new: 0; error: < 0.
 * Units: m/s^2 and rad/s, sensor axes (the mounting decides which is longitudinal). */
int tm_imu_read(tm_imu_t *m, float acc[3], float gyr[3]);

typedef struct {
    const tm_i2c_t *bus;
    uint8_t addr;           /* 0x48 to 0x4B */
    uint32_t errors;
} tm_tmp117_t;

int tm_tmp117_init(tm_tmp117_t *t, const tm_i2c_t *bus, uint8_t addr);
/* Temperature in centi-degC (rounded); < 0 return on error, the value is then not written. */
int tm_tmp117_read(tm_tmp117_t *t, int16_t *centi_degc);

#endif
