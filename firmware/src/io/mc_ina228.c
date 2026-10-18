#include "semmc/mc_ina228.h"

#include <math.h>
#include <string.h>

static bool reg_ok(const mc_reg_t *r) { return r->bytes >= 1u && r->bytes <= 4u; }

static bool desc_usable(const mc_ina228_desc_t *d)
{
    return d != NULL && d->verified && d->source != NULL && reg_ok(&d->config) && reg_ok(&d->adc_config) &&
           reg_ok(&d->shunt_cal) && reg_ok(&d->vbus) && reg_ok(&d->vshunt) && reg_ok(&d->diag) &&
           reg_ok(&d->manufacturer_id) && reg_ok(&d->device_id) && d->vbus_shift < 32u && d->vshunt_shift < 32u &&
           mc_isfinite(d->vbus_lsb_V) && d->vbus_lsb_V > 0.0f && mc_isfinite(d->vshunt_lsb_V) &&
           d->vshunt_lsb_V > 0.0f && mc_isfinite(d->shunt_cal_k) && d->shunt_cal_k > 0.0f &&
           mc_isfinite(d->vbus_max_V) && d->vbus_max_V > 0.0f && d->cnvrf_mask != 0u;
}

static void enter(mc_ina228_t *m, mc_ina_state_t s, mc_time_us_t now_us)
{
    m->state = s;
    m->t_state_us = now_us;
}

static void fail(mc_ina228_t *m, mc_ina_error_t e, mc_time_us_t now_us)
{
    m->error = e;
    m->vbus.valid = false;
    m->vshunt.valid = false;
    enter(m, MC_INA_FAULT, now_us);
}

static bool rd(mc_ina228_t *m, const mc_reg_t *r, uint32_t *v)
{
    uint8_t b[4] = {0u, 0u, 0u, 0u};
    if (m->rd(m->ctx, r->addr, b, r->bytes) != 0) {
        m->bus_errors++;
        m->consecutive_errors++;
        return false;
    }
    uint32_t x = 0u;
    for (uint8_t i = 0u; i < r->bytes; i++) {
        const uint8_t byte = m->d->msb_first ? b[i] : b[r->bytes - 1u - i];
        x = (x << 8u) | byte;
    }
    *v = x;
    m->consecutive_errors = 0u;
    return true;
}

static bool wr(mc_ina228_t *m, const mc_reg_t *r, uint32_t v)
{
    uint8_t b[4];
    for (uint8_t i = 0u; i < r->bytes; i++) {
        const uint8_t byte = (uint8_t)(v >> (8u * (uint32_t)(r->bytes - 1u - i)));
        if (m->d->msb_first) {
            b[i] = byte;
        } else {
            b[r->bytes - 1u - i] = byte;
        }
    }
    if (m->wr(m->ctx, r->addr, b, r->bytes) != 0) {
        m->bus_errors++;
        m->consecutive_errors++;
        return false;
    }
    m->consecutive_errors = 0u;
    return true;
}

static uint32_t width_mask(const mc_reg_t *r) { return r->bytes >= 4u ? 0xFFFFFFFFu : (1u << (8u * r->bytes)) - 1u; }

void mc_ina228_init(mc_ina228_t *m, const mc_ina228_desc_t *d, const mc_ina228_settings_t *s, mc_bus_read_fn rdf,
                    mc_bus_write_fn wrf, void *ctx, uint32_t max_init_attempts, mc_time_us_t now_us)
{
    memset(m, 0, sizeof *m);
    m->vbus.value = NAN;
    m->vshunt.value = NAN;
    m->rd = rdf;
    m->wr = wrf;
    m->ctx = ctx;
    m->max_init_attempts = max_init_attempts;
    if (!desc_usable(d) || rdf == NULL || wrf == NULL || s == NULL) {
        m->error = MC_INA_ERR_NO_DESCRIPTION;
        enter(m, MC_INA_UNVERIFIED, now_us);
        return;
    }
    m->d = d;
    m->s = *s;
    const float cal = d->shunt_cal_k * s->current_lsb_A * s->shunt_ohm;
    if (!mc_isfinite(cal) || !(s->shunt_ohm > 0.0f) || !(s->current_lsb_A > 0.0f) || cal < 1.0f ||
        cal > (float)d->shunt_cal_max) {
        m->error = MC_INA_ERR_SETTINGS;
        enter(m, MC_INA_FAULT, now_us);
        m->init_attempts = max_init_attempts; /* a wrong setting does not heal by retrying */
        return;
    }
    m->shunt_cal_value = (uint32_t)lroundf(cal);
    enter(m, MC_INA_RESET, now_us);
}

static float signed_field(uint32_t raw, uint32_t bits)
{
    const uint32_t mask = bits >= 32u ? 0xFFFFFFFFu : (1u << bits) - 1u;
    raw &= mask;
    if (bits < 32u && (raw & (1u << (bits - 1u))) != 0u) {
        return (float)((int32_t)(raw | ~mask));
    }
    return (float)raw;
}

