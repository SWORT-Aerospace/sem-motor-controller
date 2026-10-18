/* Unit tests of the portable telematics firmware (host build). Run by ctest and by
 * tests/telematics/test_firmware_host.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tm_app.h"
#include "tm_crc32.h"
#include "tm_fakeflash.h"
#include "tm_le.h"
#include "tm_reset.h"
#include "tm_time.h"

static int g_fail, g_n;
#define CHECK(c)                                                                 \
    do {                                                                         \
        g_n++;                                                                   \
        if (!(c)) {                                                              \
            g_fail++;                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #c); \
        }                                                                        \
    } while (0)

static uint64_t g_now;
static uint64_t now_us(void) { return g_now; }
static bool g_high = true;
static bool line_high(uint8_t ch) { (void)ch; return g_high; }
static int g_masked;
static void mask(bool m) { g_masked += m ? 1 : -1; }

static void test_crc32(void)
{
    CHECK(tm_crc32(0u, (const uint8_t *)"123456789", 9) == 0xCBF43926u);   /* the CRC-32 check value */
    uint32_t c = tm_crc32(0u, (const uint8_t *)"1234", 4);
    CHECK(tm_crc32(c, (const uint8_t *)"56789", 5) == 0xCBF43926u);          /* running value */
}

static void test_time_extend(void)
{
    CHECK(tm_time_extend(0u, 5u, false) == 5u);
    CHECK(tm_time_extend(2u, 0xFFFFFFF0u, false) == ((2ull << 32) | 0xFFFFFFF0u));
    /* the counter wrapped, the update interrupt has not run yet: a small value is after the wrap */
    CHECK(tm_time_extend(2u, 10u, true) == ((3ull << 32) | 10u));
    /* a large value was captured just before the wrap */
    CHECK(tm_time_extend(2u, 0xFFFFFFF0u, true) == ((2ull << 32) | 0xFFFFFFF0u));
}

static void test_wheel(void)
{
    tm_wheel_acc_t a = {0};
    tm_wheel_rec_t r;
    tm_wheel_take(&a, 1, 1000u, true, &r);
    CHECK(r.n == 0 && r.t_us == 1000u && r.flags == (TM_WHEEL_FLAG_LINE_HIGH | TM_WHEEL_FLAG_HEARTBEAT) && r.rec_seq == 0);
    tm_wheel_edge(&a, 2000u);
    tm_wheel_edge(&a, 2500u);
    tm_wheel_edge(&a, 3100u);
    tm_wheel_overrun(&a);
    tm_wheel_take(&a, 1, 4000u, false, &r);
    CHECK(r.n == 3 && r.t_us == 3100u && r.span_us == 1100u && r.total == 3 && r.lost == 1 && r.rec_seq == 1);
    CHECK(r.flags == TM_WHEEL_FLAG_OVERRUN);
    uint8_t b[TM_WHEEL_BODY_BYTES];
    CHECK(tm_wheel_body(&r, b) == 16u);
    CHECK(b[0] == 1 && b[1] == TM_WHEEL_FLAG_OVERRUN && tm_rd16(b + 2) == 3 && tm_rd32(b + 4) == 1100u);
    CHECK(tm_rd32(b + 8) == 3u && tm_rd16(b + 12) == 1 && tm_rd16(b + 14) == 1);
    tm_wheel_take(&a, 1, 5000u, true, &r);
    CHECK(r.n == 0 && r.lost == 0 && r.total == 3 && !(r.flags & TM_WHEEL_FLAG_OVERRUN));
}

/* One record period on every channel: edges every period_us[ch] (0: none) up to t, line levels as given. */
static void wheel_step(tm_wheel_acc_t *acc, tm_wheel_track_t *tr, uint64_t *next, const uint32_t *period_us,
                       const bool *line_high, uint64_t t)
{
    for (unsigned ch = 0; ch < 3u; ch++) {
        while (period_us[ch] && next[ch] <= t) {
            tm_wheel_edge(&acc[ch], next[ch]);
            next[ch] += period_us[ch];
        }
        tm_wheel_rec_t r;
        tm_wheel_take(&acc[ch], (uint8_t)ch, t, line_high[ch], &r);
        tm_wheel_track_update(&tr[ch], &r);
    }
}

