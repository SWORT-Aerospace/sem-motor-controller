/* GENERATED from protocol/protocol.yaml by tools/gen_protocol.py - do not edit. */
/* spec hash 3365b84b45a16c63. Conversion arithmetic is in double (slow-loop only), matching the Python codec. */
#include "semmc_protocol.h"

#include <math.h>
#include <string.h>

static uint8_t crc8_upd(uint8_t crc, const uint8_t *d, unsigned n)
{
    for (unsigned i = 0; i < n; i++) {
        crc ^= d[i];
        for (int b = 0; b < 8; b++) {
            const unsigned c = crc;
            crc = (uint8_t)((c & 0x80u) ? ((c << 1) ^ 0x1Du) : (c << 1));
        }
    }
    return crc;
}

uint8_t semmc_crc8_data_id(uint16_t data_id, const uint8_t *payload7)
{
    const uint8_t id[2] = {(uint8_t)(data_id & 0xFFu), (uint8_t)(data_id >> 8)};
    return (uint8_t)(crc8_upd(crc8_upd(0xFFu, id, 2u), payload7, 7u) ^ 0xFFu);
}

static void put_bits(uint8_t *b, unsigned start, unsigned width, uint32_t raw)
{
    for (unsigned k = 0; k < width; k++) {
        const unsigned bit = start + k;
        if ((raw >> k) & 1u) b[bit / 8u] = (uint8_t)(b[bit / 8u] | (1u << (bit % 8u)));
    }
}

static uint32_t get_bits(const uint8_t *b, unsigned start, unsigned width)
{
    uint32_t raw = 0u;
    for (unsigned k = 0; k < width; k++) {
        const unsigned bit = start + k;
        raw |= (uint32_t)((b[bit / 8u] >> (bit % 8u)) & 1u) << k;
    }
    return raw;
}

static int64_t sext(uint32_t raw, unsigned width)
{
    if (width < 32u && (raw & (1u << (width - 1u)))) return (int64_t)raw - ((int64_t)1 << width);
    if (width == 32u && (raw & 0x80000000u)) return (int64_t)raw - ((int64_t)1 << 32);
    return (int64_t)raw;
}

static int64_t round_half_away(double x)
{
    return x >= 0.0 ? (int64_t)floor(x + 0.5) : -(int64_t)floor(-x + 0.5);
}

/* Encode one scaled field. Returns raw bits; flags saturation / sentinel. */
static uint32_t enc_scaled(float v, double mn, double mx, double scale, double offset, int64_t rlo,
                           int64_t rhi, bool has_inv, int64_t inv, unsigned width, uint32_t bit,
                           semmc_result_t *r)
{
    double x = (double)v;
    int64_t raw;
    if (x != x) {
        if (!has_inv) { r->status = SEMMC_E_NAN; return 0u; }
        r->invalid |= bit;
        raw = inv;
    } else {
        if (x < mn || x > mx) { x = x < mn ? mn : mx; r->saturated |= bit; }
        raw = round_half_away((x - offset) / scale);
        if (raw < rlo) raw = rlo;
        if (raw > rhi) raw = rhi;
    }
    const uint64_t mask = (width == 32u) ? 0xFFFFFFFFull : ((1ull << width) - 1ull);
    return (uint32_t)((uint64_t)raw & mask);
}

static float dec_scaled(int64_t raw, double mn, double mx, double scale, double offset, int64_t rlo,
                        int64_t rhi, bool has_inv, int64_t inv, uint32_t bit, semmc_result_t *r)
{
    if (has_inv && raw == inv) { r->invalid |= bit; return NAN; }
    const float x = (float)((double)raw * scale + offset);
    if (raw < rlo || raw > rhi || (double)x < (double)(float)mn || (double)x > (double)(float)mx) r->out_of_range |= bit;
    return x;
}

static uint32_t enc_raw(uint32_t v, uint32_t hi, uint32_t bit, semmc_result_t *r)
{
    if (v > hi) { r->saturated |= bit; return hi; }
    return v;
}

