/* Hall-sensor sector decoding, speed estimation and angle interpolation.
 *
 * Normal events that must NOT be treated as faults: standstill (no edges),
 * very low speed (long edge periods), direction reversal. Faults are only
 * illegal codes (000/111 with a standard table) and repeated non-adjacent
 * sector jumps, each counted consecutively so a single glitch is tolerated.
 */
#include "semmc/mc_control.h"

#define MC_HALL_SECTOR_RAD (MC_PI_F / 3.0f)
#define MC_HALL_ILLEGAL_LIMIT 3u
#define MC_HALL_SKIP_LIMIT 3u

void mc_hall_init(mc_hall_t *h, const int8_t code_to_sector[8], float offset_rad, float timeout_s)
{
    for (int k = 0; k < 8; k++) h->code_to_sector[k] = code_to_sector[k];
    h->offset_rad = offset_rad;
    h->timeout_s = timeout_s;
    h->have_sector = false;
    h->sector = 0;
    h->direction = 0;
    h->t_since_edge = 0.0f;
    h->edge_period = 0.0f;
    h->omega_e = 0.0f;
    h->illegal_codes = 0;
    h->skipped_sectors = 0;
    h->invalid = false;
}

float mc_hall_update(mc_hall_t *h, uint8_t code, float dt)
{
    if (mc_isfinite(dt) && dt > 0.0f) h->t_since_edge += dt;
    const int8_t s = h->code_to_sector[code & 7u];
    if (s < 0) {
        if (h->illegal_codes < UINT16_MAX) h->illegal_codes++;
        if (h->illegal_codes >= MC_HALL_ILLEGAL_LIMIT) h->invalid = true;
    } else {
        h->illegal_codes = 0;
        if (!h->have_sector) {
            h->have_sector = true;
            h->sector = s;
            h->t_since_edge = 0.0f;
            h->edge_period = 0.0f;
        } else if (s != h->sector) {
            const int diff = ((s - h->sector) + 6) % 6; /* 1 = forward, 5 = reverse */
            if (diff == 1 || diff == 5) {
                const int8_t dir = (diff == 1) ? 1 : -1;
                /* A reversal invalidates the period estimate. */
                h->edge_period = (dir == h->direction) ? h->t_since_edge : 0.0f;
                h->direction = dir;
                h->skipped_sectors = 0;
            } else {
                if (h->skipped_sectors < UINT16_MAX) h->skipped_sectors++;
                if (h->skipped_sectors >= MC_HALL_SKIP_LIMIT) h->invalid = true;
                h->edge_period = 0.0f;
                h->direction = 0;
            }
            h->sector = s;
            h->t_since_edge = 0.0f;
        }
    }

    /* Speed: from the last full sector period, decaying toward zero if the
     * current sector is already longer than that period, zero after timeout. */
    if (h->edge_period > 0.0f && h->t_since_edge < h->timeout_s) {
        const float period = mc_maxf(h->edge_period, h->t_since_edge);
        h->omega_e = (float)h->direction * MC_HALL_SECTOR_RAD / period;
    } else {
        h->omega_e = 0.0f;
        if (h->t_since_edge >= h->timeout_s) {
            h->edge_period = 0.0f;
        }
    }

    if (!h->have_sector) return mc_wrap_2pi(h->offset_rad);
    const float start = h->offset_rad + (float)h->sector * MC_HALL_SECTOR_RAD;
    float frac;
    if (h->omega_e != 0.0f) {
        /* Interpolate from the sector boundary we entered through. */
        const float travelled = mc_absf(h->omega_e) * h->t_since_edge;
        const float within = mc_minf(travelled, MC_HALL_SECTOR_RAD);
        frac = (h->direction > 0) ? within : (MC_HALL_SECTOR_RAD - within);
    } else {
        frac = 0.5f * MC_HALL_SECTOR_RAD; /* standstill: sector centre (+-30 deg error) */
    }
    return mc_wrap_2pi(start + frac);
}
