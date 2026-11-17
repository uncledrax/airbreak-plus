/*
 * Offline numeric probes for the real AirBreak iVAPS AutoEPAP core.c.
 * Unused firmware-coupled functions are removed at link time.
 * Observations are NOT clinical safety or physical pressure tests.
 */
#include <math.h>
#include <stdio.h>
#include "../../patches/autoepap/core.c"

static int failed = 0, passed = 0;

static int near(float actual, float expected)
{
    return isfinite(actual) && fabsf(actual - expected) < 0.0001f;
}
static void test(const char *id, int ok, float actual)
{
    printf("CASE|%s|%s|observed=%g\n", id, ok ? "PASS" : "FAIL", actual);
    if (ok) ++passed;
    else ++failed;
}

int main(void)
{
    Pressure p = {0};
    p.target = 8.0f;
    p.lower = 4.0f;
    p.upper = 12.0f;
    float current = 5.0f;
    pressure_slew(&p, &current, 0.2f, 4.0f, 12.0f, 1, 0);
    test("EPAP-01-rise-limited-to-001-per-tick", near(current, 5.01f), current);

    current = 5.0f;
    pressure_slew(&p, &current, 0.75f, 4.0f, 12.0f, 1, 0);
    test("EPAP-02-no-rise-on-expiratory-phase", near(current, 5.0f), current);

    p.target = 4.0f;
    current = 8.0f;
    pressure_slew(&p, &current, 0.75f, 4.0f, 12.0f, 1, 0);
    test("EPAP-03-decrease-on-expiratory-phase", near(current, 7.99f), current);

    p.target = 8.0f;
    current = 5.0f;
    pressure_slew(&p, &current, 0.2f, 4.0f, 12.0f, 1, 1);
    test("EPAP-04-inhibited-no-slew", near(current, 5.0f), current);

    Pressure bounds = {0};
    bounds.target = 15.0f;
    bounds.lower = 4.0f;
    bounds.upper = 20.0f;
    current = 16.0f;
    pressure_refresh(&bounds, &current, 0.2f, 6.0f, 10.0f);
    int held = near(current, 16.0f) && near(bounds.target, 15.0f);
    pressure_refresh(&bounds, &current, 0.75f, 6.0f, 10.0f);
    test("EPAP-05-bounds-latched-at-phase-transition",
         held && near(current, 10.0f) && near(bounds.target, 10.0f), current);

    Pressure event = {0};
    event.target = 8.0f;
    event.lower = 4.0f;
    event.upper = 12.0f;
    current = 8.0f;
    float published = 0.0f;
    pressure_target(&event, &current, &published, 1, 1, 100,
                    4.0f, 1.5f, 0.0f, 0, 0);
    test("EPAP-06-positive-event-adjustment",
         near(event.target, 9.5f) && near(published, 9.5f), published);

    /* Deliberate nonfinite fault: records propagation, not a safety pass. */
    Pressure bad = {0};
    bad.target = NAN;
    bad.lower = 4.0f;
    bad.upper = 12.0f;
    current = 6.0f;
    pressure_slew(&bad, &current, 0.25f, 4.0f, 12.0f, 1, 0);
    printf("OBSERVATION|AUTOEPAP-NONFINITE-TARGET|%s\n",
           isfinite(current) ? "FINITE" : "NONFINITE");

    printf("SUMMARY|passed=%d|failed=%d\n", passed, failed);
    return failed ? 1 : 0;
}
