/* Telematics firmware for the NUCLEO-U575ZI-Q: wheel edges (and, in the CAN image, the controller's
 * broadcast) to a persistent STLG log in internal flash bank 2. Receive-only: nothing is transmitted on the
 * vehicle bus. Not run on hardware; the bench procedure is telematics/firmware/BENCH.md.
 *
 * UART commands (115200 8N1, line ending CR or LF): STATUS, DUMP (prints the log as hex; acquisition is
 * paused while it runs), ERASE YES (erases the log region, then restarts), HELP. */
#include <stdio.h>
#include <string.h>

#include "board_u575.h"
#include "drivers_u575.h"
#include "stm32u5xx.h"
#include "tm_app.h"
#include "tm_imu.h"
#include "tm_le.h"
#include "tm_reset.h"
#include "tm_time.h"

#ifndef TM_ENABLE_CAN
#define TM_ENABLE_CAN 0
#endif
#ifndef TM_GIT_REV
#define TM_GIT_REV "unknown"
#endif
#define TM_CAN_BITRATE 500000u   /* the semmc fixture's rate; the real one comes from the interface agreement */

tm_app_t g_app;
extern volatile uint32_t g_tim2_hi;

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

static void hex_slot(uint32_t k)
{
    static const char H[] = "0123456789abcdef";
    char buf[2 * 64 + 1];
    const uint8_t *p = (const uint8_t *)(g_flash_bank2.base + k * TM_SLOT_BYTES);
    char head[24];
    int n = snprintf(head, sizeof head, "S %lu ", (unsigned long)k);
    uart_write_blocking(head, (size_t)n);
    for (uint32_t off = 0; off < TM_SLOT_BYTES; off += 64u) {
        for (uint32_t i = 0; i < 64u; i++) {
            buf[2u * i] = H[p[off + i] >> 4];
            buf[2u * i + 1u] = H[p[off + i] & 15u];
        }
        uart_write_blocking(buf, 128u);
    }
    uart_write_blocking("\r\n", 2u);
}

static void command(const char *line)
{
    char s[200];
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
        snprintf(s, sizeof s, "DUMP BEGIN %lu\r\n", (unsigned long)g_flash_bank2.slots);
        uart_write_blocking(s, strlen(s));
        for (uint32_t k = 0; k < g_app.fl.next_slot; k++) {
            hex_slot(k);
            board_kick_watchdog();
        }
        uart_write_blocking("DUMP END\r\n", 10u);
        g_app.paused = false;
    } else if (strcmp(line, "ERASE YES") == 0) {
        uart_write_blocking("ERASING the log region, then restarting\r\n", 41u);
        g_app.paused = false;
        tm_app_erase_log(&g_app);
        while (tm_flashlog_erasing(&g_app.fl)) {
            tm_app_poll(&g_app);
            board_kick_watchdog();
        }
        NVIC_SystemReset();
    } else if (strcmp(line, "HELP") == 0) {
        uart_write("commands: STATUS, DUMP, ERASE YES, HELP\r\n");
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
    i2c1_init();
    static tm_imu_t imu;
    static tm_tmp117_t tmp;
    bool imu_ok = tm_imu_init(&imu, &g_i2c1, 0x6Au) == 0 || tm_imu_init(&imu, &g_i2c1, 0x6Bu) == 0;
    bool tmp_ok = tm_tmp117_init(&tmp, &g_i2c1, 0x48u) == 0;
    char imu_desc[40];
    snprintf(imu_desc, sizeof imu_desc, "%s", imu_ok ? (imu.who == 0x6Cu ? "LSM6DSOX" : "ISM330DHCX") : "none");
    tm_platform_t pf = {.now_us = now_us, .line_high = board_wheel_line_high, .mask_capture = board_mask_capture,
                        .storage = &g_flash_bank2};
    tm_app_info_t info = {.unit_id = uid, .firmware = (TM_ENABLE_CAN ? "tm_u575_can " TM_GIT_REV : "tm_u575 " TM_GIT_REV),
                          .clock_source = clock, .storage = "internal flash bank 2 (0x08100000, 1 MB)",
                          .reset_flags = g_board.reset_flags, .reset_cause = cause, .can_enabled = TM_ENABLE_CAN,
                          .wheel_circumference_mm = 0u, .wheel_ppr = 0u, .wheel_active_high = false,
                          .imu = imu_desc, .temp_channels_json = tmp_ok ? "{\"0\":\"tmp117_0\"}" : "{}"};
    tm_app_init(&g_app, &pf, &info);
    bool ecc = g_board.last_fault == FAULT_NMI_ECC;
    if (ecc) g_app.paused = true;          /* leave the log alone until ERASE YES */
    const char *can = "off (not in this image)";
#if TM_ENABLE_CAN
    can = can_monitor_init(TM_CAN_BITRATE);
#endif
    char s[640];
    snprintf(s, sizeof s, "\r\ntelematics %s boot=%lu reset=%s\r\nclock: %s\r\nlog: slot %lu of %lu%s\r\nCAN: %s\r\n"
             "IMU: %s, TMP117: %s\r\n", info.firmware, (unsigned long)g_app.boot, cause, clock,
             (unsigned long)g_app.fl.next_slot, (unsigned long)g_flash_bank2.slots,
             ecc ? " (PAUSED: flash ECC error; ERASE YES to clear)" : "", can, imu_desc, tmp_ok ? "yes" : "no");
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
        if (tmp_ok && t >= next_tmp) {
            int16_t c = 0;
            int rc = tm_tmp117_read(&tmp, &c);
            uint8_t b[4] = {0u, (uint8_t)(rc == 0 ? 0u : 1u), 0u, 0u};
            tm_le16(b + 2, (uint16_t)(rc == 0 ? c : -32768));
            (void)tm_app_record(&g_app, t, TM_REC_TEMP, b, 4u);
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
