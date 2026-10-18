#include "event_log.h"

#define LOG_MAGIC 0x534D4C47u /* "SMLG" */
#define LOG_N 64u

typedef struct {
    uint32_t magic;
    uint32_t head;          /* next slot */
    uint32_t count;
    uint32_t boots;
    uint32_t now_ms;
    event_t e[LOG_N];
    uint32_t check;         /* magic ^ head ^ count ^ boots: rejects a log corrupted by the reset */
} log_t;

static log_t g_log __attribute__((section(".noinit")));

static uint32_t check_of(const log_t *l) { return l->magic ^ l->head ^ l->count ^ l->boots; }

void event_log_init(void)
{
    if (g_log.magic != LOG_MAGIC || g_log.check != check_of(&g_log) || g_log.head >= LOG_N || g_log.count > LOG_N) {
        g_log.magic = LOG_MAGIC;
        g_log.head = 0u;
        g_log.count = 0u;
        g_log.boots = 0u;
    }
    g_log.boots++;
    g_log.now_ms = 0u;
    g_log.check = check_of(&g_log);
}

void event_log_set_time(uint32_t t_ms) { g_log.now_ms = t_ms; }
uint32_t event_log_boot_count(void) { return g_log.boots; }

void event_log_add(uint16_t code, uint16_t a, uint32_t b)
{
    if (g_log.magic != LOG_MAGIC || g_log.head >= LOG_N) return;
    event_t *e = &g_log.e[g_log.head];
    e->t_ms = g_log.now_ms;
    e->code = code;
    e->a = a;
    e->b = b;
    g_log.head = (g_log.head + 1u) % LOG_N;
    if (g_log.count < LOG_N) g_log.count++;
    g_log.check = check_of(&g_log);
}

void event_log_record_fault(uint16_t code) { event_log_add(code, 0u, 0u); }

static void put_hex(void (*put)(const char *), uint32_t v, int digits)
{
    char b[9];
    for (int i = digits - 1; i >= 0; i--) {
        const uint32_t n = v & 0xFu;
        b[i] = (char)(n < 10u ? '0' + n : 'a' + n - 10u);
        v >>= 4u;
    }
    b[digits] = '\0';
    put(b);
}

void event_log_dump(void (*put)(const char *s))
{
    put("event log (oldest first): t_ms code a b\r\n");
    const uint32_t start = (g_log.head + LOG_N - g_log.count) % LOG_N;
    for (uint32_t i = 0; i < g_log.count; i++) {
        const event_t *e = &g_log.e[(start + i) % LOG_N];
        put_hex(put, e->t_ms, 8);
        put(" ");
        put_hex(put, e->code, 4);
        put(" ");
        put_hex(put, e->a, 4);
        put(" ");
        put_hex(put, e->b, 8);
        put("\r\n");
    }
}
