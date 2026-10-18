/* FDCAN1 in bus-monitoring mode (CCCR.MON = 1): the controller receives every frame on the bus and sends
 * nothing, not even the acknowledge bit or an error frame, so the unit cannot take part in the bus traffic
 * (a two-node bench therefore needs another node that acknowledges: BENCH.md). This is protocol-level
 * receive-only; electrical noninterference is a property of the transceiver and the wiring
 * (docs/CONTROLLER_INTERFACE_REQUEST.md, section 5), checked on the bench.
 *
 * The decoding of the frames is done at the pit by the controller adapter named in the log; the firmware
 * only timestamps and logs them. SIMULATION FIXTURE until the controller team's message definitions exist:
 * the bit rate is the semmc fixture's 500 kbit/s; classic frames only (FDOE = 0; an FD frame on the bus is a
 * protocol error to this node, counted and, in monitoring mode, not signalled).
 *
 * The STM32U5 FDCAN has the simplified message RAM of the STM32G4 (fixed layout: 28 standard and 8 extended
 * filters, 3-element receive FIFOs of 72-byte elements); offsets as ST's HAL (SRAMCAN_* in
 * stm32u5xx_hal_fdcan.c). Not run on hardware. */
#include "drivers_u575.h"

#include "board_u575.h"
#include "stm32u5xx.h"
#include "tm_app.h"

void board_gpio_af(GPIO_TypeDef *g, uint32_t pin, uint32_t af, bool pull_up, bool open_drain);
extern tm_app_t g_app;

#define RAM_RF0 0x0B0u
#define RAM_SIZE 0x350u
#define RF0_ELEM 72u
#define KERNEL_HZ 20000000u

static uint32_t g_errors, g_hw_lost;
static volatile uint32_t *ram(uint32_t off) { return (volatile uint32_t *)(SRAMCAN_BASE + off); }

static bool wait_cccr(uint32_t mask, bool set)
{
    for (uint32_t i = 0; i < 100000u; i++)
        if (((FDCAN1->CCCR & mask) != 0u) == set) return true;
    return false;
}

const char *can_monitor_init(uint32_t bitrate)
{
    /* nominal bit time in kernel-clock quanta, prescaler 1: at 500 kbit/s 40 tq, sample point 87.5 % */
    if (bitrate == 0u || KERNEL_HZ % bitrate) return "off: bit rate not reachable";
    uint32_t tq = KERNEL_HZ / bitrate;
    if (tq < 8u || tq > 256u) return "off: bit rate not reachable";
    uint32_t tseg2 = tq / 8u, tseg1 = tq - 1u - tseg2, sjw = tseg2;
    if (!board_pll1q_20mhz()) return "off: no FDCAN kernel clock (needs the LSE-locked MSIS and PLL1)";
    RCC->APB1ENR2 |= RCC_APB1ENR2_FDCAN1EN;
    (void)RCC->APB1ENR2;
    board_gpio_af(GPIOD, 0u, 9u, false, false);   /* FDCAN1_RX */
    board_gpio_af(GPIOD, 1u, 9u, false, false);   /* FDCAN1_TX: recessive in monitoring mode */
    FDCAN1->CCCR &= ~FDCAN_CCCR_CSR;
    if (!wait_cccr(FDCAN_CCCR_CSA, false)) return "off: clock stop not released";
    FDCAN1->CCCR |= FDCAN_CCCR_INIT;
    if (!wait_cccr(FDCAN_CCCR_INIT, true)) return "off: init not entered";
    FDCAN1->CCCR |= FDCAN_CCCR_CCE;
    FDCAN_CONFIG->CKDIV = 0u;
    FDCAN1->CCCR = (FDCAN1->CCCR & ~(FDCAN_CCCR_FDOE | FDCAN_CCCR_BRSE | FDCAN_CCCR_TEST | FDCAN_CCCR_ASM)) |
                   FDCAN_CCCR_MON | FDCAN_CCCR_DAR;
    FDCAN1->NBTP = ((sjw - 1u) << FDCAN_NBTP_NSJW_Pos) | (0u << FDCAN_NBTP_NBRP_Pos) |
                   ((tseg1 - 1u) << FDCAN_NBTP_NTSEG1_Pos) | ((tseg2 - 1u) << FDCAN_NBTP_NTSEG2_Pos);
    for (uint32_t off = 0; off < RAM_SIZE; off += 4u) *ram(off) = 0u;
    /* no filter elements; every standard and extended frame to FIFO 0; remote frames rejected */
    FDCAN1->RXGFC = (0u << FDCAN_RXGFC_ANFS_Pos) | (0u << FDCAN_RXGFC_ANFE_Pos) | FDCAN_RXGFC_RRFS | FDCAN_RXGFC_RRFE;
    FDCAN1->IE = FDCAN_IE_RF0NE | FDCAN_IE_RF0LE | FDCAN_IE_PEAE;
    FDCAN1->ILS = 0u;
    FDCAN1->ILE = FDCAN_ILE_EINT0;
    NVIC_SetPriority(FDCAN1_IT0_IRQn, 2u);
    NVIC_EnableIRQ(FDCAN1_IT0_IRQn);
    FDCAN1->CCCR &= ~FDCAN_CCCR_INIT;
    return "on (bus monitoring, 500 kbit/s classic)";
}

static uint32_t dlc_len(uint32_t dlc)
{
    static const uint8_t L[16] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64};
    return L[dlc & 15u];
}

void FDCAN1_IT0_IRQHandler(void);
void FDCAN1_IT0_IRQHandler(void)
{
    uint32_t ir = FDCAN1->IR;
    FDCAN1->IR = ir;
    if (ir & FDCAN_IR_RF0L) g_hw_lost++;
    if (ir & FDCAN_IR_PEA) g_errors++;
    while (FDCAN1->RXF0S & FDCAN_RXF0S_F0FL) {
        uint32_t idx = (FDCAN1->RXF0S & FDCAN_RXF0S_F0GI) >> FDCAN_RXF0S_F0GI_Pos;
        volatile uint32_t *e = ram(RAM_RF0 + idx * RF0_ELEM);
        uint32_t r0 = e[0], r1 = e[1];
        tm_can_frame_t f;
        f.t_us = board_now_us();
        bool xtd = (r0 >> 30) & 1u, fdf = (r1 >> 21) & 1u, brs = (r1 >> 20) & 1u;
        f.id_flags = (xtd ? ((r0 & 0x1FFFFFFFu) | (1uL << 31)) : ((r0 >> 18) & 0x7FFu)) | (fdf ? (1uL << 30) : 0u) |
                     (brs ? (1uL << 29) : 0u);
        uint32_t len = dlc_len((r1 >> 16) & 0xFu);
        if (!fdf && len > 8u) len = 8u;
        f.len = (uint8_t)len;
        for (uint32_t i = 0; i < len; i++) f.data[i] = (uint8_t)(e[2u + i / 4u] >> (8u * (i % 4u)));
        FDCAN1->RXF0A = idx;
        (void)tm_app_can_frame(&g_app, &f);
    }
}

uint32_t can_bus_errors(void) { return g_errors; }
uint32_t can_hw_fifo_lost(void) { return g_hw_lost; }
