/* HOST-ONLY executable: closed-loop simulation, log replay, and an interactive
 * lockstep mode for co-simulation with a Python supervisor.
 *
 *   semmc_host --cal cal.bin --log scenario.log --out result.csv [--frames tx.log]
 *   semmc_host --cal cal.bin --interactive --out result.csv [--frames tx.log]
 *   common options: [--no-plant] [--build sim|hardware] [--decimate N] [--boot-id N]
 *
 * Event format "semmc-log v1" (one per line, nondecreasing time):
 *   <t_us> IO throttle=<f> throttle_valid=<0|1> brake=.. cancel=.. eco=.. arm=..
 *             reset=.. estop_ok=.. present=..          (any subset; others held)
 *   <t_us> CAN <id hex> <16 hex chars>                  (frame received by controller)
 *   <t_us> HW gdr=<0|1> gdf=<0|1> oc=<0|1> ov=<0|1> wdg=<0|1> offsets_ok=<0|1>
 *   <t_us> MEAS vbus=<f> ibatt=<f|nan> tfet=<f|nan> tmotor=<f|nan> hall=<0..7>  (--no-plant)
 *   <t_us> FAULT bias_a= bias_b= bias_c= miss_a= miss_b= miss_c= hall_stuck= hall_code=
 *                vbus_nan= tfet_nan= tmotor_nan= ibatt_bias= ibatt_missing= tfet_offset=
 *                grade= extra_load= hw_oc= gdf=
 *   <t_us> BUSOFF <0|1>
 *   <t_us> RESET                      (controller reboot; plant state continues)
 *   <t_us> STEP                       (interactive: simulate through t, then report)
 *   <t_us> END
 * Interactive output per STEP: controller TX frames as "<t> CAN <id> <hex>", one
 * "<t> STATE ..." line, then "<t> END_STEP".
 *
 * Test tooling only: uses stdio and malloc; nothing here is linked into the
 * portable core.
 */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "semmc/mc_core.h"
#include "semmc_protocol.h"
#include "sim_plant.h"

typedef struct {
    uint64_t t_us;
    char kind[8];
    char rest[192];
} event_t;

typedef struct {
    float vbus, ibatt, tfet, tmotor;
    uint8_t hall;
} meas_override_t;

typedef struct {
    /* config */
    uint8_t *blob;
    size_t blob_len;
    mc_build_kind_t build;
    bool plant_on;
    bool plant_params;
    int decimate;
    unsigned boot_id;
    /* objects */
    mc_core_t core;
    mc_config_t pcfg;
    mc_params_t pp;
    sim_plant_t plant;
    /* io state */
    mc_driver_inputs_t drv;
    mc_slow_inputs_t si;
    meas_override_t mo;
    mc_duty_t duty;
    bool pwm;
    bool reset_pending;
    uint64_t t;           /* next tick time */
    uint32_t fast_us, slow_us;
    uint64_t slow_count;
    FILE *fo, *ff, *fstep;
} sim_t;

static uint8_t *read_file(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    const long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = malloc((size_t)n + 1u);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    buf[n] = 0;
    *len = (size_t)n;
    return buf;
}

static int parse_event(const char *line, event_t *e)
{
    while (*line == ' ' || *line == '\t') line++;
    if (*line == '#' || *line == '\0' || *line == '\r' || *line == '\n') return 0;
    memset(e, 0, sizeof *e);
    unsigned long long t = 0;
    int consumed = 0;
    if (sscanf(line, "%llu %7s %n", &t, e->kind, &consumed) < 2) return -1;
    e->t_us = t;
    strncpy(e->rest, line + consumed, sizeof e->rest - 1);
    size_t n = strlen(e->rest);
    while (n > 0 && (e->rest[n - 1] == '\n' || e->rest[n - 1] == '\r')) e->rest[--n] = '\0';
    return 1;
}

static int kv_float(const char *rest, const char *key, float *out)
{
    char pat[48];
    snprintf(pat, sizeof pat, "%s=", key);
    const char *p = strstr(rest, pat);
    while (p && p != rest && p[-1] != ' ') p = strstr(p + 1, pat);
    if (!p) return 0;
    p += strlen(pat);
    if (strncmp(p, "nan", 3) == 0) {
        *out = NAN;
        return 1;
    }
    *out = strtof(p, NULL);
    return 1;
}

