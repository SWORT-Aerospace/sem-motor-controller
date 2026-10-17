/* Startup for the STM32G474: vector table, reset handler, fault handlers.
 *
 * The device interrupt list (positions 0 .. 101, 85 reserved) is ST's IRQn_Type from the vendored
 * stm32g474xx.h; the table below was generated from it and is checked against it by
 * tests/integration/test_target_firmware.py. Handler names follow the CMSIS convention
 * <name>_IRQHandler; any handler the firmware does not define falls through to Default_Handler.
 *
 * Every fault handler first forces the power stage into its safe state (board_force_safe(), registers
 * only, no stack or RAM data trusted), records the fault in the reset-surviving event log and then
 * waits for the independent watchdog. It does not return. */
#include <stdint.h>

#include "board.h"
#include "event_log.h"
#include "stm32g4xx.h"

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
int main(void);
void Reset_Handler(void);
void Default_Handler(void);
void SystemInit(void);

static void __attribute__((noreturn)) fault_halt(uint16_t code)
{
    board_force_safe();
    event_log_record_fault(code);
    for (;;) {
        /* The IWDG (and the external MAX6369) are no longer kicked: the MCU resets. */
    }
}

void Default_Handler(void) { fault_halt(EVT_FAULT_UNEXPECTED_IRQ); }
void NMI_Handler(void) { fault_halt(EVT_FAULT_NMI); }
void HardFault_Handler(void) { fault_halt(EVT_FAULT_HARD); }
void MemManage_Handler(void) { fault_halt(EVT_FAULT_MEMMANAGE); }
void BusFault_Handler(void) { fault_halt(EVT_FAULT_BUS); }
void UsageFault_Handler(void) { fault_halt(EVT_FAULT_USAGE); }
void SVC_Handler(void) __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void) __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void) __attribute__((weak, alias("Default_Handler")));

void WWDG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void PVD_PVM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RTC_TAMP_LSECSS_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RTC_WKUP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FLASH_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RCC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC1_2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USB_HP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USB_LP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN1_IT0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN1_IT1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI9_5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_BRK_TIM15_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_UP_TIM16_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_TRG_COM_TIM17_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_CC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C1_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C1_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C2_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C2_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI15_10_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RTC_Alarm_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USBWakeUp_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_BRK_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_UP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_TRG_COM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_CC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FMC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPTIM1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UART4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UART5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM6_DAC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM7_DAC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UCPD1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void COMP1_2_3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void COMP4_5_6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void COMP7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_Master_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIMA_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIMB_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIMC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIMD_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIME_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_FLT_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HRTIM1_TIMF_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void CRS_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SAI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM20_BRK_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM20_UP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM20_TRG_COM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM20_CC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FPU_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C4_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C4_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN2_IT0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN2_IT1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN3_IT0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN3_IT1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RNG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPUART1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C3_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C3_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMAMUX_OVR_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void QUADSPI_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA1_Channel8_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2_Channel8_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void CORDIC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FMAC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));

typedef void (*vector_t)(void);

