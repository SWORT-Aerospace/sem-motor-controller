/* Telematics firmware for the NUCLEO-U575ZI-Q: wheel edges (and, in the CAN image, the controller's
 * broadcast) to a persistent STLG log, on a W25Q NOR on SPI1 when one answers at start, else in internal
 * flash bank 2. Receive-only: nothing is transmitted on the vehicle bus. Not run on hardware; the bench
 * procedure is telematics/firmware/BENCH.md.
 *
 * UART commands (115200 8N1, line ending CR or LF): STATUS; DUMP (prints the used slots as hex, acquisition
 * paused while it runs); DUMP <first> <last> (those slots, preceded by the session header they belong to);
 * ERASE YES (erases the log storage, then restarts); HELP. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "board_u575.h"
#include "drivers_u575.h"
#include "stm32u5xx.h"
#include "tm_app.h"
#include "tm_imu.h"
#include "tm_le.h"
#include "tm_reset.h"
#include "tm_time.h"
#include "tm_w25q.h"

#ifndef TM_ENABLE_CAN
#define TM_ENABLE_CAN 0
#endif
#ifndef TM_GIT_REV
#define TM_GIT_REV "unknown"
#endif
#define TM_CAN_BITRATE 500000u   /* the semmc fixture's rate; the real one comes from the interface agreement */

tm_app_t g_app;
extern volatile uint32_t g_tim2_hi;
static tm_w25q_t g_nor;
static const tm_flash_if_t *g_log;          /* the storage in use: &g_nor.io or &g_flash_bank2 */

/* TIM2: capture on CH4 (wheel_0, PA3), CH3 (wheel_1, PA2), CH1 (wheel_2, PA0); update = 2^32 us overflow.
 * The capture registers are read first and the update flag after them, so a capture taken just after the
 * counter wrapped (small value, update flag already set) is placed after the wrap (tm_time_extend). */
void TIM2_IRQHandler(void);
void TIM2_IRQHandler(void)
{
    static const struct {
        uint32_t ccif, ccof;
        uint8_t ch;
    } M[3] = {{TIM_SR_CC4IF, TIM_SR_CC4OF, 0u}, {TIM_SR_CC3IF, TIM_SR_CC3OF, 1u}, {TIM_SR_CC1IF, TIM_SR_CC1OF, 2u}};
    uint32_t sr = TIM2->SR;
    uint32_t v[3] = {0u, 0u, 0u};
    if (sr & TIM_SR_CC4IF) v[0] = TIM2->CCR4;   /* reading CCRx clears CCxIF */
    if (sr & TIM_SR_CC3IF) v[1] = TIM2->CCR3;
    if (sr & TIM_SR_CC1IF) v[2] = TIM2->CCR1;
    bool ovf = (TIM2->SR & TIM_SR_UIF) != 0u;
    uint32_t hi = g_tim2_hi;
    uint32_t clear = 0u;
    for (unsigned k = 0; k < 3u; k++) {
        if (!(sr & M[k].ccif)) continue;
        tm_app_wheel_edge(&g_app, M[k].ch, tm_time_extend(hi, v[k], ovf));
        if (sr & M[k].ccof) {
            tm_app_wheel_overrun(&g_app, M[k].ch);
            clear |= M[k].ccof;
        }
    }
    if (ovf) {
        g_tim2_hi = hi + 1u;
        clear |= TIM_SR_UIF;
    }
    TIM2->SR = ~clear;                            /* rc_w0: zeros clear, ones leave the flag */
}

/* one slot as "S <k> <8192 hex digits>", read through the storage interface (internal flash or NOR) */
static void hex_slot(uint32_t k)
{
    static const char H[] = "0123456789abcdef";
    char buf[2 * 64 + 1];
    uint8_t p[64];
    char head[24];
    int n = snprintf(head, sizeof head, "S %lu ", (unsigned long)k);
    uart_write_blocking(head, (size_t)n);
    for (uint32_t off = 0; off < TM_SLOT_BYTES; off += 64u) {
        if (g_log->read(g_log->ctx, g_log->base + k * TM_SLOT_BYTES + off, p, sizeof p) != 0) memset(p, 0, sizeof p);
        for (uint32_t i = 0; i < 64u; i++) {
            buf[2u * i] = H[p[i] >> 4];
            buf[2u * i + 1u] = H[p[i] & 15u];
        }
        uart_write_blocking(buf, 128u);
    }
    uart_write_blocking("\r\n", 2u);
}