static int kv_bool(const char *rest, const char *key, bool *out)
{
    float v;
    if (!kv_float(rest, key, &v)) return 0;
    *out = v != 0.0f;
    return 1;
}

static int hexbytes(const char *s, uint8_t out[8])
{
    for (int k = 0; k < 8; k++) {
        unsigned v;
        if (sscanf(s + 2 * k, "%2x", &v) != 1) return 0;
        out[k] = (uint8_t)v;
    }
    return 1;
}

static void apply_event(sim_t *S, const event_t *e)
{
    if (!strcmp(e->kind, "IO")) {
        mc_driver_inputs_t *d = &S->drv;
        kv_float(e->rest, "throttle", &d->throttle);
        kv_bool(e->rest, "throttle_valid", &d->throttle_valid);
        kv_bool(e->rest, "brake", &d->brake);
        kv_bool(e->rest, "cancel", &d->cancel);
        kv_bool(e->rest, "eco", &d->mode_eco);
        kv_bool(e->rest, "arm", &d->arm_switch);
        kv_bool(e->rest, "reset", &d->fault_reset);
        kv_bool(e->rest, "estop_ok", &d->estop_chain_ok);
        kv_bool(e->rest, "present", &d->driver_present);
    } else if (!strcmp(e->kind, "CAN")) {
        unsigned id;
        char hex[32];
        uint8_t d[8];
        if (sscanf(e->rest, "%x %31s", &id, hex) == 2 && strlen(hex) == 16 && hexbytes(hex, d)) {
            mc_core_on_can_rx(&S->core, S->t, id, d, 8u);
        }
    } else if (!strcmp(e->kind, "HW")) {
        kv_bool(e->rest, "gdr", &S->si.gate_driver_ready);
        kv_bool(e->rest, "gdf", &S->si.gate_driver_fault);
        kv_bool(e->rest, "oc", &S->si.hw_overcurrent);
        kv_bool(e->rest, "ov", &S->si.hw_overvoltage);
        kv_bool(e->rest, "wdg", &S->si.watchdog_fault);
        kv_bool(e->rest, "offsets_ok", &S->si.current_offsets_ok);
    } else if (!strcmp(e->kind, "MEAS")) {
        float h = 0.0f;
        kv_float(e->rest, "vbus", &S->mo.vbus);
        kv_float(e->rest, "ibatt", &S->mo.ibatt);
        kv_float(e->rest, "tfet", &S->mo.tfet);
        kv_float(e->rest, "tmotor", &S->mo.tmotor);
        if (kv_float(e->rest, "hall", &h)) S->mo.hall = (uint8_t)h;
    } else if (!strcmp(e->kind, "FAULT") && S->plant_params) {
        sim_fault_t *pf = &S->plant.fault;
        float v;
        if (kv_float(e->rest, "bias_a", &v)) pf->current_bias_A[0] = v;
        if (kv_float(e->rest, "bias_b", &v)) pf->current_bias_A[1] = v;
        if (kv_float(e->rest, "bias_c", &v)) pf->current_bias_A[2] = v;
        kv_bool(e->rest, "miss_a", &pf->phase_missing[0]);
        kv_bool(e->rest, "miss_b", &pf->phase_missing[1]);
        kv_bool(e->rest, "miss_c", &pf->phase_missing[2]);
        kv_bool(e->rest, "hall_stuck", &pf->hall_stuck);
        if (kv_float(e->rest, "hall_code", &v)) pf->hall_stuck_code = (uint8_t)v;
        kv_bool(e->rest, "vbus_nan", &pf->vbus_sensor_nan);
        kv_bool(e->rest, "tfet_nan", &pf->tfet_sensor_nan);
        kv_bool(e->rest, "tmotor_nan", &pf->tmotor_sensor_nan);
        if (kv_float(e->rest, "ibatt_bias", &v)) pf->ibatt_bias_A = v;
        kv_bool(e->rest, "ibatt_missing", &pf->ibatt_missing);
        if (kv_float(e->rest, "tfet_offset", &v)) pf->tfet_offset_degC = v;
        if (kv_float(e->rest, "grade", &v)) pf->grade_rad = v;
        if (kv_float(e->rest, "extra_load", &v)) pf->extra_load_N = v;
        kv_bool(e->rest, "hw_oc", &pf->hw_overcurrent);
        kv_bool(e->rest, "gdf", &pf->gate_driver_fault);
    } else if (!strcmp(e->kind, "BUSOFF")) {
        mc_core_on_can_bus_off(&S->core, atoi(e->rest) != 0);
    } else if (!strcmp(e->kind, "RESET")) {
        S->reset_pending = true;
    }
}

