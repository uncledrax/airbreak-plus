"""Synthetic breathing signal generator; not physiological validation."""
from __future__ import annotations

import csv
import math
from pathlib import Path

TICK_S = 0.01
KINDS = ("normal", "central", "obstructive", "hypopnea")

def generate(seconds: float = 30.0, rate_bpm: float = 15.0,
             tidal_volume_ml: float = 500.0, event: str = "normal",
             event_start: float = 10.0, event_end: float = 20.0,
             leak_lpm: float = 0.0) -> list[dict]:
    if event not in KINDS:
        raise ValueError("unknown synthetic event")
    if not (seconds > 0 and rate_bpm > 0 and tidal_volume_ml > 0
            and 0 <= event_start <= event_end <= seconds and leak_lpm >= 0):
        raise ValueError("invalid synthetic scenario parameters")
    steps = round(seconds / TICK_S)
    period = 60.0 / rate_bpm
    inhale = 0.4 * period
    exhale = period - inhale
    # Integral of half-sine: 2*A*phase_duration/(pi*60) litres.
    a_in = (tidal_volume_ml / 1000.0) * 60.0 * math.pi / (2.0 * inhale)
    a_ex = (tidal_volume_ml / 1000.0) * 60.0 * math.pi / (2.0 * exhale)
    rows = []
    for i in range(steps):
        time_s = round(i * TICK_S, 6)
        phase = time_s % period
        if phase < inhale:
            flow = a_in * math.sin(math.pi * phase / inhale)
        else:
            flow = -a_ex * math.sin(math.pi * (phase - inhale) / exhale)
        synthetic_effort = math.sin(2.0 * math.pi * time_s / period)
        label = event if event_start <= time_s < event_end else "normal"
        if label == "central":
            synthetic_effort = 0.0
            flow = 0.0
        elif label == "obstructive":
            flow = 0.0  # effort retained in separate independent synthetic channel
        elif label == "hypopnea":
            flow *= 0.4
        rows.append(dict(time_s=time_s,
                         patient_flow_lpm=round(flow, 6),
                         respiratory_effort_au=round(synthetic_effort, 6),
                         added_leak_lpm=leak_lpm,
                         measured_flow_lpm=round(flow + leak_lpm, 6),
                         event_label=label))
    return rows

def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
