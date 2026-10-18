#include "tm_imu.h"

#define WHO_AM_I 0x0Fu
#define CTRL1_XL 0x10u
#define CTRL2_G 0x11u
#define CTRL3_C 0x12u
#define STATUS_REG 0x1Eu
#define OUTX_L_G 0x22u
#define WHO_LSM6DSOX 0x6Cu
#define WHO_ISM330DHCX 0x6Bu
#define XL_104HZ_4G 0x48u        /* ODR_XL 0100 = 104 Hz, FS_XL 10 = +-4 g */
#define G_104HZ_500DPS 0x44u     /* ODR_G 0100 = 104 Hz, FS_G 01 = 500 dps */
#define C3_BDU_IFINC 0x44u       /* BDU, IF_INC */
#define ACC_MG_PER_LSB 0.122f    /* +-4 g */
#define GYR_MDPS_PER_LSB 17.50f  /* 500 dps */
#define G0 9.80665f
#define DEG2RAD 0.017453292519943295f

static int wr(const tm_i2c_t *b, uint8_t a, uint8_t reg, uint8_t v)
{
    uint8_t w[2] = {reg, v};
    return b->write_read(b->ctx, a, w, 2, 0, 0);
}

int tm_imu_init(tm_imu_t *m, const tm_i2c_t *bus, uint8_t addr)
{
    m->bus = bus;
    m->addr = addr;
    m->errors = 0;
    uint8_t reg = WHO_AM_I;
    int e = bus->write_read(bus->ctx, addr, &reg, 1, &m->who, 1);
    if (e) return e;
    if (m->who != WHO_LSM6DSOX && m->who != WHO_ISM330DHCX) return TM_BUS_ERROR;
    if ((e = wr(bus, addr, CTRL3_C, C3_BDU_IFINC)) || (e = wr(bus, addr, CTRL1_XL, XL_104HZ_4G)) ||
        (e = wr(bus, addr, CTRL2_G, G_104HZ_500DPS)))
        return e;
    return TM_BUS_OK;
}

int tm_imu_read(tm_imu_t *m, float acc[3], float gyr[3])
{
    uint8_t reg = STATUS_REG, st, raw[12];
    int e = m->bus->write_read(m->bus->ctx, m->addr, &reg, 1, &st, 1);
    if (e) {
        m->errors++;
        return e;
    }
    if ((st & 0x03u) != 0x03u) return 0;
    reg = OUTX_L_G;                       /* gyro x,y,z then accel x,y,z, little-endian int16 */
    if ((e = m->bus->write_read(m->bus->ctx, m->addr, &reg, 1, raw, 12)) != 0) {
        m->errors++;
        return e;
    }
    for (int i = 0; i < 3; i++) {
        int16_t g = (int16_t)(raw[2 * i] | (raw[2 * i + 1] << 8));
        int16_t a = (int16_t)(raw[6 + 2 * i] | (raw[6 + 2 * i + 1] << 8));
        gyr[i] = (float)g * GYR_MDPS_PER_LSB * 1e-3f * DEG2RAD;
        acc[i] = (float)a * ACC_MG_PER_LSB * 1e-3f * G0;
    }
    return 1;
}

int tm_tmp117_init(tm_tmp117_t *t, const tm_i2c_t *bus, uint8_t addr)
{
    t->bus = bus;
    t->addr = addr;
    t->errors = 0;
    uint8_t reg = 0x0Fu, id[2];
    int e = bus->write_read(bus->ctx, addr, &reg, 1, id, 2);
    if (e) return e;
    return ((id[0] << 8 | id[1]) & 0x0FFFu) == 0x0117u ? TM_BUS_OK : TM_BUS_ERROR;
}

int tm_tmp117_read(tm_tmp117_t *t, int16_t *centi_degc)
{
    uint8_t reg = 0x00u, v[2];
    int e = t->bus->write_read(t->bus->ctx, t->addr, &reg, 1, v, 2);
    if (e) {
        t->errors++;
        return e;
    }
    int32_t raw = (int16_t)(v[0] << 8 | v[1]);             /* big-endian, 7.8125 m degC per LSB */
    if (raw == -32768) return TM_BUS_ERROR;                 /* reset value before the first conversion */
    int32_t c = (raw * 78125 + (raw >= 0 ? 50000 : -50000)) / 100000;   /* 0.78125 centi-degC per LSB */
    *centi_degc = (int16_t)c;
    return TM_BUS_OK;
}
