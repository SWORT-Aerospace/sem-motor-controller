/* System initialisation and clock tree.
 *
 * SYSCLK = 160 MHz from the main PLL: source / M 4 x N 80 / R 2, with a 16 MHz source
 * (PLL input 4 MHz, VCO 320 MHz). AHB, APB1 and APB2 undivided, so every timer clock is 160 MHz.
 *
 * Source: the 16 MHz crystal (HSE) when the build defines SEMMC_HSE_HZ=16000000, otherwise the
 * internal 16 MHz RC (HSI16). The board's crystal is not selected yet (hardware/kicad sheet 08,
 * "HSE UNSELECTED"); the 16 MHz value is the PROPOSED choice in hardware/timing/clock_tree_alternatives.md
 * because it gives exact classic CAN bit rates with the FDCAN kernel on HSE. Without a crystal the
 * firmware keeps CAN off (can.c): the RC oscillator's tolerance is not shown to meet a CAN bus's.
 *
 * Sequence after ST's HAL (stm32g4xx-hal-driver@a6001282, HAL_RCC_OscConfig / HAL_RCC_ClockConfig /
 * HAL_PWREx_ControlVoltageScaling): range-1 boost mode (PWR_CR5.R1MODE = 0) before going above
 * 150 MHz; flash latency 4 wait states for 136 .. 170 MHz in boost mode; AHB prescaler /2 while
 * switching SYSCLK to a PLL above 80 MHz, then /1 after at least 1 us. Every wait is bounded; a
 * timeout leaves the MCU on HSI16 at 16 MHz and is reported to main(). */
#include "system_clock.h"

#include "stm32g4xx.h"

uint32_t SystemCoreClock = 16000000u;

#define PLL_M 4u
#define PLL_N 80u
#define PLL_R 2u
#define WAIT_LIMIT 1000000u

static bool wait_set(volatile uint32_t *reg, uint32_t mask)
{
    for (uint32_t i = 0; i < WAIT_LIMIT; i++) {
        if ((*reg & mask) == mask) return true;
    }
    return false;
}

static bool wait_clear(volatile uint32_t *reg, uint32_t mask)
{
    for (uint32_t i = 0; i < WAIT_LIMIT; i++) {
        if ((*reg & mask) == 0u) return true;
    }
    return false;
}

void SystemInit(void)
{
    /* FPU: full access for CP10 and CP11 (the core is built with -mfloat-abi=hard). */
    SCB->CPACR |= (3uL << (10u * 2u)) | (3uL << (11u * 2u));
    SCB->VTOR = FLASH_BASE; /* the linker script places .isr_vector at the start of flash */
    __DSB();
    __ISB();
}

clock_status_t system_clock_init(void)
{
    clock_status_t st = {false, false, 16000000u};

    RCC->APB1ENR1 |= RCC_APB1ENR1_PWREN;
    (void)RCC->APB1ENR1;
    /* Range 1 boost (R1MODE = 0); wait until the regulator reports the new range. */
    PWR->CR5 &= ~PWR_CR5_R1MODE;
    if (!wait_clear(&PWR->SR2, PWR_SR2_VOSF)) return st;

#if defined(SEMMC_HSE_HZ)
#if SEMMC_HSE_HZ != 16000000
#error "the PLL settings below assume a 16 MHz HSE"
#endif
    RCC->CR |= RCC_CR_HSEON;
    if (!wait_set(&RCC->CR, RCC_CR_HSERDY)) return st;
    const uint32_t src = RCC_PLLCFGR_PLLSRC_HSE;
    st.hse = true;
#else
    if (!wait_set(&RCC->CR, RCC_CR_HSIRDY)) return st;
    const uint32_t src = RCC_PLLCFGR_PLLSRC_HSI;
#endif

    RCC->CR &= ~RCC_CR_PLLON;
    if (!wait_clear(&RCC->CR, RCC_CR_PLLRDY)) return st;
    RCC->PLLCFGR = src | ((PLL_M - 1u) << RCC_PLLCFGR_PLLM_Pos) | (PLL_N << RCC_PLLCFGR_PLLN_Pos) |
                   (((PLL_R >> 1u) - 1u) << RCC_PLLCFGR_PLLR_Pos) | RCC_PLLCFGR_PLLREN;
    RCC->CR |= RCC_CR_PLLON;
    if (!wait_set(&RCC->CR, RCC_CR_PLLRDY)) return st;

    FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) | FLASH_ACR_LATENCY_4WS | FLASH_ACR_PRFTEN | FLASH_ACR_ICEN |
                 FLASH_ACR_DCEN;
    if ((FLASH->ACR & FLASH_ACR_LATENCY) != FLASH_ACR_LATENCY_4WS) return st;

    RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_HPRE | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2)) | RCC_CFGR_HPRE_DIV2;
    RCC->CFGR = (RCC->CFGR & ~RCC_CFGR_SW) | RCC_CFGR_SW_PLL;
    bool switched = false;
    for (uint32_t i = 0; i < WAIT_LIMIT; i++) {
        if ((RCC->CFGR & RCC_CFGR_SWS) == RCC_CFGR_SWS_PLL) {
            switched = true;
            break;
        }
    }
    if (!switched) return st;
    /* At least 1 us at HCLK = 80 MHz before removing the /2: 200 iterations of a counted loop is
     * well over 80 cycles. */
    for (volatile uint32_t i = 0; i < 200u; i++) {
    }
    RCC->CFGR &= ~RCC_CFGR_HPRE;

    SystemCoreClock = 160000000u;
    st.ok = true;
    st.sysclk_hz = SystemCoreClock;

    /* Cycle counter for the fast-step time base and execution-time measurement. */
    DCB->DEMCR |= DCB_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0u;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    return st;
}
