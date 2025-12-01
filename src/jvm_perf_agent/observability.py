"""
Observability helpers: logging and simple in-memory metrics.

Exports:
- `logger` : module-level logger (INFO level)
- `log_run_start(run_id, context)`
- `log_run_end(run_id, classification, key_metrics)`
- `record_analysis_time(seconds)`
- `get_metrics_snapshot()` -> serializable dict

This is intentionally small and thread-safe for demos and notebooks.
"""
from __future__ import annotations
import logging
import threading
from typing import Any, Dict, Optional
import time

# module-level logger
logger = logging.getLogger("jvm_perf_agent.observability")
if not logger.handlers:
    # configure basic handler if not configured elsewhere
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Simple in-memory metrics with a lock
_metrics_lock = threading.Lock()
_metrics: Dict[str, Any] = {
    "runs_total": 0,
    "cpu_bound_total": 0,
    "gc_heavy_total": 0,
    "latency_other_total": 0,
    "inconclusive_total": 0,
    "analysis_time_total_seconds": 0.0,
}


def log_run_start(run_id: str, context: Optional[Dict[str, Any]] = None) -> None:
    """Log the start of a run and bump runs_total."""
    context = context or {}
    logger.info("Run start: %s; context=%s", run_id, context)
    with _metrics_lock:
        _metrics["runs_total"] = int(_metrics.get("runs_total", 0)) + 1


def log_run_end(run_id: str, classification: str, key_metrics: Optional[Dict[str, Any]] = None) -> None:
    """Log end of run, record classification counters and key metrics.

    `classification` expected values: CPU_BOUND, GC_HEAVY, LATENCY_OTHER, INCONCLUSIVE
    """
    key_metrics = key_metrics or {}
    logger.info("Run end: %s; classification=%s; key_metrics=%s", run_id, classification, key_metrics)
    klass = (classification or "").upper()
    with _metrics_lock:
        if klass == "CPU_BOUND":
            _metrics["cpu_bound_total"] = int(_metrics.get("cpu_bound_total", 0)) + 1
        elif klass == "GC_HEAVY":
            _metrics["gc_heavy_total"] = int(_metrics.get("gc_heavy_total", 0)) + 1
        elif klass == "LATENCY_OTHER":
            _metrics["latency_other_total"] = int(_metrics.get("latency_other_total", 0)) + 1
        elif klass == "INCONCLUSIVE":
            _metrics["inconclusive_total"] = int(_metrics.get("inconclusive_total", 0)) + 1
        # optionally record some key metric snapshot
        # e.g., capture last p95 in metrics for quick access
        try:
            p95 = float(key_metrics.get("p95_ms")) if key_metrics and key_metrics.get("p95_ms") is not None else None
        except Exception:
            p95 = None
        if p95 is not None:
            _metrics["last_p95_ms"] = round(float(p95), 3)


def record_analysis_time(seconds: float) -> None:
    """Record seconds spent in analysis (accumulated)."""
    try:
        secs = float(seconds)
    except Exception:
        return
    with _metrics_lock:
        _metrics["analysis_time_total_seconds"] = float(_metrics.get("analysis_time_total_seconds", 0.0)) + secs


def get_metrics_snapshot() -> Dict[str, Any]:
    """Return a serializable snapshot of current metrics including averages."""
    with _metrics_lock:
        snap = dict(_metrics)
    # compute average analysis time per run if possible
    runs = int(snap.get("runs_total", 0) or 0)
    total_time = float(snap.get("analysis_time_total_seconds", 0.0) or 0.0)
    snap["avg_analysis_time_s"] = round((total_time / runs) if runs > 0 else 0.0, 3)
    # ensure simple types
    snap["runs_total"] = int(snap.get("runs_total", 0))
    snap["analysis_time_total_seconds"] = round(float(snap.get("analysis_time_total_seconds", 0.0)), 3)
    return snap


__all__ = [
    "logger",
    "log_run_start",
    "log_run_end",
    "record_analysis_time",
    "get_metrics_snapshot",
]
