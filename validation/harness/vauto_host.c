/*
 * Native boundary tests for the unchanged Custom VAuto wrapper.
 *
 * The real wrapper also includes real my_asv.c and feat_triggercycle.c. The
 * tracker records, settings, scheduler list and stock limiter are host fixtures.
 * In particular the limiter records its INPUT; it does not simulate ResMed's
 * limiter or a blower. No pressure here is a delivered-pressure measurement.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Adapt declarations, not numeric logic. ARM half storage stays 16 bits. */
#define __fp16 _Float16
#define size_t firmware_size_t
#define malloc firmware_malloc
#define snprintf firmware_snprintf
#define pid_t firmware_pid_t
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-variable"
#include "../../patches/wrapper_limit_max_pdiff.c"
#pragma GCC diagnostic pop
#undef pid_t
#undef snprintf
#undef malloc
#undef size_t
#undef __fp16

_Static_assert(sizeof(float16) == 2, "host adaptation must preserve half storage");
_Static_assert(sizeof(float) == 4, "fixtures require binary32-sized float");

float fvars[256];
int ivars[256];

enum { SET_ENABLED = 0x100, SET_TC, SET_ASV_MAX, SET_SENS, SET_EPS, SET_SHAPE };
const unsigned short wrapper_limit_max_pdiff_toggle_var_id = SET_ENABLED;
const unsigned short wrapper_limit_max_pdiff_triggercycle_var_id = SET_TC;
const unsigned short wrapper_limit_max_pdiff_asv_max_var_id = SET_ASV_MAX;
const unsigned short wrapper_limit_max_pdiff_asv_sens_var_id = SET_SENS;
const unsigned short wrapper_limit_max_pdiff_eps_var_id = SET_EPS;
const unsigned short wrapper_limit_max_pdiff_exhale_shape_var_id = SET_SHAPE;

static therapy_worker *manager[5];
static breath_tracking_t tracker;
static void *allocation;
static unsigned allocation_calls, append_calls;
static int mock_error, pending_callback_id;
static int settings[6];
static int limiter_calls;
static float limiter_ps, limiter_reference, limiter_request;
static const float limiter_sentinel = 17.125f;
static FILE *trace;
static unsigned passed, failed;

void *firmware_malloc(unsigned bytes)
{
    ++allocation_calls;
    if (allocation) {
        mock_error = 1;
        return NULL;
    }
    allocation = malloc(bytes);
    if (!allocation) {
        fputs("host allocation failed\n", stderr);
        exit(2);
    }
    return allocation;
}

void *therapy_manager_get(void) { return manager; }

void therapy_worker_append(therapy_worker *node, int group)
{
    if (group != 2 || !node) {
        mock_error = 1;
        return;
    }
    therapy_worker **tail = &manager[4];
    while (*tail) tail = &(*tail)->next;
    node->next = NULL;
    *tail = node;
    ++append_calls;
}

int variable_get_by_id(int id)
{
    if (id < SET_ENABLED || id > SET_SHAPE) {
        mock_error = 1;
        return 0;
    }
    if (id == pending_callback_id) {
        pending_callback_id = 0;
        custom_breath_settings_changed();
    }
    return settings[id - SET_ENABLED];
}

/* A constant-pressure fixture, not a test of the production history detector. */
bool is_cmd_ipap_constant(history_t *hist)
{
    if (hist != &tracker.hist) mock_error = 1;
    return true;
}

void pressure_limit_max_difference(void)
{
    ++limiter_calls;
    limiter_ps = *cmd_ps;
    limiter_reference = *cmd_epap_ramp;
    limiter_request = limiter_reference + limiter_ps;
    *cmd_ipap = limiter_sentinel;  /* Verify the wrapper preserves callback output. */
}

static int near(float observed, float expected)
{
    return isfinite(observed) && fabsf(observed - expected) <= 0.0001f;
}

static void check(const char *id, int ok, const char *description)
{
    printf("CASE|%s|%s|%s\n", id, ok ? "PASS" : "FAIL", description);
    if (ok) ++passed;
    else ++failed;
}

