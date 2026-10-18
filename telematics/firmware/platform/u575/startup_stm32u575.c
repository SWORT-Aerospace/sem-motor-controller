/* Startup for the STM32U575 (NUCLEO-U575ZI-Q): vector table, reset handler, fault handlers.
 *
 * The device interrupt list (positions 0 .. 125) is ST's IRQn_Type from the vendored stm32u575xx.h
 * (STMicroelectronics/cmsis-device-u5 v1.4.3); the table below was generated from it and
 * tests/telematics/test_firmware_target.py checks the linked image against it. A handler the firmware does
 * not define falls through to Default_Handler. Fault handlers record the fault code in a RAM word that survives
 * a reset without power loss and wait for the watchdog; nothing on this board drives anything outside it.
 * TrustZone is assumed disabled (the factory default, option byte TZEN = 0): everything runs non-secure. */
#include <stdint.h>

#include "board_u575.h"

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
int main(void);
void Reset_Handler(void);
void Default_Handler(void);
void SystemInit(void);

static void __attribute__((noreturn)) fault_halt(uint32_t code)
{
    board_record_fault(code);
    for (;;) {
    }
}

void Default_Handler(void) { fault_halt(FAULT_UNEXPECTED_IRQ); }
void HardFault_Handler(void) { fault_halt(FAULT_HARD); }
void MemManage_Handler(void) { fault_halt(FAULT_MEMMANAGE); }
void BusFault_Handler(void) { fault_halt(FAULT_BUS); }
void UsageFault_Handler(void) { fault_halt(FAULT_USAGE); }
void SecureFault_Handler(void) { fault_halt(FAULT_SECURE); }
void NMI_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void) __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void) __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void) __attribute__((weak, alias("Default_Handler")));

void WWDG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void PVD_PVM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RTC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RTC_S_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TAMP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RAMCFG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FLASH_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FLASH_S_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GTZC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RCC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RCC_S_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI8_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI9_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI10_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI11_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI12_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI13_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI14_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void EXTI15_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void IWDG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DAC1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN1_IT0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FDCAN1_IT1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_BRK_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_UP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_TRG_COM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM1_CC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM6_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM7_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_BRK_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_UP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_TRG_COM_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM8_CC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C1_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C1_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C2_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C2_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UART4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UART5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPUART1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPTIM1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPTIM2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM15_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM16_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TIM17_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void COMP_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void OTG_FS_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void CRS_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FMC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void OCTOSPI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void PWR_S3WU_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SDMMC1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SDMMC2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel8_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel9_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel10_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel11_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel12_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel13_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel14_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void GPDMA1_Channel15_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C3_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C3_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SAI1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SAI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void TSC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void RNG_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FPU_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HASH_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPTIM3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void SPI3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C4_ER_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void I2C4_EV_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void UCPD1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ICACHE_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPTIM4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DCACHE1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADF1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void ADC4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPDMA1_Channel0_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPDMA1_Channel1_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPDMA1_Channel2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LPDMA1_Channel3_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DMA2D_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void DCMI_PSSI_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void OCTOSPI2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT4_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void MDF1_FLT5_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void CORDIC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void FMAC_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void LSECSSD_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));

