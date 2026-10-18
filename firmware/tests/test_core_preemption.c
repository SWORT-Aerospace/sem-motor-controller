/* Preemption of the slow step by the current interrupt, emulated deterministically on the host.
 *
 * On the target the fast step (ADC interrupt) preempts the slow step at any instruction. These tests run a
 * real fast step at chosen points inside a real slow step, through the linker's --wrap (built only with GNU
 * ld, CMakeLists.txt):
 *   mc_prot_evaluate  runs after the slow step has read the fast-step event counters and before it
 *                     publishes and acknowledges: the "during acknowledgment" point;
 *   mc_arb_step       runs before the publish: a fast step there must still use the previous command.
 * The fast step is called with phase currents above the software trip, or with valid normal currents. */
#include <math.h>
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_core.h"
#include "test_support.h"

static mc_core_t C;
static int g_oc_in_prot;        /* number of overcurrent fast steps to run inside mc_prot_evaluate */
static int g_fast_in_arb;       /* run one normal fast step inside mc_arb_step */
static mc_fast_outputs_t g_arb_fast_out;
static mc_fast_cmd_t g_arb_pub_seen;

static mc_fast_inputs_t fast_in(float amps)
{
    mc_fast_inputs_t fi;
    memset(&fi, 0, sizeof fi);
    fi.phase.measured_mask = 7u;
    fi.phase.i[0] = amps;
    fi.phase.i[1] = -amps / 2.0f;
    fi.phase.i[2] = -amps / 2.0f;
    fi.hall_code = 1u;
    fi.vbus_V = 48.0f;
    fi.dt = 50e-6f;
    return fi;
}

static void fast_overcurrent_step(void)
{
    mc_fast_inputs_t fi = fast_in(10.0f * C.p.sw_overcurrent_A);
    mc_fast_outputs_t fo;
    mc_core_fast_step(&C, &fi, &fo);
    CHECK(!fo.pwm_enable); /* the fast step turns the outputs off in the same interrupt */
}

static unsigned pending_oc(void)
{
    return atomic_load(&C.fast_oc_events) - atomic_load(&C.fast_oc_ack);
}

void __real_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt);
void __wrap_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt);
void __wrap_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt)
{
    for (; g_oc_in_prot > 0; g_oc_in_prot--) fast_overcurrent_step(); /* the interrupt fires here */
    __real_mc_prot_evaluate(pr, in, dt);
}

void __real_mc_arb_step(mc_arbiter_t *a, const mc_sm_t *sm, const mc_driver_inputs_t *drv,
                        const mc_supervisor_input_t *sup, const mc_arb_meas_t *m, const mc_protection_t *prot,
                        bool hw_trip, float dt);
void __wrap_mc_arb_step(mc_arbiter_t *a, const mc_sm_t *sm, const mc_driver_inputs_t *drv,
                        const mc_supervisor_input_t *sup, const mc_arb_meas_t *m, const mc_protection_t *prot,
                        bool hw_trip, float dt);
void __wrap_mc_arb_step(mc_arbiter_t *a, const mc_sm_t *sm, const mc_driver_inputs_t *drv,
                        const mc_supervisor_input_t *sup, const mc_arb_meas_t *m, const mc_protection_t *prot,
                        bool hw_trip, float dt)
{
    if (g_fast_in_arb) {
        g_fast_in_arb = 0;
        g_arb_pub_seen = C.fast_pub[atomic_load(&C.fast_pub_idx)];
        mc_fast_inputs_t fi = fast_in(0.1f);
        mc_core_fast_step(&C, &fi, &g_arb_fast_out); /* preempts before this slow step publishes */
    }
    __real_mc_arb_step(a, sm, drv, sup, m, prot, hw_trip, dt);
}

static mc_slow_inputs_t slow_in(void)
{
    mc_slow_inputs_t si;
    memset(&si, 0, sizeof si);
    si.gate_driver_ready = true;
    si.current_offsets_ok = true;
    return si;
}

static void init_core(void)
{
    static uint8_t blob[8192];
    const size_t n = load_blob(SEMMC_SYNTH_BLOB, blob, sizeof blob);
    CHECK(mc_core_init(&C, blob, n, MC_BUILD_HOST_SIM, 1u));
    g_oc_in_prot = 0;
    g_fast_in_arb = 0;
}

static bool oc_latched(void) { return (C.prot.latched & MC_FAULT_BIT(MC_F_SW_OVERCURRENT)) != 0u; }

