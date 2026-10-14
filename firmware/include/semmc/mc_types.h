/* Common types for the SEM motor-controller portable core.
 *
 * Portable C11. No dynamic allocation, no I/O. Floating point is single
 * precision (Cortex-M4F FPU); builds use -Wdouble-promotion to catch
 * accidental double arithmetic.
 *
 * Sign conventions (also in config/parameters.yaml):
 *   battery current  > 0 : discharge
 *   phase current    > 0 : into motor terminal
 *   torque           > 0 : forward motoring
 *   angles               : electrical radians, rotor d-axis from phase-a axis
 */
#ifndef SEMMC_MC_TYPES_H
#define SEMMC_MC_TYPES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MC_PI_F      3.14159265358979f
#define MC_TWO_PI_F  6.28318530717959f
#define MC_SQRT3_F   1.73205080756888f
#define MC_INV_SQRT3_F 0.577350269189626f

/* Local monotonic time, microseconds since controller boot. 64-bit so that it
 * never wraps in practice; the platform extends its 32-bit hardware counter
 * with mc_time_extend(). */
typedef uint64_t mc_time_us_t;

/* Per-signal validity flags. 0 == valid. */
typedef uint16_t mc_validity_t;
#define MC_VAL_OK            0x0000u
#define MC_VAL_MISSING       0x0001u /* never received in this session */
#define MC_VAL_STALE         0x0002u /* last NEW sample older than its window */
#define MC_VAL_INVALID       0x0004u /* source flagged invalid / plausibility fail */
#define MC_VAL_SATURATED     0x0008u /* measurement at/over its range limit */
#define MC_VAL_NONFINITE     0x0010u /* NaN / Inf */
#define MC_VAL_OUT_OF_RANGE  0x0020u /* outside physical plausibility bounds */
#define MC_VAL_SESSION_NEW   0x0040u /* source session changed; authority must be re-established */
#define MC_VAL_INTEGRITY     0x0080u /* application CRC / format failure */
#define MC_VAL_RECONSTRUCTED 0x0100u /* derived from other signals, not measured */

static inline bool mc_valid(mc_validity_t v) { return v == MC_VAL_OK; }

/* Usable for control: not missing/stale/invalid/nonfinite/out-of-range/integrity.
 * SATURATED and RECONSTRUCTED are informational for this predicate. */
static inline bool mc_usable(mc_validity_t v)
{
    return (v & (MC_VAL_MISSING | MC_VAL_STALE | MC_VAL_INVALID | MC_VAL_NONFINITE |
                 MC_VAL_OUT_OF_RANGE | MC_VAL_INTEGRITY)) == 0u;
}

typedef enum {
    MC_BUILD_HOST_SIM = 0,   /* host simulation: no physical output exists */
    MC_BUILD_HARDWARE = 1    /* target build: physical output gated by config */
} mc_build_kind_t;

static inline float mc_clampf(float x, float lo, float hi)
{
    return x < lo ? lo : (x > hi ? hi : x);
}

static inline float mc_absf(float x) { return x < 0.0f ? -x : x; }
static inline float mc_minf(float a, float b) { return a < b ? a : b; }
static inline float mc_maxf(float a, float b) { return a > b ? a : b; }

/* isfinite() without pulling double promotion warnings on some libcs. */
static inline bool mc_isfinite(float x)
{
    return (x == x) && (x - x == 0.0f);
}

#endif /* SEMMC_MC_TYPES_H */
