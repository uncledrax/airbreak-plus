# AirBreak Plus — offline algorithm validation (Milestone 1)

**Research-only. Do not use this suite to certify, prescribe, or justify use of modified firmware on a patient.** Do not flash a therapy device as part of these tests.

This directory adds an independent test harness without modifying any existing `patches/`, `python/`, or production firmware.

## Run

From repository root, on Linux or WSL with Python 3.10+ and GCC with `_Float16` support:

```sh
python3 validation/run.py
```

Optional explicit sanitizers (used in CI):

```sh
python3 validation/run.py --sanitizers
```

Outputs: `validation/reports/report.html`, `report.json`, five synthetic-signal CSVs, and `vauto-pressure-trace.csv` (ignored by Git). The report distinguishes regression results, the proposed pressure contract, unresolved findings, and missing coverage.

To make the proposed selected-Max-IPAP ceiling an explicit required gate:

```sh
python3 validation/run.py --sanitizers --enforce-vauto-max-ipap
```

The current source is expected to fail that gate: the native VAuto trace records a 23 cmH2O request entering the stock limiter with selected Max IPAP 20 and ASV Max 3. This is consistent with the feature's documented pressure policy. The default run reports this conflict separately from behavioral regression status. It does not measure delivered pressure. See [the Custom VAuto test specification](requirements/custom_vauto.md).

In a debugger/ptrace environment where LeakSanitizer cannot run, use `--sanitizers --no-leak-check`. This explicitly disables only leak checking and records that limitation in the report. CI retains leak checking.

## What's actually exercised

- **Native AirBreak C source**: `patches/asv_task_wrapper.c` is compiled into two host executables, with a configurable firmware mock (back-up rate variable present and absent), and tested for phase clamping, passthrough, and call-through. No production code is copied or reimplemented.
- **AutoEPAP numeric core**: compiles the actual `patches/autoepap/core.c` inside an isolated host TU; exercises slew rate, inhibition, bound latch, and event response. A non-finite target injection is separately reported as an observed numerical risk (not a safety pass).
- **Custom VAuto**: compiles the unchanged wrapper, adaptive-support controller, and trigger/cycle code. Twenty-three cases exercise lifecycle, pass-through, pressure shaping, relative support caps, and nonfinite input behavior. A 6,600-tick sequence learns from 25 normal-volume breaths followed by 8 lower-volume breaths. Firmware services and tracker records are fixtures; the limiter records its input rather than implementing stock pressure control.
- **Static audit**: parses Air10 patch-option defaults from Python AST; inspects Plus preset and selected source paths for known design deviations. Static findings are not claims that physical pressure faults were reproduced.
- **Synthetic signals**: generates a reproducible 100 Hz, artificial patient-flow/effort/leak sequence, with distinct central and obstructive *simulation labels*. It is not an actual lung model, a device simulator, or a clinical validation.
- **Reporting**: captures command exit status, stdout/stderr, source revision, audit evidence, and conspicuous untested requirements.

## Independent acceptance and evidence

`requirements/contracts.json` defines the proposed safety contracts and outstanding requirements. Requirements are intentionally separate from implementation defaults. A test that proves a risky behavior exists is **not** a safety PASS.

Code checks can detect regressions in the instrumentation; they cannot establish equivalence to ResMed's proprietary therapy implementation. Stock-reference testing requires measured reference outputs under matched bench conditions. HIL and clinical verification are out of scope.

## Roadmap

| Area | Current scope | Next evidence needed |
|---|---|---|
| ASV wrapper | Real C native host tests | Backend function mocks, scheduling, timing and non-finite fault injection |
| Custom VAuto | Native state/boundary checks, 63 paired support-cap comparisons, learned sequence, explicit pressure-contract evidence | Real tracker integration, allocation failures, missing-menu fallback, firmware scheduler and stock-limiter reference |
| iVAPS AutoEPAP | Real pressure-core host tests and source-risk audit | Instrumented inactive-mode equivalence and full flow-shape kernel tests |
| ST iBR / Square Wave / Fall Time | Inventory only | Deterministic native integration and bounds tests |
| Memory failures | Known-risk source audit; successful VAuto attachment is exercised | Native allocator-failure injection across worker constructors |
| Baseline equivalence | Not established | Original-vs-patched, same simulated circuit and independently measured output |
| HIL | Not performed | Dedicated bench circuit, calibrated pressure and flow instrumentation |
| Clinical effectiveness | Not established | Qualified independent clinical assessment |

**Do not equate green CI with safety approval.** The HTML report includes open high-priority findings even when all runnable host tests pass.
