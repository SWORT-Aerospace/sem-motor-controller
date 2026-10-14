/* Shared helpers for host unit tests. */
#ifndef SEMMC_TEST_SUPPORT_H
#define SEMMC_TEST_SUPPORT_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "semmc/mc_config.h"

static inline size_t load_blob(const char *path, uint8_t *buf, size_t cap)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    const size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return n;
}

/* Load the synthetic configuration and derive parameters. */
static inline void load_synthetic(mc_config_t *cfg, mc_params_t *p)
{
    static uint8_t buf[8192];
    const size_t n = load_blob(SEMMC_SYNTH_BLOB, buf, sizeof buf);
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_parse_blob(buf, n, cfg, &rep) || !mc_config_derive(cfg, p)) {
        fprintf(stderr, "synthetic blob did not load\n");
        exit(2);
    }
}

#endif
