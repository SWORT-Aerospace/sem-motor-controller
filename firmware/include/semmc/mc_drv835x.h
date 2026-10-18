/* DRV8353S gate driver: SPI configuration and fault supervision, with every device constant held in a
 * description.
 *
 * The driver implements the sequence: wake with the gates held off (ENABLE high, the PWM outputs remain
 * disabled by TIM1 MOE = 0), wait the wake-up time, write each configuration register, read every one
 * back and compare it under its mask, clear the latched faults, and confirm that nFAULT is released and
 * the status registers are clear. Only then is it READY. While READY it reads the status registers every
 * step and re-reads one configuration register, so a device that lost its configuration (a supply dip
 * that reset it) is found within n steps. A set fault bit, nFAULT asserted, a read-back mismatch or
 * repeated SPI failures make it FAULT, which is reported to the core as a gate-driver fault. A fault is
 * cleared only on request (the driver's fault-reset input), and the clear re-runs the whole
 * configuration and read-back before the clear-fault command, so it cannot hide a device that reset.
 * The clear-fault bit is written together with the configured value of its register, not over it.
 *
 * In FAULT the ENABLE command is left as it was, so the status registers stay readable; the gates are
 * held off by the core (gate_driver_ready = false keeps TIM1 MOE = 0). Whether ENABLE should instead
 * drop on a fault is a design-review item against the data sheet's sleep-mode gate behaviour.
 *
 * It does NOT contain the device's SPI frame format, register addresses, bit positions or timings, nor
 * the gate-drive, VDS-monitor and amplifier settings: the frame and addresses come from an
 * mc_drv835x_desc_t filled from the DRV835x data sheet (SLVSDY6, docs/reference/datasheets/README.md,
 * priority 1), and the register values from the design review (they depend on the MOSFETs and the motor).
 * Until both exist the platform passes none, the driver stays in MC_DRV_UNVERIFIED with ENABLE low, and the
 * power stage cannot be driven.
 *
 * The SPI call is the platform's: one full-duplex frame, bounded in time, 0 = success. */
#ifndef SEMMC_MC_DRV835X_H
#define SEMMC_MC_DRV835X_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_types.h"

typedef int (*mc_spi_xfer_fn)(void *ctx, uint16_t tx, uint16_t *rx);

#define MC_DRV_MAX_STATUS 2u
#define MC_DRV_MAX_SETTINGS 8u

typedef struct {
    const char *source;      /* document, revision and tables the values below were read from */
    bool verified;           /* set only when every field has been checked against that document */
    uint16_t read_flag;      /* bit that marks a read command */
    uint8_t addr_shift;      /* address field position */
    uint16_t addr_mask;      /* address field width, applied before shifting */
    uint16_t data_mask;      /* data field */
    bool response_in_same_frame; /* read data returned in the same frame (else in the next one) */
    uint8_t n_status;
    uint8_t status_addr[MC_DRV_MAX_STATUS];
    uint16_t status_fault_mask[MC_DRV_MAX_STATUS]; /* bits that are faults */
    uint8_t clear_addr;      /* register holding the clear-fault bit */
    uint16_t clear_bit;      /* self-clearing on the device */
    uint32_t t_wake_us;      /* ENABLE high to the first SPI access */
    uint32_t t_clear_us;     /* clear request to a valid status read */
} mc_drv835x_desc_t;

typedef struct {
    uint8_t n;
    uint8_t addr[MC_DRV_MAX_SETTINGS];
    uint16_t value[MC_DRV_MAX_SETTINGS];
    uint16_t verify_mask[MC_DRV_MAX_SETTINGS]; /* bits compared on read-back (reserved bits excluded) */
} mc_drv835x_settings_t;

typedef enum {
    MC_DRV_UNVERIFIED = 0, /* no verified description or settings: ENABLE stays low */
    MC_DRV_SLEEP,          /* ENABLE low (not requested) */
    MC_DRV_WAKING,
    MC_DRV_CONFIGURE,
    MC_DRV_CLEARING,
    MC_DRV_READY,
    MC_DRV_FAULT
} mc_drv_state_t;

typedef enum {
    MC_DRV_ERR_NONE = 0,
    MC_DRV_ERR_NO_DESCRIPTION,
    MC_DRV_ERR_SPI,
    MC_DRV_ERR_READBACK,
    MC_DRV_ERR_FAULT_BITS,
    MC_DRV_ERR_NFAULT,
    MC_DRV_ERR_NOT_CLEARED
} mc_drv_error_t;

#define MC_DRV_SPI_ERRORS_TO_FAULT 3u

typedef struct {
    const mc_drv835x_desc_t *d;
    mc_drv835x_settings_t s;
    mc_spi_xfer_fn xfer;
    void *ctx;
    mc_drv_state_t state;
    mc_drv_error_t error;
    mc_time_us_t t_state_us;
    bool enable_pin;         /* command for the ENABLE pin */
    bool clear_requested;
    bool status_ok;          /* the status registers were read without error in the last step */
    uint8_t mismatch_index;  /* setting that failed read-back */
    uint8_t verify_next;     /* setting re-read while READY (one per step, round robin) */
    uint16_t status[MC_DRV_MAX_STATUS]; /* last status words read */
    uint32_t spi_errors, consecutive_errors;
} mc_drv835x_t;

void mc_drv835x_init(mc_drv835x_t *m, const mc_drv835x_desc_t *d, const mc_drv835x_settings_t *s,
                     mc_spi_xfer_fn xfer, void *ctx, mc_time_us_t now_us);
/* One bounded step. want_awake: the start-up sequence wants the driver configured; nfault_low: the
 * driver's nFAULT pin as read now. */
void mc_drv835x_step(mc_drv835x_t *m, mc_time_us_t now_us, bool want_awake, bool nfault_low);
/* Request a fault clear (driver fault-reset input, with the outputs off). */
void mc_drv835x_request_clear(mc_drv835x_t *m);
/* READY, and the status registers read clean in the last step. */
static inline bool mc_drv835x_ready(const mc_drv835x_t *m) { return m->state == MC_DRV_READY && m->status_ok; }

#endif /* SEMMC_MC_DRV835X_H */
