/* ADC1, ADC2, ADC3.
 *
 * Phase currents, injected group, one conversion each, all three started by TIM1_TRGO2 (rising edge,
 * one timer tick before the PWM valley): ADC1_IN1 (PA0, ISENSE_A), ADC2_IN2 (PA1, ISENSE_B),
 * ADC3_IN4 (PE7, ISENSE_C). Independent mode: the three conversions start on the same trigger edge;
 * that they sample at the same instant is not measured yet (bring-up stage 4). The ADC1 end-of-
 * injected-sequence interrupt runs the fast step.
 *
 * Slow signals, ADC3 regular group, continuous, circular DMA (DMA1 channel 1, DMAMUX request 37 =
 * ADC3 per ST's HAL) into adc_slow[]: VBUS_SENSE IN2 (PE9), TEMP_FET IN14 (PE10), TEMP_MOTOR IN15
 * (PE11), THROTTLE_A IN16 (PE12), THROTTLE_B IN3 (PE13). An injected trigger interrupts a regular
 * conversion, which restarts afterwards.
 *
 * Clock: synchronous HCLK / 4 = 40 MHz (ADC_CCR.CKMODE = 11). Sampling time 24.5 cycles for the
 * currents, 247.5 cycles for the slow signals (sources: 1 k + 100 nF filters, sheets 07 and 10).
 * Both are ASSUMPTIONS pending DS12288 (maximum ADC clock, minimum sampling time for the source
 * impedance) and the current amplifier's output impedance (DRV8353 datasheet). 12-bit resolution.
 *
 * Start-up after ST's HAL/LL (stm32g4xx-hal-driver@a6001282): leave deep power-down, enable the
 * regulator and wait 20 us (LL_ADC_DELAY_INTERNAL_REGUL_STAB_US), single-ended calibration, wait
 * 4 ADC cycles (LL_ADC_DELAY_CALIB_ENABLE_ADC_CYCLES), enable and wait for ADRDY. */
#ifndef SEMMC_STM32G4_ADC_H
#define SEMMC_STM32G4_ADC_H

#include <stdbool.h>
#include <stdint.h>

enum { ADC_SLOW_VBUS = 0, ADC_SLOW_TEMP_FET, ADC_SLOW_TEMP_MOTOR, ADC_SLOW_THROTTLE_A, ADC_SLOW_THROTTLE_B, ADC_SLOW_N };

extern volatile uint16_t adc_slow[ADC_SLOW_N];

bool adc_init(uint32_t fast_irq_priority);
/* Read in the fast interrupt. a is ready when it runs; b and c are polled for a bounded time.
 * Returns a bit mask of the phases whose conversion completed this cycle; *wait_cycles is how long b and c
 * took after a (CPU cycles). */
uint8_t adc_read_currents(uint16_t raw[3], uint32_t *wait_cycles);

#endif
