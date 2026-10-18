/* Linker script for the STM32G474VET6 (512 KB flash, 128 KB SRAM), GNU ld.
 *
 * Memory sizes are ST's (to be confirmed in DS12288 for the xE variant), from the IAR template stm32g474xx_flash.icf in
 * STMicroelectronics/cmsis-device-g4@626ee412 (Source/Templates/iar/linker):
 *   flash  0x08000000 - 0x0807FFFF
 *   SRAM   0x20000000 - 0x2001FFFF (SRAM1 80 KB, SRAM2 16 KB, CCM SRAM alias 32 KB at 0x20018000)
 *   CCM    0x10000000 - 0x10007FFF (the same 32 KB at its core-coupled address)
 *
 * The last 4 KB of flash hold the calibration blob (config/vehicle.*.yaml encoded by
 * tools/config_tool.py), programmed separately from the image (FLASHING.md). The firmware only
 * reads it. 4 KB is two 2 KB pages in the default dual-bank mode or one 4 KB page in single-bank
 * mode, so erasing it never touches the code (0x0807F000 is a multiple of 4 KB, hence of 2 KB, whichever bank
 * mode the option bytes select; the factory default is to be read in RM0440). The blob is at most 36 + 8 x 256
 * = 2084 bytes.
 *
 * SRAM ends 32 KB early so that the CCM alias at 0x20018000 is not used twice; the stack is at the
 * top of the 96 KB of SRAM1 + SRAM2. */
ENTRY(Reset_Handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 512K - 4K
    CAL   (r)   : ORIGIN = 0x0807F000, LENGTH = 4K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 96K
    CCM   (rwx) : ORIGIN = 0x10000000, LENGTH = 32K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);
_min_stack = 4K;

__cal_start = ORIGIN(CAL);
__cal_size = LENGTH(CAL);

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

    /* Initialised data: stored after the code, copied to RAM by Reset_Handler. */
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

    /* Kept across a reset that does not remove power (watchdog, software, pin): the event log. */
    .noinit (NOLOAD) :
    {
        . = ALIGN(4);
        *(.noinit*)
        . = ALIGN(4);
    } > RAM

    ._stack_check (NOLOAD) :
    {
        . = ALIGN(8);
        _stack_limit = .;   /* lowest address the stack may reach; main.c paints from here and measures */
        . = . + _min_stack;
        . = ALIGN(8);
    } > RAM
}
