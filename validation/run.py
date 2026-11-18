#!/usr/bin/env python3
"""AirBreak Plus offline algorithm checks. No device connection, flash, or clinical validation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "validation/reports"
sys.path.insert(0, str(ROOT / "validation/tools"))
from audit import audit
from scenarios import generate, write_csv
from vauto_evidence import MEASUREMENT_POINT, REQUIRED_SCENARIOS, evaluate_trace, enforce_selected_max

def command(argv: list[str], env: dict[str, str] | None = None) -> dict:
    try:
        done = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                              env=env, check=False, timeout=120)
        return {"command": argv, "exit_code": done.returncode,
                "stdout": done.stdout, "stderr": done.stderr,
                "passed": done.returncode == 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": argv, "exit_code": None, "stdout": "",
                "stderr": str(exc), "passed": False}

def sanitizer_environment(sanitizers: bool, leak_check: bool) -> dict[str, str]:
    env = os.environ.copy()
    if sanitizers:
        env["ASAN_OPTIONS"] = f"detect_leaks={int(leak_check)}:halt_on_error=1"
        env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    return env

def native_test(build_dir: Path, no_menu: bool, sanitizers: bool,
                leak_check: bool = True) -> list[dict]:
    build_dir.mkdir(parents=True, exist_ok=True)
    label = "ASV: fallback var absent" if no_menu else "ASV: menu-controlled"
    target = build_dir / ("asv_fallback" if no_menu else "asv_menu")
    cmd = ["gcc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
           "-fno-omit-frame-pointer"]
    if sanitizers:
        cmd += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    if no_menu:
        cmd += ["-DASV_NO_MENU=1"]
    cmd += ["validation/harness/asv_host.c", "patches/asv_task_wrapper.c",
            "-lm", "-o", str(target)]
    build = command(cmd)
    build["name"] = label + " (compile)"
    results = [build]
    if build["passed"]:
        run = command([str(target)], env=sanitizer_environment(sanitizers, leak_check))
        run["name"] = label + " (execute)"
        results.append(run)
    return results

def autoepap_kernel_test(build_dir: Path, sanitizers: bool,
                        leak_check: bool = True) -> list[dict]:
    """Compile the real numerical kernel with dead-stripped firmware-only functions."""
    build_dir.mkdir(parents=True, exist_ok=True)
    target = build_dir / "autoepap_core"
    cmd = ["gcc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
           "-Wno-unused-const-variable", "-ffunction-sections", "-fdata-sections",
           "-fno-omit-frame-pointer"]
    if sanitizers:
        cmd += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    cmd += ["validation/harness/autoepap_core_host.c", "-Wl,--gc-sections",
            "-lm", "-o", str(target)]
    build = command(cmd)
    build["name"] = "AutoEPAP core (compile)"
    result = [build]
    if build["passed"]:
        test = command([str(target)], env=sanitizer_environment(sanitizers, leak_check))
        test["name"] = "AutoEPAP core (execute)"
        result.append(test)
    return result

def vauto_test(build_dir: Path, trace_path: Path, sanitizers: bool,
               leak_check: bool = True) -> list[dict]:
    """Execute the real wrapper and record its inputs to the stock limiter."""
    build_dir.mkdir(parents=True, exist_ok=True)
    # A failed build or execution must never reuse evidence from an earlier run.
    trace_path.unlink(missing_ok=True)
    target = build_dir / "vauto_host"
    cmd = ["gcc", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
           "-fno-fast-math", "-ffp-contract=off", "-fno-omit-frame-pointer"]
    if sanitizers:
        cmd += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    cmd += ["validation/harness/vauto_host.c", "-lm", "-o", str(target)]
    build = command(cmd)
    build["name"] = "Custom VAuto (compile)"
    result = [build]
    if build["passed"]:
        test = command([str(target), str(trace_path)],
                       env=sanitizer_environment(sanitizers, leak_check))
        test["name"] = "Custom VAuto (execute)"
        result.append(test)
    return result

def vauto_contract_check(evidence: dict) -> dict:
    passed = enforce_selected_max(evidence)
    return {"name": "Proposed VAuto selected-Max-IPAP ceiling (explicit gate)",
            "command": ["internal: enforce selected Max IPAP at limiter input"],
            "exit_code": 0 if passed else 1, "passed": passed,
            "stdout": evidence["status"], "stderr": ""}

def git_sha() -> str:
    result = command(["git", "rev-parse", "HEAD"])
    return result["stdout"].strip() if result["passed"] else "unknown"

def working_tree_dirty() -> bool | None:
    result = command(["git", "status", "--porcelain"])
    return bool(result["stdout"].strip()) if result["passed"] else None

def native_cases(commands: list[dict]) -> list[dict]:
    cases = []
    for command_result in commands:
        for line in command_result["stdout"].splitlines():
            if line.startswith("CASE|"):
                _, case_id, status, description = line.split("|", 3)
                cases.append({"id": case_id, "status": status, "description": description,
                              "command": command_result["name"]})
    return cases

def write_html(report: dict, target: Path) -> None:
    esc = lambda val: html.escape(str(val), quote=True)
    sections = []
    for test in report["commands"]:
        status = "PASS" if test["passed"] else "FAIL"
        sections.append(
            "<tr><td>" + esc(test["name"]) + "</td><td>" + status +
            "</td><td>" + esc(test["exit_code"]) + "</td></tr>"
        )
    findings = []
    for item in report["findings"]:
        findings.append("<tr><td>" + esc(item["id"]) + "</td><td>" +
                        esc(item["severity"]) + "</td><td>" +
                        esc(item["classification"]) + "</td><td>" +
                        esc(item["description"]) + "</td><td><code>" +
                        esc(item["location"]) + "</code></td></tr>")
    commands = []
    for item in report["commands"]:
        cmd = " ".join(item["command"])
        text = (item["stdout"] + ("\n" + item["stderr"] if item["stderr"] else "")).strip()
        commands.append("<details><summary>" + esc(item["name"]) + " — " +
                        esc(cmd) + "</summary><pre>" + esc(text) + "</pre></details>")
    contracts = "".join("<tr><td>" + esc(c["id"]) + "</td><td>" +
                        esc(c["status"]) + "</td><td>" + esc(c["claim"]) +
                        "</td></tr>" for c in report["contracts"])
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirBreak offline validation report</title>
<style>
body{font:15px/1.55 system-ui,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#17212c}
h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%;margin:1rem 0 2rem}
td,th{border-bottom:1px solid #ccd4db;text-align:left;vertical-align:top;padding:.5rem}
th{background:#f3f5f7}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:1rem}
.warning{border-left:4px solid #b45309;padding:1rem;background:#fff8eb}
small{color:#566476}details{margin:1rem 0}
</style></head><body>"""
    document += "<h1>AirBreak Plus — offline validation</h1>"
    document += "<p><small>Revision " + esc(report["revision"]) + " · " + esc(report["generated_utc"]) + "</small></p>"
    if report["working_tree_dirty"]:
        document += "<p><strong>Local working tree contains uncommitted changes.</strong></p>"
    document += "<div class='warning'><strong>NOT VALIDATED FOR PATIENT USE.</strong> Offline checks measure only limited code paths. Passing tests do not prove clinical safety, treatment efficacy, stock-firmware equivalence, physical pressure performance, or alarm integrity.</div>"
    document += "<p>Regression command status: <strong>" + esc(report["regression_status"]) + "</strong>. Overall command status: <strong>" + esc(report["offline_status"]) + "</strong>. Open engineering findings: <strong>" + str(len(report["findings"])) + "</strong>.</p>"
    document += "<p>ASan/UBSan: " + esc(report["sanitizers"]) + "; leak checking: " + esc(report["leak_check"]) + ".</p>"
    evidence = report["vauto_pressure_contract"]
    document += "<h2>Custom VAuto: selected-Max-IPAP contract</h2><div class='warning'><strong>" + esc(evidence["status"]) + "</strong><p>" + esc(evidence["measurement_point"]) + ".</p></div>"
    document += "<p>This is an independently proposed absolute ceiling. The current feature documentation permits adaptive support above the selected Max IPAP. Its result is separate from regression status; <code>--enforce-vauto-max-ipap</code> makes it a required command gate. Enforcement for this run: <strong>" + esc(report["enforce_vauto_max_ipap"]) + "</strong>.</p>"
    if evidence["status"] == "UNAVAILABLE":
        document += "<p>Evidence unavailable: " + esc(evidence["error"]) + "</p>"
    else:
        document += "<p><a href='" + esc(evidence["trace_file"]) + "'>Download the finite pressure-request trace (CSV)</a>. Units: cmH2O; sequence ticks are 10 ms. Tracker states and phase events are injected inputs. The firmware scheduler, stock limiter and pneumatic system are not simulated.</p>"
        document += "<table><thead><tr><th>Scenario</th><th>Samples</th><th>Over selected ceiling</th><th>Peak request</th><th>Largest excess</th><th>Stock inputs over ceiling</th></tr></thead><tbody>"
        for item in evidence["scenarios"]:
            document += "<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                item["scenario"], item["samples"], item["exceedance_samples"],
                f'{item["peak_request_cmh2o"]:.4f}', f'{item["max_excess_cmh2o"]:.4f}',
                item["stock_exceedance_samples"])) + "</tr>"
        document += "</tbody></table>"
        examples = [item["largest_exceedance"] for item in evidence["scenarios"]
                    if item["largest_exceedance"] is not None]
        if examples:
            document += "<h3>Captured counterexamples</h3><table><thead><tr><th>Scenario / tick</th><th>Stock request</th><th>Wrapper request</th><th>Selected Max IPAP</th></tr></thead><tbody>"
            for row in examples:
                document += "<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                    f'{row["scenario"]} / {row["tick"]}', row["stock_request_cmh2o"],
                    row["wrapper_request_cmh2o"], row["selected_max_ipap_cmh2o"])) + "</tr>"
            document += "</tbody></table>"
    document += "<h2>Executable checks</h2><table><thead><tr><th>Check</th><th>Status</th><th>Exit</th></tr></thead><tbody>" + "".join(sections) + "</tbody></table>"
    document += "<h2>Native assertions</h2><p>These check specified behavior and include fault characterization. A PASS for characterization does not make the characterized behavior an accepted safety policy.</p><table><thead><tr><th>Case</th><th>Status</th><th>Assertion</th></tr></thead><tbody>"
    for case in report["native_cases"]:
        document += "<tr><td>" + esc(case["id"]) + "</td><td>" + esc(case["status"]) + "</td><td>" + esc(case["description"]) + "</td></tr>"
    document += "</tbody></table>"
    document += "<h2>Open engineering findings</h2><p>Source indicators, native observations and design conflicts; these are not hardware-reproduced defects.</p>"
    document += "<table><thead><tr><th>ID</th><th>Priority</th><th>Evidence class</th><th>Observation</th><th>Source</th></tr></thead><tbody>" + "".join(findings) + "</tbody></table>"
    document += "<h2>Independent contracts (mostly unverified)</h2><table><thead><tr><th>ID</th><th>Status</th><th>Contract</th></tr></thead><tbody>" + contracts + "</tbody></table>"
    document += "<h2>Command logs</h2>" + "".join(commands)
    document += "</body></html>"
    target.write_text(document, encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitizers", action="store_true",
                        help="run native C tests with ASan and UBSan")
    parser.add_argument("--no-leak-check", action="store_true",
                        help="disable only LeakSanitizer for ptrace/debugger environments; recorded in report")
    parser.add_argument("--enforce-vauto-max-ipap", action="store_true",
                        help="fail if a recorded VAuto request exceeds the selected Max IPAP (proposed contract)")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()
    if args.no_leak_check and not args.sanitizers:
        parser.error("--no-leak-check requires --sanitizers")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build = out / ".build"

    leak_check = args.sanitizers and not args.no_leak_check
    commands = native_test(build, False, args.sanitizers, leak_check)
    commands += native_test(build, True, args.sanitizers, leak_check)
    commands += autoepap_kernel_test(build, args.sanitizers, leak_check)
    trace_path = out / "vauto-pressure-trace.csv"
    vauto_commands = vauto_test(build, trace_path, args.sanitizers, leak_check)
    commands += vauto_commands
    try:
        if not all(c["passed"] for c in vauto_commands):
            raise ValueError("Custom VAuto compile or execution failed; trace is not accepted")
        vauto_evidence = evaluate_trace(trace_path, REQUIRED_SCENARIOS)
    except (OSError, ValueError) as exc:
        vauto_evidence = {"status": "UNAVAILABLE", "measurement_point": MEASUREMENT_POINT,
                          "error": str(exc)}
        commands.append({"name": "VAuto trace integrity", "command": ["internal: read VAuto trace"],
                         "exit_code": 1, "stdout": "", "stderr": str(exc), "passed": False})
    unit = command([sys.executable, "-m", "unittest", "discover", "-s",
                    "validation/tests", "-p", "test_*.py", "-v"])
    unit["name"] = "Python audit, scenario and independent evidence tests"
    commands.append(unit)

    for kind in ("normal", "central", "obstructive", "hypopnea"):
        write_csv(out / ("scenario-" + kind + ".csv"),
                  generate(event=kind))
    (out / "scenario-leak.csv").write_text("", encoding="utf-8")
    write_csv(out / "scenario-leak.csv", generate(leak_lpm=20.0))

    try:
        findings = audit()
        for entry in commands:
            if entry["passed"] and "OBSERVATION|AUTOEPAP-NONFINITE-TARGET|NONFINITE" in entry["stdout"]:
                findings.append({"id": "AB-AUD-11", "severity": "HIGH",
                                 "classification": "NATIVE_FAULT_INJECTION",
                                 "description": "Injected nonfinite AutoEPAP target propagates to the pressure-slew output; physical reachability unproven",
                                 "location": "patches/autoepap/core.c:pressure_slew"})
            if entry["passed"] and "OBSERVATION|VAUTO-NONFINITE-STOCK-INPUT|FORWARDED" in entry["stdout"]:
                findings.append({"id": "AB-AUD-12", "severity": "HIGH",
                                 "classification": "NATIVE_FAULT_INJECTION",
                                 "description": "Injected NaN in the original VAuto waveform is forwarded to the stock limiter on fallback; upstream origin and downstream handling remain unverified",
                                 "location": "patches/wrapper_limit_max_pdiff.c:start"})
        if vauto_evidence["status"] == "EXCEEDED_AT_LIMITER_INPUT":
            for item in findings:
                if item["id"] == "AB-AUD-07":
                    item["classification"] = "NATIVE_PROPOSED_REQUIREMENT_CONFLICT"
                    item["description"] = (
                        "Custom VAuto requests exceed selected Max IPAP at the stock-limiter input; "
                        f'maximum recorded excess {vauto_evidence["max_excess_cmh2o"]:.4f} cmH2O. '
                        "Final delivered pressure remains unverified.")
                    item["location"] = "patches/wrapper_limit_max_pdiff.c:start; vauto-pressure-trace.csv"
        audit_error = None
    except Exception as exc:
        findings = []
        audit_error = repr(exc)
        commands.append({"name": "Source risk audit", "command": ["internal: audit"],
                         "exit_code": 1, "stdout": "", "stderr": audit_error,
                         "passed": False})
    contracts = json.loads((ROOT / "validation/requirements/contracts.json").read_text(encoding="utf-8"))["contracts"]
    regression_status = "PASS" if all(c["passed"] for c in commands) else "FAIL"
    if args.enforce_vauto_max_ipap:
        commands.append(vauto_contract_check(vauto_evidence))
    report = {"schema_version": 2, "generated_utc": datetime.now(timezone.utc).isoformat(),
              "revision": git_sha(), "safety_status": "NOT_VALIDATED_FOR_PATIENT_USE",
              "working_tree_dirty": working_tree_dirty(),
              "regression_status": regression_status,
              "offline_status": "PASS" if all(c["passed"] for c in commands) else "FAIL",
              "sanitizers": args.sanitizers, "leak_check": leak_check, "commands": commands,
              "native_cases": native_cases(commands),
              "enforce_vauto_max_ipap": args.enforce_vauto_max_ipap,
              "vauto_pressure_contract": vauto_evidence,
              "findings": findings, "audit_error": audit_error, "contracts": contracts}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_html(report, out / "report.html")
    print("AirBreak offline status:", report["offline_status"])
    print("Regression command status:", regression_status)
    print("VAuto selected-Max-IPAP contract:", vauto_evidence["status"])
    print("Open engineering findings:", len(findings))
    for item in findings:
        print("FINDING|{id}|{severity}|{classification}|{description}".format(**item))
    for item in commands:
        if not item["passed"]:
            print("FAILED COMMAND:", item["name"])
            print((item["stderr"] or item["stdout"]).strip())
        cases = [line for line in item["stdout"].splitlines() if line.startswith("CASE|")]
        if cases:
            print("CASES|{}|{}".format(item["name"], " ".join(
                line.split("|")[1] + ":" + line.split("|")[2] for line in cases)))
    print("Patient-use safety status: NOT VALIDATED")
    print("Report:", out / "report.html")
    return 0 if report["offline_status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
