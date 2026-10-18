/* Internal flash bank 2 driver (non-secure registers). Sequences as ST's HAL (stm32u5xx_hal_flash.c and
 * _flash_ex.c v1.6.3): unlock with the two keys, page erase with BKER + PNB + PER then STRT, quad-word
 * programming with PG and four 32-bit writes to a 16-byte-aligned address. Each call starts one operation
 * and returns; busy() reports completion and clears the operation bits, so nothing waits. */
#include "drivers_u575.h"

#include <string.h>

#include "stm32u5xx.h"

#define LOG_BASE 0x08100000u
#define LOG_SIZE 0x00100000u
#define PAGE 8192u
#define KEY1 0x45670123u     /* FLASH_KEY1, stm32u5xx_hal_flash.h */
#define KEY2 0xCDEF89ABu
#define ERRORS (FLASH_NSSR_OPERR | FLASH_NSSR_PROGERR | FLASH_NSSR_WRPERR | FLASH_NSSR_PGAERR | FLASH_NSSR_SIZERR | \
                FLASH_NSSR_PGSERR)

static volatile uint32_t g_ecc_addr;

static void unlock(void)
{
    if (FLASH->NSCR & FLASH_NSCR_LOCK) {
        FLASH->NSKEYR = KEY1;
        FLASH->NSKEYR = KEY2;
    }
}

static int f_busy(void *ctx)
{
    (void)ctx;
    uint32_t sr = FLASH->NSSR;
    if (sr & (FLASH_NSSR_BSY | FLASH_NSSR_WDW)) return 1;
    FLASH->NSCR &= ~(FLASH_NSCR_PG | FLASH_NSCR_PER);
    if (sr & ERRORS) {
        FLASH->NSSR = sr & ERRORS;      /* write 1 to clear */
        return -1;
    }
    if (sr & FLASH_NSSR_EOP) FLASH->NSSR = FLASH_NSSR_EOP;
    return 0;
}

static int f_erase(void *ctx, uint32_t addr)
{
    (void)ctx;
    if (addr < LOG_BASE || addr >= LOG_BASE + LOG_SIZE || (addr - LOG_BASE) % PAGE) return -1;
    if (f_busy(0) != 0) return -1;
    unlock();
    uint32_t page = (addr - LOG_BASE) / PAGE;
    FLASH->NSCR = (FLASH->NSCR & ~(FLASH_NSCR_PNB_Msk | FLASH_NSCR_PG)) | FLASH_NSCR_BKER |
                  (page << FLASH_NSCR_PNB_Pos) | FLASH_NSCR_PER;
    FLASH->NSCR |= FLASH_NSCR_STRT;
    return 0;
}

static int f_program(void *ctx, uint32_t addr, const uint8_t *src, uint32_t n)
{
    (void)ctx;
    if (n != 16u || addr % 16u || addr < LOG_BASE || addr + n > LOG_BASE + LOG_SIZE) return -1;
    if (f_busy(0) != 0) return -1;
    unlock();
    uint32_t w[4];
    memcpy(w, src, 16);
    FLASH->NSCR = (FLASH->NSCR & ~FLASH_NSCR_PER) | FLASH_NSCR_PG;
    uint32_t pm = __get_PRIMASK();
    __disable_irq();
    volatile uint32_t *dst = (volatile uint32_t *)addr;
    for (unsigned i = 0; i < 4u; i++) dst[i] = w[i];
    __set_PRIMASK(pm);
    return 0;
}

static int f_read(void *ctx, uint32_t addr, uint8_t *dst, uint32_t n)
{
    (void)ctx;
    if (addr < LOG_BASE || addr + n > LOG_BASE + LOG_SIZE) return -1;
    memcpy(dst, (const void *)addr, n);
    return 0;
}

const tm_flash_if_t g_flash_bank2 = {.base = LOG_BASE, .slots = LOG_SIZE / 4096u, .page_bytes = PAGE, .prog_bytes = 16u,
                                     .erase = f_erase, .program = f_program, .busy = f_busy, .read = f_read, .ctx = 0};

uint32_t flash_ecc_address(void) { return g_ecc_addr; }

/* A double ECC error on a flash read (a quad-word whose programming was interrupted by a power loss) raises
 * the NMI. Record the address (FLASH_ECCR), clear the flag and stop: the next start reads the record and
 * leaves the log alone until "ERASE YES" (main_u575.c). Not exercised on hardware. */
void NMI_Handler(void);
void NMI_Handler(void)
{
    uint32_t e = FLASH->ECCR;
    if (e & FLASH_ECCR_ECCD) {
        /* ADDR_ECC: byte offset in the bank (20 bits for 1 MB); BK_ECC: the bank */
        g_ecc_addr = ((e & FLASH_ECCR_BK_ECC) ? LOG_BASE : 0x08000000u) + (e & FLASH_ECCR_ADDR_ECC_Msk);
        FLASH->ECCR = e | FLASH_ECCR_ECCD;
        extern void board_record_fault(uint32_t code);
        board_record_fault(8u);   /* FAULT_NMI_ECC */
    }
    for (;;) {
    }
}
