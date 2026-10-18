/* STM32G474 controller firmware: start-up, the current interrupt (fast step), the 1 kHz slow step.
 *
 * Contexts and priorities (lower number preempts higher; all four priority bits are preemption bits):
 *   0  ADC1_2   fast step at the PWM rate: currents, hall code, mc_core_fast_step, duties
 *   1  TIM1_BRK records which break input cleared the outputs (the hardware already did)
 *   3  TIM6     slow step at 1 kHz: inputs, battery meter, start-up sequence and gate driver, CAN,
 *               mc_core_slow_step, watchdogs
 *   -  main     sleeps (WFI)
 * The fast/slow data handoff relies on the slow step never preempting the fast step (mc_core.h, "Shared
 * state"): checked below at compile time.
 *
 * Fast-step deadline (pwm.h): sampling triggers at the counter valley; the compare values the fast step
 * writes load at the next update event, the counter peak, half a period later. The last compare write must
 * therefore complete before the peak: T/2 minus the ADC sampling and conversion time and the interrupt entry.
 * g_bench.fast_margin_min_ticks is the smallest timer-tick distance to the peak seen after that write, and
 * fast_late_writes counts writes made after it; these are the on-target evidence, observed maxima only.
 *
 * Start-up (mc_startup.h): the bypass closes only on fresh, cross-checked battery and link readings; the
 * gate driver (supplied from the link) is then woken with the gates off, configured and read back; the
 * current offsets are measured with its amplifiers running; only then may the core arm.
 *
 * What this revision does NOT drive, and why (docs/BLOCKERS.md):
 *   - the gate driver and the battery-side meter: their driver logic is linked (mc_drv835x, mc_ina228),
 *     but no device description is passed, because the DRV8353 and INA228 data sheets have not been
 *     read (docs/reference/datasheets/README.md), and the SPI1 and I2C1 transports are not written. Both
 *     stay UNVERIFIED, the start-up sequence stays INHIBITED, DRV_ENABLE stays low (also behind
 *     GATE_DRIVER_CONFIGURED), the bypass stays open and the core never leaves its pre-drive states;
 *   - CAN without a crystal and a configured bit rate (can.h).
 * Each of these is also refused by the core unless the calibration is hardware-valid, bench-measured
 * and permits output (mc_config_permits_physical_output); a synthetic calibration never runs.
 *
 * Bench readout: g_bench (below) holds raw ADC averages, loop timings and status for a debugger
 * (FLASHING.md, "Reading the bench values").
 *
 * SEMMC_BENCH_PWM_TEST builds a separate image (semmc_stm32g474_pwmtest) for acceptance stage 4: TIM1
 * switches its six outputs at fixed duties (A 25 %, B 50 %, C 75 %) at the sampling-only frequency and dead
 * time, with the calibration ignored, the core never driving and DRV_ENABLE held low, so the gate signals can
 * be measured at the MCU pins while the gate driver stays disabled. A break latches the outputs off until the
 * fault-reset input is pressed with both break inputs inactive. Never load it on a board whose bridge is
 * powered. */
#include <math.h>
#include <string.h>

#include "adc.h"
#include "board.h"
#include "calstore.h"
#include "can.h"
#include "event_log.h"
#include "pwm.h"
#include "semmc/mc_core.h"
#include "semmc/mc_drv835x.h"
#include "semmc/mc_ina228.h"
#include "semmc/mc_io.h"
#include "semmc/mc_startup.h"
#include "stm32g4xx.h"
#include "system_clock.h"
#include "timebase.h"
#include "uart.h"
#include "watchdog.h"

#ifndef SEMMC_GIT_REV
#define SEMMC_GIT_REV "unknown"
#endif

#define PRIO_FAST 0u
#define PRIO_BREAK 1u
#define PRIO_SLOW 3u
_Static_assert(PRIO_FAST < PRIO_BREAK && PRIO_BREAK < PRIO_SLOW && PRIO_SLOW < (1u << __NVIC_PRIO_BITS),
               "the fast step must preempt the slow step (mc_core.h, Shared state)");
#define NVIC_GROUP_ALL_PREEMPT 3u /* PRIGROUP 3: the 4 implemented bits are all preemption priority */

#if defined(SEMMC_TIMING_MARKER)
/* Timing image: the status-LED pin (PE14) is high while the fast-step interrupt runs, for a scope. */
#define MARK_FAST_ON() (GPIOE->BSRR = 1u << BOARD_LED_STATUS_PIN)
#define MARK_FAST_OFF() (GPIOE->BSRR = 1u << (BOARD_LED_STATUS_PIN + 16u))
#define TIMING_MARKER true
#else
#define MARK_FAST_ON() ((void)0)
#define MARK_FAST_OFF() ((void)0)
#define TIMING_MARKER false
#endif

/* With no configured PWM frequency TIM1 still runs, outputs permanently off, so that the phase-current
 * ADC readings can be taken on the bench (offset calibration needs them before a calibration exists).
 * A sampling clock only: it never reaches a gate. */
