#include "tm_reset.h"

#include <string.h>

size_t tm_reset_cause(uint32_t csr, char *out, size_t cap)
{
    static const struct {
        uint32_t bit;
        const char *name;
    } F[] = {{TM_RST_BOR, "BOR"},   {TM_RST_PIN, "PIN"},   {TM_RST_SFT, "SOFTWARE"}, {TM_RST_IWDG, "IWDG"},
             {TM_RST_WWDG, "WWDG"}, {TM_RST_LPWR, "LOWPOWER"}, {TM_RST_OBL, "OPTION_BYTES"}};
    size_t n = 0;
    if (cap == 0u) return 0u;
    out[0] = '\0';
    for (size_t i = 0; i < sizeof F / sizeof F[0]; i++) {
        if (!(csr & F[i].bit)) continue;
        size_t l = strlen(F[i].name);
        if (n + (n ? 1u : 0u) + l + 1u > cap) break;
        if (n) out[n++] = '+';
        memcpy(out + n, F[i].name, l);
        n += l;
        out[n] = '\0';
    }
    if (n == 0u && cap >= 5u) {
        memcpy(out, "none", 5);
        n = 4u;
    }
    return n;
}