/* the session header at or before slot k (bounded: one 4-byte read per slot) */
static int64_t header_before(uint32_t k)
{
    for (int64_t s = k; s >= 0; s--) {
        uint8_t m[4];
        if (g_log->read(g_log->ctx, g_log->base + (uint32_t)s * TM_SLOT_BYTES, m, 4) == 0 && memcmp(m, "STLG", 4) == 0)
            return s;
        if ((k - (uint32_t)s) % 256u == 0u) board_kick_watchdog();
    }
    return -1;
}

static void command(const char *line)
{
    char s[TM_STATUS_MAX];
    if (strcmp(line, "STATUS") == 0) {
        tm_app_status(&g_app, s, sizeof s);
        uart_write(s);
        uart_write("\r\n");
    } else if (strcmp(line, "DUMP") == 0) {
        tm_app_request_flush(&g_app);
        uint64_t t_end = board_now_us() + 3000000u;
        while (!tm_app_idle(&g_app) && board_now_us() < t_end) {
            tm_app_poll(&g_app);
            board_kick_watchdog();
        }
        g_app.flush_requested = false;
        g_app.paused = true;
        snprintf(s, sizeof s, "DUMP BEGIN %lu\r\n", (unsigned long)g_log->slots);
        uart_write_blocking(s, strlen(s));
        for (uint32_t k = 0; k < g_app.fl.next_slot; k++) {
            hex_slot(k);
            board_kick_watchdog();
        }
        uart_write_blocking("DUMP END\r\n", 10u);
        g_app.paused = false;
    } else if (strncmp(line, "DUMP ", 5) == 0) {
        /* two decimal numbers; strtoul keeps the stdio input functions (and newlib's _read stub) out of the image */
        char *e1, *e2;
        unsigned long a = strtoul(line + 5, &e1, 10), b = e1 > line + 5 ? strtoul(e1, &e2, 10) : 0u;
        if (e1 == line + 5 || e2 == e1 || *e2 != '\0' || a > b || b >= g_app.fl.next_slot) {
            uart_write("DUMP <first> <last>: slots in use are 0 to next-1 (STATUS: slots=next/total)\r\n");
            return;
        }
        g_app.paused = true;
        snprintf(s, sizeof s, "DUMP BEGIN %lu\r\n", (unsigned long)g_log->slots);
        uart_write_blocking(s, strlen(s));
        int64_t h = header_before((uint32_t)a);
        if (h >= 0 && (uint32_t)h < a) hex_slot((uint32_t)h);
        for (uint32_t k = (uint32_t)a; k <= (uint32_t)b; k++) {
            hex_slot(k);
            board_kick_watchdog();
        }
        uart_write_blocking("DUMP END\r\n", 10u);
        g_app.paused = false;
    } else if (strcmp(line, "ERASE YES") == 0) {
        uart_write_blocking("ERASING the log storage, then restarting\r\n", 42u);
        g_app.paused = false;
        tm_app_erase_log(&g_app);
        while (tm_flashlog_erasing(&g_app.fl)) {
            tm_app_poll(&g_app);
            board_kick_watchdog();
        }
        NVIC_SystemReset();
    } else if (strcmp(line, "HELP") == 0) {
        uart_write("commands: STATUS, DUMP, DUMP <first> <last>, ERASE YES, HELP\r\n");
    } else if (line[0]) {
        uart_write("unknown command (HELP)\r\n");
    }
}

static uint64_t now_us(void) { return board_now_us(); }

