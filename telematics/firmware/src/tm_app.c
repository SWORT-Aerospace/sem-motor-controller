#include "tm_app.h"

#include <stdio.h>
#include <string.h>

#include "tm_le.h"

/* every record must fit the queue's record slot, or it would be refused and counted as dropped */
_Static_assert(1u + 5u * TM_CNT_ITEMS <= TM_REC_MAX, "COUNTERS2 body larger than TM_REC_MAX");
_Static_assert(5u + 64u <= TM_REC_MAX, "CAN2 FD body larger than TM_REC_MAX");

static void counters_body(const tm_counters_t *c, uint8_t *out, uint32_t *len)
{
    const struct {
        uint8_t id;
        uint32_t v;
    } items[] = {
        {TM_CNT_RX_FRAMES, c->rx_frames},
        {TM_CNT_LOG_RECORDS, c->log_records},
        {TM_CNT_LOG_DROPPED_QUEUE, c->log_dropped_queue},
        {TM_CNT_LOG_DROPPED_STORAGE, c->log_dropped_storage},
        {TM_CNT_QUEUE_HIGH_WATER, c->queue_high_water},
        {TM_CNT_WHEEL_EDGES_LOST, c->wheel_edges_lost},
        {TM_CNT_WHEEL_RECORDS, c->wheel_records},
        {TM_CNT_STORAGE_BLOCKS_WRITTEN, c->storage_blocks_written},
        {TM_CNT_STORAGE_STALL_EVENTS, c->storage_stall_events},
        {TM_CNT_CAN_RX_OVERRUN, c->can_rx_overrun},
        {TM_CNT_CAN_BUS_ERRORS, c->can_bus_errors},
        {TM_CNT_LOG_QUEUE_CAPACITY, TM_QUEUE_LEN},
        {TM_CNT_STORAGE_WRITE_ERRORS, c->storage_write_errors},
        {TM_CNT_UPTIME_S, c->uptime_s},
        {TM_CNT_WHEEL_SUSPECT_ACTIVE, c->wheel_suspect_active},
        {TM_CNT_WHEEL_SUSPECT_INACTIVE, c->wheel_suspect_inactive},
        {TM_CNT_LOG_THINNED, c->log_thinned},
        {TM_CNT_CAN_NOT_LOGGED, c->can_not_logged},
    };
    const uint32_t n = sizeof items / sizeof items[0];
    _Static_assert(sizeof items / sizeof items[0] == TM_CNT_ITEMS, "TM_CNT_ITEMS out of date");
    out[0] = (uint8_t)n;
    for (uint32_t i = 0; i < n; i++) {
        out[1u + 5u * i] = items[i].id;
        tm_le32(out + 2u + 5u * i, items[i].v);
    }
    *len = 1u + 5u * n;
}

static void sync_counters(tm_app_t *app)
{
    app->c.log_dropped_queue = app->q.dropped;
    app->c.queue_high_water = app->q.high_water;
    app->c.can_rx_overrun = app->can.overrun;
    app->c.log_dropped_storage = app->fl.dropped_records;
    app->c.storage_blocks_written = app->fl.blocks_written;
    app->c.storage_write_errors = app->fl.write_errors;
}

