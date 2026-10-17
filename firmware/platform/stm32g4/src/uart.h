/* USART1 on PC4 (TX) / PC5 (RX), bench UART header J802 (sheet 08): 115200 8N1, transmit only, polled.
 * Used at boot for the banner, the calibration report and the event log; not used while driving. */
#ifndef SEMMC_STM32G4_UART_H
#define SEMMC_STM32G4_UART_H

#include <stdint.h>

void uart_init(void);
void uart_puts(const char *s);
void uart_put_u32(uint32_t v);

#endif