#define SAMPLING_ONLY_PWM_HZ 10000.0f
#define SAMPLING_ONLY_DEADTIME_S 1.0e-6f
#define OFFSET_SAMPLES 1024u

/* Second, compile-time inhibit of DRV_ENABLE, set true only in the reviewed revision that also passes a
 * verified DRV8353 description (see the header). */
#define GATE_DRIVER_CONFIGURED false
#define OFFSET_TIMEOUT_MS 500u

#if defined(SEMMC_BENCH_PWM_TEST)
#define BENCH_PWM_TEST true
#define IMAGE_NAME "semmc stm32g474 BENCH PWM TEST "
#elif defined(SEMMC_TIMING_MARKER)
#define BENCH_PWM_TEST false
#define IMAGE_NAME "semmc stm32g474 TIMING MARKER "
#else
#define BENCH_PWM_TEST false
#define IMAGE_NAME "semmc stm32g474 "
#endif

enum {
    PF_GATE_DRIVER_NOT_CONFIGURED = 1u << 0,
    PF_BATTERY_METER_NOT_READ = 1u << 1,
    PF_PWM_NOT_CONFIGURED = 1u << 2,
    PF_CAN_OFF = 1u << 3,
    PF_ADC_INIT = 1u << 4,
    PF_OFFSETS = 1u << 5,
    PF_ENABLE_PATH = 1u << 6,
    PF_PRECHARGE = 1u << 7,
    PF_ADC_RESOLUTION = 1u << 8
};

typedef struct {
    uint32_t platform_faults;      /* PF_* */
    uint32_t can_status;           /* can_status_t */
    uint32_t fast_count;
    uint32_t fast_max_cycles;      /* worst fast-step execution time, CPU cycles at 160 MHz */
    uint32_t fast_overruns;        /* duties written after the counter peak */
    uint32_t slow_max_cycles;
    float raw_current_avg[3];      /* counts, running average (gate driver disabled: the zero-current offset) */
    uint16_t raw_slow[ADC_SLOW_N]; /* counts: VBUS, TEMP_FET, TEMP_MOTOR, THROTTLE_A, THROTTLE_B */
    float offsets_measured[3];
    float pedal_frac_a, pedal_frac_b;
    float f_pwm_Hz, deadtime_s;
    uint32_t state;                /* mc_state_t */
    uint32_t precharge_state;      /* mc_pc_state_t */
    uint32_t inputs;               /* BENCH_IN_* bits, sampled by the slow step */
    uint32_t fast_isr_max_cycles;  /* whole fast interrupt, first to last instruction (not the entry latency) */
    uint32_t fast_margin_min_ticks; /* smallest TIM1 ticks left to the peak after the last compare write */
    uint32_t fast_late_writes;     /* compare writes made after the peak (the deadline was missed) */
    uint32_t adc_wait_max_cycles;  /* longest wait for ADC2/ADC3 after ADC1 finished: sampling skew evidence */
    uint32_t slow_overruns;        /* slow steps that ended with the next 1 ms tick already pending */
    uint32_t stack_unused_min_bytes; /* painted stack never written so far (high-water mark), main loop */
    uint32_t startup;              /* mc_su_state_t | fault << 8 | missing << 16 | attempts << 24 */
    uint32_t devices;              /* drv state | drv error << 4 | ina state << 8 | ina error << 12 | exhausted << 16 */
} bench_view_t;

enum {
    BENCH_IN_BRAKE = 1u << 0, BENCH_IN_CANCEL = 1u << 1, BENCH_IN_MODE_ECO = 1u << 2, BENCH_IN_ARM = 1u << 3,
    BENCH_IN_FAULT_RESET = 1u << 4, BENCH_IN_DRIVER_PRESENT = 1u << 5, BENCH_IN_HW_PERMIT = 1u << 6,
    BENCH_IN_DRV_EN_GATED = 1u << 7, BENCH_IN_DRV_NFAULT = 1u << 8, BENCH_IN_EXT_WDG_RESET = 1u << 9,
    BENCH_IN_INA_ALERT = 1u << 10, BENCH_IN_BREAK_DRIVER = 1u << 11, BENCH_IN_BREAK_OVERVOLT = 1u << 12,
    BENCH_IN_BREAK_SYSTEM = 1u << 13, BENCH_IN_OUTPUTS_ON = 1u << 14
    /* bits 16..18: hall code (A, B, C) */
};

/* tools/bench_read.py decodes this layout ("<6I3f5H2x3f2f2f3I6I2I", 120 bytes); keep both in step. */
_Static_assert(sizeof(bench_view_t) == 120u, "bench_view_t layout changed: update tools/bench_read.py");
volatile bench_view_t g_bench __attribute__((used));