static void reset_fixture(void)
{
    free(allocation);
    allocation = NULL;
    memset(manager, 0, sizeof(manager));
    memset(&tracker, 0, sizeof(tracker));
    memset(fvars, 0, sizeof(fvars));
    memset(ivars, 0, sizeof(ivars));
    memset(settings, 0, sizeof(settings));
    allocation_calls = append_calls = 0;
    mock_error = pending_callback_id = 0;
    settings[SET_ENABLED - SET_ENABLED] = 1;
    settings[SET_TC - SET_ENABLED] = 1;
    settings[SET_SENS - SET_ENABLED] = 2;
    settings[SET_SHAPE - SET_ENABLED] = 3;  /* Linear expiration; EPS/boost initially zero. */
    vauto_ps = 4.0f;
    vauto_reference_max = 18.0f; /* Selected Max IPAP 20, nominal PS 4. */
    vauto_reference_min = 10.0f;
    *cmd_epap_ramp = 10.0f;
    *cmd_ps = 2.0f;
    fvars[0x7] = 4.8f;
    fvars[0x8] = 0.5f;
    ivars[0x12] = MODE_VAUTO;
    ivars[0x6f] = MODE_VAUTO;
    tracker.tr.st_valid_sample = true;
    tracker.tr.recent.ti = 1.2f;
    tracker.tr.recent.te = 0.8f;
    tracker.tr.current.inh_maxflow = 25.0f;
}

static breath_controller_t *attach(void)
{
    custom_breath_attach_prepare(&tracker);
    custom_breath_attach_finish(&tracker);
    return find_breath_controller();
}

static breath_controller_t *begin(int enabled)
{
    reset_fixture();
    settings[SET_ENABLED - SET_ENABLED] = enabled;
    breath_controller_t *s = attach();
    breath_mode(&s->prepare);
    breath_prepare(&s->prepare);
    return s;
}

static void accept_inspiration(breath_controller_t *s)
{
    tracker.tr.st_inhaling = true;
    tracker.tr.st_just_started = true;
    breath_finish(&s->finish);
}

static const char *state_name(int state)
{
    switch (state) {
    case VAUTO_OFF: return "OFF";
    case VAUTO_WAIT_INSPIRATION: return "WAIT_INSPIRATION";
    case VAUTO_ACTIVE: return "ACTIVE";
    case -1: return "NO_CONTROLLER";
    default: return "UNKNOWN";
    }
}

/* Wrapper identity requirements: one callback, same input restored, output retained. */
static int invoke(const char *scenario, unsigned tick)
{
    const float original = *cmd_ps;
    const float stock_request = *cmd_epap_ramp + original;
    limiter_calls = 0;
    *cmd_ipap = -123.0f;
    start();
    const int identity = limiter_calls == 1 &&
        memcmp(cmd_ps, &original, sizeof(original)) == 0 &&
        near(*cmd_ipap, limiter_sentinel) && !mock_error;
    if (trace && scenario) {
        const breath_controller_t *s = find_breath_controller();
        fprintf(trace, "%s,%u,%s,%.9g,%.9g,%.9g,%.9g\n", scenario, tick,
                state_name(s ? (int)s->vauto_state : -1), stock_request, limiter_request,
                vauto_reference_max + vauto_ps / 2.0f,
                limiter_request - stock_request);
    }
    return identity;
}

