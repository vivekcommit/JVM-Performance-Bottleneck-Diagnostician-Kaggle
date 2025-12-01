# jvm-perf-agent

A compact Python AI agent (built with Google’s Agent Development Kit — ADK) to analyze JMeter CSV results and simplified JVM stats JSON, classify JVM performance bottlenecks (CPU_BOUND, GC_HEAVY, LATENCY_OTHER, INCONCLUSIVE), and produce actionable tuning recommendations for Vert.x or Tomcat on JDK 8 and JDK 21.

## Problem

Java services (Vert.x, Tomcat) frequently encounter performance regressions that are time-consuming to diagnose. Engineers must manually inspect JMeter results and JVM metrics (GC, heap, CPU) across JDK versions to determine whether problems are CPU-bound, GC-heavy, or caused by external latency.

## Solution

`jvm-perf-agent` automates diagnosis by:
- Parsing JMeter CSV aggregate results and extracting key metrics (p50/p95/p99, error rate, throughput, time-series).
- Parsing a simplified JVM stats JSON (GC overhead, pause times, heap trend, CPU utilization).
- Applying deterministic rule-based logic to classify the bottleneck and generate clear tuning recommendations tailored for Vert.x or Tomcat on JDK 8/21.

## Architecture

Project layout (under `src/jvm_perf_agent/`):

- `agent.py` — orchestrator and public entrypoints (e.g., `analyze_performance_run(...)`).
- `tools/jmeter_parser.py` — custom JMeter CSV parser tool.
- `tools/jvm_parser.py` — custom JVM stats parser tool.
- `diagnosis.py` — deterministic rule-based classification and recommendation engine.
- `sessions.py` — per-session state (compact run summaries).
- `observability.py` — logging, in-memory metrics, and trace lists.

The code favors readability and determinism over opaque heuristics.

## Agent Concepts

- Multi-agent: An orchestrator LLM agent coordinates small, focused tool agents for parsing and diagnosis.
- Tools: Minimal custom tools only — JMeter parser, JVM parser, diagnosis/run-summary tool.
- Sessions & Memory: Use an in-memory session service (ADK `InMemorySessionService` or equivalent) to store compact summaries and enable "compared to your last run..." comparisons.
- Observability: Python `logging` (INFO), an in-memory metrics dict (runs, classification counts, avg analysis time), and a simple trace of tool invocations.
- A2A & Deployment: Expose a single function such as `analyze_performance_run(...)` or `run_http_like_handler(body)` for easy integration by other agents or HTTP services.

## Getting Started

Prerequisites:

- Python 3.10+
- (Optional) Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies (if provided):

```powershell
pip install -r requirements.txt
```

Or install the package in editable mode (if packaging is prepared):

```powershell
pip install -e .
```

## How to Run Locally

Typical usage patterns:

1. CLI (example — placeholder):

```powershell
python -m src.jvm_perf_agent.agent analyze_performance_run --jmeter ./data/sample.csv --jvm ./data/jvm_stats.json
```

2. Programmatic import:

```python
from jvm_perf_agent.agent import analyze_performance_run
result = analyze_performance_run(jmeter_csv_text, jvm_json_text)
print(result["classification"])
print(result["recommendations"])
```

Notes:
- The agent uses explicit rule-based logic for classification; avoid opaque ML unless clearly documented.
- Logging at INFO level provides run lifecycle and tool trace information.

## Kaggle Notebook Submission

The final Kaggle notebook should include:

- Problem & Solution overview.
- Installation or simulated-install instructions for the package.
- At least 2–3 synthetic example runs (CPU_BOUND, GC_HEAVY, LATENCY_OTHER).
- Both structured output (JSON/dict) and a natural-language explanation for each run.
- A short "Deployment & A2A" section showing how another agent or HTTP service would call `analyze_performance_run(...)`.

---

## A2A & Deployment

This project is intentionally small and 3-day deployable for demos or POC. Two practical integration patterns are:

1) Wrap the agent in a tiny HTTP service (FastAPI/Flask)

- Architecture: a lightweight web server exposes an endpoint (e.g., `POST /analyze`) that accepts a JSON body with fields `jmeter_path`, `jvm_stats_path`, `context`, and optional `session_id`. The endpoint calls the package function `run_http_like_handler(request_body)` (or `analyze_performance_run(...)`) and returns the JSON response. Observability hooks (`observability.log_run_start` / `log_run_end`) and the in-memory session helper are used to persist or compare runs.
- Why this is 3-day realistic: no infra changes required — a single-process FastAPI app can be developed and tested locally; containerization (Docker) is optional and straightforward.

2) Agent-to-Agent (A2A) invocation

- Architecture: another agent (or orchestration layer) prepares the same JSON payload and invokes the HTTP endpoint or directly imports `run_http_like_handler` if running in the same environment. This supports automated pipelines where a CI job or test orchestrator calls the agent after a load test completes.
- Why this is 3-day realistic: the handler is framework-agnostic and returns simple JSON; wiring into an existing orchestrator or CI script is just an HTTP POST or a module import.

Example request JSON shape (POST body or A2A payload):

```json
{
	"jmeter_path": "<path or raw CSV text>",
	"jvm_stats_path": "<path or raw JSON text>",
	"context": { "sla_ms": 200, "framework": "Tomcat", "jdk": "8", "service": "payments", "debug": false },
	"session_id": "session-123"
}
```

Example response shape:

```json
{
	"summary": "Classification: GC_HEAVY\nTop findings: ...",
	"diagnosis": { "classification": "GC_HEAVY", "findings": [...], "recommendations": [...] },
	"raw": { "jmeter": {...}, "jvm": {...}, "context": {...} },
	"comparison": "p95 change: -120ms (prev 420ms -> now 300ms)"
}
```

If you'd like, I can scaffold a minimal `app.py` (FastAPI) showing the exact endpoint and a Dockerfile for local testing.

---

If you want, I can also add `requirements.txt`, a minimal `pyproject.toml`, example data under `data/`, and a small `examples/runner.py` to demonstrate the agent locally.