static void write_row(sim_t *S)
{
    mc_core_t *c = &S->core;
    sim_plant_t *pl = &S->plant;
    const bool po = S->plant_on;
    fprintf(S->fo,
            "%.4f,%s,%d,%d,%.5f,%.5f,%u,%.4f,%.4f,%.4f,%.4f,%.5f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.3f,%.3f,%.4f,"
            "%u,%u,%u,%u,%d,%.4f,%u,%d,%d,%u\n",
            (double)S->t * 1e-6, mc_state_name(c->sm.state), (int)c->sm.owner, (int)c->last_transition,
            (double)c->arb.requested_Nm, (double)c->arb.accepted_Nm, (unsigned)c->arb.reason,
            (double)c->fast_cmd.iq_ref_A, (double)c->iq_meas_A, (double)c->id_meas_A, (double)c->speed_mech_rad_s,
            po ? sim_plant_vehicle_speed(pl) : 0.0, po ? pl->s_m : 0.0, (double)S->si.vbus_V, (double)S->si.ibatt_A,
            (double)c->p_batt_W, c->energy_J, po ? pl->energy_J : 0.0, (double)S->si.t_fet_degC,
            (double)S->si.t_motor_degC, (double)c->prot.derate, (unsigned)c->prot.latched,
            (unsigned)c->prot.first_fault, (unsigned)c->sup.req_val,
            (unsigned)(c->sess.established ? 2 : (c->sess.hello_seen ? 1 : 0)), (int)S->pwm, (double)c->csia.trust,
            (unsigned)mc_csia_status(&c->csia, S->t), po ? (int)pl->rectifying : 0, (int)c->pc.kcl_available,
            (unsigned)c->pc.measured_mask);
}

/* One fast tick (and the slow step when due) at time S->t. */
static void tick(sim_t *S)
{
    if (S->reset_pending) {
        S->boot_id = (S->boot_id * 2654435761u + 1u) & 0xFFFFu;
        (void)mc_core_init(&S->core, S->blob, S->blob_len, S->build, (uint16_t)S->boot_id);
        S->pwm = false;
        S->reset_pending = false;
    }
    sim_sensors_t sens;
    memset(&sens, 0, sizeof sens);
    if (S->plant_on) {
        sim_plant_sense(&S->plant, &S->duty, S->pwm, &sens);
    } else {
        sens.phase.measured_mask = 7u;
        sens.hall_code = S->mo.hall;
        sens.vbus_V = S->mo.vbus;
        sens.vbus_valid = mc_isfinite(S->mo.vbus);
        sens.ibatt_A = S->mo.ibatt;
        sens.ibatt_valid = mc_isfinite(S->mo.ibatt);
        sens.t_fet_degC = S->mo.tfet;
        sens.t_fet_valid = mc_isfinite(S->mo.tfet);
        sens.t_mot_degC = S->mo.tmotor;
        sens.t_mot_valid = mc_isfinite(S->mo.tmotor);
    }
    const bool plant_hw_oc = S->plant_params && S->plant.fault.hw_overcurrent;
    const bool plant_gdf = S->plant_params && S->plant.fault.gate_driver_fault;
    mc_fast_inputs_t fi;
    fi.phase = sens.phase;
    fi.hall_code = sens.hall_code;
    fi.vbus_V = sens.vbus_V;
    fi.dt = (float)S->fast_us * 1e-6f;
    fi.hw_trip = S->si.hw_overcurrent || S->si.hw_overvoltage || S->si.gate_driver_fault || plant_hw_oc || plant_gdf;
    mc_fast_outputs_t fout;
    mc_core_fast_step(&S->core, &fi, &fout);
    S->pwm = fout.pwm_enable && !fi.hw_trip;
    S->duty = fout.duty;
    if (S->plant_on) {
        const uint32_t sub = 2u;
        for (uint32_t s = 0; s < sub; s++)
            sim_plant_step(&S->plant, S->pwm, &S->duty, (double)S->fast_us * 1e-6 / (double)sub);
    }
    if (S->t % S->slow_us == 0u) {
        mc_slow_inputs_t si = S->si;
        si.driver = S->drv;
        si.vbus_V = sens.vbus_V;
        si.vbus_val = sens.vbus_valid ? MC_VAL_OK : MC_VAL_INVALID;
        si.ibatt_A = sens.ibatt_A;
        si.ibatt_val = sens.ibatt_valid ? MC_VAL_OK : MC_VAL_MISSING;
        si.t_fet_degC = sens.t_fet_degC;
        si.t_fet_val = sens.t_fet_valid ? MC_VAL_OK : MC_VAL_INVALID;
        si.t_motor_degC = sens.t_mot_degC;
        si.t_motor_val = sens.t_mot_valid ? MC_VAL_OK : MC_VAL_INVALID;
        si.hw_overcurrent = si.hw_overcurrent || plant_hw_oc;
        si.gate_driver_fault = si.gate_driver_fault || plant_gdf;
        S->si.vbus_V = si.vbus_V;
        S->si.ibatt_A = si.ibatt_A;
        S->si.t_fet_degC = si.t_fet_degC;
        S->si.t_motor_degC = si.t_motor_degC;
        mc_core_slow_step(&S->core, S->t, &si);
        uint32_t id;
        uint8_t d[8];
        while (mc_core_can_tx_poll(&S->core, S->t, &id, d)) {
            char line[64];
            int n = snprintf(line, sizeof line, "%llu CAN %03X ", (unsigned long long)S->t, id);
            for (int b = 0; b < 8; b++) n += snprintf(line + n, sizeof line - (size_t)n, "%02X", d[b]);
            if (S->ff) fprintf(S->ff, "%s\n", line);
            if (S->fstep) fprintf(S->fstep, "%s\n", line);
        }
        if (S->decimate > 0 && (S->slow_count % (uint64_t)S->decimate) == 0u) write_row(S);
        S->slow_count++;
    }
    S->t += S->fast_us;
}

