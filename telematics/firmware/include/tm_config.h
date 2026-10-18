/* Build-time configuration of the telematics firmware (portable part). */
#ifndef TM_CONFIG_H
#define TM_CONFIG_H

#define TM_WHEEL_CHANNELS 3u              /* TIM2 capture channels in use (platform/u575/board_u575.c) */
#define TM_REC_MAX 96u                    /* largest record body: COUNTERS2 with TM_CNT_ITEMS (81), CAN2 FD (69) */
#define TM_QUEUE_LEN 256u                 /* log queue, records (power of two) */
#define TM_CAN_RING_LEN 128u              /* received frames waiting for the main loop (power of two) */
#define TM_SLOT_BYTES 4096u               /* one STLG header or block per slot */
#define TM_BLOCK_HDR 20u
#define TM_BLOCK_PAYLOAD (TM_SLOT_BYTES - TM_BLOCK_HDR)
#define TM_BASE_SLACK_US 1000000u         /* block base before its first record (host/telematics/stlg.py) */
#define TM_WHEEL_RECORD_PERIOD_US 50000u  /* one WHEEL_EDGES record per channel per period */
#define TM_COUNTERS_PERIOD_US 1000000u
#define TM_BLOCK_FLUSH_US 2000000u        /* a partly filled block is written after this long */
#define TM_META_MAX 1024u                 /* run metadata JSON in the session header */
/* Sparse logging: when only the reserve is left, wheel and counters records every TM_SPARSE_PERIOD_US and
 * nothing else (counted as log_thinned), so a full storage still keeps the time and edge evidence. */
#define TM_RESERVE_SLOTS 32u              /* at most; never more than 1/8 of the storage */
#define TM_SPARSE_PERIOD_US 10000000u
#define TM_SPARSE_FLUSH_US 300000000u     /* a sparse block fills in about 270 s */

#endif
