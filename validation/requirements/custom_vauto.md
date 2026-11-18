# Native Custom VAuto test specification

## Measurement and independence

The system under test is the repository's unchanged Custom VAuto wrapper and its included adaptive-support and trigger/cycle implementations. Expected behavior is expressed as lifecycle invariants, independent numeric sample points, callback ownership rules, and a separately evaluated proposed absolute-pressure ceiling.

The pressure measurement is **the request entering the stock limiter**:

`cmd_epap_ramp + cmd_ps`, captured at entry to `pressure_limit_max_difference()`.

The callback does not implement the stock limiter. Its sentinel output only checks that the wrapper preserves callback results. No value in this suite is a measured delivered pressure, and passing a callback an unchanged value does not prove whole-firmware equivalence.

The source's [Pressure limits documentation](../../docs/guide/features/custom_vauto.md#pressure-limits) explicitly allows adaptive support above the selected Max IPAP. The independent proposal in AB-003 is stricter: every captured request should be at or below the selected setting, with a numerical tolerance of 0.0001 cmH2O. A conflict must remain visible without silently rewriting either the algorithm or the requirement to make the report green.

## Case map

| Cases | Expected behavior and scope |
|---|---|
| VAUTO-01–03 | Missing controller and Off forward stock inputs; settings callbacks do not allocate; repeated attachment creates one allocation and two worker nodes. |
| VAUTO-04–07 | Off enters Waiting; only a new accepted inspiration activates shaping; zero PS and disable clear demand; re-enable waits again. |
| VAUTO-08–10 | Stop immediately disables decisions; state clears on subsequent preparation; requested mode controls re-entry even when published mode is stale; S mode bypasses VAuto shaping. |
| VAUTO-11–12 | A settings change during reload remains pending; an invalid tracker sample leaves trigger/cycle decisions to stock. |
| VAUTO-13 | With nominal PS 4, midpoint 10, zero boost and zero EPS, three requests are independently specified as 8.45, 10.225 and 12 cmH2O. |
| VAUTO-14–16 | EPS relief follows its defined endpoint; pre-limiter pressure stays at least 4, or preserves an already-lower stock request. |
| VAUTO-17 | A positive PS edit during expiration retains the completed inspiration's pressure scale. |
| VAUTO-18–19 | Corrupt internal expiratory state with NaN or infinity; custom shaping resets and forwards the finite original stock input. |
| VAUTO-20 | Characterization: an already-NaN stock waveform remains NaN at the callback. This does not satisfy a universal finite-output requirement. |
| VAUTO-21 | Sixty-three paired base-only/demand fixtures cover 21 waveform points and ASV Max values 0.4, 3 and 10. Added adaptive support is finite, nonnegative, and no greater than that relative cap. |
| VAUTO-22 | Seeded mature demand executes the actual adaptive code and preserves callback/input ownership. Pressure is evaluated separately against AB-003. |
| VAUTO-23 | A cold controller processes 6,600 continuous tracker inputs, warms all 20 checkpoint histories, and remains finite. Pressure is evaluated separately against AB-003. |

Each wrapper invocation also checks exactly one stock callback, bitwise restoration of the incoming waveform, and preservation of the callback's output. Fixtures are reset between independent cases, with intentional state continuity within lifecycle and learned-sequence tests.

## Pressure-contract scenarios

Both primary scenarios use nominal PS 4, selected Max IPAP 20, a stock midpoint reference of 18, ASV Max 3, medium sensitivity, and zero EPS. Full stock inspiration requests 20 cmH2O.

| Scenario | Input construction | What the evidence establishes |
|---|---|---|
| `seeded_max_ipap` | One deliberately initialized mature-feedback state with high finite PID demand. | A reproducible unit-level boundary counterexample; preloaded demand does not establish natural reachability. |
| `learned_breaths` | 25 inspirations of 0.5 L followed by 8 of 0.2 L; 200 ticks per breath at 10 ms, with 120 inspiratory ticks and 80 expiratory ticks. Volume starts at zero at the accepted inspiration. | The real adaptive code learns demand from the supplied sequence without preloading its learned references or PID. Tracker records and accepted phase events are still injected. |

The recorded maximum in each scenario is 23 cmH2O at the limiter input. The complete CSV also contains finite disabled, waiting, base-shape, relief, floor, mode and PS-edit sample points. Invalid-number probes remain in the native case log.

`validation/tools/vauto_evidence.py` reads captured values rather than recomputing the VAuto waveform. It checks each row's selected limit, rejects nonfinite/malformed pressure data and inconsistent pressure deltas, requires valid states and increasing ticks, and requires all 6,600 learned-sequence samples plus the seeded sample. A failed compile/execution or incomplete trace produces unavailable evidence and a failed command result. Old traces are removed before a run.

## Run and interpret

```sh
python3 validation/run.py --sanitizers
python3 validation/run.py --sanitizers --enforce-vauto-max-ipap
```

The first command checks behavior and reports the absolute-pressure conflict separately. The second command additionally requires the proposed ceiling; the current implementation is expected to exit 1 because of that conflict. A future implementation that respects the ceiling can pass the gate without changing the evaluator.

The JSON report separates `regression_status`, `offline_status` (including any requested gate), and `vauto_pressure_contract.status`. `EXCEEDED_AT_LIMITER_INPUT` is never counted as acceptance of AB-003. `WITHIN_LIMIT_FOR_TESTED_TRACE` is limited to the recorded inputs. HTML includes each native assertion, per-scenario counts, peak counterexamples and the CSV link.

CI uses ASan, UBSan and leak detection. Local environments that prohibit LeakSanitizer under ptrace may use `--sanitizers --no-leak-check`; the report records the explicit reduction. This does not change CI defaults.

## Remaining evidence

- Integrate actual tracking and history code, then exercise invalid/missing samples and phase-event ordering.
- Inject allocator failure at worker construction, in isolated processes with a specific fail-safe requirement.
- Exercise the `0xffff` missing-menu fallback configuration.
- Compare firmware-specific stock-limiter and inactive-mode behavior against an independently obtained reference.
- Verify embedded ABI, floating-point behavior, full scheduling, and physical pressure on a separate instrumented bench.

AB-002, AB-007 and AB-008 remain broader, unverified system claims despite this partial native coverage. AB-003 now has a reproducible native counterexample at the defined boundary. No production algorithm or firmware default is changed by this test work.
