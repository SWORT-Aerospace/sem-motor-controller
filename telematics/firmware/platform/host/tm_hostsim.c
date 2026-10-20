/* Host simulator of the telematics firmware: the portable application (src/) with a simulated clock,
 * simulated line levels and a RAM flash, driven by a script on standard input. It runs the same code as
 * the target image except the register-level drivers (platform/u575) and the SPI transport (the W25Q model
 * stands for it), so the log it writes is what the
 * firmware's own logic writes for those inputs. It is not the target: interrupt timing, flash timing and
 * the peripherals are not modelled.
 *
 *   T <t_us>                                    start time, before I (default 0)
 *   I <slots> <circumference_mm> <ppr> <image> [internal|nor|norslow] [gnss]
 *                                               start (load <image> if it exists, else erased storage) on a
 *                                               model of internal flash (default) or of a W25Q NOR on SPI;
 *                                               gnss: the image has a GNSS receiver (the vehicle image)
 *   K <t_us> <type> <body hex>                  a record from a main-loop driver (IMU, temperature)
 *   E <t_us> <channel>                          a wheel edge at t (polls run up to t first)
 *   O <t_us> <channel>                          a capture overrun at t
 *   L <t_us> <channel> <0|1>                    line level from t on
 *   C <t_us> <id_flags hex> <data hex>          a received CAN frame at t
 *   G <t_us> <hex>                              bytes from the GNSS receiver's UART at t (tm_gnss)
 *   U <t_us>                                    a PPS edge captured at t
 *   Y <path> [imu] [temp <n>] [batt]           run the live summary (tm_live) from now on, publishing to <path>:
 *                                               one line per message, "<t_us> <seq> <json>"; the link is up
 *   N <t_us> <0|1>                              the link down (0) or up (1) from t
 *   S <t0_us> <t1_us>                           storage busy throughout [t0, t1)
 *   P <t_us>                                    run polls up to t
 *   R <t_us> <cause>                            restart at t without shutdown (RAM lost, flash kept)
 *   F                                           flush: run polls until everything queued is in the flash
 *   W                                           write the flash image
 *   Q                                           print the status line
 *   V                                           print the NOR model's counters (violations must stay 0)
 *   X                                           ERASE YES without the restart
 * Polls run every TM_HOST_POLL_US of simulated time. */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tm_app.h"
#include "tm_fakeflash.h"
#include "tm_fakew25q.h"
#include "tm_gnss.h"
#include "tm_live.h"
#include "tm_reset.h"
#include "tm_w25q.h"

#define TM_HOST_POLL_US 250u

static uint64_t g_now;
static bool g_line[TM_WHEEL_CHANNELS];
static uint64_t now_us(void) { return g_now; }
static bool line_high(uint8_t ch) { return g_line[ch]; }
static void mask_capture(bool m) { (void)m; }

static tm_app_t g_app;
static tm_fakeflash_t g_ff;
static tm_fakew25q_t g_nor;
static tm_w25q_t g_w25q;
static const tm_flash_if_t *g_io;
static bool g_is_nor;
static uint8_t *g_mem;
static uint32_t g_size;
static char g_image[512];
static uint32_t g_circ, g_ppr;
static tm_gnss_t g_gnss;
static bool g_gnss_on;                         /* GNSS counters only once the script feeds a GNSS */
static tm_live_t g_live;
static tm_live_cfg_t g_live_cfg;
static bool g_live_on, g_link_up = true;
static FILE *g_live_out;
static tm_app_info_t g_info;
static const char *const TEMP_NAMES[TM_LIVE_TEMP_MAX] = {"0", "1", "2", "3"};   /* as the log's default names */

static bool link_up(void *ctx, uint64_t now)
{
    (void)ctx;
    (void)now;
    return g_link_up;
}

static bool link_publish(void *ctx, const char *topic, const char *msg, uint32_t len, uint32_t seq)
{
    (void)ctx;
    (void)topic;
    fprintf(g_live_out, "%" PRIu64 " %" PRIu32 " %.*s\n", g_now, seq, (int)len, msg);
    return true;
}

static const tm_link_t g_link = {.ctx = 0, .up = link_up, .publish = link_publish};

