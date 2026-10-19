#include "board_u575.h"

#include "stm32u5xx.h"
#include "tm_time.h"

board_state_t g_board;
volatile uint32_t g_tim2_hi;

/* kept across a reset without power loss (linker section .noinit) */
static struct {
    uint32_t magic;
    uint32_t code;
} g_fault __attribute__((section(".noinit")));
#define FAULT_MAGIC 0x54414C54u

void board_record_fault(uint32_t code)
{
    g_fault.magic = FAULT_MAGIC;
    g_fault.code = code;
    /* the independent watchdog, no longer refreshed, resets the MCU */
}

/* alternate function, output type, pull and speed first, mode last (the order of ST's HAL_GPIO_Init, AFR before
 * MODER): the pin never runs another function, e.g. PD1 never drives FDCAN1_TX with AF0 on the way to AF9 */
static void gpio_mode(GPIO_TypeDef *g, uint32_t pin, uint32_t mode, uint32_t af, uint32_t pull, bool open_drain)
{
    volatile uint32_t *afr = &g->AFR[pin / 8u];
    *afr = (*afr & ~(0xFuL << (4u * (pin % 8u)))) | (af << (4u * (pin % 8u)));
    g->OTYPER = (g->OTYPER & ~(1uL << pin)) | ((open_drain ? 1uL : 0uL) << pin);
    g->PUPDR = (g->PUPDR & ~(3uL << (2u * pin))) | (pull << (2u * pin));
    g->OSPEEDR = (g->OSPEEDR & ~(3uL << (2u * pin))) | (1uL << (2u * pin));   /* medium */
    g->MODER = (g->MODER & ~(3uL << (2u * pin))) | (mode << (2u * pin));
}
#define MODE_IN 0u
#define MODE_OUT 1u
#define MODE_AF 2u
#define PULL_NONE 0u
#define PULL_UP 1u

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);
void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain)
{
    gpio_mode(g, pin, MODE_AF, af, pull_up ? PULL_UP : PULL_NONE, open_drain);
}

void board_gpio_out(GPIO_TypeDef *g, uint32_t pin, bool high);
void board_gpio_out(GPIO_TypeDef *g, uint32_t pin, bool high)
{
    g->BSRR = high ? (1uL << pin) : (1uL << (pin + 16u));
    gpio_mode(g, pin, MODE_OUT, 0u, PULL_NONE, false);
}

static bool wait_set(volatile uint32_t *reg, uint32_t mask, uint32_t loops)
{
    while (loops--)
        if (*reg & mask) return true;
    return false;
}

/* the same, refreshing the watchdog: if the option bytes start the IWDG in hardware (IWDG_SW = 0), its default
 * timeout is far shorter than the LSE start-up; a refresh of a watchdog that is not running has no effect */
static bool wait_set_kick(volatile uint32_t *reg, uint32_t mask, uint32_t loops)
{
    while (loops--) {
        if (*reg & mask) return true;
        IWDG->KR = 0xAAAAu;
    }
    return false;
}

static bool wait_clear_kick(volatile uint32_t *reg, uint32_t mask, uint32_t loops)
{
    while (loops--) {
        if (!(*reg & mask)) return true;
        IWDG->KR = 0xAAAAu;
    }
    return false;
}

static void watchdog_start(void)
{
    /* IWDG on the LSI (32 kHz nominal): prescaler /64, reload 1000: about 2 s */
    IWDG->KR = 0xCCCCu;
    IWDG->KR = 0x5555u;
    IWDG->PR = 4u;
    IWDG->RLR = 1000u;
    for (uint32_t i = 0; i < 100000u && IWDG->SR != 0u; i++) {
    }
    IWDG->KR = 0xAAAAu;
}

void board_kick_watchdog(void) { IWDG->KR = 0xAAAAu; }

