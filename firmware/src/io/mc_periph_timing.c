#include "semmc/mc_periph_timing.h"

#include <math.h>

#include "semmc/mc_types.h"

bool mc_can_timing_compute(uint32_t f_kernel_Hz, uint32_t bitrate, float target_sample_point, mc_can_timing_t *out)
{
    if (bitrate == 0u || f_kernel_Hz == 0u || !(target_sample_point > 0.5f && target_sample_point < 1.0f)) {
        return false;
    }
    bool found = false;
    float best_err = 1.0f;
    for (uint32_t brp = 1u; brp <= 512u; brp++) {
        const uint64_t div = (uint64_t)brp * bitrate;
        if ((uint64_t)f_kernel_Hz % div != 0u) continue;
        const uint64_t n64 = (uint64_t)f_kernel_Hz / div;
        if (n64 < 8u || n64 > 385u) continue; /* 1 + 256 + 128 */
        const uint32_t n = (uint32_t)n64;
        uint32_t tseg2 = (uint32_t)lroundf((float)n * (1.0f - target_sample_point));
        if (tseg2 < 2u) tseg2 = 2u;
        if (tseg2 > 128u) tseg2 = 128u;
        const uint32_t tseg1 = n - 1u - tseg2;
        if (tseg1 < 2u || tseg1 > 256u) continue;
        const float sp = (float)(1u + tseg1) / (float)n;
        const float err = mc_absf(sp - target_sample_point);
        /* Prefer the closest sample point; on a tie keep the earlier (smaller prescaler, more tq). */
        if (!found || err < best_err - 1e-6f) {
            found = true;
            best_err = err;
            out->brp = (uint16_t)brp;
            out->tseg1 = (uint16_t)tseg1;
            out->tseg2 = (uint16_t)tseg2;
            out->sjw = (uint16_t)tseg2;
            out->tq_per_bit = (uint16_t)n;
            out->sample_point = sp;
        }
    }
    return found;
}

bool mc_tim_center_arr(uint32_t f_tim_Hz, float f_pwm_Hz, uint32_t *arr, float *f_actual_Hz)
{
    if (!mc_isfinite(f_pwm_Hz) || f_pwm_Hz <= 0.0f || f_tim_Hz == 0u) return false;
    const double a = (double)f_tim_Hz / (2.0 * (double)f_pwm_Hz);
    if (!(a >= 100.0 && a <= 65535.0)) return false;
    *arr = (uint32_t)lround(a);
    *f_actual_Hz = (float)((double)f_tim_Hz / (2.0 * (double)*arr));
    return true;
}

bool mc_tim_dtg_encode(float deadtime_s, uint32_t f_dts_Hz, uint8_t *dtg, float *actual_s)
{
    if (!mc_isfinite(deadtime_s) || deadtime_s < 0.0f || f_dts_Hz == 0u) return false;
    const double t = 1.0 / (double)f_dts_Hz;
    /* Round up. The allowance of 1e-4 tick (under 1 ps at 160 MHz) keeps a requested exact multiple, which
     * arrives as a float a few parts in 1e8 above it, from being pushed to the next step. */
    const double ticks_exact = (double)deadtime_s / t;
    const uint32_t ticks = (uint32_t)ceil(ticks_exact - 1e-4);
    uint32_t units;
    if (ticks <= 127u) {
        *dtg = (uint8_t)ticks;
        units = ticks;
    } else if (ticks <= 254u) {
        const uint32_t k = (ticks + 1u) / 2u - 64u;
        *dtg = (uint8_t)(0x80u | k);
        units = (64u + k) * 2u;
    } else if (ticks <= 504u) {
        const uint32_t k = (ticks + 7u) / 8u - 32u;
        *dtg = (uint8_t)(0xC0u | k);
        units = (32u + k) * 8u;
    } else if (ticks <= 1008u) {
        const uint32_t k = (ticks + 15u) / 16u - 32u;
        *dtg = (uint8_t)(0xE0u | k);
        units = (32u + k) * 16u;
    } else {
        return false;
    }
    *actual_s = (float)((double)units * t);
    return true;
}
