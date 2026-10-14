/* HOST-ONLY: run the C configuration validator on a calibration blob.
 *   semmc_cfgcheck <blob> sim|hw
 * Prints "CODES <code>:<param_id> ..." and exits 0 (valid), 1 (invalid), 2 (usage/IO).
 * Used by tests/integration/test_config_parity.py to compare with Python. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "semmc/mc_config.h"

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: %s <blob> sim|hw\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 2;
    static uint8_t buf[8192];
    const size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);
    static mc_config_t cfg;
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    if (!mc_config_parse_blob(buf, n, &cfg, &rep)) {
        printf("CODES 6:0\n");
        return 1;
    }
    const mc_cfg_mode_t mode = strcmp(argv[2], "hw") == 0 ? MC_CFG_MODE_HW : MC_CFG_MODE_SIM;
    const bool ok = mc_config_validate(&cfg, mode, &rep);
    printf("CODES");
    for (uint16_t i = 0; i < rep.count && i < MC_CFG_MAX_ISSUES; i++) printf(" %u:%u", rep.items[i].code, rep.items[i].param_id);
    printf("\nPHYSICAL_OUTPUT_PERMITTED_HW_BUILD %d\n", (int)mc_config_permits_physical_output(&cfg, MC_BUILD_HARDWARE));
    return ok ? 0 : 1;
}
