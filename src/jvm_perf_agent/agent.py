"""
Minimal ADK-style multi-tool orchestrator for JVM perf tuning.

Provides:
- create_perf_tuning_agent(): returns a lightweight agent that can register and call tools.
- analyze_performance_run(jmeter_path, jvm_stats_path, context_dict): convenience entrypoint
  that parses inputs and runs diagnosis.

This module is intentionally self-contained and defensive so it works without the
real Google ADK installed. When you install the real ADK, you can replace
or adapt this scaffold to use ADK-specific classes and registration APIs.
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Dict
import time
import uuid

try:
    from jvm_perf_agent.observability import log_run_start, log_run_end, record_analysis_time, get_metrics_snapshot
except Exception:
    # observability is optional; fall back to no-op functions
    def log_run_start(run_id, context=None):
        return None

    def log_run_end(run_id, classification, key_metrics=None):
        return None

    def record_analysis_time(seconds):
        return None

    def get_metrics_snapshot():
        return {}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class PerfTuningAgent:
    """Lightweight orchestrator that holds named tools (callables).

    Each tool is a callable that accepts positional args and keyword args and
    returns a JSON-serializable result (dict, list, scalar).
    """

    def __init__(self) -> None:
        self.tools: Dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        """Register a named tool with the agent."""
        logger.info("Registering tool: %s", name)
        self.tools[name] = func

    def call_tool(self, name: str, *args, **kwargs) -> Any:
        """Call a registered tool by name.

        Raises KeyError if the tool isn't registered.
        """
        if name not in self.tools:
            raise KeyError(f"Tool not registered: {name}")
        return self.tools[name](*args, **kwargs)


# Attempt to import real tool implementations (parsers + diagnosis) from package.
try:
    from jvm_perf_agent.tools.jmeter_parser import parse_jmeter_csv
except Exception:  # pragma: no cover - defensive fallback
    parse_jmeter_csv = None

try:
    from jvm_perf_agent.tools.jvm_parser import parse_jvm_stats
except Exception:  # pragma: no cover
    parse_jvm_stats = None

try:
    # diagnosis.py exposes diagnose_performance; import it and register under that name
    from jvm_perf_agent.diagnosis import diagnose_performance
except Exception:  # pragma: no cover
    diagnose_performance = None


def _fallback_run_diagnosis(jmeter: Dict[str, Any], jvm: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """A small deterministic rule-set used when no `run_diagnosis` is provided.

    This function provides reasonable, explainable outputs for demos and unit
    tests without requiring the full diagnosis implementation.
    """
    p95 = float(jmeter.get("p95", 0.0))
    error_rate = float(jmeter.get("error_rate", 0.0))
    gc_time = float(jvm.get("gc_time_ms", 0.0))
    heap_used = float(jvm.get("heap_used_mb", 0.0))
    cpu = float(jvm.get("cpu_system_pct", 0.0))

    reasons = []
    recommendations = []
    primary = "unknown"

    # Simple rules
    if error_rate > 1.0:
        primary = "errors_high"
        reasons.append(f"High error rate: {error_rate}%")
        recommendations.append("Investigate application errors and logs.")

    if gc_time > 1000.0:
        primary = "gc_heavy"
        reasons.append(f"High GC time: {gc_time} ms")
        recommendations.append("Tune GC, increase heap, or investigate allocation hotspots.")

    if p95 > 1000.0 and primary == "unknown":
        primary = "latency_high"
        reasons.append(f"High p95 latency: {p95} ms")
        recommendations.append("Trace slow transactions and check downstream services.")

    if cpu > 80.0 and primary == "unknown":
        primary = "cpu_bound"
        reasons.append(f"High CPU usage: {cpu}%")
        recommendations.append("Profile CPU hotspots and consider scaling CPU resources.")

    if primary == "unknown":
        primary = "no_obvious_issue"
        recommendations.append("No strong signals found; collect longer traces and more metrics.")

    return {
        "primary": primary,
        "reasons": reasons,
        "recommendations": recommendations,
        "inputs": {"jmeter": jmeter, "jvm": jvm, "context": context},
    }


def create_perf_tuning_agent() -> PerfTuningAgent:
    """Create and return a PerfTuningAgent with the core tools registered.

    The function registers three tools (names match the user's request):
      - `parse_jmeter_csv` -> callable(path_or_text) -> dict
      - `parse_jvm_stats`  -> callable(path_or_text_or_dict) -> dict
      - `run_diagnosis`    -> callable(jmeter_dict, jvm_dict, context) -> dict

    If the real implementations are not importable, light-weight fallbacks are used
    so `analyze_performance_run` remains usable for demos and notebooks.
    """
    agent = PerfTuningAgent()

    # Register parser tools (use fallbacks if imports failed)
    if parse_jmeter_csv is not None:
        agent.register_tool("parse_jmeter_csv", parse_jmeter_csv)
    else:
        def _err_jmeter(*a, **k):
            raise RuntimeError("parse_jmeter_csv not available. Ensure tools.jmeter_parser is present.")

        agent.register_tool("parse_jmeter_csv", _err_jmeter)

    if parse_jvm_stats is not None:
        agent.register_tool("parse_jvm_stats", parse_jvm_stats)
    else:
        def _err_jvm(*a, **k):
            raise RuntimeError("parse_jvm_stats not available. Ensure tools.jvm_parser is present.")

        agent.register_tool("parse_jvm_stats", _err_jvm)

    # Register diagnosis tool (prefer the real diagnose_performance if available)
    if diagnose_performance is not None:
        agent.register_tool("diagnose_performance", diagnose_performance)
    else:
        agent.register_tool("diagnose_performance", _fallback_run_diagnosis)

    return agent


def _summarize_results(diagnosis: Dict[str, Any], raw: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Create a concise, user-facing summary of the diagnosis and key findings.

    This acts as a lightweight LLM-style summarizer for demos/notebooks.
    """
    cls = diagnosis.get("classification") or diagnosis.get("primary") or "INCONCLUSIVE"
    findings = diagnosis.get("findings") or diagnosis.get("reasons") or []
    recs = diagnosis.get("recommendations") or []

    lines = [f"Classification: {cls}"]
    if findings:
        lines.append("Top findings:")
        for f in findings[:3]:
            lines.append(f" - {f}")
    if recs:
        lines.append("Top recommendations:")
        for r in recs[:3]:
            lines.append(f" - {r}")

    # small contextual pointers
    svc = context.get("service") or context.get("app") or None
    if svc:
        lines.append(f"Service: {svc}")

    return "\n".join(lines)


def analyze_performance_run(jmeter_path: str | dict, jvm_stats_path: str | dict, context_dict: Dict[str, Any] | None = None, session_id: str | None = None) -> Dict[str, Any]:
    """Convenience entrypoint to parse inputs and run diagnosis.

    Parameters:
      - jmeter_path: path to a JMeter CSV file or raw CSV text or already-parsed dict
      - jvm_stats_path: path to JVM stats (text/JSON) or dict
      - context_dict: optional context (service name, environment, timeframe)

    Returns a dict with keys `diagnosis` (the diagnosis result) and `raw` (parser outputs).
    """
    ctx = context_dict or {}
    agent = create_perf_tuning_agent()

    # run id and observability: generate a run id if not provided in context
    run_id = ctx.get("run_id") or f"run-{uuid.uuid4().hex[:8]}"
    # log start
    try:
        log_run_start(run_id, ctx)
    except Exception:
        pass
    start_ts = time.time()

    # Parse JMeter
    try:
        jmeter_out = agent.call_tool("parse_jmeter_csv", jmeter_path)
    except Exception as exc:
        logger.exception("Failed to parse JMeter input: %s", exc)
        jmeter_out = {"error": str(exc)}

    # Parse JVM stats
    try:
        jvm_out = agent.call_tool("parse_jvm_stats", jvm_stats_path)
    except Exception as exc:
        logger.exception("Failed to parse JVM stats: %s", exc)
        jvm_out = {"error": str(exc)}

    # Run diagnosis (use the registered diagnose_performance tool)
    try:
        diagnosis = agent.call_tool("diagnose_performance", jmeter_out, jvm_out, ctx)
    except Exception as exc:
        logger.exception("Diagnosis failed: %s", exc)
        diagnosis = {"error": str(exc)}

    raw = {"jmeter": jmeter_out, "jvm": jvm_out, "context": ctx}

    # Summarize (lightweight LLM-style summarizer)
    try:
        summary = _summarize_results(diagnosis, raw, ctx)
    except Exception:
        summary = "(failed to summarize results)"

    # observability: measure elapsed time and record it
    try:
        elapsed = time.time() - start_ts
        record_analysis_time(elapsed)
    except Exception:
        elapsed = None

    # log end and classification-based counters
    try:
        classification = diagnosis.get("classification") if isinstance(diagnosis, dict) else None
        # expose key metrics such as p95 if available
        key_metrics = {}
        try:
            key_metrics["p95_ms"] = jmeter_out.get("overall_stats", {}).get("p95_ms")
        except Exception:
            pass
        log_run_end(run_id, classification or "INCONCLUSIVE", key_metrics)
    except Exception:
        pass

    # If session_id provided, load previous summary, compute brief comparison text,
    # and save the current summary as the last run for the session.
    comparison_text = None
    if session_id:
        try:
            from jvm_perf_agent.sessions import load_previous_run_summary, save_run_summary

            prev = load_previous_run_summary(session_id)
            # Prepare current summary to save
            current_summary = {
                "diagnosis": diagnosis,
                "overall_stats": jmeter_out.get("overall_stats") if isinstance(jmeter_out, dict) else None,
                "gc_summary": jvm_out.get("gc_summary") if isinstance(jvm_out, dict) else None,
            }

            # Compute comparison if previous exists
            if prev:
                try:
                    prev_overall = prev.get("overall_stats") or prev.get("jmeter", {}).get("overall_stats") or {}
                    prev_p95 = float(prev_overall.get("p95_ms") or 0.0)
                except Exception:
                    prev_p95 = 0.0
                try:
                    prev_diag = prev.get("diagnosis") or prev.get("diagnosis", {})
                    prev_class = (prev_diag.get("classification") if isinstance(prev_diag, dict) else None) or prev.get("classification")
                except Exception:
                    prev_class = None

                curr_overall = current_summary.get("overall_stats") or {}
                curr_p95 = float(curr_overall.get("p95_ms") or 0.0)
                curr_class = (diagnosis.get("classification") if isinstance(diagnosis, dict) else None) or diagnosis.get("primary")

                p95_delta = None
                try:
                    p95_delta = curr_p95 - prev_p95
                except Exception:
                    p95_delta = None

                parts = []
                if p95_delta is not None:
                    sign = "+" if p95_delta >= 0 else ""
                    parts.append(f"p95 change: {sign}{round(p95_delta,3)} ms (prev {round(prev_p95,3)} -> now {round(curr_p95,3)})")
                if prev_class is not None and curr_class is not None and prev_class != curr_class:
                    parts.append(f"classification changed: {prev_class} -> {curr_class}")
                if parts:
                    comparison_text = "; ".join(parts)
                    summary = summary + "\n\nComparison with previous run:\n" + comparison_text

            # save current summary (overwrite)
            try:
                save_run_summary(session_id, current_summary)
            except Exception:
                # non-fatal
                pass
        except Exception:
            # session helper import or ops failed; ignore silently
            comparison_text = None

    return {"summary": summary, "diagnosis": diagnosis, "raw": raw, "comparison": comparison_text}


__all__ = ["create_perf_tuning_agent", "analyze_performance_run", "PerfTuningAgent"]


def run_http_like_handler(request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Framework-agnostic handler that accepts a request-like dict and returns a serializable dict.

    Expected request_body keys:
      - `jmeter_path` (str): path or raw CSV text for JMeter results
      - `jvm_stats_path` (str): path or raw JSON text for JVM stats
      - `context` (dict, optional): analysis context (sla_ms, framework, jdk, debug, service, etc.)
      - `session_id` (str, optional): session id to persist/compare runs

    Returns a JSON-serializable dict with keys `summary`, `diagnosis`, `raw`, and `comparison`,
    or an `error` key with status and message when validation fails.
    """
    if not isinstance(request_body, dict):
        return {"error": {"status": 400, "message": "request_body must be a dict"}}

    jmeter_path = request_body.get("jmeter_path")
    jvm_stats_path = request_body.get("jvm_stats_path")
    context = request_body.get("context") or {}
    session_id = request_body.get("session_id")

    if not jmeter_path:
        return {"error": {"status": 400, "message": "missing required field: jmeter_path"}}
    if not jvm_stats_path:
        return {"error": {"status": 400, "message": "missing required field: jvm_stats_path"}}

    try:
        result = analyze_performance_run(jmeter_path, jvm_stats_path, context, session_id=session_id)
    except Exception as exc:
        # Catch and return error details in a serializable form
        return {"error": {"status": 500, "message": "internal error during analysis", "detail": str(exc)}}

    # Ensure result is JSON-serializable (avoid non-serializable objects)
    # The package returns simple Python types; return as-is
    return result
