/* Controller event log in RAM that survives resets without power loss (section .noinit).
 *
 * Records boots with their reset cause, state transitions, platform faults and CPU faults, each with
 * the controller time in milliseconds. It is printed on the debug UART at boot (event_log_dump) and is
 * the controller's local record of why it stopped. Vehicle telemetry is logged by the telematics unit
 * from the CAN messages; this log covers what happens when CAN, the telematics unit or the CPU itself
 * is not working. 64 entries; the oldest is overwritten. */
#ifndef SEMMC_STM32G4_EVENT_LOG_H
#define SEMMC_STM32G4_EVENT_LOG_H

#include <stdint.h>

enum {
    EVT_BOOT = 0x01,            /* a = reset cause bits (RCC_CSR >> 24), b = boot count */
    EVT_CLOCK_FAIL = 0x02,
    EVT_CONFIG_REJECTED = 0x03, /* a = blob length found, b = number of validation issues */
    EVT_TRANSITION = 0x10,      /* a = mc_transition_t, b = new mc_state_t */
    EVT_PLATFORM = 0x20,        /* a = platform_fault bit, b = 0 */
    EVT_CAN_BUS_OFF = 0x30,     /* a = 1 entered, 0 recovered */
    EVT_FAULT_HARD = 0x80,
    EVT_FAULT_MEMMANAGE = 0x81,
    EVT_FAULT_BUS = 0x82,
    EVT_FAULT_USAGE = 0x83,
    EVT_FAULT_NMI = 0x84,
    EVT_FAULT_UNEXPECTED_IRQ = 0x85,
    EVT_FAULT_MAIN_RETURNED = 0x86
};

typedef struct {
    uint32_t t_ms;
    uint16_t code;
    uint16_t a;
    uint32_t b;
} event_t;

void event_log_init(void);          /* keeps a valid log from before the reset, else starts empty */
void event_log_add(uint16_t code, uint16_t a, uint32_t b);
void event_log_record_fault(uint16_t code); /* from fault handlers: no time base needed */
void event_log_set_time(uint32_t t_ms);
uint32_t event_log_boot_count(void);
void event_log_dump(void (*put)(const char *s));

#endif
