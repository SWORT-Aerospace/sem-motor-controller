/* SPI1 master for the external NOR flash: PA5 SCK, PA6 MISO, PA7 MOSI (AF5), chip select PD14 as GPIO (the
 * Arduino D13/D12/D11/D10 positions). Mode 0, 8-bit, PCLK2 / 2 = 2 MHz (MBR = 000). The STM32U5 SPI is the
 * "SPI v2" block (CFG1, CFG2, CR2.TSIZE, CSTART, TXP/RXP, EOT). Polled; every wait is bounded, so a missing
 * device returns TM_BUS_TIMEOUT within about (bytes + 1) x 4 ms at most. Not run on hardware. */
#include "drivers_u575.h"

#include "stm32u5xx.h"

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);
void board_gpio_out(GPIO_TypeDef *g, uint32_t pin, bool high);

#define LOOPS 4000u

static void cs(bool low) { GPIOD->BSRR = low ? (1uL << (14u + 16u)) : (1uL << 14u); }

static bool wait(uint32_t mask)
{
    for (uint32_t i = 0; i < LOOPS; i++)
        if (SPI1->SR & mask) return true;
    return false;
}

static int run(const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    int rc = TM_BUS_OK;
    while (n) {
        uint32_t chunk = n > 0xFFFFu ? 0xFFFFu : n;
        SPI1->CR2 = chunk << SPI_CR2_TSIZE_Pos;
        SPI1->CR1 |= SPI_CR1_SPE;
        SPI1->CR1 |= SPI_CR1_CSTART;
        for (uint32_t i = 0; i < chunk; i++) {
            if (!wait(SPI_SR_TXP)) {
                rc = TM_BUS_TIMEOUT;
                break;
            }
            *(volatile uint8_t *)&SPI1->TXDR = tx ? tx[i] : 0xFFu;
            if (!wait(SPI_SR_RXP)) {
                rc = TM_BUS_TIMEOUT;
                break;
            }
            uint8_t b = *(volatile uint8_t *)&SPI1->RXDR;
            if (rx) rx[i] = b;
        }
        if (rc == TM_BUS_OK && !wait(SPI_SR_EOT)) rc = TM_BUS_TIMEOUT;
        SPI1->IFCR = SPI_IFCR_EOTC | SPI_IFCR_TXTFC;
        SPI1->CR1 &= ~SPI_CR1_SPE;
        if (rc) return rc;
        n -= chunk;
        if (tx) tx += chunk;
        if (rx) rx += chunk;
    }
    return rc;
}

static int xfer(void *ctx, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    (void)ctx;
    cs(true);
    int rc = run(tx, rx, n);
    cs(false);
    return rc;
}

static int xfer2(void *ctx, const uint8_t *cmd, uint32_t ncmd, const uint8_t *tx, uint8_t *rx, uint32_t n)
{
    (void)ctx;
    cs(true);
    int rc = run(cmd, 0, ncmd);
    if (rc == TM_BUS_OK) rc = run(tx, rx, n);
    cs(false);
    return rc;
}

const tm_spi_t g_spi1 = {.xfer = xfer, .xfer2 = xfer2, .ctx = 0};

void spi1_init(void)
{
    board_gpio_out(GPIOD, 14u, true);   /* chip select high (inactive) first */
    board_gpio_af(GPIOA, 5u, 5u, false, false);
    board_gpio_af(GPIOA, 6u, 5u, true, false);
    board_gpio_af(GPIOA, 7u, 5u, false, false);
    RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;
    (void)RCC->APB2ENR;
    SPI1->CR1 = SPI_CR1_SSI;
    SPI1->CFG1 = (0u << SPI_CFG1_MBR_Pos) | (7u << SPI_CFG1_DSIZE_Pos);            /* /2, 8 bits */
    SPI1->CFG2 = SPI_CFG2_MASTER | SPI_CFG2_SSM | SPI_CFG2_AFCNTR;                  /* mode 0, software NSS */
}
