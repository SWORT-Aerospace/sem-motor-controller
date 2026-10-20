/* Register-level drivers of the NUCLEO-U575ZI-Q telematics image. Not run on hardware. */
#ifndef DRIVERS_U575_H
#define DRIVERS_U575_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "tm_bus.h"
#include "tm_flashlog.h"
#include "tm_queue.h"

/* Internal flash bank 2 as log storage: 256 slots of 4 KiB in 128 pages of 8 KiB, quad-word programming.
 * Code runs from bank 1, so programming bank 2 does not stall it (read-while-write between banks). */
extern const tm_flash_if_t g_flash_bank2;
uint32_t flash_ecc_address(void);   /* address of the last double ECC error, 0 if none */

/* USART1, 115200 8N1 on the ST-LINK virtual COM port. Writes go to a ring the main loop drains; a full ring
 * drops and counts. uart_write_blocking is for the DUMP command only. */
void uart_init(void);
void uart_poll(void);
void uart_write(const char *s);
void uart_write_blocking(const char *s, size_t n);
bool uart_getc(char *c);
uint32_t uart_dropped(void);

/* FDCAN1 in bus-monitoring mode: receives every frame, sends nothing (no acknowledge, no error frame).
 * Returns a reason string; "on" when running. */
const char *can_monitor_init(uint32_t bitrate);
uint32_t can_bus_errors(void);
uint32_t can_hw_fifo_lost(void);

/* SPI1 master, mode 0, PCLK2 / 2; chip select PD14. I2C1 standard mode (about 100 kHz). */
extern const tm_spi_t g_spi1;
extern const tm_i2c_t g_i2c1;
void spi1_init(void);
void i2c1_init(void);

/* GNSS receiver on USART2 (PD6 RX, PD5 TX), 38400 8N1: received bytes with their arrival time into a ring the main
 * loop drains (gnss_uart_get); a full ring drops and counts. gnss_uart_send is for the receiver's configuration
 * only (bounded, blocking). Images built with TM_ENABLE_GNSS. */
void gnss_uart_init(void);
void gnss_uart_send(const uint8_t *p, size_t n);
bool gnss_uart_get(uint8_t *b, uint64_t *t_us);
uint32_t gnss_uart_dropped(void);

#endif
