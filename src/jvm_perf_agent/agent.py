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
    from jvm_perf_agent.diagnosis import run_diagnosis
except Exception:  # pragma: no cover
    run_diagnosis = None


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

    # Register diagnosis tool (use fallback if not present)
    if run_diagnosis is not None:
        agent.register_tool("run_diagnosis", run_diagnosis)
    else:
        agent.register_tool("run_diagnosis", _fallback_run_diagnosis)

    return agent


def analyze_performance_run(jmeter_path: str | dict, jvm_stats_path: str | dict, context_dict: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Convenience entrypoint to parse inputs and run diagnosis.

    Parameters:
      - jmeter_path: path to a JMeter CSV file or raw CSV text or already-parsed dict
      - jvm_stats_path: path to JVM stats (text/JSON) or dict
      - context_dict: optional context (service name, environment, timeframe)

    Returns a dict with keys `diagnosis` (the diagnosis result) and `raw` (parser outputs).
    """
    ctx = context_dict or {}
    agent = create_perf_tuning_agent()

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

    # Run diagnosis
    try:
        diagnosis = agent.call_tool("run_diagnosis", jmeter_out, jvm_out, ctx)
    except Exception as exc:
        logger.exception("Diagnosis failed: %s", exc)
        diagnosis = {"error": str(exc)}

    return {"diagnosis": diagnosis, "raw": {"jmeter": jmeter_out, "jvm": jvm_out, "context": ctx}}


__all__ = ["create_perf_tuning_agent", "analyze_performance_run", "PerfTuningAgent"]
