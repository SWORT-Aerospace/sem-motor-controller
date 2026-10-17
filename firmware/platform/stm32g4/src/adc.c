#include "adc.h"

#include "stm32g4xx.h"

volatile uint16_t adc_slow[ADC_SLOW_N];

#define SMP_24_5 3u
#define SMP_247_5 6u
#define JEXTSEL_TIM1_TRGO2 (ADC_JSQR_JEXTSEL_3) /* LL_ADC_INJ_TRIG_EXT_TIM1_TRGO2 */
#define DMAMUX_REQ_ADC3 37u                     /* DMA_REQUEST_ADC3 */
#define CKMODE_HCLK_DIV4 (ADC_CCR_CKMODE_1 | ADC_CCR_CKMODE_0)

static void delay_cycles(uint32_t n)
{
    const uint32_t t0 = DWT->CYCCNT;
    while ((DWT->CYCCNT - t0) < n) {
    }
}

static bool wait_flag(volatile uint32_t *reg, uint32_t mask, bool set)
{
    for (uint32_t i = 0; i < 1000000u; i++) {
        if (((*reg & mask) != 0u) == set) return true;
    }
    return false;
}

static void set_smp(ADC_TypeDef *a, uint32_t ch, uint32_t smp)
{
    if (ch < 10u) {
        a->SMPR1 = (a->SMPR1 & ~(7uL << (ch * 3u))) | (smp << (ch * 3u));
    } else {
        const uint32_t s = (ch - 10u) * 3u;
        a->SMPR2 = (a->SMPR2 & ~(7uL << s)) | (smp << s);
    }
}

static bool adc_power_up(ADC_TypeDef *a)
{
    a->CR &= ~ADC_CR_DEEPPWD;
    a->CR |= ADC_CR_ADVREGEN;
    delay_cycles(20u * 160u); /* 20 us at 160 MHz */
    a->CR &= ~ADC_CR_ADCALDIF;
    a->CR |= ADC_CR_ADCAL;
    if (!wait_flag(&a->CR, ADC_CR_ADCAL, false)) return false;
    delay_cycles(4u * 4u); /* 4 ADC cycles at HCLK / 4 */
    a->ISR = ADC_ISR_ADRDY;
    a->CR |= ADC_CR_ADEN;
    return wait_flag(&a->ISR, ADC_ISR_ADRDY, true);
}

static void inj_one(ADC_TypeDef *a, uint32_t ch)
{
    /* JL = 0: one conversion; rising edge of TIM1_TRGO2. CFGR.JQDIS is 1 out of reset (no queue),
     * so JSQR takes effect directly. */
    a->JSQR = (ch << ADC_JSQR_JSQ1_Pos) | JEXTSEL_TIM1_TRGO2 | ADC_JSQR_JEXTEN_0;
    set_smp(a, ch, SMP_24_5);
}

bool adc_init(uint32_t fast_irq_priority)
{
    RCC->AHB2ENR |= RCC_AHB2ENR_ADC12EN | RCC_AHB2ENR_ADC345EN;
    RCC->AHB1ENR |= RCC_AHB1ENR_DMA1EN | RCC_AHB1ENR_DMAMUX1EN;
    (void)RCC->AHB1ENR;
    ADC12_COMMON->CCR = CKMODE_HCLK_DIV4; /* DUAL = 0: independent */
    ADC345_COMMON->CCR = CKMODE_HCLK_DIV4;

    if (!adc_power_up(ADC1) || !adc_power_up(ADC2) || !adc_power_up(ADC3)) return false;

    inj_one(ADC1, 1u);
    inj_one(ADC2, 2u);
    inj_one(ADC3, 4u);

    /* ADC3 regular scan. */
    static const uint32_t seq[ADC_SLOW_N] = {2u, 14u, 15u, 16u, 3u};
    for (uint32_t i = 0; i < ADC_SLOW_N; i++) set_smp(ADC3, seq[i], SMP_247_5);
    ADC3->SQR1 = ((ADC_SLOW_N - 1u) << ADC_SQR1_L_Pos) | (seq[0] << ADC_SQR1_SQ1_Pos) |
                 (seq[1] << ADC_SQR1_SQ2_Pos) | (seq[2] << ADC_SQR1_SQ3_Pos) | (seq[3] << ADC_SQR1_SQ4_Pos);
    ADC3->SQR2 = seq[4] << ADC_SQR2_SQ5_Pos;
    ADC3->CFGR |= ADC_CFGR_CONT | ADC_CFGR_DMAEN | ADC_CFGR_DMACFG | ADC_CFGR_OVRMOD;

    DMA1_Channel1->CCR = 0u;
    DMAMUX1_Channel0->CCR = DMAMUX_REQ_ADC3;
    DMA1_Channel1->CPAR = (uint32_t)(uintptr_t)&ADC3->DR;
    DMA1_Channel1->CMAR = (uint32_t)(uintptr_t)adc_slow;
    DMA1_Channel1->CNDTR = ADC_SLOW_N;
    DMA1_Channel1->CCR = DMA_CCR_MINC | DMA_CCR_CIRC | DMA_CCR_PSIZE_0 | DMA_CCR_MSIZE_0 | DMA_CCR_EN;

    ADC1->ISR = ADC_ISR_JEOS | ADC_ISR_JEOC;
    ADC1->IER = ADC_IER_JEOSIE;
    NVIC_SetPriority(ADC1_2_IRQn, fast_irq_priority);
    NVIC_EnableIRQ(ADC1_2_IRQn);

    ADC1->CR |= ADC_CR_JADSTART;
    ADC2->CR |= ADC_CR_JADSTART;
    ADC3->CR |= ADC_CR_JADSTART;
    ADC3->CR |= ADC_CR_ADSTART;
    return true;
}

uint8_t adc_read_currents(uint16_t raw[3])
{
    uint8_t ok = 0u;
    raw[0] = (uint16_t)ADC1->JDR1;
    ok |= 1u;
    /* ADC2 and ADC3 started on the same edge with the same sampling time; allow 2 us (320 cycles). */
    const uint32_t t0 = DWT->CYCCNT;
    while ((ADC2->ISR & ADC_ISR_JEOS) == 0u || (ADC3->ISR & ADC_ISR_JEOS) == 0u) {
        if ((DWT->CYCCNT - t0) > 320u) break;
    }
    if (ADC2->ISR & ADC_ISR_JEOS) {
        raw[1] = (uint16_t)ADC2->JDR1;
        ADC2->ISR = ADC_ISR_JEOS | ADC_ISR_JEOC;
        ok |= 2u;
    }
    if (ADC3->ISR & ADC_ISR_JEOS) {
        raw[2] = (uint16_t)ADC3->JDR1;
        ADC3->ISR = ADC_ISR_JEOS | ADC_ISR_JEOC;
        ok |= 4u;
    }
    return ok;
}