static mc_core_t g_core;
static mc_adc_scale_t g_scale;
static mc_ntc_t g_ntc_fet, g_ntc_mot;
static mc_pedal_t g_pedal;
static mc_startup_t g_su;
static mc_drv835x_t g_drv;
static mc_ina228_t g_ina;
static uint32_t g_batt_age_us; /* power.battery_sample_max_age_s */
static mc_enable_check_t g_en;
static pwm_setup_t g_pwm;
static bool g_pwm_drive_allowed; /* TIM1 runs at the CONFIGURED frequency and the calibration is valid */
static bool g_offsets_ok;      /* boot measurement, driver asleep: bench readout only */
static uint32_t g_ofs_seq;     /* start-up offsets request being measured (0: none) */
static uint32_t g_ofs_done_seq;
static bool g_ofs_ok;          /* result of g_ofs_done_seq, driver awake: the one the core uses */
static uint32_t g_ofs_t0_ms;
static uint8_t g_reset_cause;
static float g_settle_s;
static can_status_t g_can;
static bool g_bus_off;

/* fast-loop state */
static volatile bool g_cal_active;
static volatile uint32_t g_cal_n;
static volatile uint32_t g_cal_sum[3];
static uint32_t g_last_cyc;
static mc_duty_t g_applied = {0.5f, 0.5f, 0.5f};
static bool g_applied_on;
static bool g_turn_on_pending;

/* slow-loop state */
static uint32_t g_fast_at_kick;
static bool g_prev_fault_reset;
static mc_state_t g_prev_state = MC_ST_BOOT;
static uint32_t g_ms;

static float cfg(uint8_t id) { return mc_config_get(&g_core.cfg, id); }

static uint8_t hall_code(void)
{
    const uint32_t idr = GPIOE->IDR;
    return (uint8_t)(((idr >> BOARD_HALL_A_PIN) & 1u) | (((idr >> BOARD_HALL_B_PIN) & 1u) << 1u) |
                     (((idr >> BOARD_HALL_C_PIN) & 1u) << 2u));
}

/* ------------------------------------------------------------------ fast step */
static void fast_isr_end(uint32_t c_entry)
{
    const uint32_t cyc = DWT->CYCCNT - c_entry;
    if (cyc > g_bench.fast_isr_max_cycles) g_bench.fast_isr_max_cycles = cyc;
    MARK_FAST_OFF();
}

void ADC1_2_IRQHandler(void)
{
    const uint32_t c_entry = DWT->CYCCNT;
    MARK_FAST_ON();
    if ((ADC1->ISR & ADC_ISR_JEOS) == 0u) {
        ADC1->ISR = ADC_ISR_OVR | ADC_ISR_EOC | ADC_ISR_EOS;
        MARK_FAST_OFF();
        return;
    }
    ADC1->ISR = ADC_ISR_JEOS | ADC_ISR_JEOC;
    const uint32_t c0 = DWT->CYCCNT;
    uint16_t raw[3] = {0u, 0u, 0u};
    uint32_t wait = 0u;
    const uint8_t done = adc_read_currents(raw, &wait);
    if (wait > g_bench.adc_wait_max_cycles) g_bench.adc_wait_max_cycles = wait;
    for (int k = 0; k < 3; k++) {
        g_bench.raw_current_avg[k] += ((float)raw[k] - g_bench.raw_current_avg[k]) * (1.0f / 256.0f);
    }
    if (g_cal_active || !g_pwm_drive_allowed) {
        if (g_cal_active && done == 7u && g_cal_n < OFFSET_SAMPLES) {
            for (int k = 0; k < 3; k++) g_cal_sum[k] += raw[k];
            g_cal_n++;
        }
        if (!BENCH_PWM_TEST) pwm_outputs_off();
        g_last_cyc = c0;
        g_bench.fast_count++;
        fast_isr_end(c_entry);
        return;
    }

    mc_fast_inputs_t in;
    memset(&in, 0, sizeof in);
    const uint8_t window =
        mc_lowside_sample_mask(&g_applied, g_applied_on, g_pwm.deadtime_s, g_settle_s, g_pwm.f_pwm_Hz);
    in.phase.measured_mask = g_scale.current_configured ? (uint8_t)(window & done) : 0u;
    for (int k = 0; k < 3; k++) in.phase.i[k] = mc_adc_phase_A(&g_scale, k, raw[k]);
    in.hall_code = hall_code();
    mc_validity_t vv;
    const float vbus = mc_adc_vbus_V(&g_scale, adc_slow[ADC_SLOW_VBUS], &vv);
    in.vbus_V = mc_usable(vv) ? vbus : NAN;
    in.dt = (float)(c0 - g_last_cyc) * (1.0f / (float)SYSCLK_HZ);
    g_last_cyc = c0;
    in.hw_trip = pwm_break_flags() != 0u;

    mc_fast_outputs_t out;
    mc_core_fast_step(&g_core, &in, &out);

    const bool allow = out.pwm_enable && GATE_DRIVER_CONFIGURED && board_drv_enable_commanded() && !in.hw_trip;
    if (allow) {
        pwm_write_duty(&out.duty);
        const uint32_t left = pwm_ticks_to_peak(); /* 0 if the peak has passed: the duties load half a period late */
        if (left == 0u) {
            g_bench.fast_late_writes++;
        } else if (left < g_bench.fast_margin_min_ticks) {
            g_bench.fast_margin_min_ticks = left;
        }
        /* The new compare values load at the next counter peak. Turning the outputs on now would run
         * the rest of this half period on the old values (all low sides on at the first start), so
         * the outputs come on one cycle later, when the requested duties are in the active registers. */
        if (g_applied_on || g_turn_on_pending) {
            pwm_outputs_on();
            g_applied_on = true;
            g_turn_on_pending = false;
        } else {
            g_turn_on_pending = true;
        }
        g_applied = out.duty;
    } else {
        pwm_outputs_off();
        g_applied_on = false;
        g_turn_on_pending = false;
    }
    if (pwm_counting_down()) g_bench.fast_overruns++;
    const uint32_t cyc = DWT->CYCCNT - c0;
    if (cyc > g_bench.fast_max_cycles) g_bench.fast_max_cycles = cyc;
    g_bench.fast_count++;
    fast_isr_end(c_entry);
}

