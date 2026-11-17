# Firmware-interface mocks

`asv_host.c` defines only the symbols required by the **actual** `patches/asv_task_wrapper.c` and links the production file unchanged. Two distinct binaries test the runtime menu variable path and the special `0xffff` fallback ABI slot.

The test's assertions describe observed function behaviour, **not a safe clinical policy**. ASV backup suppression is an intentionally documented feature and is separately raised as a high-priority configuration finding.

Future harness work should:
1. Locate exact firmware-version targets and isolate native C algorithms without copying their calculations.
2. Inject deterministic clock, data stream, stock callbacks, faults and memory allocation failures.
3. Capture all state transitions and floating-point pressure commands, with unit-labeled traces.
4. Keep original, separately measured ResMed reference traces distinct from synthetic expected values.
5. Use static, native and embedded builds; never connect CI runners to a CPAP or issue flash commands.

This folder contains no device transport or programming code.