static void lifecycle_tests(void)
{
    reset_fixture();
    custom_breath_settings_changed();
    int ok = invoke(NULL, 0) && near(limiter_request, 12.0f) &&
        allocation_calls == 0 && custom_tc_decision(0) == TC_STOCK &&
        custom_tc_decision(1) == TC_STOCK;
    check("VAUTO-01-no-controller", ok,
          "no controller: stock input forwarded; startup setting callback does not allocate");

    breath_controller_t *s = attach();
    custom_breath_attach_prepare(&tracker);
    custom_breath_attach_finish(&tracker);
    ok = allocation_calls == 1 && append_calls == 2 && s->tracking == &tracker &&
        s->prepare.next == &s->finish && s->finish.next == NULL && !mock_error;
    check("VAUTO-02-idempotent-attachment", ok, "one allocation and two worker nodes");

    s = begin(0);
    ok = s->vauto_state == VAUTO_OFF;
    for (int i = -2; i <= 2; i += 2) {
        *cmd_ps = (float)i;
        ok &= invoke("disabled", (unsigned)(i + 2)) && near(limiter_ps, (float)i);
    }
    check("VAUTO-03-disabled-passthrough", ok,
          "Custom VAuto Off forwards all three tested waveform positions unchanged");

    s = begin(1);
    tracker.tr.st_inhaling = true;
    tracker.tr.st_just_started = false;
    breath_finish(&s->finish);
    ok = s->vauto_state == VAUTO_WAIT_INSPIRATION;
    tracker.tr.st_inhaling = false;
    tracker.tr.st_just_started = true;
    breath_finish(&s->finish);
    ok &= s->vauto_state == VAUTO_WAIT_INSPIRATION &&
          custom_tc_decision(0) == TC_STOCK && invoke("waiting", 0) && near(limiter_ps, 2.0f);
    check("VAUTO-04-wait-for-new-inspiration", ok,
          "retained inspiration and a new expiration cannot activate the wrapper");

    accept_inspiration(s);
    check("VAUTO-05-activation", s->vauto_state == VAUTO_ACTIVE,
          "accepted new inspiration activates a waiting controller");

    s->asv.pid.cumulative_error = 1.0f;
    s->features.final_ips = 8.0f;
    vauto_ps = 0.0f;
    breath_prepare(&s->prepare);
    check("VAUTO-06-zero-ps", s->vauto_state == VAUTO_OFF &&
          near(s->asv.pid.cumulative_error, 0.0f) && near(s->features.final_ips, 0.0f) &&
          invoke(NULL, 0) && near(limiter_ps, 2.0f),
          "zero PS disables shaping, clears previous demand and forwards input");

    s = begin(1);
    accept_inspiration(s);
    s->asv.pid.cumulative_error = 1.0f;
    s->features.final_ips = 8.0f;
    settings[SET_ENABLED - SET_ENABLED] = 0;
    custom_breath_settings_changed();
    breath_prepare(&s->prepare);
    ok = s->vauto_state == VAUTO_OFF && near(s->asv.pid.cumulative_error, 0.0f) &&
        near(s->features.final_ips, 0.0f) && custom_tc_decision(0) == TC_STOCK;
    settings[SET_ENABLED - SET_ENABLED] = 1;
    custom_breath_settings_changed();
    breath_prepare(&s->prepare);
    ok &= s->vauto_state == VAUTO_WAIT_INSPIRATION;
    tracker.tr.st_just_started = false;
    breath_finish(&s->finish);
    ok &= s->vauto_state == VAUTO_WAIT_INSPIRATION;
    check("VAUTO-07-toggle-rearms", ok,
          "disable clears demand; re-enable waits for the next new inspiration");

    accept_inspiration(s);
    s->features.final_ips = 8.0f;
    s->asv.pid.cumulative_error = 1.0f;
    s->trc.trigger = s->trc.cycle = TC_SWITCH;
    breath_stop(&s->prepare);
    ok = !s->prepare.enabled && !s->finish.enabled && s->vauto_state == VAUTO_OFF &&
         s->reset && custom_tc_decision(0) == TC_STOCK &&
         custom_tc_decision(1) == TC_STOCK && invoke(NULL, 0) && near(limiter_ps, 2.0f);
    breath_mode(&s->prepare);
    breath_prepare(&s->prepare);
    ok &= s->vauto_state == VAUTO_WAIT_INSPIRATION &&
          near(s->features.final_ips, 0.0f) && near(s->asv.pid.cumulative_error, 0.0f);
    check("VAUTO-08-stop-and-restart", ok,
          "stop immediately disables decisions; numeric state clears on the next prepare");

    s->features.final_ips = 8.0f;
    s->asv.pid.cumulative_error = 1.0f;
    ivars[0x12] = MODE_APAP;
    ivars[0x6f] = MODE_VAUTO; /* Deliberately stale published mode. */
    breath_mode(&s->prepare);
    ok = s->mode == MODE_APAP && !s->prepare.enabled && s->vauto_state == VAUTO_OFF &&
         s->reset && invoke(NULL, 0) && near(limiter_ps, 2.0f);
    ivars[0x12] = MODE_VAUTO;
    ivars[0x6f] = MODE_APAP;
    breath_mode(&s->prepare);
    breath_prepare(&s->prepare);
    ok &= s->mode == MODE_VAUTO && s->prepare.enabled &&
          s->vauto_state == VAUTO_WAIT_INSPIRATION &&
          near(s->features.final_ips, 0.0f) && near(s->asv.pid.cumulative_error, 0.0f);
    check("VAUTO-09-requested-mode-reset", ok,
          "requested mode controls lifecycle despite stale published mode; re-entry starts fresh");

    ivars[0x12] = MODE_S;
    breath_mode(&s->prepare);
    breath_prepare(&s->prepare);
    check("VAUTO-10-s-mode-passthrough", s->prepare.enabled && s->vauto_state == VAUTO_OFF &&
          invoke("s_mode", 0) && near(limiter_ps, 2.0f),
          "S mode can retain its worker while VAuto pressure shaping stays off");

    pending_callback_id = SET_ENABLED;
    custom_breath_settings_changed();
    breath_prepare(&s->prepare);
    ok = s->settings_dirty;
    breath_prepare(&s->prepare);
    check("VAUTO-11-reload-callback", ok && !s->settings_dirty,
          "a setting callback during reload remains pending for the following prepare");

    s = begin(1);
    accept_inspiration(s);
    tracker.tr.st_valid_sample = false;
    breath_prepare(&s->prepare);
    check("VAUTO-12-invalid-sample-tc", custom_tc_decision(0) == TC_STOCK &&
          custom_tc_decision(1) == TC_STOCK,
          "invalid tracker sample leaves trigger and cycle comparisons to stock");
}