/* ------------------------------------------------------------------ slow step */
static void can_service(mc_time_us_t now)
{
    if (g_can != CAN_ON) return;
    const bool bo = can_service_bus_off(g_ms);
    if (bo != g_bus_off) {
        g_bus_off = bo;
        mc_core_on_can_bus_off(&g_core, bo);
        event_log_add(EVT_CAN_BUS_OFF, bo ? 1u : 0u, 0u);
    }
    uint32_t id;
    uint8_t d[8];
    uint8_t len;
    for (int i = 0; i < 3 && can_rx(&id, d, &len); i++) mc_core_on_can_rx(&g_core, now, id, d, len);
}

static void can_transmit(mc_time_us_t now)
{
    if (g_can != CAN_ON) return;
    uint32_t id;
    uint8_t d[8];
    /* Ask the core for a message only when the TX FIFO has room, so none is produced and then lost. */
    for (int i = 0; i < 3 && can_tx_free() && mc_core_can_tx_poll(&g_core, now, &id, d); i++) (void)can_tx(id, d);
}

/* Offsets for the start-up sequence: driver awake, gates off. Non-blocking: the fast step accumulates
 * while g_cal_active and, in that branch, neither drives nor reads g_scale, so g_scale is written here
 * before g_cal_active is cleared (the barrier keeps that order). */
static void offsets_service(void)
{
    if (g_su.request_offsets && g_ofs_seq != g_su.offsets_req_seq && !g_cal_active) {
        g_ofs_seq = g_su.offsets_req_seq;
        g_cal_n = 0u;
        g_cal_sum[0] = g_cal_sum[1] = g_cal_sum[2] = 0u;
        __DMB();
        g_cal_active = true;
        g_ofs_t0_ms = g_ms;
        return;
    }
    if (!g_cal_active || g_ofs_seq == 0u || g_ofs_done_seq == g_ofs_seq) return;
    if (g_cal_n >= OFFSET_SAMPLES) {
        float avg[3];
        for (int k = 0; k < 3; k++) avg[k] = (float)g_cal_sum[k] / (float)OFFSET_SAMPLES;
        g_ofs_ok = mc_adc_accept_offsets(&g_scale, avg);
    } else if (g_ms - g_ofs_t0_ms > OFFSET_TIMEOUT_MS) {
        g_ofs_ok = false;
    } else {
        return;
    }
    if (!g_ofs_ok) g_bench.platform_faults |= PF_OFFSETS;
    g_ofs_done_seq = g_ofs_seq;
    __DMB();
    g_cal_active = false;
}

