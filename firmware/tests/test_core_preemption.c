/* Preemption of the slow step by the current interrupt, emulated deterministically on the host.
 *
 * On the target the fast step (ADC interrupt) preempts the slow step at any instruction. The case that
 * matters is a software overcurrent the fast step raises after the slow step has read the flags but
 * before it clears them: the event must survive and latch, not be erased. The linker's --wrap replaces
 * mc_prot_evaluate (called between that read and the clear) with a version that raises the flag first,
 * exactly as the interrupt would. Built only with GNU ld (CMakeLists.txt). */
#include <string.h>

#include "mc_test.h"
#include "semmc/mc_core.h"
#include "test_support.h"

static mc_core_t C;
static int g_preempt_once;

void __real_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt);
void __wrap_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt);
void __wrap_mc_prot_evaluate(mc_protection_t *pr, const mc_prot_inputs_t *in, float dt)
{
    if (g_preempt_once) {
        g_preempt_once = 0;
        C.fast_overcurrent = true; /* the current interrupt fires here */
    }
    __real_mc_prot_evaluate(pr, in, dt);
}

static void test_overcurrent_raised_during_slow_step_is_not_lost(void)
{
    static uint8_t blob[8192];
    const size_t n = load_blob(SEMMC_SYNTH_BLOB, blob, sizeof blob);
    CHECK(mc_core_init(&C, blob, n, MC_BUILD_HOST_SIM, 1u));
    mc_slow_inputs_t si;
    memset(&si, 0, sizeof si);
    si.gate_driver_ready = true;
    si.current_offsets_ok = true;
    mc_core_slow_step(&C, 1000u, &si);
    CHECK(!C.fast_overcurrent);
    CHECK((C.prot.latched & MC_FAULT_BIT(MC_F_SW_OVERCURRENT)) == 0u);

    g_preempt_once = 1;
    mc_core_slow_step(&C, 2000u, &si);
    CHECK(g_preempt_once == 0);
    CHECK(C.fast_overcurrent); /* raised after this step's read: kept for the next step */

    mc_core_slow_step(&C, 3000u, &si);
    CHECK(C.prot.latched & MC_FAULT_BIT(MC_F_SW_OVERCURRENT));
    CHECK(!C.fast_pub[C.fast_pub_idx].pwm_enable);
    CHECK(!C.fast_overcurrent); /* observed, latched, then cleared */
}

int main(void)
{
    RUN(test_overcurrent_raised_during_slow_step_is_not_lost);
    TEST_MAIN_END();
}
