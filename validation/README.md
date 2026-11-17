# AirBreak Plus — offline algorithm validation (Milestone 1)

**Research-only. Do not use this suite to certify, prescribe, or justify use of modified firmware on a patient.** Do not flash a therapy device as part of these tests.

This directory adds an independent test harness without modifying any existing `patches/`, `python/`, or production firmware.

## Run

From repository root, on Linux or WSL with Python 3.10+, gcc, and make:

```sh
python3 validation/run.py
```

Optional explicit sanitizers (used in CI):

```sh
python3 validation/run.py --sanitizers
```

Outputs: `validation/reports/report.html`, `report.json`, and `scenario-normal.csv` (ignored by Git). The report distinguishes passing tests from unresolved safety findings and missing validation coverage.

## What's actually exercised

- **Native AirBreak C source**: `patches/asv_task_wrapper.c` is compiled into two host executables, with a configurable firmware mock (back-up rate variable present and absent), and tested for phase clamping, passthrough, and call-through. No production code is copied or reimplemented.
- **AutoEPAP numeric core**: compiles the actual `patches/autoepap/core.c` inside an isolated host TU; exercises slew rate, inhibition, bound latch, and event response. A non-finite target injection is separately reported as an observed numerical risk (not a safety pass).
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
| Custom VAuto | Source-risk audit only | C-level dependency isolation, explicit selected-Max-IPAP contract, tracking worker tests |
| iVAPS AutoEPAP | Real pressure-core host tests and source-risk audit | Instrumented inactive-mode equivalence and full flow-shape kernel tests |
| ST iBR / Square Wave / Fall Time | Inventory only | Deterministic native integration and bounds tests |
| Memory failures | Known-risk source audit | Native allocator-failure injection across worker constructors |
| Baseline equivalence | Not established | Original-vs-patched, same simulated circuit and independently measured output |
| HIL | Not performed | Dedicated bench circuit, calibrated pressure and flow instrumentation |
| Clinical effectiveness | Not established | Qualified independent clinical assessment |

**Do not equate green CI with safety approval.** The HTML report includes open high-priority findings even when all runnable host tests pass.
