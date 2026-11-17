/*
 * ASV wrapper native-host checks: compile with the actual patches/asv_task_wrapper.c.
 * Only the imported ResMed firmware dependencies are mocked.
 * No physical CPAP, patched image or firmware dump is required.
 */
#include <math.h>
#include <stdio.h>

float asv_phase_estimate;
int asv_low_flow_state;

#ifdef ASV_NO_MENU
const unsigned short asv_task_wrapper_backup_rate_var_id = 0xffffu;
#else
const unsigned short asv_task_wrapper_backup_rate_var_id = 0x03a5u;
#endif

static int backup_enabled = 0;
static int published = 0;
static int wrong_var_id = 0;
static int wrong_context = 0;
static int marker = 42;
static int passed = 0;
static int failed = 0;

int variable_get_by_id(int var_id)
{
    if (var_id != 0x03a5) wrong_var_id = 1;
    return backup_enabled;
}

void asv_publish_target_ventilation_and_pressure(void *ctx)
{
    ++published;
    if (ctx != &marker) wrong_context = 1;
}

/* The production function's symbol is 'start'. */
extern void start(void *ctx);

static void trial(const char *id, int enabled, int low_flow,
                  float initial, float expected)
{
    backup_enabled = enabled;
    asv_low_flow_state = low_flow;
    asv_phase_estimate = initial;
    published = 0;
    wrong_var_id = 0;
    wrong_context = 0;
    start(&marker);

    int ok = fabsf(asv_phase_estimate - expected) < 0.00001f &&
             published == 1 && !wrong_var_id && !wrong_context;
    printf("CASE|%s|%s|initial=%g expected=%g observed=%g calls=%d\n",
           id, ok ? "PASS" : "FAIL", initial, expected,
           asv_phase_estimate, published);
    if (ok) ++passed;
    else ++failed;
}

int main(void)
{
#ifdef ASV_NO_MENU
    trial("ASV-07-fallback-no-menu-suppresses-backup", 1, 1, 0.995f, 0.98f);
    trial("ASV-08-fallback-no-low-flow", 1, 0, 0.995f, 0.995f);
#else
    trial("ASV-01-off-clamps-late-phase", 0, 1, 0.995f, 0.98f);
    trial("ASV-02-on-preserves-late-phase", 1, 1, 0.995f, 0.995f);
    trial("ASV-03-off-without-low-flow-preserves", 0, 0, 0.995f, 0.995f);
    trial("ASV-04-off-early-phase-preserves", 0, 1, 0.7f, 0.7f);
    trial("ASV-05-off-boundary-preserves", 0, 1, 0.98f, 0.98f);
    trial("ASV-06-off-high-phase-clamps", 0, 1, 1.3f, 0.98f);
#endif
    printf("SUMMARY|passed=%d|failed=%d\n", passed, failed);
    return failed ? 1 : 0;
}