typedef void (*vector_t)(void);
__attribute__((section(".isr_vector"), used)) const vector_t g_vectors[16 + 126] = {
    (vector_t)&_estack,
    Reset_Handler,
    NMI_Handler,
    HardFault_Handler,
    MemManage_Handler,
    BusFault_Handler,
    UsageFault_Handler,
    SecureFault_Handler,
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
    RTC_IRQHandler, /* 2 */
    RTC_S_IRQHandler, /* 3 */
    TAMP_IRQHandler, /* 4 */
    RAMCFG_IRQHandler, /* 5 */
    FLASH_IRQHandler, /* 6 */
    FLASH_S_IRQHandler, /* 7 */
    GTZC_IRQHandler, /* 8 */
    RCC_IRQHandler, /* 9 */
    RCC_S_IRQHandler, /* 10 */
    EXTI0_IRQHandler, /* 11 */
    EXTI1_IRQHandler, /* 12 */
    EXTI2_IRQHandler, /* 13 */
    EXTI3_IRQHandler, /* 14 */
    EXTI4_IRQHandler, /* 15 */
    EXTI5_IRQHandler, /* 16 */
    EXTI6_IRQHandler, /* 17 */
    EXTI7_IRQHandler, /* 18 */
    EXTI8_IRQHandler, /* 19 */
    EXTI9_IRQHandler, /* 20 */
    EXTI10_IRQHandler, /* 21 */
    EXTI11_IRQHandler, /* 22 */
    EXTI12_IRQHandler, /* 23 */
    EXTI13_IRQHandler, /* 24 */
    EXTI14_IRQHandler, /* 25 */
    EXTI15_IRQHandler, /* 26 */
    IWDG_IRQHandler, /* 27 */
    0, /* 28 reserved */
    GPDMA1_Channel0_IRQHandler, /* 29 */
    GPDMA1_Channel1_IRQHandler, /* 30 */
    GPDMA1_Channel2_IRQHandler, /* 31 */
    GPDMA1_Channel3_IRQHandler, /* 32 */
    GPDMA1_Channel4_IRQHandler, /* 33 */
    GPDMA1_Channel5_IRQHandler, /* 34 */
    GPDMA1_Channel6_IRQHandler, /* 35 */
    GPDMA1_Channel7_IRQHandler, /* 36 */
    ADC1_IRQHandler, /* 37 */
    DAC1_IRQHandler, /* 38 */
    FDCAN1_IT0_IRQHandler, /* 39 */
    FDCAN1_IT1_IRQHandler, /* 40 */
    TIM1_BRK_IRQHandler, /* 41 */
    TIM1_UP_IRQHandler, /* 42 */
    TIM1_TRG_COM_IRQHandler, /* 43 */
    TIM1_CC_IRQHandler, /* 44 */
    TIM2_IRQHandler, /* 45 */
    TIM3_IRQHandler, /* 46 */
    TIM4_IRQHandler, /* 47 */
    TIM5_IRQHandler, /* 48 */
    TIM6_IRQHandler, /* 49 */
    TIM7_IRQHandler, /* 50 */
    TIM8_BRK_IRQHandler, /* 51 */
    TIM8_UP_IRQHandler, /* 52 */
    TIM8_TRG_COM_IRQHandler, /* 53 */
    TIM8_CC_IRQHandler, /* 54 */
    I2C1_EV_IRQHandler, /* 55 */
    I2C1_ER_IRQHandler, /* 56 */
    I2C2_EV_IRQHandler, /* 57 */
    I2C2_ER_IRQHandler, /* 58 */
    SPI1_IRQHandler, /* 59 */
    SPI2_IRQHandler, /* 60 */
    USART1_IRQHandler, /* 61 */
    USART2_IRQHandler, /* 62 */
    USART3_IRQHandler, /* 63 */
    UART4_IRQHandler, /* 64 */
    UART5_IRQHandler, /* 65 */
    LPUART1_IRQHandler, /* 66 */
    LPTIM1_IRQHandler, /* 67 */
    LPTIM2_IRQHandler, /* 68 */
    TIM15_IRQHandler, /* 69 */
    TIM16_IRQHandler, /* 70 */
    TIM17_IRQHandler, /* 71 */
    COMP_IRQHandler, /* 72 */
    OTG_FS_IRQHandler, /* 73 */
    CRS_IRQHandler, /* 74 */
    FMC_IRQHandler, /* 75 */
    OCTOSPI1_IRQHandler, /* 76 */
    PWR_S3WU_IRQHandler, /* 77 */
    SDMMC1_IRQHandler, /* 78 */
    SDMMC2_IRQHandler, /* 79 */
    GPDMA1_Channel8_IRQHandler, /* 80 */
    GPDMA1_Channel9_IRQHandler, /* 81 */
    GPDMA1_Channel10_IRQHandler, /* 82 */
    GPDMA1_Channel11_IRQHandler, /* 83 */
    GPDMA1_Channel12_IRQHandler, /* 84 */
    GPDMA1_Channel13_IRQHandler, /* 85 */
    GPDMA1_Channel14_IRQHandler, /* 86 */
    GPDMA1_Channel15_IRQHandler, /* 87 */
    I2C3_EV_IRQHandler, /* 88 */
    I2C3_ER_IRQHandler, /* 89 */
    SAI1_IRQHandler, /* 90 */
    SAI2_IRQHandler, /* 91 */
    TSC_IRQHandler, /* 92 */
    0, /* 93 reserved */
    RNG_IRQHandler, /* 94 */
    FPU_IRQHandler, /* 95 */
    HASH_IRQHandler, /* 96 */
    0, /* 97 reserved */
    LPTIM3_IRQHandler, /* 98 */
    SPI3_IRQHandler, /* 99 */
    I2C4_ER_IRQHandler, /* 100 */
    I2C4_EV_IRQHandler, /* 101 */
    MDF1_FLT0_IRQHandler, /* 102 */
    MDF1_FLT1_IRQHandler, /* 103 */
    MDF1_FLT2_IRQHandler, /* 104 */
    MDF1_FLT3_IRQHandler, /* 105 */
    UCPD1_IRQHandler, /* 106 */
    ICACHE_IRQHandler, /* 107 */
    0, /* 108 reserved */
    0, /* 109 reserved */
    LPTIM4_IRQHandler, /* 110 */
    DCACHE1_IRQHandler, /* 111 */
    ADF1_IRQHandler, /* 112 */
    ADC4_IRQHandler, /* 113 */
    LPDMA1_Channel0_IRQHandler, /* 114 */
    LPDMA1_Channel1_IRQHandler, /* 115 */
    LPDMA1_Channel2_IRQHandler, /* 116 */
    LPDMA1_Channel3_IRQHandler, /* 117 */
    DMA2D_IRQHandler, /* 118 */
    DCMI_PSSI_IRQHandler, /* 119 */
    OCTOSPI2_IRQHandler, /* 120 */
    MDF1_FLT4_IRQHandler, /* 121 */
    MDF1_FLT5_IRQHandler, /* 122 */
    CORDIC_IRQHandler, /* 123 */
    FMAC_IRQHandler, /* 124 */
    LSECSSD_IRQHandler, /* 125 */
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata;) *dst++ = *src++;
    for (uint32_t *dst = &_sbss; dst < &_ebss;) *dst++ = 0u;
    SystemInit();
    (void)main();
    fault_halt(FAULT_MAIN_RETURNED);
}
