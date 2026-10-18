/* INA228 battery-side power monitor: driver logic, with every device constant held in a description.
 *
 * The driver implements the protocol: identification, reset, configuration, read-back verification,
 * conversion polling, scaling, sample age and validity, error counting and bounded re-initialisation.
 * It does NOT contain the device's register addresses, field positions, byte order, LSB sizes or timings:
 * those come from an mc_ina228_desc_t filled from the INA228 data sheet
 * (docs/reference/datasheets/README.md, priority 2) and marked verified with its source. Until then the
 * platform passes no description, the driver stays in MC_INA_UNVERIFIED, the battery voltage is missing
 * and the precharge never closes.
 *
 * Validity is tracked apart from bus success. A sample is valid only if it came from a completed
 * conversion (the description's conversion-ready flag), was read without a bus error or a diagnostic
 * error flag, and lies within the bus range of the description; the caller adds the maximum age. A bus
 * access that succeeds but reports no new conversion leaves the previous sample in place, ageing, so a
 * converter that stopped converting cannot pass as fresh.
 *
 * Bus calls are the platform's and must return within a bounded time (0 = success). */
#ifndef SEMMC_MC_INA228_H
#define SEMMC_MC_INA228_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_types.h"

typedef int (*mc_bus_read_fn)(void *ctx, uint8_t reg, uint8_t *data, uint8_t n);
typedef int (*mc_bus_write_fn)(void *ctx, uint8_t reg, const uint8_t *data, uint8_t n);

typedef struct {
    uint8_t addr;
    uint8_t bytes; /* 1..4 */
} mc_reg_t;

typedef struct {
    const char *source;     /* document, revision and tables the values below were read from */
    bool verified;          /* set only when every field has been checked against that document */
    bool msb_first;         /* register byte order on the bus */
    mc_reg_t config, adc_config, shunt_cal, vbus, vshunt, diag, manufacturer_id, device_id;
    uint32_t manufacturer_id_value, device_id_value, device_id_mask;
    uint32_t reset_mask;    /* bit in config that resets the device (not compared on read-back) */
    uint32_t cnvrf_mask;    /* conversion-ready flag in diag */
    uint32_t diag_error_mask; /* diag bits that make a sample invalid */
    uint8_t vbus_shift, vshunt_shift; /* the field is raw >> shift */
    bool vshunt_signed;     /* two's complement field of (8 bytes - shift) bits */
    float vbus_lsb_V, vshunt_lsb_V;
    float shunt_cal_k;      /* SHUNT_CAL = k x current_lsb x R_shunt (the data sheet's equation) */
    uint32_t shunt_cal_max;
    uint32_t t_reset_us;    /* wait after reset before the next access */
    float vbus_max_V;       /* bus input range */
} mc_ina228_desc_t;

typedef struct {
    uint32_t config_value, adc_config_value; /* chosen in the design review from the data sheet */
    float shunt_ohm, current_lsb_A;
} mc_ina228_settings_t;

typedef enum {
    MC_INA_UNVERIFIED = 0, /* no verified description: never touches the bus */
    MC_INA_RESET,
    MC_INA_WAIT_RESET,
    MC_INA_IDENTIFY,
    MC_INA_CONFIGURE,
    MC_INA_RUNNING,
    MC_INA_FAULT
} mc_ina_state_t;

typedef enum {
    MC_INA_ERR_NONE = 0,
    MC_INA_ERR_NO_DESCRIPTION,
    MC_INA_ERR_SETTINGS,  /* settings out of the description's limits: no retry */
    MC_INA_ERR_BUS,
    MC_INA_ERR_ID,
    MC_INA_ERR_READBACK
} mc_ina_error_t;

typedef struct {
    float value;
    bool valid;           /* from a completed, error-free, in-range conversion */
    mc_time_us_t t_us;    /* when it was read */
    uint32_t seq;         /* +1 per new sample */
} mc_sample_t;

#define MC_INA_BUS_ERRORS_TO_FAULT 3u
#define MC_INA_RETRY_US 1000000u

typedef struct {
    const mc_ina228_desc_t *d;
    mc_ina228_settings_t s;
    mc_bus_read_fn rd;
    mc_bus_write_fn wr;
    void *ctx;
    mc_ina_state_t state;
    mc_ina_error_t error;     /* the cause of the last fault */
    bool retries_exhausted;   /* re-initialisation attempts used up: FAULT until mc_ina228_init */
    mc_time_us_t t_state_us;
    uint32_t bus_errors, consecutive_errors, init_attempts, max_init_attempts;
    uint32_t shunt_cal_value;
    mc_sample_t vbus, vshunt;
} mc_ina228_t;

void mc_ina228_init(mc_ina228_t *m, const mc_ina228_desc_t *d, const mc_ina228_settings_t *s, mc_bus_read_fn rd,
                    mc_bus_write_fn wr, void *ctx, uint32_t max_init_attempts, mc_time_us_t now_us);
/* One bounded step (a few bus transactions at most), from one context only. */
void mc_ina228_step(mc_ina228_t *m, mc_time_us_t now_us);
/* The battery-side voltage if running, valid and younger than max_age_us; otherwise NAN and *ok = false. */
float mc_ina228_vbus_V(const mc_ina228_t *m, mc_time_us_t now_us, uint32_t max_age_us, bool *ok);
float mc_ina228_vshunt_V(const mc_ina228_t *m, mc_time_us_t now_us, uint32_t max_age_us, bool *ok);

#endif /* SEMMC_MC_INA228_H */