__attribute__((section(".isr_vector"), used)) const vector_t g_vectors[16 + 102] = {
    (vector_t)(uintptr_t)&_estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    0,
    0,
    0,
    0,
    SVC_Handler,
    DebugMon_Handler,
    0,
    PendSV_Handler,
    SysTick_Handler,
    WWDG_IRQHandler, /* 0 */
    PVD_PVM_IRQHandler, /* 1 */
    RTC_TAMP_LSECSS_IRQHandler, /* 2 */
    RTC_WKUP_IRQHandler, /* 3 */
    FLASH_IRQHandler, /* 4 */
    RCC_IRQHandler, /* 5 */
    EXTI0_IRQHandler, /* 6 */
    EXTI1_IRQHandler, /* 7 */
    EXTI2_IRQHandler, /* 8 */
    EXTI3_IRQHandler, /* 9 */
    EXTI4_IRQHandler, /* 10 */
    DMA1_Channel1_IRQHandler, /* 11 */
    DMA1_Channel2_IRQHandler, /* 12 */
    DMA1_Channel3_IRQHandler, /* 13 */
    DMA1_Channel4_IRQHandler, /* 14 */
    DMA1_Channel5_IRQHandler, /* 15 */
    DMA1_Channel6_IRQHandler, /* 16 */
    DMA1_Channel7_IRQHandler, /* 17 */
    ADC1_2_IRQHandler, /* 18 */
    USB_HP_IRQHandler, /* 19 */
    USB_LP_IRQHandler, /* 20 */
    FDCAN1_IT0_IRQHandler, /* 21 */
    FDCAN1_IT1_IRQHandler, /* 22 */
    EXTI9_5_IRQHandler, /* 23 */
    TIM1_BRK_TIM15_IRQHandler, /* 24 */
    TIM1_UP_TIM16_IRQHandler, /* 25 */
    TIM1_TRG_COM_TIM17_IRQHandler, /* 26 */
    TIM1_CC_IRQHandler, /* 27 */
    TIM2_IRQHandler, /* 28 */
    TIM3_IRQHandler, /* 29 */
    TIM4_IRQHandler, /* 30 */
    I2C1_EV_IRQHandler, /* 31 */
    I2C1_ER_IRQHandler, /* 32 */
    I2C2_EV_IRQHandler, /* 33 */
    I2C2_ER_IRQHandler, /* 34 */
    SPI1_IRQHandler, /* 35 */
    SPI2_IRQHandler, /* 36 */
    USART1_IRQHandler, /* 37 */
    USART2_IRQHandler, /* 38 */
    USART3_IRQHandler, /* 39 */
    EXTI15_10_IRQHandler, /* 40 */
    RTC_Alarm_IRQHandler, /* 41 */
    USBWakeUp_IRQHandler, /* 42 */
    TIM8_BRK_IRQHandler, /* 43 */
    TIM8_UP_IRQHandler, /* 44 */
    TIM8_TRG_COM_IRQHandler, /* 45 */
    TIM8_CC_IRQHandler, /* 46 */
    ADC3_IRQHandler, /* 47 */
    FMC_IRQHandler, /* 48 */
    LPTIM1_IRQHandler, /* 49 */
    TIM5_IRQHandler, /* 50 */
    SPI3_IRQHandler, /* 51 */
    UART4_IRQHandler, /* 52 */
    UART5_IRQHandler, /* 53 */
    TIM6_DAC_IRQHandler, /* 54 */
    TIM7_DAC_IRQHandler, /* 55 */
    DMA2_Channel1_IRQHandler, /* 56 */
    DMA2_Channel2_IRQHandler, /* 57 */
    DMA2_Channel3_IRQHandler, /* 58 */
    DMA2_Channel4_IRQHandler, /* 59 */
    DMA2_Channel5_IRQHandler, /* 60 */
    ADC4_IRQHandler, /* 61 */
    ADC5_IRQHandler, /* 62 */
    UCPD1_IRQHandler, /* 63 */
    COMP1_2_3_IRQHandler, /* 64 */
    COMP4_5_6_IRQHandler, /* 65 */
    COMP7_IRQHandler, /* 66 */
    HRTIM1_Master_IRQHandler, /* 67 */
    HRTIM1_TIMA_IRQHandler, /* 68 */
    HRTIM1_TIMB_IRQHandler, /* 69 */
    HRTIM1_TIMC_IRQHandler, /* 70 */
    HRTIM1_TIMD_IRQHandler, /* 71 */
    HRTIM1_TIME_IRQHandler, /* 72 */
    HRTIM1_FLT_IRQHandler, /* 73 */
    HRTIM1_TIMF_IRQHandler, /* 74 */
    CRS_IRQHandler, /* 75 */
    SAI1_IRQHandler, /* 76 */
    TIM20_BRK_IRQHandler, /* 77 */
    TIM20_UP_IRQHandler, /* 78 */
    TIM20_TRG_COM_IRQHandler, /* 79 */
    TIM20_CC_IRQHandler, /* 80 */
    FPU_IRQHandler, /* 81 */
    I2C4_EV_IRQHandler, /* 82 */
    I2C4_ER_IRQHandler, /* 83 */
    SPI4_IRQHandler, /* 84 */
    0, /* 85 reserved */
    FDCAN2_IT0_IRQHandler, /* 86 */
    FDCAN2_IT1_IRQHandler, /* 87 */
    FDCAN3_IT0_IRQHandler, /* 88 */
    FDCAN3_IT1_IRQHandler, /* 89 */
    RNG_IRQHandler, /* 90 */
    LPUART1_IRQHandler, /* 91 */
    I2C3_EV_IRQHandler, /* 92 */
    I2C3_ER_IRQHandler, /* 93 */
    DMAMUX_OVR_IRQHandler, /* 94 */
    QUADSPI_IRQHandler, /* 95 */
    DMA1_Channel8_IRQHandler, /* 96 */
    DMA2_Channel6_IRQHandler, /* 97 */
    DMA2_Channel7_IRQHandler, /* 98 */
    DMA2_Channel8_IRQHandler, /* 99 */
    CORDIC_IRQHandler, /* 100 */
    FMAC_IRQHandler, /* 101 */
};

void Reset_Handler(void)
{
    /* Until main() configures the pins they are in their reset state (analog, high impedance): the
     * board's pull-downs hold DRV_EN_GATED and PRECHG_EN low, so the gate driver is disabled and the
     * precharge bypass open whatever the gate-signal pins do. main() sets the pins first. */
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata;) *dst++ = *src++;
    for (uint32_t *dst = &_sbss; dst < &_ebss;) *dst++ = 0u;
    SystemInit();
    (void)main();
    fault_halt(EVT_FAULT_MAIN_RETURNED);
}