static void pressure_tests(void)
{
    breath_controller_t *s = begin(1);
    accept_inspiration(s);
    const float inputs[] = {-2.0f, 0.0f, 2.0f};
    /* Independently specified sample points at EPAP 8 / IPAP 12, boost off. */
    const float expected[] = {8.45f, 10.225f, 12.0f};
    int ok = 1;
    for (unsigned i = 0; i < 3; ++i) {
        *cmd_ps = inputs[i];
        ok &= invoke("base_waveform", i) && near(limiter_request, expected[i]);
    }
    check("VAUTO-13-base-waveform", ok,
          "three independent pressure points with zero adaptive boost and zero EPS");

    s = begin(1);
    settings[SET_EPS - SET_ENABLED] = 100; /* EPS 2.0 */
    custom_breath_settings_changed();
    breath_prepare(&s->prepare);
    accept_inspiration(s);
    ok = invoke(NULL, 0);
    tracker.tr.st_inhaling = false;
    tracker.tr.st_just_started = true;
    tracker.tr.current.ti = 1.0f;
    *cmd_ps = -2.0f;
    ok &= invoke("eps_relief", 0) && near(limiter_request, 6.0f);
    check("VAUTO-14-eps-relief", ok,
          "EPS 2 lowers an 8 cmH2O stock end-expiratory request to 6 at the limiter input");

    *cmd_epap_ramp = 7.0f;
    check("VAUTO-15-floor-four", invoke("floor_four", 0) && near(limiter_request, 4.0f),
          "relief cannot lower a stock request of 5 below the pre-limiter floor of 4");
    *cmd_epap_ramp = 5.0f;
    check("VAUTO-16-floor-stock-if-lower", invoke("floor_stock", 0) && near(limiter_request, 3.0f),
          "an already-low stock request of 3 remains 3 rather than being raised to 4");

    s = begin(1);
    accept_inspiration(s);
    ok = invoke(NULL, 0) && near(limiter_request, 12.0f);
    vauto_ps = 2.0f;
    *cmd_epap_ramp = 9.0f; /* EPAP stays 8 after the configured PS changes. */
    *cmd_ps = 1.0f;       /* Same absolute stock request of 10 as halfway through old PS. */
    tracker.tr.st_inhaling = false;
    tracker.tr.st_just_started = false;
    tracker.tr.current.ti = 0.5f;
    ok &= invoke("positive_ps_edit", 0) && near(limiter_request, 10.0f) &&
          near(s->features.insp_ps, 4.0f);
    check("VAUTO-17-expiratory-ps-edit", ok,
          "a positive PS edit retains the completed inspiration's scale for expiration");

    for (int variant = 0; variant < 2; ++variant) {
        s = begin(1);
        accept_inspiration(s);
        const int setup_ok = invoke(NULL, 0);
        tracker.tr.st_inhaling = false;
        tracker.tr.st_just_started = false;
        s->features.final_ips = variant ? INFINITY : NAN;
        *cmd_ps = 0.0f;
        ok = invoke(NULL, 0) && setup_ok && near(limiter_ps, 0.0f) &&
             s->vauto_state == VAUTO_OFF && s->reset;
        check(variant ? "VAUTO-19-internal-infinity" : "VAUTO-18-internal-nan", ok,
              "nonfinite internal expiratory output resets shaping and forwards finite stock input");
    }
    s = begin(1);
    accept_inspiration(s);
    *cmd_ps = NAN;
    ok = invoke(NULL, 0) && isnan(limiter_ps) && s->vauto_state == VAUTO_OFF && s->reset;
    check("VAUTO-20-nonfinite-stock-fallback", ok,
          "characterization: invalid stock input is forwarded by fallback, not sanitized");
    printf("OBSERVATION|VAUTO-NONFINITE-STOCK-INPUT|%s|scenario=stock_nan\n",
           isnan(limiter_ps) ? "FORWARDED" : "NOT_FORWARDED");
}