void TIM6_DAC_IRQHandler(void)
{
    TIM6->SR = 0u;
    const uint32_t c0 = DWT->CYCCNT;
    const mc_time_us_t now = timebase_now_us();
    g_ms = (uint32_t)(now / 1000u);
    event_log_set_time(g_ms);

    board_inputs_t bi;
    board_read_inputs(&bi);
    for (int i = 0; i < ADC_SLOW_N; i++) g_bench.raw_slow[i] = adc_slow[i];

    mc_slow_inputs_t si;
    memset(&si, 0, sizeof si);
    mc_pedal_out_t po;
    mc_pedal_eval(&g_pedal, mc_adc_volts(&g_scale, adc_slow[ADC_SLOW_THROTTLE_A]),
                  mc_adc_volts(&g_scale, adc_slow[ADC_SLOW_THROTTLE_B]), &po);
    g_bench.pedal_frac_a = po.frac_a;
    g_bench.pedal_frac_b = po.frac_b;
    si.driver.throttle = po.throttle;
    si.driver.throttle_valid = po.valid;
    si.driver.brake = bi.brake;
    si.driver.cancel = bi.cancel;
    si.driver.mode_eco = bi.mode_eco;
    si.driver.arm_switch = bi.arm;
    si.driver.fault_reset = bi.fault_reset;
    si.driver.estop_chain_ok = bi.hw_permit;
    si.driver.driver_present = bi.driver_present;

    si.vbus_V = mc_adc_vbus_V(&g_scale, adc_slow[ADC_SLOW_VBUS], &si.vbus_val);
    /* Battery side (INA228 VBUS on VBAT_SH, shunt on the battery side of the precharge; sheets 01, 06).
     * UNVERIFIED in this revision: never touches the bus and reports nothing. */
    mc_ina228_step(&g_ina, now);
    bool vb_ok = false, vs_ok = false;
    const float v_batt = mc_ina228_vbus_V(&g_ina, now, g_batt_age_us, &vb_ok);
    const float v_shunt = mc_ina228_vshunt_V(&g_ina, now, g_batt_age_us, &vs_ok);
    /* Discharge positive with IN+ on the VBAT_PROT side of the shunt (sheet 06); confirmed at acceptance S6. */
    si.ibatt_A = vs_ok ? v_shunt / g_ina.s.shunt_ohm : NAN;
    si.ibatt_val = vs_ok ? MC_VAL_OK : MC_VAL_MISSING;
    const float fs = 4096.0f; /* the ADC runs at 12 bits; the temperature dividers are ratiometric */
    si.t_fet_degC = mc_ntc_temp_degC(&g_ntc_fet, (float)adc_slow[ADC_SLOW_TEMP_FET] / fs, &si.t_fet_val);
    si.t_motor_degC = mc_ntc_temp_degC(&g_ntc_mot, (float)adc_slow[ADC_SLOW_TEMP_MOTOR] / fs, &si.t_motor_val);

    /* Start-up sequence: precharge bypass, gate-driver wake and configuration, offsets, permission. */
    mc_startup_in_t su;
    memset(&su, 0, sizeof su);
    su.config_ok = g_core.output_permitted;
    su.drv_state = g_drv.state;
    su.drv_ready = mc_drv835x_ready(&g_drv);
    su.ina_state = g_ina.state;
    su.v_batt_V = v_batt;
    su.v_batt_ok = vb_ok;
    su.i_batt_A = si.ibatt_A;
    su.i_batt_ok = vs_ok;
    su.v_link_V = si.vbus_V;
    su.v_link_ok = mc_usable(si.vbus_val);
    su.offsets_done_seq = g_ofs_done_seq;
    su.offsets_ok = g_ofs_ok;
    su.fault_reset_edge = bi.fault_reset && !g_prev_fault_reset;
    su.outputs_off = !pwm_outputs_are_on();
    mc_startup_step(&g_su, 1e-3f, &su);
    if (g_su.clear_driver) mc_drv835x_request_clear(&g_drv);
    mc_drv835x_step(&g_drv, now, g_su.want_driver_awake, bi.drv_nfault);
    offsets_service();
    board_set_precharge_bypass(g_su.bypass && g_core.config_ok);
    if (g_su.pc.state == MC_PC_FAULT) g_bench.platform_faults |= PF_PRECHARGE;

    if (mc_enable_path_check(&g_en, board_drv_enable_commanded(), bi.hw_permit, bi.drv_en_gated)) {
        g_bench.platform_faults |= PF_ENABLE_PATH;
    }
    board_set_drv_enable(GATE_DRIVER_CONFIGURED && g_drv.enable_pin);

    const uint32_t brk = pwm_break_flags();
    si.hw_overcurrent = false; /* no separate hardware overcurrent signal reaches the MCU (hardware review H-OC) */
    si.hw_overvoltage = (brk & PWM_BREAK_OVERVOLT) != 0u;
    si.gate_driver_fault = (brk & (PWM_BREAK_DRIVER | PWM_BREAK_SYSTEM)) != 0u || g_en.fault ||
                           (board_drv_enable_commanded() && bi.drv_nfault);
    si.gate_driver_ready = GATE_DRIVER_CONFIGURED && g_su.gate_driver_ready && !g_en.fault;
    si.watchdog_fault = bi.ext_wdg_reset;
    si.current_offsets_ok = g_ofs_done_seq != 0u && g_ofs_done_seq == g_su.offsets_req_seq && g_ofs_ok;
    si.reset_reason = g_reset_cause;

    can_service(now);
    mc_core_slow_step(&g_core, now, &si);
    can_transmit(now);

    /* Driver fault reset (rising edge) also clears the break latch if its cause is gone; the start-up
     * sequence took the same edge above for its own faults. */
    if (bi.fault_reset && !g_prev_fault_reset) (void)pwm_break_clear();
    g_prev_fault_reset = bi.fault_reset;

    const mc_state_t st = g_core.sm.state;
    if (st != g_prev_state) {
        event_log_add(EVT_TRANSITION, (uint16_t)g_core.last_transition, (uint32_t)st);
        g_prev_state = st;
    }
    g_bench.state = (uint32_t)st;
    g_bench.precharge_state = (uint32_t)g_su.pc.state;
    g_bench.startup = (uint32_t)g_su.state | ((uint32_t)g_su.fault << 8u) | ((uint32_t)g_su.missing << 16u) |
                      ((g_su.attempts > 255u ? 255u : g_su.attempts) << 24u);
    g_bench.devices = (uint32_t)g_drv.state | ((uint32_t)g_drv.error << 4u) | ((uint32_t)g_ina.state << 8u) |
                      ((uint32_t)g_ina.error << 12u) | (g_ina.retries_exhausted ? 1u << 16u : 0u);
    g_bench.inputs = (bi.brake ? BENCH_IN_BRAKE : 0u) | (bi.cancel ? BENCH_IN_CANCEL : 0u) |
                     (bi.mode_eco ? BENCH_IN_MODE_ECO : 0u) | (bi.arm ? BENCH_IN_ARM : 0u) |
                     (bi.fault_reset ? BENCH_IN_FAULT_RESET : 0u) | (bi.driver_present ? BENCH_IN_DRIVER_PRESENT : 0u) |
                     (bi.hw_permit ? BENCH_IN_HW_PERMIT : 0u) | (bi.drv_en_gated ? BENCH_IN_DRV_EN_GATED : 0u) |
                     (bi.drv_nfault ? BENCH_IN_DRV_NFAULT : 0u) | (bi.ext_wdg_reset ? BENCH_IN_EXT_WDG_RESET : 0u) |
                     (bi.ina_alert ? BENCH_IN_INA_ALERT : 0u) | ((brk & PWM_BREAK_DRIVER) ? BENCH_IN_BREAK_DRIVER : 0u) |
                     ((brk & PWM_BREAK_OVERVOLT) ? BENCH_IN_BREAK_OVERVOLT : 0u) |
                     ((brk & PWM_BREAK_SYSTEM) ? BENCH_IN_BREAK_SYSTEM : 0u) |
                     (pwm_outputs_are_on() ? BENCH_IN_OUTPUTS_ON : 0u) | ((uint32_t)hall_code() << 16u);
    board_set_led_fault(st == MC_ST_FAULT_LATCHED);
    if (!TIMING_MARKER) {
        board_set_led_status(((g_ms / (st >= MC_ST_READY && st != MC_ST_FAULT_LATCHED ? 125u : 500u)) & 1u) != 0u);
    }

    /* Watchdogs: this step ran, and the current loop has run since the previous kick. */
    if (g_bench.fast_count != g_fast_at_kick) {
        watchdog_kick();
        g_fast_at_kick = g_bench.fast_count;
    }
    const uint32_t cyc = DWT->CYCCNT - c0; /* wall time: includes the fast interrupts that preempted it */
    if (cyc > g_bench.slow_max_cycles) g_bench.slow_max_cycles = cyc;
    if (timebase_slow_tick_pending()) g_bench.slow_overruns++;
}