void board_init(void)
{
    g_board.reset_flags = RCC->CSR;
    RCC->CSR |= RCC_CSR_RMVF;
    g_board.last_fault = (g_fault.magic == FAULT_MAGIC) ? g_fault.code : FAULT_NONE;
    g_fault.magic = 0u;
    /* option SRAM_RST = 0 erases SRAM1 on a system reset (ST: "All SRAMs (except SRAM2 and BKPSRAM) erased"), and
     * with it the fault record above; the banner says which applies */
    g_board.fault_record_kept = (FLASH->OPTR & FLASH_OPTR_SRAM_RST) != 0u;
    g_board.flash_swapped = (FLASH->OPTR & FLASH_OPTR_SWAP_BANK) != 0u;
    g_board.rev_id = (uint16_t)((DBGMCU->IDCODE & DBGMCU_IDCODE_REV_ID) >> DBGMCU_IDCODE_REV_ID_Pos);
    RCC->AHB2ENR1 |= RCC_AHB2ENR1_GPIOAEN | RCC_AHB2ENR1_GPIOBEN | RCC_AHB2ENR1_GPIOCEN | RCC_AHB2ENR1_GPIODEN;
    RCC->AHB3ENR |= RCC_AHB3ENR_PWREN;
    (void)RCC->AHB3ENR;
    board_gpio_out(GPIOC, 7u, false);   /* LD1 green */
    board_gpio_out(GPIOB, 7u, false);   /* LD2 blue */
    /* LSE (the X2 32.768 kHz crystal, fitted by default: UM2861 Rev 10 7.7.1) and MSIS locked to it.
     * The LSE can take seconds to start: wait a bounded time, then run untrimmed. */
    PWR->DBPR |= PWR_DBPR_DBP;
    (void)wait_set(&PWR->DBPR, PWR_DBPR_DBP, 10000u);   /* backup domain writable before LSEON (HAL rcc.c) */
    /* LSE drive: ES0499 Rev 12 2.2.3 and 2.2.16 forbid the low (00) and medium-low (01) drives on silicon
     * revision X, which NUCLEO-U575ZI-Q $AT1 and $AT2 carry (UM2861 Rev 10 Table 21). Medium-high is the lowest
     * drive left on every revision. The drive cannot be raised while LSEON = 1 (HAL rcc.h,
     * __HAL_RCC_LSEDRIVE_CONFIG) and the backup domain survives a reset, so an LSE left on at a lower drive or in
     * bypass (the board has the X2 crystal, UM2861 7.7.1) is switched off first, as HAL_RCC_OscConfig does. */
    if ((RCC->BDCR & RCC_BDCR_LSEDRV) < RCC_BDCR_LSEDRV_1 || (RCC->BDCR & RCC_BDCR_LSEBYP)) {
        RCC->BDCR &= ~(RCC_BDCR_LSEON | RCC_BDCR_LSESYSEN);
        RCC->BDCR &= ~RCC_BDCR_LSEBYP;
        (void)wait_clear_kick(&RCC->BDCR, RCC_BDCR_LSERDY, 3000000u);
        RCC->BDCR = (RCC->BDCR & ~RCC_BDCR_LSEDRV) | RCC_BDCR_LSEDRV_1;
    }
    /* LSCO is never used; a missed backup domain reset on revision X with VBAT and VDD from one source (ES0499
     * 2.2.9; SB50, UM2861 Table 9) can leave it driving PA2, wheel_1's input */
    RCC->BDCR &= ~RCC_BDCR_LSCOEN;
    RCC->BDCR |= RCC_BDCR_LSEON;
    g_board.lse_ok = wait_set_kick(&RCC->BDCR, RCC_BDCR_LSERDY, 3000000u);
    /* LSEON alone is ST's "LSE for RTC only"; LSESYSEN makes the LSE available to RCC and peripherals
     * (HAL RCC_LSE_ON), which MSI PLL mode needs (RM0456 RCC_BDCR to confirm) */
    if (g_board.lse_ok) {
        RCC->BDCR |= RCC_BDCR_LSESYSEN;
        g_board.lse_ok = wait_set_kick(&RCC->BDCR, RCC_BDCR_LSESYSRDY, 3000000u);
    }
    if (g_board.lse_ok) {
        RCC->CR |= RCC_CR_MSIPLLSEL;    /* PLL mode on MSIS: select the LSE while MSIPLLEN is 0 */
        RCC->CR |= RCC_CR_MSIPLLEN;
    }
    watchdog_start();
}

void board_led(int which, bool on)
{
    if (which == 0) GPIOC->BSRR = on ? (1uL << 7) : (1uL << 23);
    else GPIOB->BSRR = on ? (1uL << 7) : (1uL << 23);
}

uint64_t board_now_us(void)
{
    uint32_t pm = __get_PRIMASK();
    __disable_irq();
    uint32_t c = TIM2->CNT;
    bool ovf = (TIM2->SR & TIM_SR_UIF) != 0u;
    uint32_t hi = g_tim2_hi;
    __set_PRIMASK(pm);
    return tm_time_extend(hi, c, ovf);
}

/* wheel channel -> (GPIOA pin) */
static const uint8_t WHEEL_PIN[3] = {3u, 2u, 0u};

bool board_wheel_line_high(uint8_t ch) { return ch < 3u && (GPIOA->IDR & (1uL << WHEEL_PIN[ch])) != 0u; }

void board_mask_capture(bool masked)
{
    if (masked) NVIC_DisableIRQ(TIM2_IRQn);
    else NVIC_EnableIRQ(TIM2_IRQn);
}

