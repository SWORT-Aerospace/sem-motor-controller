#include "can.h"

#include <math.h>

#include "stm32g4xx.h"

/* Message RAM of FDCAN1 (stm32g4xx_hal_fdcan.c: SRAMCAN_* layout). */
#define RAM_FLS 0x000u  /* 28 x 4 bytes */
#define RAM_RF0 0x0B0u  /* after 8 extended filters x 8 bytes */
#define RAM_TFQ 0x278u
#define RAM_SIZE 0x350u
#define RF0_ELEM 72u
#define TFQ_ELEM 72u

#define SFT_CLASSIC 2u  /* filter + mask */
#define SFEC_FIFO0 1u
#define ANF_REJECT 2u

static bool g_on;
static bool g_bus_off;
static uint32_t g_bus_off_since_ms;

static volatile uint32_t *ram(uint32_t off) { return (volatile uint32_t *)(SRAMCAN_BASE + off); }

static bool wait_cccr(uint32_t mask, bool set)
{
    for (uint32_t i = 0; i < 1000000u; i++) {
        if (((FDCAN1->CCCR & mask) != 0u) == set) return true;
    }
    return false;
}

can_status_t can_init(bool hse, bool config_ok, float bitrate_bps, uint32_t id_base, mc_can_timing_t *timing)
{
    g_on = false;
    if (!hse) return CAN_OFF_NO_CRYSTAL;
    if (!(bitrate_bps > 0.0f) || !(bitrate_bps <= 1.0e6f)) return CAN_OFF_NO_BITRATE;
    if (!mc_can_timing_compute(16000000u, (uint32_t)lroundf(bitrate_bps), 0.875f, timing)) return CAN_OFF_NO_TIMING;
    if (!config_ok) return CAN_OFF_CONFIG_INVALID;

    RCC->CCIPR &= ~RCC_CCIPR_FDCANSEL; /* 00: HSE */
    RCC->APB1ENR1 |= RCC_APB1ENR1_FDCANEN;
    (void)RCC->APB1ENR1;

    FDCAN1->CCCR &= ~FDCAN_CCCR_CSR;
    if (!wait_cccr(FDCAN_CCCR_CSA, false)) return CAN_OFF_INIT_FAILED;
    FDCAN1->CCCR |= FDCAN_CCCR_INIT;
    if (!wait_cccr(FDCAN_CCCR_INIT, true)) return CAN_OFF_INIT_FAILED;
    FDCAN1->CCCR |= FDCAN_CCCR_CCE;
    FDCAN_CONFIG->CKDIV = 0u; /* kernel clock / 1 */
    /* Automatic retransmission on (DAR = 0), no transmit pause, protocol exception handling on,
     * classic frames only (FDOE = BRSE = 0), normal operation. */
    FDCAN1->CCCR &= ~(FDCAN_CCCR_DAR | FDCAN_CCCR_TXP | FDCAN_CCCR_PXHD | FDCAN_CCCR_FDOE | FDCAN_CCCR_BRSE |
                      FDCAN_CCCR_TEST | FDCAN_CCCR_MON | FDCAN_CCCR_ASM);
    FDCAN1->NBTP = ((uint32_t)(timing->sjw - 1u) << FDCAN_NBTP_NSJW_Pos) |
                   ((uint32_t)(timing->brp - 1u) << FDCAN_NBTP_NBRP_Pos) |
                   ((uint32_t)(timing->tseg1 - 1u) << FDCAN_NBTP_NTSEG1_Pos) |
                   ((uint32_t)(timing->tseg2 - 1u) << FDCAN_NBTP_NTSEG2_Pos);

    for (uint32_t off = 0; off < RAM_SIZE; off += 4u) *ram(off) = 0u;
    *ram(RAM_FLS) = (SFT_CLASSIC << 30u) | (SFEC_FIFO0 << 27u) | ((id_base & 0x7FFu) << 16u) | 0x7C0u;
    FDCAN1->RXGFC = (1uL << FDCAN_RXGFC_LSS_Pos) | (ANF_REJECT << FDCAN_RXGFC_ANFS_Pos) |
                    (ANF_REJECT << FDCAN_RXGFC_ANFE_Pos) | FDCAN_RXGFC_RRFS | FDCAN_RXGFC_RRFE;
    FDCAN1->TXBC = 0u; /* TX FIFO mode */
    FDCAN1->IE = 0u;

    FDCAN1->CCCR &= ~FDCAN_CCCR_INIT; /* joins the bus after 11 recessive bits */
    g_on = true;
    g_bus_off = false;
    return CAN_ON;
}