/* ------------------------------------------------------------------ stack high-water mark */
#define STACK_PAINT 0x5AA5A55Au
extern uint32_t _stack_limit;

/* Fills the unused stack below the current stack pointer, before interrupts are enabled. */
static void stack_paint(void)
{
    volatile uint32_t *p = &_stack_limit;
    const uint32_t *sp = (const uint32_t *)__get_MSP();
    while (p < sp - 16) *p++ = STACK_PAINT; /* keep 64 bytes below the live frame */
}

/* Bytes from the stack limit up to the deepest word ever written. Run in the main loop (lowest priority). */
static void stack_measure(void)
{
    const volatile uint32_t *p = &_stack_limit;
    const uint32_t *sp = (const uint32_t *)__get_MSP();
    uint32_t n = 0u;
    while (p + n < sp && p[n] == STACK_PAINT) n++;
    if (n * 4u < g_bench.stack_unused_min_bytes) g_bench.stack_unused_min_bytes = n * 4u;
}

/* ------------------------------------------------------------------ start-up */
static void report(const char *k, const char *v)
{
    uart_puts(k);
    uart_puts(": ");
    uart_puts(v);
    uart_puts("\r\n");
}

static void init_converters(void)
{
    const float off[3] = {cfg(MC_P_INVERTER_CURRENT_OFFSET_COUNTS_0), cfg(MC_P_INVERTER_CURRENT_OFFSET_COUNTS_1),
                          cfg(MC_P_INVERTER_CURRENT_OFFSET_COUNTS_2)};
    mc_adc_scale_init(&g_scale, cfg(MC_P_INVERTER_ADC_VREF_V), cfg(MC_P_INVERTER_ADC_BITS), cfg(MC_P_INVERTER_SHUNT_OHM),
                      cfg(MC_P_INVERTER_AMP_GAIN_V_PER_V), cfg(MC_P_SENSING_PHASE_CURRENT_POLARITY), off,
                      cfg(MC_P_SENSING_CURRENT_OFFSET_TOLERANCE_COUNTS), cfg(MC_P_INVERTER_VBUS_DIVIDER_RATIO));
    if (mc_config_has(&g_core.cfg, MC_P_INVERTER_ADC_BITS) && cfg(MC_P_INVERTER_ADC_BITS) != 12.0f) {
        g_scale.current_configured = g_scale.vbus_configured = false; /* the firmware runs the ADC at 12 bits */
        g_bench.platform_faults |= PF_ADC_RESOLUTION;
    }
    mc_ntc_init(&g_ntc_fet, cfg(MC_P_SENSING_FET_NTC_R25_OHM), cfg(MC_P_SENSING_FET_NTC_BETA_K),
                cfg(MC_P_SENSING_FET_NTC_BIAS_OHM));
    mc_ntc_init(&g_ntc_mot, cfg(MC_P_SENSING_MOTOR_NTC_R25_OHM), cfg(MC_P_SENSING_MOTOR_NTC_BETA_K),
                cfg(MC_P_SENSING_MOTOR_NTC_BIAS_OHM));
    mc_pedal_init(&g_pedal, cfg(MC_P_CONTROLS_THROTTLE_A_RELEASED_V), cfg(MC_P_CONTROLS_THROTTLE_A_FULL_V),
                  cfg(MC_P_CONTROLS_THROTTLE_B_RELEASED_V), cfg(MC_P_CONTROLS_THROTTLE_B_FULL_V),
                  cfg(MC_P_CONTROLS_THROTTLE_TRACK_TOLERANCE), cfg(MC_P_CONTROLS_THROTTLE_DIVIDER_RATIO));
    const mc_startup_params_t sp = {
        .fraction = cfg(MC_P_POWER_PRECHARGE_COMPLETE_FRACTION),
        .timeout_s = cfg(MC_P_POWER_PRECHARGE_TIMEOUT_S),
        .uv_trip_V = cfg(MC_P_LIMITS_UNDERVOLTAGE_TRIP_V),
        .ov_trip_V = cfg(MC_P_LIMITS_OVERVOLTAGE_TRIP_V),
        .r_pre_ohm = cfg(MC_P_POWER_PRECHARGE_RESISTOR_OHM),
        .agreement_V = cfg(MC_P_POWER_PRECHARGE_AGREEMENT_V),
        .sample_max_age_s = cfg(MC_P_POWER_BATTERY_SAMPLE_MAX_AGE_S),
        .step_timeout_s = cfg(MC_P_POWER_STARTUP_STEP_TIMEOUT_S),
        .max_attempts = mc_config_has(&g_core.cfg, MC_P_POWER_STARTUP_MAX_ATTEMPTS)
                            ? (uint32_t)cfg(MC_P_POWER_STARTUP_MAX_ATTEMPTS)
                            : 0u};
    mc_startup_init(&g_su, &sp);
    g_batt_age_us = g_su.params_ok ? (uint32_t)(sp.sample_max_age_s * 1.0e6f) : 0u;
    /* No device descriptions and no bus transports in this revision (see the header): both drivers stay
     * UNVERIFIED and never touch ENABLE or the buses. */
    mc_drv835x_init(&g_drv, NULL, NULL, NULL, NULL, 0u);
    mc_ina228_init(&g_ina, NULL, NULL, NULL, NULL, NULL, 0u, 0u);
    g_settle_s = cfg(MC_P_INVERTER_CURRENT_SAMPLE_SETTLE_S);
    /* Unknown switch type: normally open is assumed for the reading, and the calibration is invalid for
     * hardware anyway (controls.brake_switch is required), so the core never drives on that assumption. */
    board_set_brake_switch_nc(cfg(MC_P_CONTROLS_BRAKE_SWITCH) == (float)MC_SWITCH_TYPE_NORMALLY_CLOSED);
}