int semmc_msg_index(uint32_t can_id)
{
    switch (can_id) {
    case 0x300u: return 0;
    case 0x308u: return 1;
    case 0x309u: return 2;
    case 0x30Au: return 3;
    case 0x310u: return 4;
    case 0x311u: return 5;
    case 0x312u: return 6;
    case 0x313u: return 7;
    case 0x318u: return 8;
    case 0x319u: return 9;
    case 0x320u: return 10;
    case 0x321u: return 11;
    case 0x322u: return 12;
    case 0x323u: return 13;
    case 0x328u: return 14;
    case 0x330u: return 15;
    default: return -1;
    }
}

semmc_result_t semmc_encode_ctrl_fault(const semmc_ctrl_fault_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 24u, enc_raw(m->latched, 16777215u, (1u << 0), &r));
    put_bits(b, 40u, 8u, enc_raw(m->first_fault, 255u, (1u << 1), &r));
    put_bits(b, 48u, 8u, enc_raw(m->reset_reason, 255u, (1u << 2), &r));
    put_bits(b, 56u, 8u, enc_raw(m->fault_count, 255u, (1u << 3), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_FAULT, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_fault(const uint8_t *in, uint8_t len, semmc_ctrl_fault_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_FAULT, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->latched = get_bits(in, 16u, 24u);
    m->first_fault = get_bits(in, 40u, 8u);
    m->reset_reason = get_bits(in, 48u, 8u);
    m->fault_count = get_bits(in, 56u, 8u);
    return r;
}

semmc_result_t semmc_encode_sup_torque_req(const semmc_sup_torque_req_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 8u, enc_raw(m->session_tag, 255u, (1u << 0), &r));
    put_bits(b, 24u, 4u, enc_raw(m->limits_ref, 15u, (1u << 1), &r));
    put_bits(b, 28u, 1u, m->coast_request ? 1u : 0u);
    put_bits(b, 29u, 3u, enc_raw(m->reserved, 7u, (1u << 3), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->torque_Nm, -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 4), &r));
    put_bits(b, 48u, 16u, enc_raw(m->src_time_ms, 65535u, (1u << 5), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_SUP_TORQUE_REQ, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_sup_torque_req(const uint8_t *in, uint8_t len, semmc_sup_torque_req_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_SUP_TORQUE_REQ, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->session_tag = get_bits(in, 16u, 8u);
    m->limits_ref = get_bits(in, 24u, 4u);
    m->coast_request = get_bits(in, 28u, 1u) != 0u;
    m->reserved = get_bits(in, 29u, 3u);
    m->torque_Nm = dec_scaled(sext(get_bits(in, 32u, 16u), 16u), -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 4), &r);
    m->src_time_ms = get_bits(in, 48u, 16u);
    return r;
}

semmc_result_t semmc_encode_sup_limits(const semmc_sup_limits_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 8u, enc_raw(m->session_tag, 255u, (1u << 0), &r));
    put_bits(b, 24u, 8u, enc_raw(m->limits_seq, 255u, (1u << 1), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->max_torque_Nm, 0.0, 131.07, 0.002, 0.0, 0LL, 65535LL, false, 0LL, 16u, (1u << 2), &r));
    put_bits(b, 48u, 16u, enc_scaled(m->max_batt_power_W, 0.0, 65535.0, 1.0, 0.0, 0LL, 65535LL, false, 0LL, 16u, (1u << 3), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_SUP_LIMITS, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_sup_limits(const uint8_t *in, uint8_t len, semmc_sup_limits_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_SUP_LIMITS, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->session_tag = get_bits(in, 16u, 8u);
    m->limits_seq = get_bits(in, 24u, 8u);
    m->max_torque_Nm = dec_scaled((int64_t)get_bits(in, 32u, 16u), 0.0, 131.07, 0.002, 0.0, 0LL, 65535LL, false, 0LL, (1u << 2), &r);
    m->max_batt_power_W = dec_scaled((int64_t)get_bits(in, 48u, 16u), 0.0, 65535.0, 1.0, 0.0, 0LL, 65535LL, false, 0LL, (1u << 3), &r);
    return r;
}

semmc_result_t semmc_encode_sup_hello(const semmc_sup_hello_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 4u, enc_raw(m->proto_major, 15u, (1u << 0), &r));
    put_bits(b, 20u, 4u, enc_raw(m->proto_minor, 15u, (1u << 1), &r));
    put_bits(b, 24u, 8u, enc_raw(m->role, 255u, (1u << 2), &r));
    put_bits(b, 32u, 32u, enc_raw(m->companion_session, 4294967295u, (1u << 3), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_SUP_HELLO, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_sup_hello(const uint8_t *in, uint8_t len, semmc_sup_hello_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_SUP_HELLO, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->proto_major = get_bits(in, 16u, 4u);
    m->proto_minor = get_bits(in, 20u, 4u);
    m->role = get_bits(in, 24u, 8u);
    m->companion_session = get_bits(in, 32u, 32u);
    return r;
}

semmc_result_t semmc_encode_ctrl_status(const semmc_ctrl_status_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 4u, enc_raw(m->state, 15u, (1u << 0), &r));
    put_bits(b, 20u, 2u, enc_raw(m->owner, 3u, (1u << 1), &r));
    put_bits(b, 22u, 2u, enc_raw(m->sup_link, 3u, (1u << 2), &r));
    put_bits(b, 24u, 8u, enc_raw(m->session_tag, 255u, (1u << 3), &r));
    put_bits(b, 32u, 16u, enc_raw(m->boot_id, 65535u, (1u << 4), &r));
    put_bits(b, 48u, 1u, m->build_is_sim ? 1u : 0u);
    put_bits(b, 49u, 2u, enc_raw(m->cal_provenance, 3u, (1u << 6), &r));
    put_bits(b, 51u, 1u, m->output_permitted ? 1u : 0u);
    put_bits(b, 52u, 1u, m->pwm_enabled ? 1u : 0u);
    put_bits(b, 53u, 1u, m->derating ? 1u : 0u);
    put_bits(b, 54u, 1u, m->hw_trip ? 1u : 0u);
    put_bits(b, 55u, 1u, enc_raw(m->reserved, 1u, (1u << 11), &r));
    put_bits(b, 56u, 8u, enc_raw(m->last_transition, 255u, (1u << 12), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_STATUS, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_status(const uint8_t *in, uint8_t len, semmc_ctrl_status_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_STATUS, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->state = get_bits(in, 16u, 4u);
    m->owner = get_bits(in, 20u, 2u);
    m->sup_link = get_bits(in, 22u, 2u);
    m->session_tag = get_bits(in, 24u, 8u);
    m->boot_id = get_bits(in, 32u, 16u);
    m->build_is_sim = get_bits(in, 48u, 1u) != 0u;
    m->cal_provenance = get_bits(in, 49u, 2u);
    m->output_permitted = get_bits(in, 51u, 1u) != 0u;
    m->pwm_enabled = get_bits(in, 52u, 1u) != 0u;
    m->derating = get_bits(in, 53u, 1u) != 0u;
    m->hw_trip = get_bits(in, 54u, 1u) != 0u;
    m->reserved = get_bits(in, 55u, 1u);
    m->last_transition = get_bits(in, 56u, 8u);
    return r;
}

semmc_result_t semmc_encode_ctrl_cmd_trace(const semmc_ctrl_cmd_trace_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 16u, enc_scaled(m->requested_Nm, -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 0), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->accepted_Nm, -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 1), &r));
    put_bits(b, 48u, 16u, enc_raw(m->reason, 65535u, (1u << 2), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_CMD_TRACE, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_cmd_trace(const uint8_t *in, uint8_t len, semmc_ctrl_cmd_trace_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_CMD_TRACE, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->requested_Nm = dec_scaled(sext(get_bits(in, 16u, 16u), 16u), -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 0), &r);
    m->accepted_Nm = dec_scaled(sext(get_bits(in, 32u, 16u), 16u), -65.534, 65.534, 0.002, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 1), &r);
    m->reason = get_bits(in, 48u, 16u);
    return r;
}

semmc_result_t semmc_encode_driver_controls(const semmc_driver_controls_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 16u, enc_scaled(m->throttle, 0.0, 1.0, 0.0001, 0.0, 0LL, 65534LL, true, 65535LL, 16u, (1u << 0), &r));
    put_bits(b, 32u, 1u, m->brake ? 1u : 0u);
    put_bits(b, 33u, 1u, m->cancel ? 1u : 0u);
    put_bits(b, 34u, 1u, m->mode_eco ? 1u : 0u);
    put_bits(b, 35u, 1u, m->arm_switch ? 1u : 0u);
    put_bits(b, 36u, 1u, m->estop_chain_ok ? 1u : 0u);
    put_bits(b, 37u, 1u, m->driver_present ? 1u : 0u);
    put_bits(b, 38u, 1u, m->fault_reset ? 1u : 0u);
    put_bits(b, 39u, 1u, m->throttle_valid ? 1u : 0u);
    put_bits(b, 40u, 24u, enc_raw(m->reserved, 16777215u, (1u << 9), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_DRIVER_CONTROLS, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_driver_controls(const uint8_t *in, uint8_t len, semmc_driver_controls_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_DRIVER_CONTROLS, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->throttle = dec_scaled((int64_t)get_bits(in, 16u, 16u), 0.0, 1.0, 0.0001, 0.0, 0LL, 65534LL, true, 65535LL, (1u << 0), &r);
    m->brake = get_bits(in, 32u, 1u) != 0u;
    m->cancel = get_bits(in, 33u, 1u) != 0u;
    m->mode_eco = get_bits(in, 34u, 1u) != 0u;
    m->arm_switch = get_bits(in, 35u, 1u) != 0u;
    m->estop_chain_ok = get_bits(in, 36u, 1u) != 0u;
    m->driver_present = get_bits(in, 37u, 1u) != 0u;
    m->fault_reset = get_bits(in, 38u, 1u) != 0u;
    m->throttle_valid = get_bits(in, 39u, 1u) != 0u;
    m->reserved = get_bits(in, 40u, 24u);
    return r;
}

semmc_result_t semmc_encode_ctrl_session(const semmc_ctrl_session_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 8u, enc_raw(m->session_tag, 255u, (1u << 0), &r));
    put_bits(b, 24u, 32u, enc_raw(m->companion_session_echo, 4294967295u, (1u << 1), &r));
    put_bits(b, 56u, 4u, enc_raw(m->proto_major, 15u, (1u << 2), &r));
    put_bits(b, 60u, 4u, enc_raw(m->proto_minor, 15u, (1u << 3), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_SESSION, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_session(const uint8_t *in, uint8_t len, semmc_ctrl_session_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_SESSION, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->session_tag = get_bits(in, 16u, 8u);
    m->companion_session_echo = get_bits(in, 24u, 32u);
    m->proto_major = get_bits(in, 56u, 4u);
    m->proto_minor = get_bits(in, 60u, 4u);
    return r;
}

semmc_result_t semmc_encode_ctrl_motion(const semmc_ctrl_motion_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 16u, enc_scaled(m->speed_mech_rad_s, -1638.35, 1638.35, 0.05, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 0), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->iq_A, -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 1), &r));
    put_bits(b, 48u, 16u, enc_scaled(m->vbus_V, 0.0, 655.34, 0.01, 0.0, 0LL, 65534LL, true, 65535LL, 16u, (1u << 2), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_MOTION, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_motion(const uint8_t *in, uint8_t len, semmc_ctrl_motion_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_MOTION, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->speed_mech_rad_s = dec_scaled(sext(get_bits(in, 16u, 16u), 16u), -1638.35, 1638.35, 0.05, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 0), &r);
    m->iq_A = dec_scaled(sext(get_bits(in, 32u, 16u), 16u), -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 1), &r);
    m->vbus_V = dec_scaled((int64_t)get_bits(in, 48u, 16u), 0.0, 655.34, 0.01, 0.0, 0LL, 65534LL, true, 65535LL, (1u << 2), &r);
    return r;
}

semmc_result_t semmc_encode_ctrl_currents(const semmc_ctrl_currents_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 16u, enc_scaled(m->id_A, -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 0), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->ibatt_A, -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 1), &r));
    put_bits(b, 48u, 3u, enc_raw(m->measured_mask, 7u, (1u << 2), &r));
    put_bits(b, 51u, 3u, enc_raw(m->reconstructed_mask, 7u, (1u << 3), &r));
    put_bits(b, 54u, 1u, m->kcl_available ? 1u : 0u);
    put_bits(b, 55u, 1u, enc_raw(m->reserved, 1u, (1u << 5), &r));
    put_bits(b, 56u, 8u, enc_scaled(m->kcl_residual_A, -12.7, 12.7, 0.1, 0.0, -127LL, 127LL, true, -128LL, 8u, (1u << 6), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_CURRENTS, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_currents(const uint8_t *in, uint8_t len, semmc_ctrl_currents_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_CURRENTS, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->id_A = dec_scaled(sext(get_bits(in, 16u, 16u), 16u), -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 0), &r);
    m->ibatt_A = dec_scaled(sext(get_bits(in, 32u, 16u), 16u), -327.67, 327.67, 0.01, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 1), &r);
    m->measured_mask = get_bits(in, 48u, 3u);
    m->reconstructed_mask = get_bits(in, 51u, 3u);
    m->kcl_available = get_bits(in, 54u, 1u) != 0u;
    m->reserved = get_bits(in, 55u, 1u);
    m->kcl_residual_A = dec_scaled(sext(get_bits(in, 56u, 8u), 8u), -12.7, 12.7, 0.1, 0.0, -127LL, 127LL, true, -128LL, (1u << 6), &r);
    return r;
}

semmc_result_t semmc_encode_ctrl_energy(const semmc_ctrl_energy_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 32u, enc_scaled(m->energy_J, 0.0, 429496729.4, 0.1, 0.0, 0LL, 4294967294LL, true, 4294967295LL, 32u, (1u << 0), &r));
    put_bits(b, 48u, 16u, enc_scaled(m->p_batt_W, -32767.0, 32767.0, 1.0, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 1), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_ENERGY, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_energy(const uint8_t *in, uint8_t len, semmc_ctrl_energy_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_ENERGY, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->energy_J = dec_scaled((int64_t)get_bits(in, 16u, 32u), 0.0, 429496729.4, 0.1, 0.0, 0LL, 4294967294LL, true, 4294967295LL, (1u << 0), &r);
    m->p_batt_W = dec_scaled(sext(get_bits(in, 48u, 16u), 16u), -32767.0, 32767.0, 1.0, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 1), &r);
    return r;
}

semmc_result_t semmc_encode_ctrl_thermal(const semmc_ctrl_thermal_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 16u, enc_scaled(m->t_fet_degC, -3276.7, 3276.7, 0.1, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 0), &r));
    put_bits(b, 32u, 16u, enc_scaled(m->t_motor_degC, -3276.7, 3276.7, 0.1, 0.0, -32767LL, 32767LL, true, -32768LL, 16u, (1u << 1), &r));
    put_bits(b, 48u, 8u, enc_scaled(m->derate, 0.0, 1.0, 0.004, 0.0, 0LL, 254LL, true, 255LL, 8u, (1u << 2), &r));
    put_bits(b, 56u, 8u, enc_raw(m->derate_reasons, 255u, (1u << 3), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_THERMAL, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_thermal(const uint8_t *in, uint8_t len, semmc_ctrl_thermal_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_THERMAL, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->t_fet_degC = dec_scaled(sext(get_bits(in, 16u, 16u), 16u), -3276.7, 3276.7, 0.1, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 0), &r);
    m->t_motor_degC = dec_scaled(sext(get_bits(in, 32u, 16u), 16u), -3276.7, 3276.7, 0.1, 0.0, -32767LL, 32767LL, true, -32768LL, (1u << 1), &r);
    m->derate = dec_scaled((int64_t)get_bits(in, 48u, 8u), 0.0, 1.0, 0.004, 0.0, 0LL, 254LL, true, 255LL, (1u << 2), &r);
    m->derate_reasons = get_bits(in, 56u, 8u);
    return r;
}

semmc_result_t semmc_encode_ctrl_validity(const semmc_ctrl_validity_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 4u, enc_raw(m->v_speed, 15u, (1u << 0), &r));
    put_bits(b, 20u, 4u, enc_raw(m->v_ia, 15u, (1u << 1), &r));
    put_bits(b, 24u, 4u, enc_raw(m->v_ib, 15u, (1u << 2), &r));
    put_bits(b, 28u, 4u, enc_raw(m->v_ic, 15u, (1u << 3), &r));
    put_bits(b, 32u, 4u, enc_raw(m->v_vbus, 15u, (1u << 4), &r));
    put_bits(b, 36u, 4u, enc_raw(m->v_ibatt, 15u, (1u << 5), &r));
    put_bits(b, 40u, 4u, enc_raw(m->v_t_fet, 15u, (1u << 6), &r));
    put_bits(b, 44u, 4u, enc_raw(m->v_t_motor, 15u, (1u << 7), &r));
    put_bits(b, 48u, 4u, enc_raw(m->v_throttle, 15u, (1u << 8), &r));
    put_bits(b, 52u, 4u, enc_raw(m->v_sup_req, 15u, (1u << 9), &r));
    put_bits(b, 56u, 4u, enc_raw(m->v_sup_limits, 15u, (1u << 10), &r));
    put_bits(b, 60u, 4u, enc_raw(m->v_hall, 15u, (1u << 11), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_VALIDITY, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_validity(const uint8_t *in, uint8_t len, semmc_ctrl_validity_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_VALIDITY, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->v_speed = get_bits(in, 16u, 4u);
    m->v_ia = get_bits(in, 20u, 4u);
    m->v_ib = get_bits(in, 24u, 4u);
    m->v_ic = get_bits(in, 28u, 4u);
    m->v_vbus = get_bits(in, 32u, 4u);
    m->v_ibatt = get_bits(in, 36u, 4u);
    m->v_t_fet = get_bits(in, 40u, 4u);
    m->v_t_motor = get_bits(in, 44u, 4u);
    m->v_throttle = get_bits(in, 48u, 4u);
    m->v_sup_req = get_bits(in, 52u, 4u);
    m->v_sup_limits = get_bits(in, 56u, 4u);
    m->v_hall = get_bits(in, 60u, 4u);
    return r;
}

semmc_result_t semmc_encode_ctrl_energy_quality(const semmc_ctrl_energy_quality_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 24u, enc_scaled(m->integrated_s, 0.0, 167772.14, 0.01, 0.0, 0LL, 16777214LL, true, 16777215LL, 24u, (1u << 0), &r));
    put_bits(b, 40u, 24u, enc_scaled(m->gap_s, 0.0, 167772.14, 0.01, 0.0, 0LL, 16777214LL, true, 16777215LL, 24u, (1u << 1), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_ENERGY_QUALITY, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_energy_quality(const uint8_t *in, uint8_t len, semmc_ctrl_energy_quality_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_ENERGY_QUALITY, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->integrated_s = dec_scaled((int64_t)get_bits(in, 16u, 24u), 0.0, 167772.14, 0.01, 0.0, 0LL, 16777214LL, true, 16777215LL, (1u << 0), &r);
    m->gap_s = dec_scaled((int64_t)get_bits(in, 40u, 24u), 0.0, 167772.14, 0.01, 0.0, 0LL, 16777214LL, true, 16777215LL, (1u << 1), &r);
    return r;
}

semmc_result_t semmc_encode_csia_advisory(const semmc_csia_advisory_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 8u, enc_scaled(m->trust, 0.0, 1.0, 0.004, 0.0, 0LL, 254LL, true, 255LL, 8u, (1u << 0), &r));
    put_bits(b, 24u, 2u, enc_raw(m->mode, 3u, (1u << 1), &r));
    put_bits(b, 26u, 2u, enc_raw(m->observability, 3u, (1u << 2), &r));
    put_bits(b, 28u, 1u, m->monitor_ok ? 1u : 0u);
    put_bits(b, 29u, 1u, m->evidence_fresh ? 1u : 0u);
    put_bits(b, 30u, 2u, enc_raw(m->reserved, 3u, (1u << 5), &r));
    put_bits(b, 32u, 8u, enc_raw(m->evidence_mask, 255u, (1u << 6), &r));
    put_bits(b, 40u, 8u, enc_raw(m->explanation, 255u, (1u << 7), &r));
    put_bits(b, 48u, 16u, enc_raw(m->src_time_ms, 65535u, (1u << 8), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CSIA_ADVISORY, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_csia_advisory(const uint8_t *in, uint8_t len, semmc_csia_advisory_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CSIA_ADVISORY, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->trust = dec_scaled((int64_t)get_bits(in, 16u, 8u), 0.0, 1.0, 0.004, 0.0, 0LL, 254LL, true, 255LL, (1u << 0), &r);
    m->mode = get_bits(in, 24u, 2u);
    m->observability = get_bits(in, 26u, 2u);
    m->monitor_ok = get_bits(in, 28u, 1u) != 0u;
    m->evidence_fresh = get_bits(in, 29u, 1u) != 0u;
    m->reserved = get_bits(in, 30u, 2u);
    m->evidence_mask = get_bits(in, 32u, 8u);
    m->explanation = get_bits(in, 40u, 8u);
    m->src_time_ms = get_bits(in, 48u, 16u);
    return r;
}

semmc_result_t semmc_encode_ctrl_identity(const semmc_ctrl_identity_t *m, uint8_t out[8])
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    uint8_t b[8] = {0};
    b[1] = m->seq;
    put_bits(b, 16u, 4u, enc_raw(m->proto_major, 15u, (1u << 0), &r));
    put_bits(b, 20u, 4u, enc_raw(m->proto_minor, 15u, (1u << 1), &r));
    put_bits(b, 24u, 8u, enc_raw(m->fw_major, 255u, (1u << 2), &r));
    put_bits(b, 32u, 8u, enc_raw(m->fw_minor, 255u, (1u << 3), &r));
    put_bits(b, 40u, 16u, enc_raw(m->cal_version, 65535u, (1u << 4), &r));
    put_bits(b, 56u, 2u, enc_raw(m->cal_provenance, 3u, (1u << 5), &r));
    put_bits(b, 58u, 1u, m->build_is_sim ? 1u : 0u);
    put_bits(b, 59u, 5u, enc_raw(m->hw_rev, 31u, (1u << 7), &r));
    if (r.status != SEMMC_OK) { memset(out, 0, 8); return r; }
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_CTRL_IDENTITY, &b[1]);
    memcpy(out, b, 8);
    return r;
}

semmc_result_t semmc_decode_ctrl_identity(const uint8_t *in, uint8_t len, semmc_ctrl_identity_t *m)
{
    semmc_result_t r = {SEMMC_OK, 0u, 0u, 0u};
    if (len != 8u) { r.status = SEMMC_E_LEN; return r; }
    if (semmc_crc8_data_id(SEMMC_DATAID_CTRL_IDENTITY, &in[1]) != in[0]) { r.status = SEMMC_E_CRC; return r; }
    m->seq = in[1];
    m->proto_major = get_bits(in, 16u, 4u);
    m->proto_minor = get_bits(in, 20u, 4u);
    m->fw_major = get_bits(in, 24u, 8u);
    m->fw_minor = get_bits(in, 32u, 8u);
    m->cal_version = get_bits(in, 40u, 16u);
    m->cal_provenance = get_bits(in, 56u, 2u);
    m->build_is_sim = get_bits(in, 58u, 1u) != 0u;
    m->hw_rev = get_bits(in, 59u, 5u);
    return r;
}
