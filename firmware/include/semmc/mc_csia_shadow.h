/* Controller-side CSIA interface: SHADOW MODE ONLY in v0.1.
 *
 * The controller receives csia_advisory frames from the companion computer,
 * tracks their freshness separately from their content, and re-reports them
 * for logging. It never changes a torque command because of them.
 *
 * mc_csia_may_restrict() is the single place a future evidence gate would
 * open. In v0.1 it is hard-wired false; enabling restriction requires the
 * evidence gate in docs/VALIDATION_PLAN.md section "CSIA evidence gate" and a
 * recorded architecture decision (ADR-0008).
 */
#ifndef SEMMC_MC_CSIA_SHADOW_H
#define SEMMC_MC_CSIA_SHADOW_H

#include "semmc/mc_freshness.h"
#include "semmc/mc_types.h"

typedef struct {
    mc_fresh_t fresh;
    float trust;              /* last received, NaN if none */
    uint8_t mode;             /* as declared by the sender */
    uint8_t observability;
    bool monitor_ok;
    bool evidence_fresh;
    uint8_t evidence_mask;
    uint8_t explanation;
    uint32_t rx_count;
    uint32_t restricting_mode_rejected; /* sender claimed mode 2: ignored and counted */
} mc_csia_shadow_t;

void mc_csia_init(mc_csia_shadow_t *s, uint32_t max_age_us);
void mc_csia_on_advisory(mc_csia_shadow_t *s, mc_time_us_t now_us, float trust, uint8_t mode, uint8_t observability,
                         bool monitor_ok, bool evidence_fresh, uint8_t evidence_mask, uint8_t explanation,
                         uint8_t seq, uint16_t src_ms);
mc_validity_t mc_csia_status(const mc_csia_shadow_t *s, mc_time_us_t now_us);
/* v0.1: always false. */
bool mc_csia_may_restrict(const mc_csia_shadow_t *s);

#endif
