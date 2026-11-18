"""Independent evaluation of requests recorded at the VAuto stock-limiter boundary.

This module never computes a replacement VAuto waveform or simulates the stock
limiter. It compares captured requests with the selected Max IPAP and keeps that
proposed contract separate from regression-test execution status.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

PRESSURE_TOLERANCE_CMH2O = 1e-4
PRESSURE_FIELDS = (
    "stock_request_cmh2o",
    "wrapper_request_cmh2o",
    "selected_max_ipap_cmh2o",
    "added_support_cmh2o",
)
MEASUREMENT_POINT = "Request entering pressure_limit_max_difference; not delivered pressure"
REQUIRED_SCENARIOS = {"seeded_max_ipap": 1, "learned_breaths": 6600}
STATES = {"OFF", "WAIT_INSPIRATION", "ACTIVE", "NO_CONTROLLER"}


def evaluate_trace(path: Path, required_scenarios: dict[str, int] | None = None) -> dict:
    """Fail closed on missing evidence; summarize only the supplied finite trace."""
    scenarios: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"scenario", "tick", "state", *PRESSURE_FIELDS}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("VAuto trace is missing required columns")
        for line_number, raw in enumerate(reader, start=2):
            if None in raw or any(raw[key] is None for key in required):
                raise ValueError(f"VAuto trace row {line_number} has the wrong column count")
            name = raw["scenario"].strip()
            if not name or raw["state"] not in STATES:
                raise ValueError(f"VAuto trace row {line_number} lacks scenario or has an unknown state")
            tick = int(raw["tick"])
            if tick < 0:
                raise ValueError(f"VAuto trace row {line_number} has a negative tick")
            values = {key: float(raw[key]) for key in PRESSURE_FIELDS}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError(f"VAuto trace row {line_number} contains nonfinite pressure")
            difference = values["wrapper_request_cmh2o"] - values["stock_request_cmh2o"]
            if abs(difference - values["added_support_cmh2o"]) > PRESSURE_TOLERANCE_CMH2O:
                raise ValueError(f"VAuto trace row {line_number} has inconsistent pressure delta")
            row = {"scenario": name, "tick": tick, "state": raw["state"], **values}
            excess = values["wrapper_request_cmh2o"] - values["selected_max_ipap_cmh2o"]
            item = scenarios.setdefault(name, {
                "scenario": name, "samples": 0, "exceedance_samples": 0,
                "stock_exceedance_samples": 0, "max_excess_cmh2o": 0.0,
                "peak_request_cmh2o": values["wrapper_request_cmh2o"],
                "first_tick": tick, "last_tick": None,
                "first_exceedance": None, "largest_exceedance": None,
            })
            if item["last_tick"] is not None and tick <= item["last_tick"]:
                raise ValueError(f"VAuto trace row {line_number} repeats or reorders a scenario tick")
            item["last_tick"] = tick
            item["samples"] += 1
            item["peak_request_cmh2o"] = max(item["peak_request_cmh2o"], values["wrapper_request_cmh2o"])
            if values["stock_request_cmh2o"] - values["selected_max_ipap_cmh2o"] > PRESSURE_TOLERANCE_CMH2O:
                item["stock_exceedance_samples"] += 1
            if excess > PRESSURE_TOLERANCE_CMH2O:
                item["exceedance_samples"] += 1
                if item["first_exceedance"] is None:
                    item["first_exceedance"] = row
                if excess > item["max_excess_cmh2o"]:
                    item["max_excess_cmh2o"] = excess
                    item["largest_exceedance"] = row
    if not scenarios:
        raise ValueError("VAuto trace contains no samples")
    for name, samples in (required_scenarios or {}).items():
        item = scenarios.get(name)
        if (item is None or item["samples"] != samples or
                item["first_tick"] != 0 or item["last_tick"] != samples - 1):
            raise ValueError(f"VAuto trace requires all {samples} consecutive ticks for {name}")
    total_exceedances = sum(s["exceedance_samples"] for s in scenarios.values())
    return {
        "status": "EXCEEDED_AT_LIMITER_INPUT" if total_exceedances else "WITHIN_LIMIT_FOR_TESTED_TRACE",
        "measurement_point": MEASUREMENT_POINT,
        "trace_file": path.name,
        "tolerance_cmh2o": PRESSURE_TOLERANCE_CMH2O,
        "samples": sum(s["samples"] for s in scenarios.values()),
        "exceedance_samples": total_exceedances,
        "max_excess_cmh2o": max(s["max_excess_cmh2o"] for s in scenarios.values()),
        "scenarios": list(scenarios.values()),
    }


def enforce_selected_max(evidence: dict) -> bool:
    """The optional gate accepts only available evidence with no exceedances."""
    return evidence["status"] == "WITHIN_LIMIT_FOR_TESTED_TRACE"
