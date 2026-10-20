/* Linker script for the STM32U575ZITxQ of the NUCLEO-U575ZI-Q (2 MB flash in two 1 MB banks, 768 KB SRAM),
 * GNU ld. Sizes from the vendored stm32u575xx.h (FLASH_BASE_NS, SRAM1_SIZE 192 KB) and ST's template
 * STM32U575xx_FLASH.ld (cmsis-device-u5 v1.4.3).
 *
 *   code      bank 1, 0x08000000 - 0x080FFFFF
 *   log       bank 2, 0x08100000 - 0x081FFFFF: 256 slots of 4 KiB in 128 pages of 8 KiB, written by
 *             flash_u575.c; never part of the image, so flashing the image does not erase the log unless
 *             the programmer is told to mass-erase (BENCH.md)
 *   RAM       SRAM1 192 KB; its last 32 bytes are not cleared at start (fault record kept across a reset)
 * Bank 2 is at 0x08100000 only while the option bit SWAP_BANK is 0, the factory setting. */
ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K
    LOG   (r)   : ORIGIN = 0x08100000, LENGTH = 1024K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 192K - 32
    NOINIT (rw) : ORIGIN = 0x20000000 + 192K - 32, LENGTH = 32
}

_estack = ORIGIN(RAM) + LENGTH(RAM);
__log_start = ORIGIN(LOG);
__log_size = LENGTH(LOG);

SECTIONS
{
    .isr_vector :
    {
        . = ALIGN(4);
        KEEP(*(.isr_vector))
        . = ALIGN(4);
    } > FLASH

    .text :
    {
        . = ALIGN(4);
        *(.text*)
        *(.rodata*)
        KEEP(*(.init))
        KEEP(*(.fini))
        . = ALIGN(4);
        _etext = .;
    } > FLASH

    .ARM.exidx :
    {
        *(.ARM.exidx* .gnu.linkonce.armexidx.*)
    } > FLASH

    _sidata = LOADADDR(.data);
    .data :
    {
        . = ALIGN(4);
        _sdata = .;
        *(.data*)
        . = ALIGN(4);
        _edata = .;
    } > RAM AT > FLASH

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        _sbss = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        _ebss = .;
    } > RAM
    /* newlib's _sbrk (pulled in by snprintf) starts its heap here; nothing in the firmware allocates */
    PROVIDE(end = _ebss);
    PROVIDE(_end = _ebss);

    .noinit (NOLOAD) :
    {
        KEEP(*(.noinit*))
    } > NOINIT

    /* at least 8 KB of stack above .bss */
    ._stack_check (NOLOAD) :
    {
        . = ALIGN(8);
        . = . + 8K;
    } > RAM
}