static void start(uint32_t reset_flags, const char *cause)
{
    tm_platform_t pf = {.now_us = now_us, .line_high = line_high, .mask_capture = mask_capture, .storage = g_io};
    g_info = (tm_app_info_t){.unit_id = "HOSTSIM-000000000000000000000000",
                          .run_prefix = g_is_nor ? "HOSTSIM-000000000000000000000000-NOR" : 0,
                          .firmware = "tm_hostsim (portable application on the host)",
                          .kind = "HOST SIMULATION - the portable firmware code on a computer; not hardware",
                          .clock_source = "simulated, exact",
                          .storage = g_is_nor ? "RAM model of a W25Q NOR on SPI1" : "RAM model of internal flash bank 2",
                          .reset_flags = reset_flags, .reset_cause = cause, .can_enabled = true,
                          .wheel_circumference_mm = g_circ, .wheel_ppr = g_ppr, .wheel_active_high = false,
                          .gnss_enabled = g_gnss_on};
    tm_app_init(&g_app, &pf, &g_info);
    if (g_live_on) tm_live_init(&g_live, &g_app, &g_info, &g_live_cfg);
}

static void run_to(uint64_t t)
{
    while (g_now + TM_HOST_POLL_US <= t) {
        g_now += TM_HOST_POLL_US;
        if (g_gnss_on) tm_gnss_tick(&g_gnss, &g_app, g_now);
        if (g_live_on) tm_live_tick(&g_live, &g_app, g_gnss_on ? &g_gnss : 0, &g_link, g_now);
        tm_app_poll(&g_app);
    }
    if (t > g_now) g_now = t;
}

static void write_image(void)
{
    FILE *f = fopen(g_image, "wb");
    if (!f || fwrite(g_mem, 1, g_size, f) != g_size) {
        fprintf(stderr, "cannot write %s\n", g_image);
        exit(1);
    }
    fclose(f);
}

