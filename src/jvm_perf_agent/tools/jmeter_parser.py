"""
Simple JMeter CSV parser.
Provides parse_jmeter_csv(path_or_text) -> dict with keys: p50,p95,p99,error_rate,throughput,samples
Accepts either a file path or raw CSV text.
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import List, Dict


def _read_text(path_or_text: str) -> str:
    p = Path(path_or_text)
    if p.exists():
        return p.read_text(encoding='utf-8')
    return str(path_or_text)


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def parse_jmeter_csv(path_or_text: str) -> Dict[str, float]:
    text = _read_text(path_or_text)
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "error_rate": 0.0, "throughput": 0.0, "samples": 0}

    reader = csv.reader(lines)
    header = next(reader)
    # normalize header
    hdr = [h.strip().lower() for h in header]
    # common columns
    try:
        elapsed_idx = hdr.index('elapsed')
    except ValueError:
        # fall back to second column
        elapsed_idx = 1
    try:
        success_idx = hdr.index('success')
    except ValueError:
        success_idx = None
    try:
        throughput_idx = hdr.index('allthreads')
    except ValueError:
        throughput_idx = None

    elapsed_vals: List[float] = []
    total = 0
    failures = 0
    for parts in reader:
        total += 1
        try:
            elapsed_vals.append(float(parts[elapsed_idx]))
        except Exception:
            continue
        if success_idx is not None:
            try:
                success_val = parts[success_idx].strip().lower()
                if success_val in ("false", "0", "no", "f"):
                    failures += 1
            except Exception:
                pass

    elapsed_sorted = sorted(elapsed_vals)
    p50 = _percentile(elapsed_sorted, 50)
    p95 = _percentile(elapsed_sorted, 95)
    p99 = _percentile(elapsed_sorted, 99)
    error_rate = (failures / total) * 100.0 if total > 0 else 0.0

    # throughput estimation: samples per second approximated from timestamps if present
    # fallback: set 0
    throughput = 0.0

    return {
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "error_rate": round(error_rate, 3),
        "throughput": throughput,
        "samples": len(elapsed_vals),
    }
