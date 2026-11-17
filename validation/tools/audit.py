"""Read-only, conservative source/config audit; not a dynamic safety test."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def air10_defaults() -> dict[str, bool]:
    tree = ast.parse((ROOT / "python/lib/as10_patch_options.py").read_text(encoding="utf-8"))
    result: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "Patch" or len(node.args) < 3:
            continue
        key, enabled = node.args[0], node.args[2]
        if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                and isinstance(enabled, ast.Constant) and isinstance(enabled.value, bool)):
            result[key.value] = enabled.value
    return result

def plus_preset() -> dict[str, bool]:
    result = {}
    for line in (ROOT / "presets/air10/plus.config").read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) == 2 and parts[0].startswith("--patch-") and parts[1] in ("y", "n"):
            result[parts[0][2:]] = parts[1] == "y"
    return result

def finding(fid: str, severity: str, classification: str,
            description: str, location: str) -> dict:
    return dict(id=fid, severity=severity, classification=classification,
                description=description, location=location)

def audit() -> list[dict]:
    defaults, plus = air10_defaults(), plus_preset()
    findings = []
    for key, fid, explanation in (
        ("patch-integrity-check", "AB-AUD-01", "Bootloader integrity-check bypass enabled by default"),
        ("patch-bypass-psuid", "AB-AUD-02", "Power-supply identification bypass enabled by default"),
        ("patch-unlock-uilimits", "AB-AUD-03", "Pressure UI range expanded beyond standard AutoSet range by default"),
        ("patch-asv-ps-range", "AB-AUD-04", "Stock ASV pressure-support constraints loosened by default"),
    ):
        if defaults.get(key) is True:
            findings.append(finding(fid, "HIGH", "CONFIRMED_CONFIGURATION",
                                    explanation, "python/lib/as10_patch_options.py"))
        elif key not in defaults:
            findings.append(finding(fid, "REVIEW", "AUDIT_INCOMPLETE",
                                    "Default option not found; inspect changed patch registration: " + key,
                                    "python/lib/as10_patch_options.py"))
    if plus.get("patch-fw-asv-wrapper"):
        text = (ROOT / "python/patch-airsense.py").read_text(encoding="utf-8")
        # This is only a code-indicator: proving a therapy hazard needs integration/bench tests.
        if re.search(r"redefine_g8_var\(backup_var,[\s\S]{0,140}?backup_label,\s*0\s*,", text):
            findings.append(finding("AB-AUD-05", "CRITICAL", "CONFIRMED_CONFIGURATION",
                                    "Plus includes ASV timed-backup suppression and default menu setting Off",
                                    "python/patch-airsense.py; presets/air10/plus.config"))
        else:
            findings.append(finding("AB-AUD-05", "REVIEW", "AUDIT_INCOMPLETE",
                                    "Plus ASV wrapper enabled; menu default not verified by pattern scan",
                                    "python/patch-airsense.py"))
    if plus.get("patch-fw-vauto-wrapper"):
        text = (ROOT / "patches/wrapper_limit_max_pdiff.c").read_text(encoding="utf-8")
        if re.search(r"malloc\(sizeof\(\*s\)\);\s*init_breath_controller\(s\)", text):
            findings.append(finding("AB-AUD-06", "HIGH", "SOURCE_DEFECT_INDICATOR",
                                    "Custom VAuto controller allocation immediately dereferenced without null check",
                                    "patches/wrapper_limit_max_pdiff.c"))
        findings.append(finding("AB-AUD-07", "HIGH", "PROPOSED_REQUIREMENT_CONFLICT",
                                "Custom VAuto may exceed selected Max IPAP; requires independent pressure contract",
                                "docs/guide/features/custom_vauto.md"))
    tracker = (ROOT / "patches/breath_tracking.c").read_text(encoding="utf-8")
    if re.search(r"malloc\(sizeof\(\*s\)\);\s*unsigned char \*p", tracker):
        findings.append(finding("AB-AUD-08", "HIGH", "SOURCE_DEFECT_INDICATOR",
                                "Breath-tracking allocation used without null check",
                                "patches/breath_tracking.c"))
    if plus.get("patch-autoepap"):
        findings.append(finding("AB-AUD-09", "REVIEW", "EQUIVALENCE_UNPROVEN",
                                "AutoEPAP replaces stock callbacks; Off-state timing equivalence untested",
                                "patches/autoepap/shared.c"))
    doc = (ROOT / "docs/guide/patching.md").read_text(encoding="utf-8")
    if defaults.get("patch-learn-targets") is True and re.search(
            r"Learn Targets[^\\n]*Off by default", doc):
        findings.append(finding("AB-AUD-10", "MEDIUM", "DOCUMENTATION_MISMATCH",
                                "Patch-option registry enables Learn Targets by default, but guide says Off by default",
                                "python/lib/as10_patch_options.py; docs/guide/patching.md"))
    return findings
