/* Register-level timing values computed from clock frequencies (portable; host-tested).
 *
 * CAN nominal bit timing for the STM32G4 FDCAN (fields of FDCAN_NBTP, RM0440): prescaler 1..512,
 * TSEG1 2..256 tq, TSEG2 2..128 tq, SJW = TSEG2. Only exact bit rates are accepted; the sample point
 * is the one closest to the target (CiA 301 recommends 87.5 % up to 800 kbit/s).
 *
 * TIM1 centre-aligned PWM: f_pwm = f_tim / (2 ARR).
 * TIM1 dead-time generator (TIMx_BDTR.DTG, RM0440), t_DTS = 1 / f_dts:
 *   DTG[7:5] = 0xx  DT = DTG[6:0] x t_DTS             (0 .. 127 t_DTS)
 *   DTG[7:5] = 10x  DT = (64 + DTG[5:0]) x 2 t_DTS    (128 .. 254)
 *   DTG[7:5] = 110  DT = (32 + DTG[4:0]) x 8 t_DTS    (256 .. 504)
 *   DTG[7:5] = 111  DT = (32 + DTG[4:0]) x 16 t_DTS   (512 .. 1008)
 * The encoder returns the smallest dead time that is not shorter than the one requested. */
#ifndef SEMMC_MC_PERIPH_TIMING_H
#define SEMMC_MC_PERIPH_TIMING_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint16_t brp;       /* prescaler (register value + 1) */
    uint16_t tseg1;     /* tq, propagation + phase 1 */
    uint16_t tseg2;     /* tq */
    uint16_t sjw;       /* tq */
    uint16_t tq_per_bit;
    float sample_point; /* (1 + tseg1) / tq_per_bit */
} mc_can_timing_t;

bool mc_can_timing_compute(uint32_t f_kernel_Hz, uint32_t bitrate, float target_sample_point, mc_can_timing_t *out);

/* ARR for centre-aligned PWM. Fails if the result does not fit 16 bits or gives fewer than
 * 100 counts per half period (duty resolution below 1 %). */
bool mc_tim_center_arr(uint32_t f_tim_Hz, float f_pwm_Hz, uint32_t *arr, float *f_actual_Hz);

bool mc_tim_dtg_encode(float deadtime_s, uint32_t f_dts_Hz, uint8_t *dtg, float *actual_s);

#endif /* SEMMC_MC_PERIPH_TIMING_H */
