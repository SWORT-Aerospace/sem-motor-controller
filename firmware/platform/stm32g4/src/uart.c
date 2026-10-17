#include "uart.h"

#include "stm32g4xx.h"
#include "system_clock.h"

void uart_init(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    (void)RCC->APB2ENR;
    USART1->CR1 = 0u;
    USART1->BRR = (SYSCLK_HZ + 115200u / 2u) / 115200u; /* PCLK2 = 160 MHz, oversampling 16 */
    USART1->CR1 = USART_CR1_TE | USART_CR1_UE;
}

void uart_puts(const char *s)
{
    while (*s) {
        for (uint32_t i = 0; i < 100000u && (USART1->ISR & USART_ISR_TXE_TXFNF) == 0u; i++) {
        }
        USART1->TDR = (uint8_t)*s++;
    }
}

void uart_put_u32(uint32_t v)
{
    char b[11];
    int i = 10;
    b[i] = '\0';
    do {
        b[--i] = (char)('0' + v % 10u);
        v /= 10u;
    } while (v != 0u && i > 0);
    uart_puts(&b[i]);
}
