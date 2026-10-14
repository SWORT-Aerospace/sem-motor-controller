#include "semmc/mc_csia_shadow.h"

#include <math.h>

void mc_csia_init(mc_csia_shadow_t *s, uint32_t max_age_us)
{
    mc_fresh_init(&s->fresh, max_age_us, 1u /* companion clock domain */, 250u);
    s->trust = NAN;
    s->mode = 0u;
    s->observability = 0u;
    s->monitor_ok = false;
    s->evidence_fresh = false;
    s->evidence_mask = 0u;
    s->explanation = 0u;
    s->rx_count = 0u;
    s->restricting_mode_rejected = 0u;
}

void mc_csia_on_advisory(mc_csia_shadow_t *s, mc_time_us_t now_us, float trust, uint8_t mode, uint8_t observability,
                         bool monitor_ok, bool evidence_fresh, uint8_t evidence_mask, uint8_t explanation,
                         uint8_t seq, uint16_t src_ms)
{
    /* The advisory has no session field of its own; the clock domain is the
     * companion's, so one session id is used for the tracker. */
    const mc_rx_result_t r = mc_fresh_on_rx(&s->fresh, now_us, 1u, 1u, seq, src_ms);
    s->rx_count++;
    if (!mc_rx_renews(r)) return; /* repeated / reordered content never updates */
    if (mode >= 2u) s->restricting_mode_rejected++;
    s->trust = trust;
    s->mode = mode;
    s->observability = observability;
    s->monitor_ok = monitor_ok;
    s->evidence_fresh = evidence_fresh;
    s->evidence_mask = evidence_mask;
    s->explanation = explanation;
}

mc_validity_t mc_csia_status(const mc_csia_shadow_t *s, mc_time_us_t now_us)
{
    return mc_fresh_status(&s->fresh, now_us);
}

bool mc_csia_may_restrict(const mc_csia_shadow_t *s)
{
    (void)s;
    return false; /* ADR-0008: shadow mode until the evidence gate is met */
}