static void read_sample(mc_ina228_t *m, mc_time_us_t now_us)
{
    const mc_ina228_desc_t *d = m->d;
    uint32_t diag = 0u, vb = 0u, vs = 0u;
    if (!rd(m, &d->diag, &diag)) return;
    if ((diag & d->cnvrf_mask) == 0u) return; /* no new conversion: the previous samples age */
    const bool ok_vb = rd(m, &d->vbus, &vb);
    const bool ok_vs = rd(m, &d->vshunt, &vs);
    const bool diag_ok = (diag & d->diag_error_mask) == 0u;
    if (ok_vb) {
        const float v = (float)(vb >> d->vbus_shift) * d->vbus_lsb_V;
        m->vbus.value = v;
        m->vbus.valid = diag_ok && mc_isfinite(v) && v >= 0.0f && v <= d->vbus_max_V;
        m->vbus.t_us = now_us;
        m->vbus.seq++;
    }
    if (ok_vs) {
        const uint32_t bits = 8u * d->vshunt.bytes - d->vshunt_shift;
        const float f = d->vshunt_signed ? signed_field(vs >> d->vshunt_shift, bits) : (float)(vs >> d->vshunt_shift);
        m->vshunt.value = f * d->vshunt_lsb_V;
        m->vshunt.valid = diag_ok && mc_isfinite(m->vshunt.value);
        m->vshunt.t_us = now_us;
        m->vshunt.seq++;
    }
}

void mc_ina228_step(mc_ina228_t *m, mc_time_us_t now_us)
{
    const mc_ina228_desc_t *d = m->d;
    switch (m->state) {
    case MC_INA_UNVERIFIED:
        return;
    case MC_INA_RESET:
        m->init_attempts++;
        if (wr(m, &d->config, d->reset_mask)) {
            enter(m, MC_INA_WAIT_RESET, now_us);
        } else if (m->consecutive_errors >= MC_INA_BUS_ERRORS_TO_FAULT) {
            fail(m, MC_INA_ERR_BUS, now_us);
        }
        return;
    case MC_INA_WAIT_RESET:
        if (now_us - m->t_state_us >= d->t_reset_us) enter(m, MC_INA_IDENTIFY, now_us);
        return;
    case MC_INA_IDENTIFY: {
        uint32_t man = 0u, dev = 0u;
        if (!rd(m, &d->manufacturer_id, &man) || !rd(m, &d->device_id, &dev)) {
            fail(m, MC_INA_ERR_BUS, now_us);
        } else if (man != d->manufacturer_id_value || (dev & d->device_id_mask) != d->device_id_value) {
            fail(m, MC_INA_ERR_ID, now_us);
        } else {
            enter(m, MC_INA_CONFIGURE, now_us);
        }
        return;
    }
    case MC_INA_CONFIGURE: {
        uint32_t c = 0u, a = 0u, k = 0u;
        const uint32_t want_c = m->s.config_value & ~d->reset_mask & width_mask(&d->config);
        const uint32_t want_a = m->s.adc_config_value & width_mask(&d->adc_config);
        if (!wr(m, &d->config, want_c) || !wr(m, &d->adc_config, want_a) || !wr(m, &d->shunt_cal, m->shunt_cal_value) ||
            !rd(m, &d->config, &c) || !rd(m, &d->adc_config, &a) || !rd(m, &d->shunt_cal, &k)) {
            fail(m, MC_INA_ERR_BUS, now_us);
        } else if ((c & ~d->reset_mask) != want_c || a != want_a || k != m->shunt_cal_value) {
            fail(m, MC_INA_ERR_READBACK, now_us);
        } else {
            m->error = MC_INA_ERR_NONE;
            enter(m, MC_INA_RUNNING, now_us);
        }
        return;
    }
    case MC_INA_RUNNING:
        read_sample(m, now_us);
        if (m->consecutive_errors >= MC_INA_BUS_ERRORS_TO_FAULT) fail(m, MC_INA_ERR_BUS, now_us);
        return;
    case MC_INA_FAULT:
        if (m->error == MC_INA_ERR_SETTINGS) return;
        if (m->init_attempts >= m->max_init_attempts) {
            m->retries_exhausted = true;
            return;
        }
        if (now_us - m->t_state_us >= MC_INA_RETRY_US) {
            m->consecutive_errors = 0u;
            enter(m, MC_INA_RESET, now_us);
        }
        return;
    }
}

static float fresh(const mc_ina228_t *m, const mc_sample_t *s, mc_time_us_t now_us, uint32_t max_age_us, bool *ok)
{
    *ok = m->state == MC_INA_RUNNING && s->valid && s->seq > 0u && now_us >= s->t_us &&
          now_us - s->t_us <= (mc_time_us_t)max_age_us;
    return *ok ? s->value : NAN;
}

float mc_ina228_vbus_V(const mc_ina228_t *m, mc_time_us_t now_us, uint32_t max_age_us, bool *ok)
{
    return fresh(m, &m->vbus, now_us, max_age_us, ok);
}

float mc_ina228_vshunt_V(const mc_ina228_t *m, mc_time_us_t now_us, uint32_t max_age_us, bool *ok)
{
    return fresh(m, &m->vshunt, now_us, max_age_us, ok);
}