bool can_rx(uint32_t *id, uint8_t data[8], uint8_t *len)
{
    while (g_on && (FDCAN1->RXF0S & FDCAN_RXF0S_F0FL) != 0u) {
        const uint32_t idx = (FDCAN1->RXF0S & FDCAN_RXF0S_F0GI) >> FDCAN_RXF0S_F0GI_Pos;
        volatile uint32_t *e = ram(RAM_RF0 + idx * RF0_ELEM);
        const uint32_t r0 = e[0], r1 = e[1], d0 = e[2], d1 = e[3];
        FDCAN1->RXF0A = idx;
        const bool xtd = (r0 >> 30u) & 1u, rtr = (r0 >> 29u) & 1u, fdf = (r1 >> 21u) & 1u;
        const uint32_t dlc = (r1 >> 16u) & 0xFu;
        if (xtd || rtr || fdf || dlc > 8u) continue; /* the filters already reject these */
        *id = (r0 >> 18u) & 0x7FFu;
        *len = (uint8_t)dlc;
        for (uint32_t i = 0; i < 4u; i++) {
            data[i] = (uint8_t)(d0 >> (8u * i));
            data[4u + i] = (uint8_t)(d1 >> (8u * i));
        }
        return true;
    }
    return false;
}

bool can_tx_free(void) { return g_on && !g_bus_off && (FDCAN1->TXFQS & FDCAN_TXFQS_TFQF) == 0u; }

bool can_tx(uint32_t id, const uint8_t data[8])
{
    if (!can_tx_free()) return false;
    const uint32_t idx = (FDCAN1->TXFQS & FDCAN_TXFQS_TFQPI) >> FDCAN_TXFQS_TFQPI_Pos;
    volatile uint32_t *e = ram(RAM_TFQ + idx * TFQ_ELEM);
    e[0] = (id & 0x7FFu) << 18u;
    e[1] = 8uL << 16u; /* DLC 8, classic, no event */
    e[2] = (uint32_t)data[0] | ((uint32_t)data[1] << 8u) | ((uint32_t)data[2] << 16u) | ((uint32_t)data[3] << 24u);
    e[3] = (uint32_t)data[4] | ((uint32_t)data[5] << 8u) | ((uint32_t)data[6] << 16u) | ((uint32_t)data[7] << 24u);
    FDCAN1->TXBAR = 1uL << idx;
    return true;
}

bool can_service_bus_off(uint32_t now_ms)
{
    if (!g_on) return false;
    const bool bo = (FDCAN1->PSR & FDCAN_PSR_BO) != 0u;
    if (bo && !g_bus_off) {
        g_bus_off = true;
        g_bus_off_since_ms = now_ms;
    }
    if (g_bus_off && (FDCAN1->CCCR & FDCAN_CCCR_INIT) != 0u && now_ms - g_bus_off_since_ms >= CAN_BUS_OFF_HOLDOFF_MS) {
        FDCAN1->CCCR &= ~FDCAN_CCCR_INIT; /* start recovery */
    }
    if (g_bus_off && !bo && (FDCAN1->CCCR & FDCAN_CCCR_INIT) == 0u) g_bus_off = false;
    return g_bus_off;
}