static void report_state(sim_t *S, uint64_t t)
{
    mc_core_t *c = &S->core;
    fprintf(S->fstep, "%llu STATE %s %.5f %.5f %u %.5f %.4f %.4f %u %u\n", (unsigned long long)t,
            mc_state_name(c->sm.state), (double)c->arb.accepted_Nm, (double)c->arb.requested_Nm,
            (unsigned)c->arb.reason, S->plant_on ? sim_plant_vehicle_speed(&S->plant) : 0.0,
            S->plant_on ? S->plant.s_m : 0.0, S->plant_on ? S->plant.energy_J : 0.0, (unsigned)c->prot.latched,
            (unsigned)c->sess.tag);
    fprintf(S->fstep, "%llu END_STEP\n", (unsigned long long)t);
    fflush(S->fstep);
}

int main(int argc, char **argv)
{
    const char *cal = NULL, *log = NULL, *out = NULL, *frames = NULL;
    bool interactive = false;
    static sim_t S;
    memset(&S, 0, sizeof S);
    S.plant_on = true;
    S.build = MC_BUILD_HOST_SIM;
    S.decimate = 10;
    S.boot_id = 0x1234u;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--cal") && i + 1 < argc) cal = argv[++i];
        else if (!strcmp(argv[i], "--log") && i + 1 < argc) log = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) out = argv[++i];
        else if (!strcmp(argv[i], "--frames") && i + 1 < argc) frames = argv[++i];
        else if (!strcmp(argv[i], "--interactive")) interactive = true;
        else if (!strcmp(argv[i], "--no-plant")) S.plant_on = false;
        else if (!strcmp(argv[i], "--build") && i + 1 < argc) S.build = !strcmp(argv[++i], "hardware") ? MC_BUILD_HARDWARE : MC_BUILD_HOST_SIM;
        else if (!strcmp(argv[i], "--decimate") && i + 1 < argc) S.decimate = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--boot-id") && i + 1 < argc) S.boot_id = (unsigned)strtoul(argv[++i], NULL, 0);
        else {
            fprintf(stderr, "usage: %s --cal cal.bin (--log scenario.log | --interactive) --out out.csv [--frames tx.log] "
                            "[--no-plant] [--build sim|hardware] [--decimate N] [--boot-id N]\n", argv[0]);
            return 2;
        }
    }
    if (!cal || !out || (!log && !interactive)) {
        fprintf(stderr, "missing --cal/--out and one of --log/--interactive\n");
        return 2;
    }
    S.blob = read_file(cal, &S.blob_len);
    if (!S.blob) {
        fprintf(stderr, "cannot read %s\n", cal);
        return 2;
    }
    const bool cfg_ok = mc_core_init(&S.core, S.blob, S.blob_len, S.build, (uint16_t)S.boot_id);
    mc_cfg_report_t rep;
    mc_cfg_report_clear(&rep);
    S.plant_params = mc_config_parse_blob(S.blob, S.blob_len, &S.pcfg, &rep) && mc_config_derive(&S.pcfg, &S.pp);
    if (S.plant_on && !S.plant_params) {
        fprintf(stderr, "plant needs a sim-valid configuration\n");
        return 2;
    }
    if (S.plant_params) sim_plant_init(&S.plant, &S.pp);
    S.fo = fopen(out, "w");
    S.ff = frames ? fopen(frames, "w") : NULL;
    if (!S.fo) return 2;
    fprintf(S.fo, "t_s,state,owner,transition,requested_Nm,accepted_Nm,reason,iq_ref_A,iq_meas_A,id_meas_A,"
                  "speed_mech_rad_s,v_mps,s_m,vbus_V,ibatt_A,p_batt_W,energy_ctrl_J,energy_plant_J,t_fet_degC,"
                  "t_motor_degC,derate,faults_latched,first_fault,sup_req_val,sup_link,pwm_enable,csia_trust,"
                  "csia_val,rectifying,kcl_available,meas_mask\n");
    if (S.ff) fprintf(S.ff, "# semmc-log v1 (controller TX)\n");
    S.fast_us = S.plant_params ? (uint32_t)lround(1e6 / (double)S.pp.pwm_frequency_Hz) : 50u;
    if (1000u % S.fast_us != 0u) {
        fprintf(stderr, "PWM period must divide 1 ms in this host tool\n");
        return 2;
    }
    S.slow_us = 1000u;
    S.drv = (mc_driver_inputs_t){0.0f, true, false, false, false, false, false, true, true};
    S.si.gate_driver_ready = true;
    S.si.current_offsets_ok = true;
    S.mo = (meas_override_t){46.0f, 0.0f, 30.0f, 30.0f, 1u};
    S.duty = (mc_duty_t){0.5f, 0.5f, 0.5f};

    size_t nev = 0;
    if (!interactive) {
        size_t len = 0;
        char *text = (char *)read_file(log, &len);
        if (!text) return 2;
        size_t cap = 1024;
        event_t *ev = malloc(cap * sizeof *ev);
        char *save = NULL;
        for (char *line = strtok_r(text, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
            event_t e;
            const int r = parse_event(line, &e);
            if (r < 0 || (r > 0 && nev > 0 && e.t_us < ev[nev - 1].t_us)) {
                fprintf(stderr, "bad or out-of-order log line: %s\n", line);
                return 2;
            }
            if (r == 0) continue;
            if (nev == cap) ev = realloc(ev, (cap *= 2) * sizeof *ev);
            ev[nev++] = e;
        }
        free(text);
        const uint64_t t_end = nev ? ev[nev - 1].t_us : 0u;
        size_t k = 0;
        while (S.t <= t_end) {
            while (k < nev && ev[k].t_us <= S.t) apply_event(&S, &ev[k++]);
            tick(&S);
        }
        free(ev);
    } else {
        S.fstep = stdout;
        char line[256];
        while (fgets(line, sizeof line, stdin)) {
            event_t e;
            const int r = parse_event(line, &e);
            if (r < 0) {
                fprintf(stderr, "bad line: %s", line);
                return 2;
            }
            if (r == 0) continue;
            nev++;
            if (!strcmp(e.kind, "END")) break;
            if (!strcmp(e.kind, "STEP")) {
                while (S.t <= e.t_us) tick(&S);
                report_state(&S, e.t_us);
                continue;
            }
            apply_event(&S, &e); /* applied at the current simulation time */
        }
    }
    fclose(S.fo);
    if (S.ff) fclose(S.ff);
    mc_core_t *c = &S.core;
    fprintf(interactive ? stderr : stdout,
            "config_ok=%d events=%zu final_state=%s energy_ctrl_J=%.3f energy_plant_J=%.3f tx_frames=%u "
            "rx_frames=%u rx_crc_fail=%u rx_tag_mismatch=%u\n",
            (int)cfg_ok, nev, mc_state_name(c->sm.state), c->energy_J, S.plant_on ? S.plant.energy_J : 0.0,
            c->can.tx_frames, c->can.rx_frames, c->can.rx_crc_fail, c->can.rx_tag_mismatch);
    free(S.blob);
    return 0;
}