/* Deliberately seeded mature feedback; this isolates the wrapper's support cap. */
static breath_controller_t *seed_demand(float cap, float waveform)
{
    breath_controller_t *s = begin(1);
    settings[SET_ASV_MAX - SET_ENABLED] = (int)(cap * 50.0f);
    custom_breath_settings_changed();
    breath_prepare(&s->prepare);
    accept_inspiration(s);
    tracker.tr.st_just_started = false;
    tracker.tr.tick = 123;
    tracker.tr.current.t = 23; /* Between checkpoint updates. */
    s->asv.tracking_tick = 122;
    s->asv.boost_enabled = true;
    s->asv.full_inspiration = true;
    s->asv.asv_skip = 0;
    s->asv.pid.cumulative_error = 1.5f;
    *cmd_epap_ramp = 18.0f;
    *cmd_ps = waveform;
    return s;
}

static void observation(const char *scenario, float selected, float stock, float request)
{
    printf("OBSERVATION|VAUTO-MAX-IPAP|%s|scenario=%s|selected_max_ipap=%.9g|"
           "stock_request=%.9g|wrapper_request=%.9g|excess=%.9g\n",
           request > selected + 0.0001f ? "EXCEEDS" : "WITHIN",
           scenario, selected, stock, request, request - selected);
}

static void support_cap_tests(void)
{
    int ok = 1;
    /* Paired zero-boost and demand fixtures compare only additional adaptive support. */
    for (unsigned cap_index = 0; cap_index < 3; ++cap_index) {
        const float caps[] = {0.4f, 3.0f, 10.0f};
        const float cap = caps[cap_index];
        for (unsigned i = 0; i <= 20; ++i) {
            const float waveform = -2.0f + (float)i / 5.0f;
            (void)seed_demand(0.0f, waveform);
            ok &= invoke(NULL, 0);
            const float base = limiter_request;
            (void)seed_demand(cap, waveform);
            ok &= invoke(NULL, 0);
            const float additional = limiter_request - base;
            ok &= isfinite(additional) && additional >= -0.0001f && additional <= cap + 0.0001f;
        }
    }
    check("VAUTO-21-adaptive-support-cap", ok,
          "63 paired fixtures: boost adds at most configured ASV Max above the base waveform");
    (void)seed_demand(3.0f, 2.0f);
    ok = invoke("seeded_max_ipap", 0);
    check("VAUTO-22-seeded-boundary-plumbing", ok && isfinite(limiter_request),
          "seeded mature feedback executes real ASV and preserves callback/input ownership");
    observation("seeded_max_ipap", 20.0f, 20.0f, limiter_request);
}

