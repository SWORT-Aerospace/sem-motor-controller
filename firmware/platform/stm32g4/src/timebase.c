#include "timebase.h"

#include "semmc/mc_freshness.h"
#include "stm32g4xx.h"
#include "system_clock.h"

static mc_time_us_t g_now64;

void timebase_init(void)
{
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM2EN | RCC_APB1ENR1_TIM6EN;
    (void)RCC->APB1ENR1;
    TIM2->CR1 = 0u;
    TIM2->PSC = TIMCLK_HZ / 1000000u - 1u;
    TIM2->ARR = 0xFFFFFFFFu;
    TIM2->EGR = TIM_EGR_UG;
    TIM2->CR1 = TIM_CR1_CEN;
    g_now64 = 0u;
}

void timebase_start_slow_tick(uint32_t priority)
{
    TIM6->CR1 = 0u;
    TIM6->PSC = TIMCLK_HZ / 1000000u - 1u;
    TIM6->ARR = 1000u - 1u;
    TIM6->EGR = TIM_EGR_UG;
    TIM6->SR = 0u;
    TIM6->DIER = TIM_DIER_UIE;
    NVIC_SetPriority(TIM6_DAC_IRQn, priority);
    NVIC_EnableIRQ(TIM6_DAC_IRQn);
    TIM6->CR1 = TIM_CR1_CEN;
}

uint32_t timebase_us32(void) { return TIM2->CNT; }

mc_time_us_t timebase_now_us(void)
{
    g_now64 = mc_time_extend(g_now64, TIM2->CNT);
    return g_now64;
}