void board_capture_start(void)
{
    for (unsigned i = 0; i < 3u; i++) board_gpio_af(GPIOA, WHEEL_PIN[i], 1u, true, false);   /* AF1 TIM2, pull-up */
    RCC->APB1ENR1 |= RCC_APB1ENR1_TIM2EN;
    (void)RCC->APB1ENR1;
    TIM2->CR1 = TIM_CR1_URS;    /* only a counter overflow sets UIF, not the UG below (ST: TIM_Base_SetConfig) */
    TIM2->PSC = SystemCoreClock / 1000000u - 1u;    /* 1 MHz: APB1 prescaler 1 after reset */
    TIM2->ARR = 0xFFFFFFFFu;
    /* CCxS = 01 (input from its own pin), ICxF = 0011 (8 samples at the timer clock: 2 us at 4 MHz) */
    TIM2->CCMR1 = (1uL << TIM_CCMR1_CC1S_Pos) | (3uL << TIM_CCMR1_IC1F_Pos);
    TIM2->CCMR2 = (1uL << TIM_CCMR2_CC3S_Pos) | (3uL << TIM_CCMR2_IC3F_Pos) | (1uL << TIM_CCMR2_CC4S_Pos) |
                  (3uL << TIM_CCMR2_IC4F_Pos);
    /* falling edge (CCxP = 1, CCxNP = 0): an open-collector Hall switch pulls low when a magnet arrives */
    TIM2->CCER = TIM_CCER_CC1E | TIM_CCER_CC1P | TIM_CCER_CC3E | TIM_CCER_CC3P | TIM_CCER_CC4E | TIM_CCER_CC4P;
    TIM2->EGR = TIM_EGR_UG;                         /* load the prescaler */
    __DSB();
    TIM2->SR = 0u;                                  /* a pending UIF here would put every time 2^32 us late */
    g_tim2_hi = 0u;
    TIM2->DIER = TIM_DIER_CC1IE | TIM_DIER_CC3IE | TIM_DIER_CC4IE | TIM_DIER_UIE;
    NVIC_SetPriority(TIM2_IRQn, 1u);
    NVIC_EnableIRQ(TIM2_IRQn);
    TIM2->CR1 = TIM_CR1_URS | TIM_CR1_CEN;
}

void board_unit_id(char *out, unsigned cap)
{
    static const char hex[] = "0123456789ABCDEF";
    const volatile uint32_t *uid = (const volatile uint32_t *)UID_BASE;
    const char *p = "U575-";
    unsigned n = 0;
    while (*p && n + 1u < cap) out[n++] = *p++;
    for (int w = 2; w >= 0; w--)
        for (int k = 28; k >= 0 && n + 1u < cap; k -= 4) out[n++] = hex[(uid[w] >> k) & 0xFu];
    out[n] = '\0';
}

bool board_pll1q_20mhz(void)
{
    /* FDCAN kernel clock 20 MHz from PLL1Q: MSIS 4 MHz / M 1 x N 40 = 160 MHz VCO, / Q 8. CAN needs an accurate
     * clock: only with the LSE-locked MSIS. Voltage range 3 first (range 4 after reset; the PLL limits per
     * range are to be checked in RM0456). */
    if (!g_board.lse_ok) return false;
    PWR->VOSR = (PWR->VOSR & ~PWR_VOSR_VOS) | (1uL << PWR_VOSR_VOS_Pos);
    if (!wait_set(&PWR->VOSR, PWR_VOSR_VOSRDY, 100000u)) return false;
    /* the range is applied when ACTVOSRDY is set and ACTVOS reads it (HAL_PWREx_ControlVoltageScaling) */
    if (!wait_set(&PWR->SVMSR, PWR_SVMSR_ACTVOSRDY, 100000u)) return false;
    if (((PWR->SVMSR & PWR_SVMSR_ACTVOS) >> PWR_SVMSR_ACTVOS_Pos) != 1u) return false;   /* 01: range 3 */
    RCC->PLL1CFGR = (1uL << RCC_PLL1CFGR_PLL1SRC_Pos) | (0uL << RCC_PLL1CFGR_PLL1RGE_Pos) |
                    (0uL << RCC_PLL1CFGR_PLL1M_Pos) | RCC_PLL1CFGR_PLL1QEN;
    RCC->PLL1DIVR = (39uL << RCC_PLL1DIVR_PLL1N_Pos) | (1uL << RCC_PLL1DIVR_PLL1P_Pos) |
                    (7uL << RCC_PLL1DIVR_PLL1Q_Pos) | (1uL << RCC_PLL1DIVR_PLL1R_Pos);
    RCC->CR |= RCC_CR_PLL1ON;
    if (!wait_set(&RCC->CR, RCC_CR_PLL1RDY, 100000u)) return false;
    RCC->CCIPR1 = (RCC->CCIPR1 & ~RCC_CCIPR1_FDCANSEL) | (1uL << RCC_CCIPR1_FDCANSEL_Pos);   /* 01: PLL1Q */
    return true;
}