static void learned_breaths_test(void)
{
    breath_controller_t *s = begin(1);
    settings[SET_ASV_MAX - SET_ENABLED] = 150; /* ASV Max 3, nominal PS 4. */
    custom_breath_settings_changed();
    *cmd_epap_ramp = 18.0f;
    const unsigned normal_breaths = 25, low_breaths = 8, ticks_per_breath = 200;
    float highest = -INFINITY, highest_stock = NAN;
    int ok = 1, warmup_without_boost = 1;
    unsigned tick = 0;
    for (unsigned breath = 0; breath < normal_breaths + low_breaths; ++breath) {
        const float volume_l = breath < normal_breaths ? 0.5f : 0.2f;
        for (unsigned t = 0; t < ticks_per_breath; ++t, ++tick) {
            tracking_t *tr = &tracker.tr;
            tr->tick = tick;
            tr->st_valid_sample = true;
            tr->st_inhaling = t < 120;
            tr->st_just_started = t == 0 || t == 120;
            tr->current.t = (int16)t;
            tr->current.ti = t < 120 ? (float)t * 0.01f : 1.2f;
            tr->current.te = t < 120 ? 0.0f : (float)(t - 120) * 0.01f;
            tr->current.volume = t < 120 ? volume_l * (float)t / 120.0f :
                volume_l * (float)(200 - t) / 80.0f;
            tr->current.volume_max = t < 120 ? tr->current.volume : volume_l;
            tr->current.inh_maxflow = volume_l * 50.0f;
            fvars[0x25] = t < 120 ? volume_l * 50.0f : -volume_l * 75.0f;
            float support_fraction;
            if (t < 120) support_fraction = t < 20 ? (float)t / 20.0f : 1.0f;
            else support_fraction = t < 150 ? (float)(150 - t) / 30.0f : 0.0f;
            *cmd_ps = support_fraction * 4.0f - 2.0f;
            const float stock = *cmd_epap_ramp + *cmd_ps;
            breath_prepare(&s->prepare);
            breath_finish(&s->finish);
            ok &= invoke("learned_breaths", tick) && isfinite(limiter_request);
            if (breath < 20 && t >= 20 && t < 120)
                warmup_without_boost &= near(limiter_request, 20.0f);
            if (limiter_request > highest) {
                highest = limiter_request;
                highest_stock = stock;
            }
        }
    }
    for (unsigned i = 0; i < ASV_STEP_COUNT; ++i)
        ok &= s->asv.target_samples[i] == ASV_WARMUP_BREATHS;
    check("VAUTO-23-learned-sequence", ok && warmup_without_boost &&
          s->asv.breath_count == normal_breaths + low_breaths,
          "6600 continuous tracker ticks: 25 normal then 8 low-volume breaths; real ASV learning");
    observation("learned_breaths", 20.0f, highest_stock, highest);
}

int main(int argc, char **argv)
{
    if (argc > 2) {
        fprintf(stderr, "usage: %s [trace.csv]\n", argv[0]);
        return 2;
    }
    if (argc == 2) {
        trace = fopen(argv[1], "w");
        if (!trace) {
            perror(argv[1]);
            return 2;
        }
        fputs("scenario,tick,state,stock_request_cmh2o,wrapper_request_cmh2o,"
              "selected_max_ipap_cmh2o,added_support_cmh2o\n", trace);
    }
    lifecycle_tests();
    pressure_tests();
    support_cap_tests();
    learned_breaths_test();
    reset_fixture();
    if (trace) {
        const int write_failed = ferror(trace);
        const int close_failed = fclose(trace);
        if (write_failed || close_failed) {
            fputs("trace write or close failed\n", stderr);
            return 2;
        }
    }
    printf("SUMMARY|passed=%u|failed=%u\n", passed, failed);
    return failed ? 1 : 0;
}
