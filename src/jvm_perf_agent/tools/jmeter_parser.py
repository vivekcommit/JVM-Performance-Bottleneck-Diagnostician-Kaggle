"""
JMeter CSV parser.

Provides parse_jmeter_csv(path) -> dict with keys:
- overall_stats: {count, avg_ms, p95_ms, p99_ms, error_rate_pct, throughput_tps}
- time_series: list of per-10-second buckets with {timestamp_ms, tps, p95_ms, count}

The implementation uses pandas if available for convenience and speed; otherwise it
falls back to the stdlib `csv` module. The function accepts a filesystem path to a
JMeter CSV (or any CSV-like string path) and returns JSON-serializable structures.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Any
import math

try:
    import pandas as pd
    _HAS_PANDAS = True
except Exception:
    _HAS_PANDAS = False

import csv


def _read_text(path: str) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    # treat as raw text
    return str(path)


def _percentile(vals: List[float], q: float) -> float:
    if not vals:
        return 0.0
    vals_sorted = sorted(vals)
    k = (len(vals_sorted) - 1) * (q / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(vals_sorted[int(k)])
    d0 = vals_sorted[f] * (c - k)
    d1 = vals_sorted[c] * (k - f)
    return float(d0 + d1)


def _choose_column(columns: List[str], candidates: List[str]) -> str | None:
    lower = {c.strip().lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def parse_jmeter_csv(path: str) -> Dict[str, Any]:
    """Parse a JMeter results CSV and return overall stats + 10s time series.

    Returns:
      {
        "overall_stats": {count, avg_ms, p95_ms, p99_ms, error_rate_pct, throughput_tps},
        "time_series": [ {timestamp_ms, tps, p95_ms, count}, ... ]
      }
    """
    p = Path(path)
    if not p.exists():
        # path might be raw CSV text (string) - attempt to parse from string
        text = _read_text(path)
        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return {"overall_stats": {}, "time_series": []}
        # write to temporary in-memory list for csv reader fallback
        reader = csv.DictReader(lines)
        rows = list(reader)
    else:
        rows = None

    # Use pandas when available
    if _HAS_PANDAS:
        if rows is None:
            try:
                df = pd.read_csv(p)
            except Exception:
                # Try reading as text held in path string
                text = _read_text(path)
                from io import StringIO

                df = pd.read_csv(StringIO(text))
        else:
            df = pd.DataFrame(rows)

        # normalize columns
        cols = list(df.columns)
        ts_col = _choose_column(cols, ["timeStamp", "timestamp", "time_stamp", "time"])
        elapsed_col = _choose_column(cols, ["elapsed", "responseTime", "latency"])
        success_col = _choose_column(cols, ["success"])

        if elapsed_col is None:
            raise RuntimeError("Could not find 'elapsed' column in JMeter CSV")

        # coerce types
        df[elapsed_col] = pd.to_numeric(df[elapsed_col], errors="coerce")
        if ts_col is not None:
            df[ts_col] = pd.to_numeric(df[ts_col], errors="coerce")
            # convert ms epoch to datetime
            df["_ts_dt"] = pd.to_datetime(df[ts_col], unit="ms", errors="coerce")
            df = df.dropna(subset=["_ts_dt", elapsed_col])
            df = df.set_index("_ts_dt")

            # resample into 10s buckets
            grouped = df[elapsed_col].resample("10S")
            ts_frames = []
            for ts, ser in grouped:
                cnt = int(ser.count())
                if cnt == 0:
                    continue
                p95 = float(ser.quantile(0.95))
                tps = cnt / 10.0
                ts_frames.append({
                    "timestamp_ms": int(ts.value // 1_000_000),
                    "tps": round(float(tps), 3),
                    "p95_ms": round(float(p95), 3),
                    "count": cnt,
                })
        else:
            ts_frames = []

        elapsed_vals = df[elapsed_col].dropna().astype(float).tolist()
        count = len(elapsed_vals)
        avg_ms = float(pd.Series(elapsed_vals).mean()) if count else 0.0
        p95_ms = float(pd.Series(elapsed_vals).quantile(0.95)) if count else 0.0
        p99_ms = float(pd.Series(elapsed_vals).quantile(0.99)) if count else 0.0

        failures = 0
        if success_col is not None and success_col in df.columns:
            # when using df index, original success column may still exist
            failures = int(((df[success_col].astype(str).str.lower() == 'false')).sum())

        error_rate = (failures / count) * 100.0 if count > 0 else 0.0

        # overall throughput: samples / duration_seconds (from timestamps if available)
        throughput_tps = 0.0
        if ts_col is not None and count > 1:
            ts_min = int(df[ts_col].min())
            ts_max = int(df[ts_col].max())
            duration_s = max(1.0, (ts_max - ts_min) / 1000.0)
            throughput_tps = round(count / duration_s, 3)

        overall = {
            "count": int(count),
            "avg_ms": round(float(avg_ms), 3),
            "p95_ms": round(float(p95_ms), 3),
            "p99_ms": round(float(p99_ms), 3),
            "error_rate_pct": round(float(error_rate), 3),
            "throughput_tps": float(throughput_tps),
        }

        return {"overall_stats": overall, "time_series": ts_frames}

    # Fallback: csv module
    # Ensure we have rows from earlier branch (if path exists we'll read it now)
    if rows is None:
        text = _read_text(path)
        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return {"overall_stats": {}, "time_series": []}
        reader = csv.DictReader(lines)
        rows = list(reader)

    # Normalize column names
    if not rows:
        return {"overall_stats": {}, "time_series": []}

    cols = list(rows[0].keys())
    ts_col = _choose_column(cols, ["timeStamp", "timestamp", "time_stamp", "time"])
    elapsed_col = _choose_column(cols, ["elapsed", "responsetime", "latency"])
    success_col = _choose_column(cols, ["success"])

    if elapsed_col is None:
        raise RuntimeError("Could not find 'elapsed' column in JMeter CSV")

    parsed = []
    for r in rows:
        try:
            elapsed = float(r.get(elapsed_col, 0) or 0)
        except Exception:
            continue
        ts = None
        if ts_col and r.get(ts_col):
            try:
                ts = int(float(r.get(ts_col)))
            except Exception:
                ts = None
        succ = None
        if success_col and r.get(success_col) is not None:
            succ = str(r.get(success_col)).strip().lower() not in ("false", "0", "no", "f")
        parsed.append({"ts": ts, "elapsed": elapsed, "success": succ})

    elapsed_vals = [p["elapsed"] for p in parsed]
    count = len(elapsed_vals)
    avg_ms = sum(elapsed_vals) / count if count else 0.0
    p95_ms = _percentile(sorted(elapsed_vals), 95) if count else 0.0
    p99_ms = _percentile(sorted(elapsed_vals), 99) if count else 0.0
    failures = sum(1 for p in parsed if p.get("success") is False)
    error_rate = (failures / count) * 100.0 if count > 0 else 0.0

    # overall throughput using timestamp span if available
    throughput_tps = 0.0
    ts_values = [p["ts"] for p in parsed if p.get("ts") is not None]
    if len(ts_values) > 1:
        duration_s = max(1.0, (max(ts_values) - min(ts_values)) / 1000.0)
        throughput_tps = round(count / duration_s, 3)

    # time series: 10s buckets
    ts_frames: List[Dict[str, Any]] = []
    if ts_values:
        buckets: Dict[int, List[float]] = {}
        for p in parsed:
            if p.get("ts") is None:
                continue
            b = (p["ts"] // 10000) * 10000
            buckets.setdefault(b, []).append(p["elapsed"])

        for b in sorted(buckets.keys()):
            vals = buckets[b]
            cnt = len(vals)
            p95b = _percentile(sorted(vals), 95) if cnt else 0.0
            ts_frames.append({"timestamp_ms": int(b), "tps": round(cnt / 10.0, 3), "p95_ms": round(float(p95b), 3), "count": cnt})

    overall = {
        "count": int(count),
        "avg_ms": round(float(avg_ms), 3),
        "p95_ms": round(float(p95_ms), 3),
        "p99_ms": round(float(p99_ms), 3),
        "error_rate_pct": round(float(error_rate), 3),
        "throughput_tps": float(throughput_tps),
    }

    return {"overall_stats": overall, "time_series": ts_frames}
