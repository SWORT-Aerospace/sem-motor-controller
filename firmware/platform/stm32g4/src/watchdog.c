#include "watchdog.h"

#include "board.h"
#include "stm32g4xx.h"

/* Key values written to IWDG_KR (RM0440): 0xCCCC start, 0x5555 unlock PR/RLR, 0xAAAA reload. */
#define IWDG_KEY_START 0xCCCCu
#define IWDG_KEY_UNLOCK 0x5555u
#define IWDG_KEY_RELOAD 0xAAAAu

void watchdog_start(void)
{
    DBGMCU->APB1FZR1 |= DBGMCU_APB1FZR1_DBG_IWDG_STOP; /* stops only while a debugger halts the core */
    IWDG->KR = IWDG_KEY_START;
    IWDG->KR = IWDG_KEY_UNLOCK;
    IWDG->PR = 3u;     /* /32 */
    IWDG->RLR = 100u;
    for (uint32_t i = 0; i < 1000000u && IWDG->SR != 0u; i++) {
    }
    IWDG->KR = IWDG_KEY_RELOAD;
}

void watchdog_kick(void)
{
    IWDG->KR = IWDG_KEY_RELOAD;
    board_toggle_ext_wdg();
}

uint8_t watchdog_reset_cause(void)
{
    const uint8_t c = (uint8_t)(RCC->CSR >> 24u);
    RCC->CSR |= RCC_CSR_RMVF;
    return c;
}