static void measure_offsets(void)
{
    /* Gate driver disabled (DRV_ENABLE low since reset), so the phase currents are zero. OPEN: whether the
     * DRV8353's current amplifiers run while ENABLE is low is in its datasheet; if they do not, these readings
     * are not the zero-current offsets, the tolerance check fails and the core refuses to arm (a safe failure).
     * Once the driver is configured, the measurement moves to "driver awake, all gates held off". */
    g_cal_n = 0u;
    g_cal_sum[0] = g_cal_sum[1] = g_cal_sum[2] = 0u;
    g_cal_active = true;
    const uint32_t t0 = timebase_us32();
    uint32_t kicked = t0;
    while (g_cal_n < OFFSET_SAMPLES && timebase_us32() - t0 < 500000u) {
        if (timebase_us32() - kicked >= 20000u) {
            watchdog_kick();
            kicked = timebase_us32();
        }
    }
    g_cal_active = false;
    if (g_cal_n == OFFSET_SAMPLES) {
        float avg[3];
        for (int k = 0; k < 3; k++) {
            avg[k] = (float)g_cal_sum[k] / (float)OFFSET_SAMPLES;
            g_bench.offsets_measured[k] = avg[k];
        }
        g_offsets_ok = mc_adc_accept_offsets(&g_scale, avg);
    }
    if (!g_offsets_ok) g_bench.platform_faults |= PF_OFFSETS;
}