/* Arrival before the slow step: seen, latched and acknowledged by that step. */
static void test_overcurrent_before_slow_step(void)
{
    init_core();
    mc_slow_inputs_t si = slow_in();
    mc_core_slow_step(&C, 1000u, &si);
    CHECK(!oc_latched());
    fast_overcurrent_step();
    CHECK_EQ_INT(pending_oc(), 1);
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(oc_latched());
    CHECK(!C.fast_pub[atomic_load(&C.fast_pub_idx)].pwm_enable);
    CHECK_EQ_INT(pending_oc(), 0);
}

/* Arrival during the slow step, after its read of the counters: not erased by the acknowledgment; the
 * fast step keeps the outputs off, and the next slow step latches it. */
static void test_overcurrent_during_acknowledgment_is_not_lost(void)
{
    init_core();
    mc_slow_inputs_t si = slow_in();
    mc_core_slow_step(&C, 1000u, &si);
    g_oc_in_prot = 1;
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(g_oc_in_prot == 0);
    CHECK(!oc_latched());            /* this step read the counters before the event */
    CHECK_EQ_INT(pending_oc(), 1);   /* kept for the next step */
    mc_fast_inputs_t fi = fast_in(0.1f);
    mc_fast_outputs_t fo;
    mc_core_fast_step(&C, &fi, &fo);
    CHECK(!fo.pwm_enable);           /* outputs stay off while the event is pending */
    mc_core_slow_step(&C, 3000u, &si);
    CHECK(oc_latched());
    CHECK_EQ_INT(pending_oc(), 0);
}

/* A repeated instance of the same fault while the first is being acknowledged: both are counted, the
 * second is still pending after the acknowledgment of the first, and no instance is lost. */
static void test_repeated_overcurrent_during_acknowledgment(void)
{
    init_core();
    mc_slow_inputs_t si = slow_in();
    mc_core_slow_step(&C, 1000u, &si);
    fast_overcurrent_step();          /* first instance, before the slow step */
    g_oc_in_prot = 2;                 /* two more, after the read, before the ack */
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(oc_latched());              /* the first instance latched */
    CHECK_EQ_INT((int)atomic_load(&C.fast_oc_events), 3);
    CHECK_EQ_INT(pending_oc(), 2);    /* the later two survive the acknowledgment of the first */
    mc_core_slow_step(&C, 3000u, &si);
    CHECK_EQ_INT(pending_oc(), 0);
    CHECK(oc_latched());
}

/* Arrival after the slow step has published and acknowledged: pending until the next step. */
static void test_overcurrent_after_slow_step(void)
{
    init_core();
    mc_slow_inputs_t si = slow_in();
    mc_core_slow_step(&C, 1000u, &si);
    CHECK_EQ_INT(pending_oc(), 0);
    fast_overcurrent_step();
    CHECK_EQ_INT(pending_oc(), 1);
    CHECK(!oc_latched());
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(oc_latched());
    CHECK_EQ_INT(pending_oc(), 0);
}

/* A fast step that preempts the slow step before its publish reads the previously published buffer, from the
 * index the previous publish stored; the slow step then writes the other buffer and switches the index. */
static void test_fast_step_before_publish_uses_previous_command(void)
{
    init_core();
    mc_slow_inputs_t si = slow_in();
    mc_core_slow_step(&C, 1000u, &si);
    const unsigned idx_before = atomic_load(&C.fast_pub_idx);
    const mc_fast_cmd_t published = C.fast_pub[idx_before];
    g_fast_in_arb = 1;
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(g_fast_in_arb == 0);
    CHECK(memcmp(&g_arb_pub_seen, &published, sizeof published) == 0);
    CHECK(g_arb_fast_out.pwm_enable == published.pwm_enable);
    CHECK(atomic_load(&C.fast_pub_idx) == 1u - idx_before);   /* the other buffer now selected */
    CHECK(memcmp(&C.fast_pub[atomic_load(&C.fast_pub_idx)], &C.fast_cmd, sizeof C.fast_cmd) == 0);
}

int main(void)
{
    RUN(test_overcurrent_before_slow_step);
    RUN(test_overcurrent_during_acknowledgment_is_not_lost);
    RUN(test_repeated_overcurrent_during_acknowledgment);
    RUN(test_overcurrent_after_slow_step);
    RUN(test_fast_step_before_publish_uses_previous_command);
    TEST_MAIN_END();
}