int main(void)
{
    board_init();
    uart_init();
    board_capture_start();
    char uid[40], cause[96], clock[96];
    board_unit_id(uid, sizeof uid);
    size_t n = tm_reset_cause(g_board.reset_flags, cause, sizeof cause);
    if (g_board.last_fault != FAULT_NONE)
        snprintf(cause + n, sizeof cause - n, " after fault %lu", (unsigned long)g_board.last_fault);
    snprintf(clock, sizeof clock, "TIM2 1 MHz from MSIS 4 MHz, %s",
             g_board.lse_ok ? "PLL mode on the LSE (LSE accuracy)" : "untrimmed: LSE did not start (MSI accuracy)");
    /* storage: a W25Q NOR on SPI1 if one answers its JEDEC id, else internal flash bank 2. Each counts its own
     * sessions, so each has its own run-id prefix. */
    spi1_init();
    char uid_nor[56], store[96];
    snprintf(uid_nor, sizeof uid_nor, "%s-NOR", uid);
    bool nor_ok = tm_w25q_init(&g_nor, &g_spi1, 0u, 0u) == 0;
    g_log = nor_ok ? &g_nor.io : &g_flash_bank2;
    if (nor_ok)
        snprintf(store, sizeof store, "W25Q NOR on SPI1 (JEDEC %02x %02x %02x, %lu KiB, %lu slots)", g_nor.jedec[0],
                 g_nor.jedec[1], g_nor.jedec[2], (unsigned long)(g_nor.capacity / 1024u), (unsigned long)g_nor.io.slots);
    else if (g_board.flash_swapped)
        snprintf(store, sizeof store, "none: no W25Q NOR answered and option SWAP_BANK is set (internal log refused)");
    else
        snprintf(store, sizeof store, "internal flash bank 2 (0x08100000, 1 MiB, 256 slots): no W25Q NOR of 1 to 16 MiB answered");
    i2c1_init();
    static tm_imu_t imu;
    static tm_tmp117_t tmp[4];
    bool imu_ok = tm_imu_init(&imu, &g_i2c1, 0x6Au) == 0 || tm_imu_init(&imu, &g_i2c1, 0x6Bu) == 0;
    /* every TMP117 address (ADD0 to GND, V+, SDA, SCL: 0x48 to 0x4B); each one found is its own channel */
    unsigned n_tmp = 0;
    char tmp_json[96] = "{", tmp_desc[40] = "";
    for (uint8_t a = 0x48u; a <= 0x4Bu; a++) {
        if (tm_tmp117_init(&tmp[n_tmp], &g_i2c1, a) != 0) continue;
        size_t l = strlen(tmp_json);
        snprintf(tmp_json + l, sizeof tmp_json - l, "%s\"%u\":\"tmp117_%02x\"", n_tmp ? "," : "", n_tmp, a);
        l = strlen(tmp_desc);
        snprintf(tmp_desc + l, sizeof tmp_desc - l, "%s0x%02x", n_tmp ? " " : "", a);
        n_tmp++;
    }
    strncat(tmp_json, "}", sizeof tmp_json - strlen(tmp_json) - 1u);
    if (!n_tmp) snprintf(tmp_desc, sizeof tmp_desc, "none");
    char imu_desc[40];
    snprintf(imu_desc, sizeof imu_desc, "%s", imu_ok ? (imu.who == 0x6Cu ? "LSM6DSOX" : "ISM330DHCX") : "none");
    tm_platform_t pf = {.now_us = now_us, .line_high = board_wheel_line_high, .mask_capture = board_mask_capture,
                        .storage = g_log};
    tm_app_info_t info = {.unit_id = uid, .run_prefix = nor_ok ? uid_nor : uid,
                          .firmware = (TM_ENABLE_CAN ? "tm_u575_can " TM_GIT_REV : "tm_u575 " TM_GIT_REV),
                          .kind = "BENCH - telematics firmware on a NUCLEO-U575ZI-Q; not a vehicle run unless the "
                                  "bench record says so",
                          .clock_source = clock, .storage = store,
                          .reset_flags = g_board.reset_flags, .reset_cause = cause, .can_enabled = TM_ENABLE_CAN,
                          .wheel_circumference_mm = 0u, .wheel_ppr = 0u, .wheel_active_high = false,
                          .imu = imu_desc, .temp_channels_json = tmp_json};
    tm_app_init(&g_app, &pf, &info);
    bool ecc = g_board.last_fault == FAULT_NMI_ECC;
    if (ecc) g_app.paused = true;          /* leave the log alone until ERASE YES */
    const char *can = "off (not in this image)";
#if TM_ENABLE_CAN
    can = can_monitor_init(TM_CAN_BITRATE);
#endif
    char s[640];
    snprintf(s, sizeof s, "\r\ntelematics %s boot=%lu reset=%s\r\nclock: %s\r\nlog: %s, slot %lu of %lu%s\r\nCAN: %s\r\n"
             "IMU: %s, TMP117: %s\r\nchip: rev 0x%04x, fault record %s\r\n", info.firmware, (unsigned long)g_app.boot,
             cause, clock, store,
             (unsigned long)g_app.fl.next_slot, (unsigned long)g_log->slots,
             ecc ? " (PAUSED: flash ECC error; ERASE YES to clear)" : "", can, imu_desc, tmp_desc,
             (unsigned)g_board.rev_id, g_board.fault_record_kept ? "kept across reset" : "lost on reset (SRAM_RST = 0)");
    uart_write(s);
    uint64_t next_status = board_now_us() + 1000000u, next_imu = next_status, next_tmp = next_status;
    char line[32];
    unsigned ln = 0;
    bool led = false;
    for (;;) {
        tm_app_poll(&g_app);
        uint64_t t = board_now_us();
        if (imu_ok && t >= next_imu) {
            float a[3], g[3];
            if (tm_imu_read(&imu, a, g) == 1) {
                uint8_t b[8];
                uint32_t ax, gz;
                memcpy(&ax, &a[0], 4);   /* sensor x as longitudinal, z as yaw: the mounting decides */
                memcpy(&gz, &g[2], 4);
                tm_le32(b, ax);
                tm_le32(b + 4, gz);
                (void)tm_app_record(&g_app, t, TM_REC_IMU, b, 8u);
            }
            next_imu = t + 10000u;
        }
        if (n_tmp && t >= next_tmp) {
            for (unsigned k = 0; k < n_tmp; k++) {
                int16_t c = 0;
                int rc = tm_tmp117_read(&tmp[k], &c);
                /* status as stlg.TEMP_STATUS: 0 ok, 2 timeout, 4 bus error (no answer or a refused transfer) */
                uint8_t st = rc == 0 ? 0u : (rc == TM_BUS_TIMEOUT ? 2u : 4u);
                uint8_t b[4] = {(uint8_t)k, st, 0u, 0u};
                tm_le16(b + 2, (uint16_t)(rc == 0 ? c : -32768));
                (void)tm_app_record(&g_app, t, TM_REC_TEMP, b, 4u);
            }
            next_tmp = t + 1000000u;
        }
        if (t >= next_status) {
            tm_app_status(&g_app, s, sizeof s);
            uart_write(s);
#if TM_ENABLE_CAN
            char e[48];
            snprintf(e, sizeof e, " can_err=%lu can_hw_lost=%lu", (unsigned long)can_bus_errors(),
                     (unsigned long)can_hw_fifo_lost());
            uart_write(e);
#endif
            uart_write("\r\n");
            led = !led;
            board_led(0, led);
            next_status += 1000000u;
        }
        board_led(1, g_app.fl.has_pending);
        uart_poll();
        char c;
        while (uart_getc(&c)) {
            if (c == '\r' || c == '\n') {
                line[ln] = '\0';
                command(line);
                ln = 0;
            } else if (ln + 1u < sizeof line) {
                line[ln++] = c;
            }
        }
        board_kick_watchdog();
    }
}