void tm_app_init(tm_app_t *app, const tm_platform_t *pf, const tm_app_info_t *info)
{
    memset(app, 0, sizeof *app);
    app->pf = *pf;
    tm_queue_init(&app->q);
    tm_block_reset(&app->blk);
    tm_flashlog_init(&app->fl, pf->storage);
    app->boot = app->fl.sessions + 1u;
    app->slot0 = app->fl.next_slot;
    app->mode_t0_us = app->t0_us;
    app->reserve_slots = pf->storage->slots / 8u;
    if (app->reserve_slots > TM_RESERVE_SLOTS) app->reserve_slots = TM_RESERVE_SLOTS;
    app->t0_us = pf->now_us();
    app->next_wheel_us = app->t0_us + TM_WHEEL_RECORD_PERIOD_US;
    app->wheel_active_high = info->wheel_active_high;
    for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) {
        tm_wheel_track_init(&app->track[ch], app->t0_us);
        app->wheel_state[ch] = (char)TM_WHEEL_NEVER;
    }
    app->next_counters_us = app->t0_us + TM_COUNTERS_PERIOD_US;
    char circ[24], ppr[16];
    if (info->wheel_circumference_mm)
        snprintf(circ, sizeof circ, "%lu.%03lu", (unsigned long)(info->wheel_circumference_mm / 1000u),
                 (unsigned long)(info->wheel_circumference_mm % 1000u));
    else
        snprintf(circ, sizeof circ, "null");
    if (info->wheel_ppr)
        snprintf(ppr, sizeof ppr, "%lu", (unsigned long)info->wheel_ppr);
    else
        snprintf(ppr, sizeof ppr, "null");
    int n = snprintf(
        app->meta, sizeof app->meta,
        "{\"boot\":%lu,\"clock\":{\"domain\":\"telematics\",\"source\":\"%s\",\"unit\":\"us\",\"utc_from\":\"%s\"},\"controller_adapter\":{\"id\":\"%s\"},\"firmware\":\"%s\",\"format\":{\"block_payload_bytes\":%u,"
        "\"name\":\"STLG\",\"slot_bytes\":%u,\"version\":1},\"kind\":\"%s\",\"reset\":{\"cause\":\"%s\",\"flags\":%lu},"
        "\"run_id\":\"%s-B%04lu\","
        "\"sensors\":{\"imu\":\"%s\",\"temp_channels\":%s,\"wheel_active_high\":%s,\"wheel_channels\":{\"0\":\"wheel_0\",\"1\":\"wheel_1\","
        "\"2\":\"wheel_2\"},\"wheel_circumference_m\":%s,\"wheel_ppr\":%s,\"wheel_record_period_s\":0.%03lu},\"storage\":\"%s\","
        "\"transmits\":\"nothing: receive-only firmware%s\",\"unit_id\":\"%s\"}",
        (unsigned long)app->boot, info->clock_source,
        info->gnss_enabled ? "logged PPS edges" : "none: no GNSS in this image", info->can_enabled ? "semmc-sim-fixture" : "none", info->firmware,
        (unsigned)TM_BLOCK_PAYLOAD, (unsigned)TM_SLOT_BYTES,
        info->kind ? info->kind : "UNKNOWN - the platform did not state what produced this log", info->reset_cause,
        (unsigned long)info->reset_flags,
        info->run_prefix ? info->run_prefix : info->unit_id, (unsigned long)app->boot, info->imu ? info->imu : "none",
        info->temp_channels_json ? info->temp_channels_json : "{}", info->wheel_active_high ? "true" : "false", circ, ppr,
        (unsigned long)(TM_WHEEL_RECORD_PERIOD_US / 1000u), info->storage,
        info->can_enabled ? " (FDCAN1 in bus-monitoring mode: no acknowledge, no error frames)" : "", info->unit_id);
    app->meta_len = (n > 0 && (size_t)n < sizeof app->meta) ? (size_t)n : 0u;
    app->header_pending = tm_stlg_header(app->header, app->meta, app->meta_len) != 0u;
    uint8_t body[9 + 64];
    size_t cl = strlen(info->reset_cause);
    if (cl > 64u) cl = 64u;
    tm_le32(body, app->boot);
    tm_le32(body + 4, info->reset_flags);
    body[8] = (uint8_t)cl;
    memcpy(body + 9, info->reset_cause, cl);
    (void)tm_queue_push(&app->q, app->t0_us, TM_REC_BOOT, body, 9u + (uint32_t)cl);
}

bool tm_app_can_frame(tm_app_t *app, const tm_can_frame_t *f) { return tm_can_ring_push(&app->can, f); }

void tm_app_set_tap(tm_app_t *app, tm_tap_fn fn, void *ctx)
{
    app->tap = fn;
    app->tap_ctx = ctx;
}

static inline void tap(const tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len)
{
    if (app->tap) app->tap(app->tap_ctx, app, t_us, type, body, len);
}

bool tm_app_record(tm_app_t *app, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len)
{
    tap(app, t_us, type, body, len);
    if (app->sparse) {
        app->c.log_thinned++;
        return false;
    }
    return tm_queue_push(&app->q, t_us, type, body, len);
}

