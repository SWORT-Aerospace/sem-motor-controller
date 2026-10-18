/* SystemInit for the STM32U575: FPU access and the vector table address. The clock stays at its reset
 * value (MSIS 4 MHz) until board_init(); SystemCoreClock is that frequency. */
#include "stm32u5xx.h"

uint32_t SystemCoreClock = 4000000u;   /* MSIS after reset (stm32u5xx HAL system file, RM0456) */

void SystemInit(void);
void SystemInit(void)
{
    SCB->CPACR |= (3uL << 20) | (3uL << 22);   /* CP10, CP11 full access: the FPU */
    SCB->VTOR = FLASH_BASE_NS;
    __DSB();
    __ISB();
}

void SystemCoreClockUpdate(void) {}
