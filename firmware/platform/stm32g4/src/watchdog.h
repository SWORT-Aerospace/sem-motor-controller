/* Watchdogs and reset cause.
 *
 * Internal IWDG on the LSI oscillator: prescaler /32, reload 100, i.e. about 100 ms at the nominal
 * 32 kHz (the LSI tolerance in DS12288 is not yet read, so the real window is unverified). Started
 * at the beginning of main() so that a hang during initialisation also resets.
 *
 * External MAX6369 (hardware/kicad sheet 08): WDI toggled from the slow step. Its timeout is set by
 * the SET0..2 straps on the board, which are not chosen; WDI gets one edge per slow step (every
 * 1 ms), so a strap setting with a timeout of a few milliseconds or more is compatible. On timeout
 * it pulls HW_PERMIT low, which disables the gate driver in hardware.
 *
 * Both are kicked only when the slow step has run and, once the current loop is running, the
 * current loop has completed at least one cycle since the previous kick. */
#ifndef SEMMC_STM32G4_WATCHDOG_H
#define SEMMC_STM32G4_WATCHDOG_H

#include <stdbool.h>
#include <stdint.h>

void watchdog_start(void);
void watchdog_kick(void);
/* RCC_CSR reset flags (bits 24..31), then cleared so the next boot reports only its own cause. */
uint8_t watchdog_reset_cause(void);

#define RESET_CAUSE_IWDG(c) (((c) & (RCC_CSR_IWDGRSTF >> 24u)) != 0u)

#endif
