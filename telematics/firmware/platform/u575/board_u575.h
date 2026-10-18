/* NUCLEO-U575ZI-Q board layer of the telematics firmware: pins, clocks, timebase, watchdog, faults.
 *
 * Pins (the connection table is telematics/firmware/BENCH.md; sources: ST's NUCLEO-U575ZI-Q BSP v1.2.3,
 * Zephyr's nucleo_u575zi_q board files and ST's open pin data, which agree; UM2861 has not been read):
 *   wheel_0  PA3  TIM2_CH4 AF1  Arduino A0      wheel_1  PA2  TIM2_CH3 AF1  Arduino A1
 *   wheel_2  PA0  TIM2_CH1 AF1  (Zio connector; position to confirm in UM2861)
 *   USART1   PA9 TX / PA10 RX AF7: the ST-LINK virtual COM port
 *   FDCAN1   PD0 RX / PD1 TX AF9 (CAN image only) to an external 3.3 V transceiver
 *   SPI1     PA5 SCK / PA6 MISO / PA7 MOSI AF5, chip select PD14 (GPIO): Arduino D13/D12/D11/D10
 *   I2C1     PB8 SCL / PB9 SDA AF4, open drain, external pull-ups: Arduino D15/D14
 *   LD1 green PC7 (heartbeat), LD2 blue PB7 (log write) */
#ifndef BOARD_U575_H
#define BOARD_U575_H

#include <stdbool.h>
#include <stdint.h>

enum {
    FAULT_NONE = 0,
    FAULT_HARD = 1,
    FAULT_MEMMANAGE = 2,
    FAULT_BUS = 3,
    FAULT_USAGE = 4,
    FAULT_SECURE = 5,
    FAULT_UNEXPECTED_IRQ = 6,
    FAULT_MAIN_RETURNED = 7,
    FAULT_NMI_ECC = 8,
};

extern uint32_t SystemCoreClock;

typedef struct {
    bool lse_ok;          /* LSE started; MSIS runs in PLL mode locked to it */
    uint32_t reset_flags; /* RCC_CSR at start, before clearing */
    uint32_t last_fault;  /* fault code recorded before the reset, FAULT_NONE if none */
    bool fault_record_kept; /* option SRAM_RST = 1: SRAM1, which holds the fault record, survives a reset */
    bool flash_swapped;   /* option SWAP_BANK = 1: the banks are swapped; the internal-flash log is refused */
    uint16_t rev_id;      /* silicon revision (DBGMCU_IDCODE.REV_ID), for the errata sheet ES0499 */
} board_state_t;

extern board_state_t g_board;

void board_init(void);               /* clocks, GPIO, LEDs, watchdog, reset flags */
void board_record_fault(uint32_t code);
void board_kick_watchdog(void);
void board_led(int which, bool on);
uint64_t board_now_us(void);         /* 64-bit microseconds from TIM2 */
bool board_wheel_line_high(uint8_t channel);
void board_mask_capture(bool masked);
void board_capture_start(void);      /* TIM2 input capture on the three wheel channels */
void board_unit_id(char *out, unsigned cap);
bool board_pll1q_20mhz(void);        /* FDCAN kernel clock; needs the LSE-locked MSIS */

#endif