static void enter_sparse(tm_app_t *app, uint64_t now)
{
    static const char text[] = "sparse logging: storage reserve reached; wheel and counters every 10 s, rest thinned";
    _Static_assert(sizeof text <= TM_REC_MAX, "event text longer than a record");
    uint8_t body[sizeof text];
    body[0] = 2u;                                  /* event code 2: sparse logging */
    memcpy(body + 1, text, sizeof text - 1u);
    app->sparse = true;
    app->slot0 = app->fl.next_slot;              /* the time-left estimate restarts at the sparse rate */
    app->mode_t0_us = now;
    (void)tm_queue_push(&app->q, now, TM_REC_EVENT, body, (uint32_t)(sizeof text));
}

static bool submit_block(tm_app_t *app)
{
    if (!app->blk.open) return true;
    if (!tm_flashlog_ready(&app->fl) && !tm_flashlog_full(&app->fl)) return false;
    tm_block_finish(&app->blk, app->block_seq);
    if (tm_flashlog_submit(&app->fl, app->blk.buf, app->blk_records)) app->block_seq++;
    /* full storage: submit counted the records as dropped; the block is released either way */
    tm_block_reset(&app->blk);
    app->blk_records = 0u;
    return true;
}

void tm_app_poll(tm_app_t *app)
{
    const uint64_t now = app->pf.now_us();
    tm_can_frame_t f;
    while (tm_can_ring_pop(&app->can, &f)) {
        uint8_t body[5 + 64];
        uint32_t len = f.len > 64u ? 64u : f.len;
        tm_le32(body, f.id_flags);
        body[4] = (uint8_t)len;
        memcpy(body + 5, f.data, len);
        app->c.rx_frames++;
        tap(app, f.t_us, TM_REC_CAN2, body, 5u + len);
        if (app->sparse)
            app->c.log_thinned++;
        else if (tm_queue_count(&app->q) >= TM_QUEUE_LEN - TM_QUEUE_OWN_RESERVE)
            app->c.can_not_logged++;          /* the rest of the queue is kept for the unit's own records */
        else
            (void)tm_queue_push(&app->q, f.t_us, TM_REC_CAN2, body, 5u + len);
    }
    if (!app->sparse && app->reserve_slots && tm_flashlog_free_slots(&app->fl) <= app->reserve_slots &&
        !tm_flashlog_erasing(&app->fl))
        enter_sparse(app, now);
    const uint64_t wheel_period = app->sparse ? TM_SPARSE_PERIOD_US : TM_WHEEL_RECORD_PERIOD_US;
    const uint64_t counters_period = app->sparse ? TM_SPARSE_PERIOD_US : TM_COUNTERS_PERIOD_US;
    if (now >= app->next_wheel_us) {
        for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) {
            tm_wheel_rec_t r;
            bool high = app->pf.line_high(ch);
            app->pf.mask_capture(true);
            tm_wheel_take(&app->wheel[ch], ch, now, high, &r);
            app->pf.mask_capture(false);
            uint8_t body[TM_WHEEL_BODY_BYTES];
            tm_wheel_body(&r, body);
            app->c.wheel_records++;
            app->c.wheel_edges_lost += r.lost;
            tm_wheel_track_update(&app->track[ch], &r);
            tap(app, r.t_us, TM_REC_WHEEL_EDGES, body, TM_WHEEL_BODY_BYTES);
            (void)tm_queue_push(&app->q, r.t_us, TM_REC_WHEEL_EDGES, body, TM_WHEEL_BODY_BYTES);
        }
        for (uint8_t ch = 0; ch < TM_WHEEL_CHANNELS; ch++) {
            char s = (char)tm_wheel_classify(app->track, TM_WHEEL_CHANNELS, ch, now, app->wheel_active_high, 0);
            if (s != app->wheel_state[ch]) {
                if (s == (char)TM_WHEEL_SUSPECT_ACTIVE) app->c.wheel_suspect_active++;
                if (s == (char)TM_WHEEL_SUSPECT_INACTIVE) app->c.wheel_suspect_inactive++;
                app->wheel_state[ch] = s;
            }
        }
        app->next_wheel_us += wheel_period;
        if (now >= app->next_wheel_us) app->next_wheel_us = now + wheel_period;   /* fell behind */
    }
    if (now >= app->next_counters_us) {
        sync_counters(app);
        app->c.uptime_s = (uint32_t)((now - app->t0_us) / 1000000u);
        uint8_t body[1u + 5u * TM_CNT_ITEMS];
        uint32_t len;
        counters_body(&app->c, body, &len);
        (void)tm_queue_push(&app->q, now, TM_REC_COUNTERS2, body, len);
        app->next_counters_us += counters_period;
        if (now >= app->next_counters_us) app->next_counters_us = now + counters_period;
    }
    if (app->paused || tm_flashlog_erasing(&app->fl)) {
        tm_flashlog_step(&app->fl);
        sync_counters(app);
        return;
    }
    if (app->header_pending && tm_flashlog_submit(&app->fl, app->header, 0u)) app->header_pending = false;
    for (uint32_t k = 0; k < TM_POLL_RECORDS && !app->header_pending; k++) {
        const tm_rec_t *r = tm_queue_peek(&app->q);
        if (r == 0) break;
        if (!tm_block_fits(&app->blk, r->t_us, r->len)) {
            if (!submit_block(app)) {          /* the storage still writes the previous slot */
                if (!app->stalled) app->c.storage_stall_events++;
                app->stalled = true;
                break;
            }
        }
        app->stalled = false;
        tm_block_add(&app->blk, r->t_us, r->type, r->body, r->len, now);
        app->blk_records++;
        app->c.log_records++;
        tm_queue_pop(&app->q);
    }
    if (app->blk.open && (now - app->blk.opened_us >= (app->sparse ? TM_SPARSE_FLUSH_US : TM_BLOCK_FLUSH_US) ||
                          (app->flush_requested && tm_queue_count(&app->q) == 0u)))
        (void)submit_block(app);
    tm_flashlog_step(&app->fl);
    sync_counters(app);
}

