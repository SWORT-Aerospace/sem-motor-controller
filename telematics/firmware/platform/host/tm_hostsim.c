/* Host simulator of the telematics firmware: the portable application (src/) with a simulated clock,
 * simulated line levels and a RAM flash, driven by a script on standard input. It runs the same code as
 * the target image except the register-level drivers (platform/u575), so the log it writes is what the
 * firmware's own logic writes for those inputs. It is not the target: interrupt timing, flash timing and
 * the peripherals are not modelled.
 *
 *   I <slots> <circumference_mm> <ppr> <image>  start (load <image> if it exists, else erased flash)
 *   E <t_us> <channel>                          a wheel edge at t (polls run up to t first)
 *   O <t_us> <channel>                          a capture overrun at t
 *   L <t_us> <channel> <0|1>                    line level from t on
 *   C <t_us> <id_flags hex> <data hex>          a received CAN frame at t
 *   S <t0_us> <t1_us>                           storage busy throughout [t0, t1)
 *   P <t_us>                                    run polls up to t
 *   R <t_us> <cause>                            restart at t without shutdown (RAM lost, flash kept)
 *   F                                           flush: run polls until everything queued is in the flash
 *   W                                           write the flash image
 *   Q                                           print the status line
 * Polls run every TM_HOST_POLL_US of simulated time. */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tm_app.h"
#include "tm_fakeflash.h"
#include "tm_reset.h"

#define TM_HOST_POLL_US 250u

static uint64_t g_now;
static bool g_line[TM_WHEEL_CHANNELS];
static uint64_t now_us(void) { return g_now; }
static bool line_high(uint8_t ch) { return g_line[ch]; }
static void mask_capture(bool m) { (void)m; }

static tm_app_t g_app;
static tm_fakeflash_t g_ff;
static uint8_t *g_mem;
static uint32_t g_size;
static char g_image[512];
static uint32_t g_circ, g_ppr;

static void start(uint32_t reset_flags, const char *cause)
{
    tm_platform_t pf = {.now_us = now_us, .line_high = line_high, .mask_capture = mask_capture, .storage = &g_ff.io};
    tm_app_info_t info = {.unit_id = "HOSTSIM-000000000000000000000000",
                          .firmware = "tm_hostsim (portable application on the host)",
                          .clock_source = "simulated, exact", .storage = "RAM model of internal flash bank 2",
                          .reset_flags = reset_flags, .reset_cause = cause, .can_enabled = true,
                          .wheel_circumference_mm = g_circ, .wheel_ppr = g_ppr, .wheel_active_high = false};
    tm_app_init(&g_app, &pf, &info);
}

static void run_to(uint64_t t)
{
    while (g_now + TM_HOST_POLL_US <= t) {
        g_now += TM_HOST_POLL_US;
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
    char line[512];
    for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) g_line[ch] = true;
    while (fgets(line, sizeof line, stdin)) {
        char op = line[0];
        uint64_t t, t1;
        unsigned ch, v;
        if (op == 'I') {
            unsigned slots;
            if (sscanf(line + 1, "%u %" SCNu32 " %" SCNu32 " %511s", &slots, &g_circ, &g_ppr, g_image) != 4) return 2;
            g_size = slots * TM_SLOT_BYTES;
            g_mem = malloc(g_size);
            memset(g_mem, 0xFF, g_size);
            FILE *f = fopen(g_image, "rb");
            if (f) {
                size_t got = fread(g_mem, 1, g_size, f);
                (void)got;
                fclose(f);
            }
            tm_fakeflash_init(&g_ff, g_mem, g_size, 8192u, 16u, now_us);
            start(TM_RST_BOR | TM_RST_PIN, "BOR+PIN");
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
            start(TM_RST_BOR, "BOR");
        } else if (op == 'F') {
            tm_app_request_flush(&g_app);
            for (int i = 0; i < 1000000 && !tm_app_idle(&g_app); i++) {
                g_now += TM_HOST_POLL_US;
                tm_app_poll(&g_app);
            }
            g_app.flush_requested = false;
        } else if (op == 'W') {
            write_image();
        } else if (op == 'Q') {
            char s[256];
            tm_app_status(&g_app, s, sizeof s);
            printf("%s\n", s);
        }
    }
    return 0;
}
