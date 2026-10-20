/* GNSS receiver on USART2: PD6 RX and PD5 TX, AF7 (UM2861 Rev 10 Table 17: Zio CN9 pins 4 and 6, USART2). Its PPS
 * output goes to PA1, TIM2_CH2 (board_capture_start). Kernel clock PCLK1 (USART2SEL = 00 after reset) = 4 MHz:
 * BRR 104 gives 38462 baud, 0.16 % above the 38400 baud the NEO-M9N uses by default (to be checked in the u-blox
 * interface description). Alternate functions from ST's open pin data at the commit in vendor/PROVENANCE.md, like every
 * other pin: PD5 GPIO_AF7_USART2 (TX), PD6 GPIO_AF7_USART2 (RX), PA1 GPIO_AF1_TIM2 (CH2); DS13737 is document check DC03.
 *
 * Each received byte goes into a ring with the low 32 bits of its arrival time; the main loop drains the ring into
 * tm_gnss_rx. A full ring drops the byte and counts it. Only images built with TM_ENABLE_GNSS contain this file.
 * Not run on hardware. */
#include "drivers_u575.h"

#include "board_u575.h"
#include "stm32u5xx.h"

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);

#define RXLEN 1024u                       /* about 1 s of NAV-PVT at 10 Hz (100 bytes each); power of two */
static volatile uint8_t g_rx[RXLEN];
static volatile uint32_t g_rx_t[RXLEN];
static volatile uint32_t g_head, g_tail, g_dropped;

void USART2_IRQHandler(void);
void USART2_IRQHandler(void)
{
    uint32_t isr = USART2->ISR;
    if (isr & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE)) {
        USART2->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NECF;
        g_dropped++;                      /* a byte lost or damaged in the peripheral */
    }
    while (USART2->ISR & USART_ISR_RXNE_RXFNE) {
        uint8_t b = (uint8_t)(USART2->RDR & 0xFFu);
        if (g_head - g_tail >= RXLEN) {
            g_dropped++;
            continue;
        }
        g_rx[g_head % RXLEN] = b;
        g_rx_t[g_head % RXLEN] = (uint32_t)board_now_us();
        g_head++;
    }
}

void gnss_uart_init(void)
{
    board_gpio_af(GPIOD, 5u, 7u, false, false);
    board_gpio_af(GPIOD, 6u, 7u, true, false);
    RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
    (void)RCC->APB1ENR1;
    USART2->CR1 = 0u;
    USART2->BRR = 104u;
    USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_RXNEIE_RXFNEIE | USART_CR1_UE;
    for (uint32_t k = 0; k < 100000u && (USART2->ISR & (USART_ISR_TEACK | USART_ISR_REACK)) !=
                                            (USART_ISR_TEACK | USART_ISR_REACK); k++) {
    }
    NVIC_SetPriority(USART2_IRQn, 2u);    /* below TIM2 (1): a wheel or PPS capture is never delayed by it */
    NVIC_EnableIRQ(USART2_IRQn);
}

void gnss_uart_send(const uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        for (uint32_t k = 0; k < 100000u && !(USART2->ISR & USART_ISR_TXE_TXFNF); k++) {
        }
        USART2->TDR = p[i];
    }
}

bool gnss_uart_get(uint8_t *b, uint64_t *t_us)
{
    if (g_tail == g_head) return false;
    uint32_t k = g_tail % RXLEN;
    *b = g_rx[k];
    uint64_t now = board_now_us();
    *t_us = now - (uint32_t)((uint32_t)now - g_rx_t[k]);   /* the byte arrived less than 2^32 us ago */
    g_tail++;
    return true;
}

uint32_t gnss_uart_dropped(void) { return g_dropped; }
