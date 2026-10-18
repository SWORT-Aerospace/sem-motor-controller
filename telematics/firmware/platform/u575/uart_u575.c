/* USART1 on PA9 (TX) / PA10 (RX), AF7: the ST-LINK virtual COM port of the NUCLEO-U575ZI-Q. Kernel clock
 * PCLK2 (USART1SEL = 00 after reset) = 4 MHz: BRR 35 gives 114286 baud, 0.8 % below 115200. */
#include "drivers_u575.h"

#include <string.h>

#include "stm32u5xx.h"

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);

#define TXLEN 4096u
static char g_tx[TXLEN];
static uint32_t g_head, g_tail, g_dropped;

void uart_init(void)
{
    board_gpio_af(GPIOA, 9u, 7u, false, false);
    board_gpio_af(GPIOA, 10u, 7u, true, false);
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    (void)RCC->APB2ENR;
    USART1->CR1 = 0u;
    USART1->BRR = 35u;
    USART1->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
    /* transmitter and receiver acknowledged before first use (ST: UART_CheckIdleState); bounded */
    for (uint32_t k = 0; k < 100000u && (USART1->ISR & (USART_ISR_TEACK | USART_ISR_REACK)) !=
                                            (USART_ISR_TEACK | USART_ISR_REACK); k++) {
    }
}

void uart_poll(void)
{
    while (g_head != g_tail && (USART1->ISR & USART_ISR_TXE_TXFNF)) {
        USART1->TDR = (uint8_t)g_tx[g_tail % TXLEN];
        g_tail++;
    }
}

void uart_write(const char *s)
{
    for (size_t i = 0; s[i]; i++) {
        if (g_head - g_tail >= TXLEN) {
            g_dropped++;
            return;
        }
        g_tx[g_head % TXLEN] = s[i];
        g_head++;
    }
}

void uart_write_blocking(const char *s, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        for (uint32_t k = 0; k < 100000u && !(USART1->ISR & USART_ISR_TXE_TXFNF); k++) {
        }
        USART1->TDR = (uint8_t)s[i];
    }
}

bool uart_getc(char *c)
{
    uint32_t isr = USART1->ISR;
    if (isr & USART_ISR_ORE) USART1->ICR = USART_ICR_ORECF;
    if (!(isr & USART_ISR_RXNE_RXFNE)) return false;
    *c = (char)(USART1->RDR & 0xFFu);
    return true;
}

uint32_t uart_dropped(void) { return g_dropped; }
