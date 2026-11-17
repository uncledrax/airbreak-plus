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
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OUT_DEFAULT = ROOT / "validation/reports"
sys.path.insert(0, str(ROOT / "validation/tools"))
from audit import audit
from scenarios import generate, write_csv

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

def native_test(build_dir: Path, no_menu: bool, sanitizers: bool) -> list[dict]:
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
        env = os.environ.copy()
        if sanitizers:
            env["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
            env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        run = command([str(target)], env=env)
        run["name"] = label + " (execute)"
        results.append(run)
    return results

def autoepap_kernel_test(build_dir: Path, sanitizers: bool) -> list[dict]:
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
        env = os.environ.copy()
        if sanitizers:
            env["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
            env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        test = command([str(target)], env=env)
        test["name"] = "AutoEPAP core (execute)"
        result.append(test)
    return result

def git_sha() -> str:
    result = command(["git", "rev-parse", "HEAD"])
    return result["stdout"].strip() if result["passed"] else "unknown"

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
    document += "<div class='warning'><strong>NOT VALIDATED FOR PATIENT USE.</strong> Offline checks measure only limited code paths. Passing tests do not prove clinical safety, treatment efficacy, stock-firmware equivalence, physical pressure performance, or alarm integrity.</div>"
    document += "<p>Offline command status: <strong>" + esc(report["offline_status"]) + "</strong>. Open audit findings: <strong>" + str(len(report["findings"])) + "</strong>.</p>"
    document += "<h2>Executable checks</h2><table><thead><tr><th>Check</th><th>Status</th><th>Exit</th></tr></thead><tbody>" + "".join(sections) + "</tbody></table>"
    document += "<h2>Open source/configuration findings</h2><p>Source indicators and design conflicts; these are not hardware-reproduced defects.</p>"
    document += "<table><thead><tr><th>ID</th><th>Priority</th><th>Evidence class</th><th>Observation</th><th>Source</th></tr></thead><tbody>" + "".join(findings) + "</tbody></table>"
    document += "<h2>Independent contracts (mostly unverified)</h2><table><thead><tr><th>ID</th><th>Status</th><th>Contract</th></tr></thead><tbody>" + contracts + "</tbody></table>"
    document += "<h2>Command logs</h2>" + "".join(commands)
    document += "</body></html>"
    target.write_text(document, encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanitizers", action="store_true",
                        help="run native C tests with ASan and UBSan")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    build = out / ".build"

    commands = native_test(build, False, args.sanitizers)
    commands += native_test(build, True, args.sanitizers)
    commands += autoepap_kernel_test(build, args.sanitizers)
    unit = command([sys.executable, "-m", "unittest", "discover", "-s",
                    "validation/tests", "-p", "test_*.py", "-v"])
    unit["name"] = "Python offline audit and synthetic-scenario unit tests"
    commands.append(unit)

    for kind in ("normal", "central", "obstructive", "hypopnea"):
        write_csv(out / ("scenario-" + kind + ".csv"),
                  generate(event=kind))
    (out / "scenario-leak.csv").write_text("", encoding="utf-8")
    write_csv(out / "scenario-leak.csv", generate(leak_lpm=20.0))

    try:
        findings = audit()
        for entry in commands:
            if "OBSERVATION|AUTOEPAP-NONFINITE-TARGET|NONFINITE" in entry["stdout"]:
                findings.append({"id": "AB-AUD-11", "severity": "HIGH",
                                 "classification": "NATIVE_FAULT_INJECTION",
                                 "description": "Injected nonfinite AutoEPAP target propagates to the pressure-slew output; physical reachability unproven",
                                 "location": "patches/autoepap/core.c:pressure_slew"})
        audit_error = None
    except Exception as exc:
        findings = []
        audit_error = repr(exc)
        commands.append({"name": "Source risk audit", "command": ["internal: audit"],
                         "exit_code": 1, "stdout": "", "stderr": audit_error,
                         "passed": False})
    contracts = json.loads((ROOT / "validation/requirements/contracts.json").read_text(encoding="utf-8"))["contracts"]
    report = {"schema_version": 1, "generated_utc": datetime.now(timezone.utc).isoformat(),
              "revision": git_sha(), "safety_status": "NOT_VALIDATED_FOR_PATIENT_USE",
              "offline_status": "PASS" if all(c["passed"] for c in commands) else "FAIL",
              "sanitizers": args.sanitizers, "commands": commands,
              "findings": findings, "audit_error": audit_error, "contracts": contracts}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_html(report, out / "report.html")
    print("AirBreak offline status:", report["offline_status"])
    print("Open engineering findings:", len(findings))
    for item in findings:
        print("FINDING|{id}|{severity}|{classification}|{description}".format(**item))
    for item in commands:
        cases = [line for line in item["stdout"].splitlines() if line.startswith("CASE|")]
        if cases:
            print("CASES|{}|{}".format(item["name"], " ".join(
                line.split("|")[1] + ":" + line.split("|")[2] for line in cases)))
    print("Patient-use safety status: NOT VALIDATED")
    print("Report:", out / "report.html")
    return 0 if report["offline_status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
