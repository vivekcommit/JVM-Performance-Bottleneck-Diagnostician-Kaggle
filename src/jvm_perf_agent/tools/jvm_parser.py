"""
Simple JVM JSON stats parser.

This parser expects a small, pre-processed JSON file containing summary GC and
heap metrics. The schema is intentionally minimal and tolerant. Example schema:

{
  "test_start_ms": 1700000000000,
  "test_end_ms": 1700000005000,
  "gc": {
    "events": [ {"ts_ms": 1700000001000, "pause_ms": 120}, ... ]
  },
  "heap": {
    "samples": [ {"ts_ms": 1700000000000, "used_mb": 256}, ... ]
  },
  "cpu": { "system_pct": 23.5 }
}

The function `parse_jvm_stats(path)` returns:
- `gc_summary`: {total_gc_count, total_pause_ms, max_pause_ms, gc_overhead_pct, test_duration_s}
- `heap_trend`: {start_heap_mb, end_heap_mb, max_heap_mb}
- `cpu_flag`: one of `low`, `medium`, `high` (based on system_pct thresholds)

The parser will also try to accept a raw JSON string (if `path` is not a file
but contains JSON text) to make testing easier.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import json


def _read_text(path_or_text: str) -> str:
    p = Path(path_or_text)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return str(path_or_text)


def _safe_float(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def parse_jvm_stats(path: str) -> Dict[str, Any]:
    """Parse pre-processed JVM JSON stats from `path` (or raw JSON string).

    Returns a dict with keys: `gc_summary`, `heap_trend`, `cpu_flag`.
    """
    text = _read_text(path)
    try:
        data = json.loads(text)
    except Exception:
        # not valid JSON -> return empty structured result
        return {"gc_summary": {}, "heap_trend": {}, "cpu_flag": "unknown"}

    # test duration
    start_ms = int(data.get("test_start_ms") or data.get("start_ms") or 0)
    end_ms = int(data.get("test_end_ms") or data.get("end_ms") or 0)
    test_duration_s = 0.0
    if start_ms and end_ms and end_ms > start_ms:
        test_duration_s = (end_ms - start_ms) / 1000.0
    else:
        # try to infer from heap samples or gc events
        s_ts = None
        e_ts = None
        heap_samples = data.get("heap", {}).get("samples") or []
        gc_events = data.get("gc", {}).get("events") or []
        for s in heap_samples:
            ts = s.get("ts_ms")
            if ts is not None:
                if s_ts is None or ts < s_ts:
                    s_ts = ts
                if e_ts is None or ts > e_ts:
                    e_ts = ts
        for g in gc_events:
            ts = g.get("ts_ms")
            if ts is not None:
                if s_ts is None or ts < s_ts:
                    s_ts = ts
                if e_ts is None or ts > e_ts:
                    e_ts = ts
        if s_ts is not None and e_ts is not None and e_ts > s_ts:
            test_duration_s = (e_ts - s_ts) / 1000.0

    # GC summary
    gc = data.get("gc", {}) or {}
    events = gc.get("events") or []
    total_gc_count = int(gc.get("total_gc_count") or len(events) or 0)
    pauses = []
    for ev in events:
        p = ev.get("pause_ms")
        if p is None:
            # try alternate keys
            p = ev.get("duration_ms") or ev.get("pause")
        try:
            pauses.append(float(p))
        except Exception:
            continue
    total_pause_ms = float(sum(pauses))
    max_pause_ms = float(max(pauses)) if pauses else 0.0
    gc_overhead_pct = 0.0
    if test_duration_s > 0:
        gc_overhead_pct = round((total_pause_ms / (test_duration_s * 1000.0)) * 100.0, 3)

    gc_summary = {
        "total_gc_count": int(total_gc_count),
        "total_pause_ms": round(float(total_pause_ms), 3),
        "max_pause_ms": round(float(max_pause_ms), 3),
        "gc_overhead_pct": float(gc_overhead_pct),
        "test_duration_s": round(float(test_duration_s), 3),
    }

    # Heap trend
    heap = data.get("heap", {}) or {}
    heap_samples = heap.get("samples") or []
    start_heap_mb = None
    end_heap_mb = None
    max_heap_mb = None
    if heap_samples:
        # assume samples are ordered by time but be defensive
        try:
            sorted_samples = sorted(heap_samples, key=lambda s: s.get("ts_ms") or 0)
        except Exception:
            sorted_samples = heap_samples
        first = sorted_samples[0]
        last = sorted_samples[-1]
        start_heap_mb = _safe_float(first.get("used_mb") or first.get("heap_used_mb") or first.get("used"), 0.0)
        end_heap_mb = _safe_float(last.get("used_mb") or last.get("heap_used_mb") or last.get("used"), 0.0)
        max_heap_mb = 0.0
        for s in sorted_samples:
            v = _safe_float(s.get("used_mb") or s.get("heap_used_mb") or s.get("used"), 0.0)
            if v > max_heap_mb:
                max_heap_mb = v
    else:
        # fallback to top-level heap metrics
        start_heap_mb = _safe_float(heap.get("start_mb") or heap.get("start_heap_mb"), 0.0)
        end_heap_mb = _safe_float(heap.get("end_mb") or heap.get("end_heap_mb"), 0.0)
        max_heap_mb = _safe_float(heap.get("max_mb") or heap.get("max_heap_mb"), 0.0)

    heap_trend = {
        "start_heap_mb": round(float(start_heap_mb or 0.0), 3),
        "end_heap_mb": round(float(end_heap_mb or 0.0), 3),
        "max_heap_mb": round(float(max_heap_mb or 0.0), 3),
    }

    # CPU flag
    cpu = data.get("cpu") or {}
    cpu_pct = None
    if isinstance(cpu, dict):
        cpu_pct = cpu.get("system_pct") or cpu.get("process_pct") or cpu.get("cpu_pct")
    else:
        # cpu might be a scalar
        cpu_pct = cpu
    try:
        cpu_val = float(cpu_pct) if cpu_pct is not None else None
    except Exception:
        cpu_val = None

    cpu_flag = "unknown"
    if cpu_val is None:
        cpu_flag = "unknown"
    else:
        if cpu_val < 30.0:
            cpu_flag = "low"
        elif cpu_val < 70.0:
            cpu_flag = "medium"
        else:
            cpu_flag = "high"

    return {"gc_summary": gc_summary, "heap_trend": heap_trend, "cpu_flag": cpu_flag}