int main(void)
{
    char line[640];
    tm_gnss_init(&g_gnss);
    for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) g_line[ch] = true;
    while (fgets(line, sizeof line, stdin)) {
        char op = line[0];
        uint64_t t, t1;
        unsigned ch, v;
        if (op == 'T' && sscanf(line + 1, "%" SCNu64, &t) == 1) {
            g_now = t;                                 /* start time (before I): e.g. just below 2^32 us */
        } else if (op == 'I') {
            unsigned slots;
            char kind[16] = "internal", opt[16] = "";
            if (sscanf(line + 1, "%u %" SCNu32 " %" SCNu32 " %511s %15s %15s", &slots, &g_circ, &g_ppr, g_image, kind,
                       opt) < 4)
                return 2;
            if (strcmp(opt, "gnss") == 0) g_gnss_on = true;
            g_size = slots * TM_SLOT_BYTES;
            g_mem = malloc(g_size);
            memset(g_mem, 0xFF, g_size);
            FILE *f = fopen(g_image, "rb");
            if (f) {
                size_t got = fread(g_mem, 1, g_size, f);
                (void)got;
                fclose(f);
            }
            g_is_nor = strncmp(kind, "nor", 3) == 0;
            if (g_is_nor) {
                /* "nor" typical timings, "norslow" 400 ms sector erase, 3 ms page program */
                tm_fakew25q_init(&g_nor, g_mem, g_size, 0x18u, now_us);
                if (strcmp(kind, "norslow") == 0) {
                    g_nor.sector_erase_us = 400000u;
                    g_nor.page_program_us = 3000u;
                }
                if (tm_w25q_init(&g_w25q, &g_nor.spi, 0u, slots) != 0) return 3;
                g_io = &g_w25q.io;
            } else {
                tm_fakeflash_init(&g_ff, g_mem, g_size, 8192u, 16u, now_us);
                g_io = &g_ff.io;
            }
            start(TM_RST_BOR | TM_RST_PIN, "BOR+PIN");
        } else if (op == 'K') {
            /* a record from a main-loop driver (IMU, temperature): K <t_us> <type> <body hex> */
            char hex[200] = {0};
            unsigned type;
            if (sscanf(line + 1, "%" SCNu64 " %u %199s", &t, &type, hex) != 3) return 2;
            run_to(t);
            uint8_t body[TM_REC_MAX];
            uint32_t len = (uint32_t)(strlen(hex) / 2u);
            if (len > TM_REC_MAX) return 2;
            for (uint32_t i = 0; i < len; i++) {
                unsigned b;
                sscanf(hex + 2u * i, "%2x", &b);
                body[i] = (uint8_t)b;
            }
            (void)tm_app_record(&g_app, t, (uint8_t)type, body, len);
        } else if (op == 'E' && sscanf(line + 1, "%" SCNu64 " %u", &t, &ch) == 2) {
            run_to(t);
            tm_app_wheel_edge(&g_app, (uint8_t)ch, t);
        } else if (op == 'O' && sscanf(line + 1, "%" SCNu64 " %u", &t, &ch) == 2) {
            run_to(t);
            tm_app_wheel_overrun(&g_app, (uint8_t)ch);
        } else if (op == 'L' && sscanf(line + 1, "%" SCNu64 " %u %u", &t, &ch, &v) == 3) {
            run_to(t);
            g_line[ch] = v != 0u;
        } else if (op == 'C') {
            char hex[160] = {0};
            unsigned idf;
            if (sscanf(line + 1, "%" SCNu64 " %x %159s", &t, &idf, hex) < 2) return 2;
            run_to(t);
            tm_can_frame_t f = {.t_us = t, .id_flags = idf, .len = (uint8_t)(strlen(hex) / 2u)};
            for (unsigned i = 0; i < f.len && i < 64u; i++) {
                unsigned b;
                sscanf(hex + 2u * i, "%2x", &b);
                f.data[i] = (uint8_t)b;
            }
            (void)tm_app_can_frame(&g_app, &f);
        } else if (op == 'G') {
            char hex[512] = {0};
            if (sscanf(line + 1, "%" SCNu64 " %511s", &t, hex) != 2) return 2;
            run_to(t);
            g_gnss_on = true;
            for (size_t i = 0; i + 1u < strlen(hex); i += 2u) {
                unsigned b;
                sscanf(hex + i, "%2x", &b);
                tm_gnss_rx(&g_gnss, &g_app, t, (uint8_t)b);
            }
        } else if (op == 'U' && sscanf(line + 1, "%" SCNu64, &t) == 1) {
            run_to(t);
            g_gnss_on = true;
            tm_gnss_pps(&g_gnss, t);
        } else if (op == 'Y') {
            char path[512] = {0}, rest[128] = {0};
            if (sscanf(line + 1, "%511s %127[^\n]", path, rest) < 1) return 2;
            g_live_out = fopen(path, "w");
            if (!g_live_out) return 4;
            g_live_cfg = (tm_live_cfg_t){.gnss = true, .imu = strstr(rest, "imu") != 0, .batt = strstr(rest, "batt") != 0};
            const char *tp = strstr(rest, "temp ");
            g_live_cfg.n_temp = tp ? (uint8_t)atoi(tp + 5) : 0u;
            for (uint8_t k = 0; k < TM_LIVE_TEMP_MAX; k++) g_live_cfg.temp_names[k] = TEMP_NAMES[k];
            g_live_on = true;
            tm_live_init(&g_live, &g_app, &g_info, &g_live_cfg);
        } else if (op == 'N' && sscanf(line + 1, "%" SCNu64 " %u", &t, &v) == 2) {
            run_to(t);
            g_link_up = v != 0u;
        } else if (op == 'S' && sscanf(line + 1, "%" SCNu64 " %" SCNu64, &t, &t1) == 2) {
            g_ff.stall_t0 = t;
            g_ff.stall_t1 = t1;
        } else if (op == 'P' && sscanf(line + 1, "%" SCNu64, &t) == 1) {
            run_to(t);
        } else if (op == 'R' && sscanf(line + 1, "%" SCNu64, &t) == 1) {
            run_to(t);
            /* restart: everything in RAM is lost (queue, open block, a slot not yet fully programmed) */
            printf("LOST %" PRIu32 " %" PRIu32 "\n", tm_queue_count(&g_app.q) + g_app.blk_records,
                   g_app.fl.has_pending ? g_app.fl.pend_records : 0u);
            if (g_is_nor) {                            /* power loss: the part's operation stops, WEL clears */
                g_nor.busy_until = 0u;
                g_nor.wel = false;
            }
            start(TM_RST_BOR, "BOR");
            tm_gnss_init(&g_gnss);
        } else if (op == 'F') {
            tm_app_request_flush(&g_app);
            for (int i = 0; i < 1000000 && !tm_app_idle(&g_app); i++) {
                g_now += TM_HOST_POLL_US;
                tm_app_poll(&g_app);
            }
            g_app.flush_requested = false;
        } else if (op == 'W') {
            if (g_live_out) fflush(g_live_out);
            write_image();
        } else if (op == 'Q') {
            char s[TM_STATUS_MAX];
            tm_app_status(&g_app, s, sizeof s);
            printf("%s\n", s);
        } else if (op == 'V') {
            printf("NOR violations=%" PRIu32 " erases=%" PRIu32 " programs=%" PRIu32 " chip_erases=%" PRIu32 "\n",
                   g_nor.violations, g_nor.erases, g_nor.programs, g_nor.chip_erases);
        } else if (op == 'X') {
            run_to(g_now);
            tm_app_erase_log(&g_app);                  /* ERASE YES, without the restart */
            for (int i = 0; i < 100000000 && tm_flashlog_erasing(&g_app.fl); i++) {
                g_now += TM_HOST_POLL_US;
                tm_app_poll(&g_app);
            }
        }
    }
    return 0;
}
