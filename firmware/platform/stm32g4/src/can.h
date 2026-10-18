/* FDCAN1 as a classic CAN 2.0 controller on PA11 (RX) / PA12 (TX), TJA1051T/3 transceiver (sheet 11).
 *
 * Enabled only when all of these hold; otherwise the controller stays in its reset state (bus
 * silent) and manual driving is unaffected:
 *   - the build has a crystal (SEMMC_HSE_HZ): the FDCAN kernel runs from HSE at 16 MHz;
 *   - supervision.can_bitrate_bps is in the calibration and gives an exact bit timing
 *     (mc_can_timing_compute, 87.5 % sample point);
 *   - the calibration is valid (the CAN binding's identifier block comes from it).
 *
 * Acceptance: one standard-id classic filter, id & 0x7C0 == base (the protocol's 64-message block),
 * into RX FIFO 0; every other standard id, every extended id and every remote frame is rejected in
 * hardware. Reception and transmission are polled from the slow step (no CAN interrupt), so the
 * core's message handling runs in one context. Transmission uses the 3-element TX FIFO.
 *
 * Bus-off: the controller sets CCCR.INIT itself; the core is told at once (mc_core_on_can_bus_off,
 * which ends any supervisor session). After CAN_BUS_OFF_HOLDOFF_MS the driver clears INIT, which
 * starts the standard recovery (128 occurrences of 11 recessive bits). The hold-off is a PROPOSED
 * value, not derived from the vehicle bus.
 *
 * Message RAM layout and element formats after ST's HAL (stm32g4xx_hal_fdcan.c@a6001282): per
 * instance, 28 standard filters, 8 extended filters, RX FIFO 0 and 1 of 3 x 72 bytes, TX event FIFO
 * 3 x 8 bytes, TX FIFO 3 x 72 bytes (0x350 bytes in all) from SRAMCAN_BASE. */
#ifndef SEMMC_STM32G4_CAN_H
#define SEMMC_STM32G4_CAN_H

#include <stdbool.h>
#include <stdint.h>

#include "semmc/mc_periph_timing.h"

#define CAN_BUS_OFF_HOLDOFF_MS 1000u

typedef enum { CAN_OFF_NO_CRYSTAL = 0, CAN_OFF_NO_BITRATE, CAN_OFF_NO_TIMING, CAN_OFF_CONFIG_INVALID, CAN_OFF_INIT_FAILED,
               CAN_ON } can_status_t;

can_status_t can_init(bool hse, bool config_ok, float bitrate_bps, uint32_t id_base, mc_can_timing_t *timing);
/* Pops one received classic standard frame. */
bool can_rx(uint32_t *id, uint8_t data[8], uint8_t *len);
/* True when the TX FIFO can take a frame. */
bool can_tx_free(void);
/* Queues one 8-byte classic standard frame. Returns false if the TX FIFO is full. */
bool can_tx(uint32_t id, const uint8_t data[8]);
/* Call every slow step. Returns true while the controller is bus-off (or recovering). */
bool can_service_bus_off(uint32_t now_ms);

#endif
