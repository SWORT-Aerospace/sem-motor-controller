/* CAN binding for the transport-neutral core.
 *
 * The protocol defines 64 message numbers (0x300..0x33F as generated). On a
 * CAN bus they are placed at an 11-bit identifier block chosen by the vehicle
 * integration: id = base + (number - 0x300), base = supervision.can_id_base
 * (a multiple of 0x40, validator rule 40). Message integrity (data id,
 * sequence, CRC) is inside the payload and does not depend on the block.
 *
 * Frames outside the block, extended (29-bit) frames and remote frames are
 * filtered by the platform layer before they reach this function; anything
 * inside the block that is not a known message is counted as rx_unknown by
 * the core. */
#include "semmc/mc_core.h"
#include "semmc_protocol.h"

_Static_assert(SEMMC_ID_CTRL_FAULT == MC_PROTO_MSG_FIRST, "protocol block must start at 0x300");
_Static_assert(SEMMC_ID_CTRL_IDENTITY < MC_PROTO_MSG_FIRST + MC_PROTO_MSG_SPAN, "protocol block exceeds 64 numbers");

uint32_t mc_can_id_base(const mc_core_t *c)
{
    return c->config_ok ? (uint32_t)c->p.can_id_base : MC_PROTO_MSG_FIRST;
}

void mc_core_on_can_rx(mc_core_t *c, mc_time_us_t now_us, uint32_t can_id, const uint8_t *data, uint8_t len)
{
    const uint32_t base = mc_can_id_base(c);
    if (can_id < base || can_id >= base + MC_PROTO_MSG_SPAN) {
        c->can.rx_frames++;
        c->can.rx_unknown++; /* foreign identifier: not part of this controller's block */
        return;
    }
    mc_core_on_msg_rx(c, now_us, can_id - base + MC_PROTO_MSG_FIRST, data, len);
}

void mc_core_on_can_bus_off(mc_core_t *c, bool bus_off)
{
    mc_core_on_link_state(c, bus_off);
}

bool mc_core_can_tx_poll(mc_core_t *c, mc_time_us_t now_us, uint32_t *can_id, uint8_t data[8])
{
    uint32_t msg_id;
    if (!mc_core_msg_tx_poll(c, now_us, &msg_id, data)) return false;
    *can_id = msg_id - MC_PROTO_MSG_FIRST + mc_can_id_base(c);
    return true;
}
