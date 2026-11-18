# Firmware-interface mocks

`asv_host.c` defines only the symbols required by the **actual** `patches/asv_task_wrapper.c` and links the production file unchanged. Two distinct binaries test the runtime menu variable path and the special `0xffff` fallback ABI slot.

The test's assertions describe observed function behaviour, **not a safe clinical policy**. ASV backup suppression is an intentionally documented feature and is separately raised as a high-priority configuration finding.

## Custom VAuto boundary harness

`vauto_host.c` includes the unchanged `patches/wrapper_limit_max_pdiff.c`, including the production `my_asv.c` and `feat_triggercycle.c`. It supplies firmware settings, a host worker list, allocator, tracker records, and a recording stock-limiter callback. The callback records `cmd_epap_ramp + cmd_ps` at entry, writes a sentinel to `cmd_ipap`, and does no limiting. Every wrapper invocation checks one callback, bitwise restoration of `cmd_ps`, and preservation of the callback output.

Host-only declaration adaptations are scoped around the source include: `__fp16` becomes `_Float16` (asserted 16-bit storage); firmware `size_t`, `malloc`, `snprintf`, and `pid_t` declarations are renamed to avoid host-library collisions. Arithmetic and controller code are unchanged. Host pointer sizes and execution do not establish ARM binary-layout, floating-point, or scheduling equivalence. Unused-production-declaration warnings are suppressed only around that include; the harness builds with `-Werror`.

Tracker volume, validity, timing, and accepted phase transitions are supplied inputs. The history predicate `is_cmd_ipap_constant` is a constant-true fixture. Tests therefore exercise only limited trigger/cycle behavior and do not validate the tracker, phase detector, Ti limits, or stock scheduler.

The test emits `CASE|id|PASS/FAIL|description` records and separate `OBSERVATION` records. A CSV path argument enables a finite pressure-request trace. `added_support_cmh2o` is the difference from the stock request and includes base-waveform shaping, not just adaptive boost. Nonfinite fault fixtures are recorded in stdout and deliberately excluded from the finite pressure-contract CSV.

See [the case map, input definitions, and evidence limits](../requirements/custom_vauto.md). Selected-Max-IPAP exceedance is a proposed-contract conflict, and a raw stock NaN reaching the callback is a separate fault observation; neither is a successful safety requirement.

Further harness work should:
1. Locate exact firmware-version targets and isolate native C algorithms without copying their calculations.
2. Inject deterministic clock, data stream, stock callbacks, faults and memory allocation failures.
3. Capture all state transitions and floating-point pressure commands, with unit-labeled traces.
4. Keep original, separately measured ResMed reference traces distinct from synthetic expected values.
5. Use static, native and embedded builds; never connect CI runners to a CPAP or issue flash commands.

This folder contains no device transport or programming code.
