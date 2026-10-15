/* Protocol codec: generated golden vectors + malformed payload handling. */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc_protocol.h"

int semmc_golden_check(void);

static void test_golden_vectors(void)
{
    CHECK_EQ_INT(semmc_golden_check(), 0);
}

static void test_malformed_payloads(void)
{
    semmc_sup_torque_req_t m;
    uint8_t buf[8] = {0};
    semmc_sup_torque_req_t in = {3u, 0x5Au, 2u, false, 0u, 1.0f, 100u};
    CHECK(semmc_encode_sup_torque_req(&in, buf).status == SEMMC_OK);
    CHECK(semmc_decode_sup_torque_req(buf, 7u, &m).status == SEMMC_E_LEN);
    CHECK(semmc_decode_sup_torque_req(buf, 9u, &m).status == SEMMC_E_LEN);
    /* Same payload under another id (wrong Data ID) fails the CRC. */
    semmc_sup_limits_t l;
    CHECK(semmc_decode_sup_limits(buf, 8u, &l).status == SEMMC_E_CRC);
    /* All-zero and all-0xFF frames are rejected. */
    uint8_t z[8] = {0}, f[8];
    memset(f, 0xFF, 8);
    CHECK(semmc_decode_sup_torque_req(z, 8u, &m).status == SEMMC_E_CRC);
    CHECK(semmc_decode_sup_torque_req(f, 8u, &m).status == SEMMC_E_CRC);
}

static void test_nonfinite_encoding(void)
{
    uint8_t buf[8];
    /* NaN in a field with a sentinel => sentinel, flagged invalid. */
    semmc_sup_torque_req_t in = {1u, 1u, 0u, false, 0u, NAN, 0u};
    semmc_result_t r = semmc_encode_sup_torque_req(&in, buf);
    CHECK(r.status == SEMMC_OK);
    CHECK(r.invalid & SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM);
    semmc_sup_torque_req_t out;
    r = semmc_decode_sup_torque_req(buf, 8u, &out);
    CHECK(isnan(out.torque_Nm));
    CHECK(r.invalid & SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM);
    /* +Inf saturates (it is not NaN). */
    in.torque_Nm = INFINITY;
    r = semmc_encode_sup_torque_req(&in, buf);
    CHECK(r.saturated & SEMMC_F_SUP_TORQUE_REQ_TORQUE_NM);
    /* NaN in a field WITHOUT a sentinel: encoding refused, no frame emitted. */
    semmc_sup_limits_t lim = {1u, 1u, 1u, NAN, 10.0f};
    r = semmc_encode_sup_limits(&lim, buf);
    CHECK(r.status == SEMMC_E_NAN);
}

static void test_out_of_range_raw_flagged(void)
{
    /* throttle raw 20000 => 2.0 > max 1.0: decodes but is flagged. */
    uint8_t b[8] = {0};
    b[1] = 1u;
    b[2] = (uint8_t)(20000u & 0xFFu);
    b[3] = (uint8_t)(20000u >> 8);
    b[0] = semmc_crc8_data_id(SEMMC_DATAID_DRIVER_CONTROLS, &b[1]);
    semmc_driver_controls_t d;
    const semmc_result_t r = semmc_decode_driver_controls(b, 8u, &d);
    CHECK(r.status == SEMMC_OK);
    CHECK(r.out_of_range & SEMMC_F_DRIVER_CONTROLS_THROTTLE);
}

static void test_ids_form_one_64_number_block(void)
{
    const uint32_t ids[] = {SEMMC_ID_CTRL_FAULT, SEMMC_ID_SUP_TORQUE_REQ, SEMMC_ID_SUP_LIMITS, SEMMC_ID_SUP_HELLO,
                            SEMMC_ID_CTRL_STATUS, SEMMC_ID_CTRL_CMD_TRACE, SEMMC_ID_DRIVER_CONTROLS,
                            SEMMC_ID_CTRL_SESSION, SEMMC_ID_CTRL_MOTION, SEMMC_ID_CTRL_CURRENTS,
                            SEMMC_ID_CTRL_ENERGY, SEMMC_ID_CTRL_THERMAL, SEMMC_ID_CTRL_VALIDITY,
                            SEMMC_ID_CSIA_ADVISORY, SEMMC_ID_CTRL_IDENTITY};
    for (size_t k = 0; k < sizeof ids / sizeof ids[0]; k++) {
        CHECK(ids[k] >= 0x300u && ids[k] <= 0x33Fu); /* one 64-number block; bus base = supervision.can_id_base */
        CHECK(semmc_msg_index(ids[k]) >= 0);
    }
    CHECK(semmc_msg_index(0x210u) < 0); /* a foreign id (e.g. reference-project CHUDS front_aux) */
}

int main(void)
{
    RUN(test_golden_vectors);
    RUN(test_malformed_payloads);
    RUN(test_nonfinite_encoding);
    RUN(test_out_of_range_raw_flagged);
    RUN(test_ids_form_one_64_number_block);
    TEST_MAIN_END();
}
