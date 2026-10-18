#include "semmc/mc_drv835x.h"

#include <string.h>

static bool desc_usable(const mc_drv835x_desc_t *d)
{
    if (d == NULL || !d->verified || d->source == NULL || d->n_status == 0u || d->n_status > MC_DRV_MAX_STATUS ||
        d->addr_shift >= 16u || d->addr_mask == 0u || d->data_mask == 0u || d->read_flag == 0u) {
        return false;
    }
    const uint32_t addr_field = (uint32_t)d->addr_mask << d->addr_shift;
    if (addr_field > 0xFFFFu || (addr_field & d->data_mask) != 0u || (addr_field & d->read_flag) != 0u ||
        (d->read_flag & d->data_mask) != 0u || (d->clear_bit & d->data_mask) != d->clear_bit || d->clear_bit == 0u ||
        (d->clear_addr & ~d->addr_mask) != 0u) {
        return false;
    }
    for (uint8_t i = 0u; i < d->n_status; i++) {
        if ((d->status_addr[i] & ~d->addr_mask) != 0u) return false;
    }
    return true;
}

static bool settings_usable(const mc_drv835x_desc_t *d, const mc_drv835x_settings_t *s)
{
    if (s == NULL || s->n == 0u || s->n > MC_DRV_MAX_SETTINGS) return false;
    for (uint8_t i = 0u; i < s->n; i++) {
        if ((s->addr[i] & ~d->addr_mask) != 0u || (s->value[i] & ~d->data_mask) != 0u ||
            (s->verify_mask[i] & ~d->data_mask) != 0u) {
            return false;
        }
    }
    return true;
}

static void enter(mc_drv835x_t *m, mc_drv_state_t s, mc_time_us_t now_us)
{
    m->state = s;
    m->t_state_us = now_us;
}

static void fail(mc_drv835x_t *m, mc_drv_error_t e, mc_time_us_t now_us)
{
    m->error = e;
    m->status_ok = false;
    enter(m, MC_DRV_FAULT, now_us);
}

static uint16_t frame(const mc_drv835x_desc_t *d, bool read, uint8_t addr, uint16_t data)
{
    return (uint16_t)((read ? d->read_flag : 0u) | (uint16_t)((uint32_t)(addr & d->addr_mask) << d->addr_shift) |
                      (data & d->data_mask));
}

static bool xfer(mc_drv835x_t *m, uint16_t tx, uint16_t *rx)
{
    if (m->xfer(m->ctx, tx, rx) != 0) {
        m->spi_errors++;
        m->consecutive_errors++;
        return false;
    }
    m->consecutive_errors = 0u;
    return true;
}

static bool reg_write(mc_drv835x_t *m, uint8_t addr, uint16_t value)
{
    uint16_t rx = 0u;
    return xfer(m, frame(m->d, false, addr, value), &rx);
}

static bool reg_read(mc_drv835x_t *m, uint8_t addr, uint16_t *value)
{
    uint16_t rx = 0u;
    const uint16_t tx = frame(m->d, true, addr, 0u);
    if (!xfer(m, tx, &rx)) return false;
    if (!m->d->response_in_same_frame && !xfer(m, tx, &rx)) return false; /* data arrives in the next frame */
    *value = rx & m->d->data_mask;
    return true;
}

/* The configured value of a register, or 0 if it is not configured. */
static uint16_t configured(const mc_drv835x_t *m, uint8_t addr)
{
    for (uint8_t i = 0u; i < m->s.n; i++) {
        if (m->s.addr[i] == addr) return m->s.value[i];
    }
    return 0u;
}

/* Read setting i back; false on an SPI error (nothing concluded), *match set otherwise. */
static bool verify_setting(mc_drv835x_t *m, uint8_t i, bool *match)
{
    uint16_t v = 0u;
    if (!reg_read(m, m->s.addr[i], &v)) return false;
    *match = (v & m->s.verify_mask[i]) == (m->s.value[i] & m->s.verify_mask[i]);
    return true;
}

/* Read every status register; false on an SPI error, *faulted if a fault bit is set. */
static bool read_status(mc_drv835x_t *m, bool *faulted)
{
    bool f = false;
    for (uint8_t i = 0u; i < m->d->n_status; i++) {
        uint16_t v = 0u;
        if (!reg_read(m, m->d->status_addr[i], &v)) return false;
        m->status[i] = v;
        f = f || (v & m->d->status_fault_mask[i]) != 0u;
    }
    *faulted = f;
    return true;
}

static void spi_retry_or_fail(mc_drv835x_t *m, mc_time_us_t now_us)
{
    if (m->consecutive_errors >= MC_DRV_SPI_ERRORS_TO_FAULT) fail(m, MC_DRV_ERR_SPI, now_us);
}