static void states(const tm_wheel_track_t *tr, uint64_t t, char *s)
{
    for (unsigned ch = 0; ch < 3u; ch++) s[ch] = (char)tm_wheel_classify(tr, 3u, ch, t, false, 0);
    s[3] = 0;
}

static void test_wheel_plausibility(void)
{
    tm_wheel_acc_t acc[3] = {{0}};
    tm_wheel_track_t tr[3];
    uint64_t next[3] = {0};
    char s[4];
    for (unsigned ch = 0; ch < 3u; ch++) tm_wheel_track_init(&tr[ch], 0u);
    /* ch0 turns (100 ms period); ch1 is shorted to ground (line low = active level, no edges);
     * ch2 is disconnected (pulled up: inactive level, no edges) */
    uint32_t per[3] = {100000u, 0u, 0u};
    bool high[3] = {true, false, true};
    next[0] = 50000u;
    uint64_t t = 0;
    for (t = 50000u; t <= 950000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(strcmp(s, "MNN") == 0);                    /* < 1 s: not yet enough evidence against ch1 and ch2 */
    for (; t <= 1500000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(strcmp(s, "MAI") == 0);                    /* a held line is not standstill while ch0 moves */
    int ref = 9;
    CHECK(tm_wheel_classify(tr, 3u, 1u, t - 50000u, false, &ref) == TM_WHEEL_SUSPECT_ACTIVE && ref == 0);
    CHECK(tm_wheel_classify(tr, 3u, 1u, t - 50000u, true, 0) == TM_WHEEL_SUSPECT_INACTIVE);  /* active-high sensor */
    /* everything stops: no channel contradicts any other; a held line proves nothing */
    per[0] = 0u;
    for (; t <= 2000000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(strcmp(s, "SNN") == 0);
    /* ch1 and ch2 recover and all three turn: moving everywhere */
    per[0] = per[1] = per[2] = 80000u;
    next[0] = next[1] = next[2] = t;
    for (; t <= 2500000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(strcmp(s, "MMM") == 0);
    /* ch0 stops with its line held low (a magnet under the sensor, or a short): suspect only after
     * 8 periods of the others and 1 s */
    per[0] = 0u;
    high[0] = false;
    uint64_t stop = t;
    for (; t <= stop + 800000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(s[0] == 'S' && s[1] == 'M' && s[2] == 'M');
    for (; t <= stop + 1300000u; t += 50000u) wheel_step(acc, tr, next, per, high, t);
    states(tr, t - 50000u, s);
    CHECK(strcmp(s, "AMM") == 0);
    /* a channel with one edge after a long gap has no period: it is no reference for the others */
    tm_wheel_track_t one[2];
    tm_wheel_track_init(&one[0], 0u);
    tm_wheel_track_init(&one[1], 0u);
    tm_wheel_rec_t r = {.t_us = 5000000u, .channel = 0, .flags = 0, .n = 1, .span_us = 0, .total = 1};
    tm_wheel_track_update(&one[0], &r);
    CHECK(one[0].period_us == 0u && one[0].ever);
    CHECK(tm_wheel_classify(one, 2u, 1u, 5100000u, false, 0) == TM_WHEEL_NEVER);
}

static void test_queue(void)
{
    static tm_queue_t q;
    tm_queue_init(&q);
    uint8_t body[TM_REC_MAX + 1] = {0};
    for (unsigned i = 0; i < TM_QUEUE_LEN; i++) CHECK(tm_queue_push(&q, i, 7, body, 4));
    CHECK(!tm_queue_push(&q, 999, 7, body, 4) && q.dropped == 1 && q.high_water == TM_QUEUE_LEN);
    CHECK(!tm_queue_push(&q, 1, 7, body, TM_REC_MAX + 1) && q.dropped == 2);
    CHECK(tm_queue_peek(&q)->t_us == 0u);
    tm_queue_pop(&q);
    CHECK(tm_queue_count(&q) == TM_QUEUE_LEN - 1 && tm_queue_peek(&q)->t_us == 1u);
    static tm_can_ring_t ring;
    tm_can_frame_t f = {.t_us = 5, .id_flags = 0x318, .len = 8}, out;
    for (unsigned i = 0; i < TM_CAN_RING_LEN; i++) CHECK(tm_can_ring_push(&ring, &f));
    CHECK(!tm_can_ring_push(&ring, &f) && ring.overrun == 1);
    CHECK(tm_can_ring_pop(&ring, &out) && out.id_flags == 0x318 && out.t_us == 5);
}

static void test_block(void)
{
    static tm_block_t b;
    tm_block_reset(&b);
    uint8_t body[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    CHECK(tm_block_fits(&b, 5000000u, 8));
    tm_block_add(&b, 5000000u, 11, body, 8, 0);
    CHECK(b.base_us == 4000000u);                       /* TM_BASE_SLACK_US before the first record */
    CHECK(tm_block_fits(&b, 4500000u, 8));              /* an older record still fits */
    CHECK(!tm_block_fits(&b, 3999999u, 8));             /* before the base: new block */
    tm_block_add(&b, 4500000u, 9, body, 8, 0);
    tm_block_finish(&b, 7u);
    CHECK(memcmp(b.buf, "BK", 2) == 0 && tm_rd32(b.buf + 2) == 7u && tm_rd16(b.buf + 14) == 28u);
    CHECK(tm_rd32(b.buf + 16) == tm_crc32(0u, b.buf + TM_BLOCK_HDR, 28u));
    CHECK(b.buf[TM_BLOCK_HDR] == 11 && tm_rd32(b.buf + TM_BLOCK_HDR + 2) == 1000000u);
    CHECK(b.buf[TM_BLOCK_HDR + 14] == 9 && tm_rd32(b.buf + TM_BLOCK_HDR + 16) == 500000u);
    CHECK(b.buf[TM_SLOT_BYTES - 1] == 0xFF);
    while (tm_block_fits(&b, 4500000u, 64)) tm_block_add(&b, 4500000u, 1, body, 0, 0);
    CHECK(b.used + 6u + 64u > TM_BLOCK_PAYLOAD);
    uint8_t slot[TM_SLOT_BYTES];
    const char *meta = "{\"run_id\":\"X\"}";
    CHECK(tm_stlg_header(slot, meta, strlen(meta)) == 14u + strlen(meta));
    CHECK(memcmp(slot, "STLG", 4) == 0 && tm_rd16(slot + 4) == 1 && tm_rd32(slot + 6) == strlen(meta));
}

static void test_reset(void)
{
    char s[64];
    tm_reset_cause(TM_RST_BOR | TM_RST_PIN, s, sizeof s);
    CHECK(strcmp(s, "BOR+PIN") == 0);
    tm_reset_cause(TM_RST_IWDG, s, sizeof s);
    CHECK(strcmp(s, "IWDG") == 0);
    tm_reset_cause(0u, s, sizeof s);
    CHECK(strcmp(s, "none") == 0);
}

#define SLOTS 8u
static uint8_t g_mem[SLOTS * TM_SLOT_BYTES];

static void fill_slot(tm_flashlog_t *fl, const uint8_t *img)
{
    CHECK(tm_flashlog_submit(fl, img, 3));
    for (int i = 0; i < 100000 && fl->has_pending; i++) {
        g_now += 100u;
        tm_flashlog_step(fl);
    }
    CHECK(!fl->has_pending);
}

static void test_flashlog(void)
{
    static tm_fakeflash_t ff;
    static tm_flashlog_t fl;
    static uint8_t img[TM_SLOT_BYTES];
    memset(g_mem, 0xFF, sizeof g_mem);
    tm_fakeflash_init(&ff, g_mem, sizeof g_mem, 8192u, 16u, now_us);
    tm_flashlog_init(&fl, &ff.io);
    CHECK(fl.next_slot == 0 && fl.sessions == 0 && fl.erased_until == 0u);
    tm_stlg_header(img, "{}", 2);
    fill_slot(&fl, img);
    CHECK(ff.erases == 1 && fl.next_slot == 1 && ff.violations == 0);
    memset(img, 0xAB, sizeof img);
    memcpy(img, "BK", 2);
    fill_slot(&fl, img);
    CHECK(ff.erases == 1 && fl.next_slot == 2);          /* same 8 KiB page: no second erase */
    fill_slot(&fl, img);
    CHECK(ff.erases == 2 && fl.next_slot == 3 && fl.blocks_written == 3);
    /* restart: the scan finds the session and the next free slot (mid-page, clean) */
    tm_flashlog_init(&fl, &ff.io);
    CHECK(fl.next_slot == 3 && fl.sessions == 1 && fl.erased_until == 4u * TM_SLOT_BYTES);
    /* a program error drops the slot's records and continues at the next page */
    ff.fail_next_program = 1;
    CHECK(tm_flashlog_submit(&fl, img, 5));
    for (int i = 0; i < 100 && fl.has_pending; i++) {
        g_now += 100u;
        tm_flashlog_step(&fl);
    }
    CHECK(fl.write_errors == 1 && fl.dropped_records == 5 && fl.next_slot == 4);
    fill_slot(&fl, img);
    fill_slot(&fl, img);
    fill_slot(&fl, img);
    fill_slot(&fl, img);
    CHECK(tm_flashlog_full(&fl) && fl.next_slot == SLOTS);
    CHECK(!tm_flashlog_submit(&fl, img, 9) && fl.dropped_records == 14);   /* full: counted, refused */
    /* a partly written slot (power loss while programming) is skipped at the next start */
    memset(g_mem, 0xFF, sizeof g_mem);
    memcpy(g_mem, "STLG", 4);
    memcpy(g_mem + TM_SLOT_BYTES, "BK", 2);              /* slot 1: header bytes written, rest erased */
    tm_flashlog_init(&fl, &ff.io);
    CHECK(fl.next_slot == 2 && fl.sessions == 1);
    memset(g_mem + 2u * TM_SLOT_BYTES + 100u, 0x00, 4); /* slot 2 has a stray programmed word */
    g_mem[2u * TM_SLOT_BYTES] = 0xFF;
    tm_flashlog_init(&fl, &ff.io);
    CHECK(fl.next_slot == 2);                            /* slot 2 starts with 0xFF: free per header ... */
    CHECK(fl.erased_until == 2u * TM_SLOT_BYTES);        /* ... at a page start: it is erased before use */
    memset(g_mem, 0xFF, sizeof g_mem);
    memcpy(g_mem, "STLG", 4);
    memset(g_mem + TM_SLOT_BYTES + 200u, 0x00, 4);       /* slot 1 (mid-page) not clean beyond its header */
    tm_flashlog_init(&fl, &ff.io);
    CHECK(fl.next_slot == 2 && fl.erased_until == 2u * TM_SLOT_BYTES);
}

static void test_app(void)
{
    static tm_fakeflash_t ff;
    static tm_app_t app;
    memset(g_mem, 0xFF, sizeof g_mem);
    g_now = 1000u;
    tm_fakeflash_init(&ff, g_mem, sizeof g_mem, 8192u, 16u, now_us);
    tm_platform_t pf = {.now_us = now_us, .line_high = line_high, .mask_capture = mask, .storage = &ff.io};
    tm_app_info_t info = {.unit_id = "T", .firmware = "test", .clock_source = "test", .storage = "ram",
                          .reset_flags = TM_RST_PIN, .reset_cause = "PIN", .wheel_circumference_mm = 1500u,
                          .wheel_ppr = 8u};
    tm_app_init(&app, &pf, &info);
    CHECK(app.boot == 1 && app.meta_len > 0 && strstr(app.meta, "\"wheel_circumference_m\":1.500") != 0);
    CHECK(strstr(app.meta, "\"run_id\":\"T-B0001\"") != 0 && tm_queue_count(&app.q) == 1);
    for (uint64_t t = 1000u; t < 3000000u; t += 250u) {
        g_now = t;
        if (t % 10000u == 0u) tm_app_wheel_edge(&app, 0, t);
        tm_app_poll(&app);
    }
    CHECK(g_masked == 0 && app.c.wheel_records >= 3u * 58u && app.wheel[0].total == 299u);
    CHECK(app.c.log_dropped_queue == 0 && app.fl.blocks_written >= 2u);   /* header + at least one block */
    tm_app_erase_log(&app);
    for (int i = 0; i < 1000 && tm_flashlog_erasing(&app.fl); i++) {
        g_now += 5000u;
        tm_app_poll(&app);
    }
    CHECK(!tm_flashlog_erasing(&app.fl) && app.fl.next_slot == 0u);
    char s[256];
    CHECK(tm_app_status(&app, s, sizeof s) > 20u && strncmp(s, "TM t=", 5) == 0);
}

void test_drivers(void);
extern int g_drv_fail;

/* Sparse logging: a small storage (16 slots, 2 in reserve) fills at the full rate; from the reserve on, the
 * wheel and counters records continue every 10 s and the rest is counted, not logged. */
static void test_app_sparse(void)
{
    static tm_fakeflash_t ff;
    static tm_app_t app;
    memset(g_mem, 0xFF, sizeof g_mem);
    g_now = 0u;
    tm_fakeflash_init(&ff, g_mem, 16u * TM_SLOT_BYTES, 8192u, 16u, now_us);
    tm_platform_t pf = {.now_us = now_us, .line_high = line_high, .mask_capture = mask, .storage = &ff.io};
    tm_app_info_t info = {.unit_id = "S", .firmware = "test", .clock_source = "test", .storage = "ram",
                          .reset_flags = TM_RST_PIN, .reset_cause = "PIN", .run_prefix = "S-NOR"};
    tm_app_init(&app, &pf, &info);
    CHECK(app.reserve_slots == 2u && strstr(app.meta, "\"run_id\":\"S-NOR-B0001\"") != 0);
    uint64_t t_sparse = 0u;
    uint32_t wr_at_sparse = 0u;
    uint8_t imu[8] = {0};
    for (uint64_t t = 250u; t <= 200000000u; t += 250u) {
        g_now = t;
        if (t % 1000u == 0u) tm_app_wheel_edge(&app, 0, t);          /* 1 kHz on wheel_0 */
        if (t % 10000u == 0u) (void)tm_app_record(&app, t, TM_REC_IMU, imu, 8u);   /* 100 Hz IMU */
        tm_app_poll(&app);
        if (app.sparse && !t_sparse) {
            t_sparse = t;
            wr_at_sparse = app.c.wheel_records;
        }
    }
    CHECK(t_sparse > 0u && t_sparse < 60000000u);                    /* the full-rate region filled first */
    CHECK(app.c.log_thinned > 100u * 100u);                          /* IMU records counted, not logged */
    uint32_t periods = (uint32_t)((200000000u - t_sparse) / 10000000u);
    uint32_t got = (app.c.wheel_records - wr_at_sparse) / 3u;
    CHECK(got + 1u >= periods && got <= periods + 1u);               /* one wheel record per channel per 10 s */
    CHECK(!tm_flashlog_full(&app.fl) && app.c.log_dropped_storage == 0u && app.q.dropped == 0u);
    char s[TM_STATUS_MAX];
    tm_app_status(&app, s, sizeof s);
    /* wheel_1 and wheel_2 are open (pulled up) while wheel_0 turns: suspect inactive, as on the bench */
    CHECK(strstr(s, "log=sparse") != 0 && strstr(s, "wheel=MII") != 0 && strstr(s, "left=?s") == 0);
    /* the worst case of every field still fits the status buffer */
    app.boot = 99999u;
    for (unsigned ch = 0; ch < 3u; ch++) app.wheel[ch].total = 0xFFFFFFFFu;
    app.c.wheel_edges_lost = app.c.log_thinned = app.c.rx_frames = app.q.high_water = app.q.dropped = 0xFFFFFFFFu;
    app.fl.dropped_records = app.can.overrun = 0xFFFFFFFFu;
    g_now = 0xFFFFFFFFFFFFull;
    char big[1024];
    size_t n = tm_app_status(&app, big, sizeof big);
    CHECK(n > 100u && n < TM_STATUS_MAX);
}

int main(void)
{
    test_crc32();
    test_time_extend();
    test_wheel();
    test_wheel_plausibility();
    test_app_sparse();
    test_queue();
    test_block();
    test_reset();
    test_flashlog();
    test_app();
    test_drivers();
    printf("%d checks, %d failed\n", g_n, g_fail);
    return (g_fail || g_drv_fail) ? 1 : 0;
}