size_t tm_app_status(const tm_app_t *app, char *out, size_t cap)
{
    const uint64_t now = app->pf.now_us();
    const uint64_t t = now - app->t0_us;
    /* recording time left at the rate of the current mode so far: free slots x seconds per used slot */
    char left[24] = "?";
    uint32_t used = app->fl.next_slot > app->slot0 ? app->fl.next_slot - app->slot0 : 0u;
    uint64_t span = now - app->mode_t0_us;
    if (used >= 1u && span >= 1000000u)
        snprintf(left, sizeof left, "%lu", (unsigned long)((uint64_t)tm_flashlog_free_slots(&app->fl) *
                                                            (span / 1000000u) / used));
    int n = snprintf(out, cap,
                     "TM t=%lu.%03lu s tov=%lu boot=%lu edges=%lu/%lu/%lu wheel=%c%c%c lost=%lu q=%lu/%u hw=%lu "
                     "drop_q=%lu drop_st=%lu slots=%lu/%lu log=%s left=%ss thin=%lu can=%lu ovr=%lu",
                     (unsigned long)(t / 1000000u), (unsigned long)((t / 1000u) % 1000u), (unsigned long)(now >> 32),
                     (unsigned long)app->boot,
                     (unsigned long)app->wheel[0].total, (unsigned long)app->wheel[1].total,
                     (unsigned long)app->wheel[2].total, app->wheel_state[0], app->wheel_state[1], app->wheel_state[2],
                     (unsigned long)app->c.wheel_edges_lost,
                     (unsigned long)tm_queue_count(&app->q), (unsigned)TM_QUEUE_LEN,
                     (unsigned long)app->q.high_water, (unsigned long)app->q.dropped,
                     (unsigned long)app->fl.dropped_records, (unsigned long)app->fl.next_slot,
                     (unsigned long)app->fl.io->slots, app->sparse ? "sparse" : "full", left,
                     (unsigned long)app->c.log_thinned, (unsigned long)app->c.rx_frames, (unsigned long)app->can.overrun);
    return n > 0 ? (size_t)n : 0u;
}

void tm_app_erase_log(tm_app_t *app) { tm_flashlog_erase_all(&app->fl); }

void tm_app_request_flush(tm_app_t *app) { app->flush_requested = true; }

bool tm_app_idle(const tm_app_t *app)
{
    return tm_queue_count(&app->q) == 0u && !app->blk.open && !app->fl.has_pending && !app->header_pending;
}
