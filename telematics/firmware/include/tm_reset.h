/* Restart reason from the reset flags (RCC_CSR on the STM32U5: bits 25 to 31, RM0456; the bit positions
 * are those of the vendored stm32u575xx.h). */
#ifndef TM_RESET_H
#define TM_RESET_H

#include <stddef.h>
#include <stdint.h>

#define TM_RST_OBL (1uL << 25)
#define TM_RST_PIN (1uL << 26)
#define TM_RST_BOR (1uL << 27)
#define TM_RST_SFT (1uL << 28)
#define TM_RST_IWDG (1uL << 29)
#define TM_RST_WWDG (1uL << 30)
#define TM_RST_LPWR (1uL << 31)

/* "BOR+PIN" etc. (every flag set, in a fixed order), "none" when no flag is set. Returns the length. */
size_t tm_reset_cause(uint32_t csr, char *out, size_t cap);

#endif