int main(void)
{
    board_gpio_init(); /* outputs to their safe levels first, at the 16 MHz reset clock */
    NVIC_SetPriorityGrouping(NVIC_GROUP_ALL_PREEMPT);
    g_bench.fast_margin_min_ticks = UINT32_MAX;
    g_bench.stack_unused_min_bytes = UINT32_MAX;
    stack_paint();
    watchdog_start();
    g_reset_cause = watchdog_reset_cause();
    event_log_init();
    event_log_add(EVT_BOOT, g_reset_cause, event_log_boot_count());

    const clock_status_t clk = system_clock_init();
    watchdog_kick();
    if (!clk.ok) {
        event_log_add(EVT_CLOCK_FAIL, 0u, 0u);
        board_force_safe();
        for (;;) {
            /* no watchdog kick: reset and retry */
        }
    }
    uart_init();
    timebase_init();
    uart_puts("\r\n" IMAGE_NAME SEMMC_GIT_REV "\r\n");
    report("clock", clk.hse ? "160 MHz from 16 MHz crystal" : "160 MHz from HSI16 (no crystal: CAN off)");
    event_log_dump(uart_puts);

    const uint8_t *blob;
    const size_t len = calstore_find(&blob);
    const bool cfg_ok = mc_core_init(&g_core, blob, len, MC_BUILD_HARDWARE, (uint16_t)event_log_boot_count());
    if (!cfg_ok) event_log_add(EVT_CONFIG_REJECTED, (uint16_t)len, 0u);
    report("calibration", len == 0u ? "none in flash (0x0807F000)" : (cfg_ok ? "valid, output permitted" : "rejected"));
    init_converters();
    g_bench.platform_faults |= PF_GATE_DRIVER_NOT_CONFIGURED | PF_BATTERY_METER_NOT_READ;

    if (!adc_init(PRIO_FAST)) g_bench.platform_faults |= PF_ADC_INIT;
    watchdog_kick();

    const float fpwm = cfg(MC_P_INVERTER_PWM_FREQUENCY_HZ), dt = cfg(MC_P_INVERTER_DEADTIME_S);
    const bool pwm_cfg = !BENCH_PWM_TEST && cfg_ok && pwm_init(fpwm, dt, PRIO_BREAK, &g_pwm);
    if (!pwm_cfg) {
        g_bench.platform_faults |= PF_PWM_NOT_CONFIGURED;
        (void)pwm_init(SAMPLING_ONLY_PWM_HZ, SAMPLING_ONLY_DEADTIME_S, PRIO_BREAK, &g_pwm);
    }
    g_bench.f_pwm_Hz = g_pwm.f_pwm_Hz;
    g_bench.deadtime_s = g_pwm.deadtime_s;
    report("pwm", pwm_cfg ? "configured, outputs off" : "sampling only (no valid calibration), outputs off");
    __enable_irq();

    measure_offsets();
    report("current offsets", g_offsets_ok ? "within tolerance" : "not accepted (calibration missing or out of tolerance)");
    g_last_cyc = DWT->CYCCNT;
    g_pwm_drive_allowed = pwm_cfg;

    mc_can_timing_t timing;
    g_can = can_init(clk.hse, cfg_ok, cfg(MC_P_SUPERVISION_CAN_BITRATE_BPS), mc_can_id_base(&g_core), &timing);
    g_bench.can_status = (uint32_t)g_can;
    if (g_can != CAN_ON) g_bench.platform_faults |= PF_CAN_OFF;
    report("can", g_can == CAN_ON ? "on" : "off");
    report("gate driver", "no verified DRV8353 description in this revision: DRV_ENABLE stays low");
    report("battery meter", "no verified INA228 description in this revision: precharge bypass stays open");
    report("start-up", g_su.params_ok ? "parameters valid; inhibited until both devices are verified"
                                      : "inhibited: start-up parameters missing from the calibration");

    timebase_start_slow_tick(PRIO_SLOW);
    if (BENCH_PWM_TEST) {
        report("BENCH PWM TEST", "gate signals switch at the MCU pins; DRV_ENABLE held low; not for a powered bridge");
        const mc_duty_t d = {0.25f, 0.50f, 0.75f};
        pwm_write_duty(&d);
        const uint32_t t0 = timebase_us32();
        while (timebase_us32() - t0 < 1000u) {
            /* let the compare values load at an update event before the outputs come on */
        }
        for (;;) {
            if (pwm_break_flags() == 0u && !pwm_outputs_are_on()) pwm_outputs_on();
            __WFI();
            stack_measure();
        }
    }
    for (;;) {
        __WFI();
        stack_measure();
    }
}
