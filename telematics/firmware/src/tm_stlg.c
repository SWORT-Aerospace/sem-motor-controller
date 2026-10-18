#include "tm_stlg.h"

#include <string.h>

#include "tm_crc32.h"
#include "tm_le.h"

size_t tm_stlg_header(uint8_t *out, const char *meta, size_t meta_len)
{
    if (meta_len + 14u > TM_SLOT_BYTES) return 0u;
    memset(out, 0xFF, TM_SLOT_BYTES);
    memcpy(out, "STLG", 4);
    tm_le16(out + 4, 1u);
    tm_le32(out + 6, (uint32_t)meta_len);
    memcpy(out + 10, meta, meta_len);
    tm_le32(out + 10 + meta_len, tm_crc32(0u, (const uint8_t *)meta, meta_len));
    return 14u + meta_len;
}

void tm_block_reset(tm_block_t *b)
{
    b->used = 0u;
    b->base_us = 0u;
    b->opened_us = 0u;
    b->open = false;
}

bool tm_block_fits(const tm_block_t *b, uint64_t t_us, uint32_t len)
{
    if (!b->open) return true;
    if (t_us < b->base_us || t_us - b->base_us > 0xFFFFFFFFu) return false;
    return b->used + 6u + len <= TM_BLOCK_PAYLOAD;
}

void tm_block_add(tm_block_t *b, uint64_t t_us, uint8_t type, const uint8_t *body, uint32_t len, uint64_t now_us)
{
    if (!b->open) {
        b->base_us = t_us > TM_BASE_SLACK_US ? t_us - TM_BASE_SLACK_US : 0u;
        b->opened_us = now_us;
        b->open = true;
    }
    uint8_t *p = b->buf + TM_BLOCK_HDR + b->used;
    p[0] = type;
    p[1] = (uint8_t)len;
    tm_le32(p + 2, (uint32_t)(t_us - b->base_us));
    if (len) memcpy(p + 6, body, len);
    b->used += 6u + len;
}

void tm_block_finish(tm_block_t *b, uint32_t seq)
{
    uint8_t *h = b->buf;
    h[0] = 'B';
    h[1] = 'K';
    tm_le32(h + 2, seq);
    tm_le64(h + 6, b->base_us);
    tm_le16(h + 14, (uint16_t)b->used);
    tm_le32(h + 16, tm_crc32(0u, b->buf + TM_BLOCK_HDR, b->used));
    memset(b->buf + TM_BLOCK_HDR + b->used, 0xFF, TM_SLOT_BYTES - TM_BLOCK_HDR - b->used);
}
