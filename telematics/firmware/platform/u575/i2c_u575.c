/* I2C1 master for the IMU and the temperature sensors: PB8 SCL, PB9 SDA (AF4, open drain; the bus needs
 * external pull-ups, e.g. 4.7 kOhm to 3.3 V on the sensor breakouts). Kernel clock PCLK1 = 4 MHz
 * (I2C1SEL = 00 after reset). TIMINGR 0x00420F13: PRESC 0 (250 ns), SCLL 19 (5.0 us low), SCLH 15 (4.0 us
 * high), SDADEL 2, SCLDEL 4 (1.25 us data setup): standard mode, about 100 kHz, computed from the I2C
 * specification's standard-mode limits; to be checked with RM0456's timing formula and measured on the
 * bench. Polled with bounded waits: a missing device gives TM_BUS_NACK, a stuck bus TM_BUS_TIMEOUT. Not run on
 * hardware. */
#include "drivers_u575.h"

#include "stm32u5xx.h"

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);

#define LOOPS 20000u     /* about 20 ms at 4 MHz per wait: far above one byte at 100 kHz */

static int wait_flag(uint32_t mask)
{
    for (uint32_t i = 0; i < LOOPS; i++) {
        uint32_t isr = I2C1->ISR;
        if (isr & I2C_ISR_NACKF) {
            I2C1->ICR = I2C_ICR_NACKCF;
            for (uint32_t k = 0; k < LOOPS && !(I2C1->ISR & I2C_ISR_STOPF); k++) {
            }
            I2C1->ICR = I2C_ICR_STOPCF;
            return TM_BUS_NACK;
        }
        if (isr & (I2C_ISR_BERR | I2C_ISR_ARLO)) {
            I2C1->ICR = I2C_ICR_BERRCF | I2C_ICR_ARLOCF;
            return TM_BUS_ERROR;
        }
        if (isr & mask) return TM_BUS_OK;
    }
    return TM_BUS_TIMEOUT;
}

static int write_read(void *ctx, uint8_t addr7, const uint8_t *w, uint32_t nw, uint8_t *r, uint32_t nr)
{
    (void)ctx;
    int rc;
    if (nw > 255u || nr > 255u) return TM_BUS_ERROR;
    if (I2C1->ISR & I2C_ISR_BUSY) return TM_BUS_TIMEOUT;
    uint32_t sadd = (uint32_t)addr7 << 1;
    if (nw) {
        I2C1->CR2 = sadd | (nw << I2C_CR2_NBYTES_Pos) | (nr ? 0u : I2C_CR2_AUTOEND) | I2C_CR2_START;
        for (uint32_t i = 0; i < nw; i++) {
            if ((rc = wait_flag(I2C_ISR_TXIS)) != TM_BUS_OK) return rc;
            I2C1->TXDR = w[i];
        }
        if ((rc = wait_flag(nr ? I2C_ISR_TC : I2C_ISR_STOPF)) != TM_BUS_OK) return rc;
    }
    if (nr) {
        I2C1->CR2 = sadd | I2C_CR2_RD_WRN | (nr << I2C_CR2_NBYTES_Pos) | I2C_CR2_AUTOEND | I2C_CR2_START;
        for (uint32_t i = 0; i < nr; i++) {
            if ((rc = wait_flag(I2C_ISR_RXNE)) != TM_BUS_OK) return rc;
            r[i] = (uint8_t)I2C1->RXDR;
        }
        if ((rc = wait_flag(I2C_ISR_STOPF)) != TM_BUS_OK) return rc;
    }
    I2C1->ICR = I2C_ICR_STOPCF;
    return TM_BUS_OK;
}

const tm_i2c_t g_i2c1 = {.write_read = write_read, .ctx = 0};

void i2c1_init(void)
{
    board_gpio_af(GPIOB, 8u, 4u, false, true);
    board_gpio_af(GPIOB, 9u, 4u, false, true);
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C1EN;
    (void)RCC->APB1ENR1;
    I2C1->CR1 = 0u;
    I2C1->TIMINGR = 0x00420F13u;
    I2C1->CR1 = I2C_CR1_PE;
}
