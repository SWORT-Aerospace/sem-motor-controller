#include "pwm.h"

#include "board.h"
#include "semmc/mc_periph_timing.h"
#include "stm32g4xx.h"
#include "system_clock.h"

static volatile uint32_t g_break;
static bool g_running;
static uint32_t g_arr;

#define OCM_PWM1 (TIM_CCMR1_OC1M_2 | TIM_CCMR1_OC1M_1)
#define OCM_PWM2 (TIM_CCMR1_OC1M_2 | TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_0)
#define TRGO2_OC4REF (TIM_CR2_MMS2_2 | TIM_CR2_MMS2_1 | TIM_CR2_MMS2_0)
#define BKF_N4 (2uL << TIM_BDTR_BKF_Pos)
#define BK2F_N4 (2uL << TIM_BDTR_BK2F_Pos)

bool pwm_init(float f_pwm_Hz, float deadtime_s, uint32_t brk_priority, pwm_setup_t *out)
{
    g_running = false;
    uint32_t arr;
    float f;
    uint8_t dtg;
    float dt;
    if (!mc_tim_center_arr(TIMCLK_HZ, f_pwm_Hz, &arr, &f)) return false;
    if (!mc_tim_dtg_encode(deadtime_s, TIMCLK_HZ, &dtg, &dt)) return false; /* CKD = 0: t_DTS = t_CK_INT */

    RCC->APB2RSTR |= RCC_APB2RSTR_TIM1RST;
    RCC->APB2RSTR &= ~RCC_APB2RSTR_TIM1RST;
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;
    (void)RCC->APB2ENR;
    DBGMCU->APB2FZ |= DBGMCU_APB2FZ_DBG_TIM1_STOP; /* a debugger halt stops the counter; MOE is unaffected */

    TIM1->CR1 = TIM_CR1_CMS_0 | TIM_CR1_ARPE;
    TIM1->PSC = 0u;
    TIM1->ARR = arr;
    TIM1->RCR = 0u;
    TIM1->CCMR1 = OCM_PWM2 | TIM_CCMR1_OC1PE | ((OCM_PWM2 | TIM_CCMR1_OC1PE) << 8u);
    TIM1->CCMR2 = OCM_PWM2 | TIM_CCMR2_OC3PE | ((OCM_PWM1 | TIM_CCMR1_OC1PE) << 8u);
    TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = arr + 1u; /* high sides never on, until the first duty */
    TIM1->CCR4 = 1u;
    TIM1->CR2 = TRGO2_OC4REF; /* OISx = OISxN = 0 */
    TIM1->CCER = TIM_CCER_CC1E | TIM_CCER_CC1NE | TIM_CCER_CC2E | TIM_CCER_CC2NE | TIM_CCER_CC3E | TIM_CCER_CC3NE;
    TIM1->AF1 = TIM1_AF1_BKINE; /* BKIN pin, not inverted (BKINP = 0) */
    TIM1->AF2 = TIM1_AF2_BK2INE;
    /* One write (RM0440: the LOCK bits freeze at the first BDTR write, and with LOCK set the other
     * fields may freeze too). BKP = BK2P = 0: active low. OSSI = OSSR = 1. AOE = 0. MOE = 0. LOCK 1. */
    TIM1->BDTR = (uint32_t)dtg | TIM_BDTR_OSSI | TIM_BDTR_OSSR | TIM_BDTR_BKE | BKF_N4 | TIM_BDTR_BK2E | BK2F_N4 |
                 TIM_BDTR_LOCK_0;
    /* System break: a core lockup or a flash double-ECC error also clears MOE (SYSCFG_CFGR2 CLL, ECCL;
     * write-once until reset). */
    RCC->APB2ENR |= RCC_APB2ENR_SYSCFGEN;
    (void)RCC->APB2ENR;
    SYSCFG->CFGR2 |= SYSCFG_CFGR2_CLL | SYSCFG_CFGR2_ECCL;
    TIM1->EGR = TIM_EGR_UG;
    TIM1->SR = 0u;
    TIM1->DIER = TIM_DIER_BIE;
    NVIC_SetPriority(TIM1_BRK_TIM15_IRQn, brk_priority);
    NVIC_EnableIRQ(TIM1_BRK_TIM15_IRQn);
    TIM1->CR1 |= TIM_CR1_CEN;

    board_pwm_pins_to_timer(); /* outputs are at their inactive level (MOE = 0, OSSI = 1) */
    g_arr = arr;
    g_running = true;
    out->arr = arr;
    out->f_pwm_Hz = f;
    out->deadtime_s = dt;
    out->dtg = dtg;
    return true;
}

bool pwm_running(void) { return g_running; }

void pwm_write_duty(const mc_duty_t *d)
{
    const float a = (float)g_arr;
    TIM1->CCR1 = (uint32_t)((1.0f - d->a) * a + 0.5f);
    TIM1->CCR2 = (uint32_t)((1.0f - d->b) * a + 0.5f);
    TIM1->CCR3 = (uint32_t)((1.0f - d->c) * a + 0.5f);
}

void pwm_outputs_on(void)
{
    if (g_running && g_break == 0u) TIM1->BDTR |= TIM_BDTR_MOE;
}

void pwm_outputs_off(void) { TIM1->BDTR &= ~TIM_BDTR_MOE; }
bool pwm_outputs_are_on(void) { return (TIM1->BDTR & TIM_BDTR_MOE) != 0u; }
uint32_t pwm_break_flags(void) { return g_break; }
bool pwm_counting_down(void) { return (TIM1->CR1 & TIM_CR1_DIR) != 0u; }

uint32_t pwm_ticks_to_peak(void)
{
    const uint32_t cnt = TIM1->CNT; /* read before DIR: if the peak passes in between, DIR reports it */
    if ((TIM1->CR1 & TIM_CR1_DIR) != 0u || cnt >= g_arr) return 0u;
    return g_arr - cnt;
}

bool pwm_break_clear(void)
{
    if (board_break_inputs_active()) return false;
    TIM1->SR = ~(TIM_SR_BIF | TIM_SR_B2IF | TIM_SR_SBIF);
    g_break = 0u;
    return true;
}

void TIM1_BRK_TIM15_IRQHandler(void)
{
    const uint32_t sr = TIM1->SR;
    uint32_t f = 0u;
    if (sr & TIM_SR_BIF) f |= PWM_BREAK_DRIVER;
    if (sr & TIM_SR_B2IF) f |= PWM_BREAK_OVERVOLT;
    if (sr & TIM_SR_SBIF) f |= PWM_BREAK_SYSTEM;
    g_break |= f;
    TIM1->SR = ~(TIM_SR_BIF | TIM_SR_B2IF | TIM_SR_SBIF);
    TIM1->BDTR &= ~TIM_BDTR_MOE; /* already cleared by the hardware; keep it so */
    if (f == 0u) TIM1->DIER &= ~TIM_DIER_BIE; /* spurious: do not loop in this handler */
}