void mc_drv835x_init(mc_drv835x_t *m, const mc_drv835x_desc_t *d, const mc_drv835x_settings_t *s,
                     mc_spi_xfer_fn xferf, void *ctx, mc_time_us_t now_us)
{
    memset(m, 0, sizeof *m);
    m->xfer = xferf;
    m->ctx = ctx;
    if (!desc_usable(d) || xferf == NULL || !settings_usable(d, s)) {
        m->error = MC_DRV_ERR_NO_DESCRIPTION;
        enter(m, MC_DRV_UNVERIFIED, now_us);
        return;
    }
    m->d = d;
    m->s = *s;
    enter(m, MC_DRV_SLEEP, now_us);
}

void mc_drv835x_request_clear(mc_drv835x_t *m)
{
    if (m->state == MC_DRV_FAULT) m->clear_requested = true;
}

static void step_configure(mc_drv835x_t *m, mc_time_us_t now_us)
{
    for (uint8_t i = 0u; i < m->s.n; i++) {
        if (!reg_write(m, m->s.addr[i], m->s.value[i])) {
            spi_retry_or_fail(m, now_us);
            return;
        }
    }
    for (uint8_t i = 0u; i < m->s.n; i++) {
        bool match = false;
        if (!verify_setting(m, i, &match)) {
            spi_retry_or_fail(m, now_us);
            return;
        }
        if (!match) {
            m->mismatch_index = i;
            fail(m, MC_DRV_ERR_READBACK, now_us);
            return;
        }
    }
    if (!reg_write(m, m->d->clear_addr, (uint16_t)(configured(m, m->d->clear_addr) | m->d->clear_bit))) {
        spi_retry_or_fail(m, now_us);
        return;
    }
    enter(m, MC_DRV_CLEARING, now_us);
}

void mc_drv835x_step(mc_drv835x_t *m, mc_time_us_t now_us, bool want_awake, bool nfault_low)
{
    if (m->state == MC_DRV_UNVERIFIED) {
        m->enable_pin = false;
        return;
    }
    if (m->state == MC_DRV_FAULT) {
        if (!want_awake) m->enable_pin = false;
        if (!m->clear_requested) return;
        m->clear_requested = false;
        m->consecutive_errors = 0u;
        m->error = MC_DRV_ERR_NONE;
        if (!want_awake) {
            enter(m, MC_DRV_SLEEP, now_us);
        } else if (m->enable_pin) {
            enter(m, MC_DRV_CONFIGURE, now_us); /* re-verify everything before the clear-fault command */
        } else {
            m->enable_pin = true;
            enter(m, MC_DRV_WAKING, now_us);
        }
        return;
    }
    if (!want_awake) {
        m->enable_pin = false;
        m->status_ok = false;
        enter(m, MC_DRV_SLEEP, now_us);
        return;
    }

    switch (m->state) {
    case MC_DRV_SLEEP:
        m->enable_pin = true;
        enter(m, MC_DRV_WAKING, now_us);
        return;
    case MC_DRV_WAKING:
        if (now_us - m->t_state_us >= m->d->t_wake_us) {
            m->consecutive_errors = 0u;
            enter(m, MC_DRV_CONFIGURE, now_us);
        }
        return;
    case MC_DRV_CONFIGURE:
        step_configure(m, now_us);
        return;
    case MC_DRV_CLEARING: {
        if (now_us - m->t_state_us < m->d->t_clear_us) return;
        bool faulted = false;
        if (!read_status(m, &faulted)) {
            spi_retry_or_fail(m, now_us);
            return;
        }
        if (faulted || nfault_low) {
            fail(m, MC_DRV_ERR_NOT_CLEARED, now_us);
            return;
        }
        m->status_ok = true;
        m->verify_next = 0u;
        enter(m, MC_DRV_READY, now_us);
        return;
    }
    case MC_DRV_READY: {
        bool faulted = false;
        m->status_ok = false;
        if (!read_status(m, &faulted)) {
            spi_retry_or_fail(m, now_us);
            return;
        }
        if (faulted) {
            fail(m, MC_DRV_ERR_FAULT_BITS, now_us);
            return;
        }
        if (nfault_low) {
            fail(m, MC_DRV_ERR_NFAULT, now_us);
            return;
        }
        bool match = false;
        const uint8_t i = m->verify_next;
        if (!verify_setting(m, i, &match)) {
            spi_retry_or_fail(m, now_us);
            return;
        }
        if (!match) {
            m->mismatch_index = i;
            fail(m, MC_DRV_ERR_READBACK, now_us);
            return;
        }
        m->verify_next = (uint8_t)((i + 1u) % m->s.n);
        m->status_ok = true;
        return;
    }
    case MC_DRV_UNVERIFIED:
    case MC_DRV_FAULT:
        return;
    }
}
