# jvm-perf-agent

A compact, explainable Python agent that helps diagnose Java service performance regressions by correlating JMeter load-test outputs with JVM-level metrics (GC, heap, CPU). The agent is intentionally small, deterministic, and easy to run from a notebook, CI job, or a lightweight HTTP wrapper.

## Problem — why this matters

Diagnosing regressions in Java services (for example, Vert.x or Tomcat) is often manual and slow: engineers must scan JMeter CSVs for latency percentiles and throughput, cross-check error rates, and then inspect JVM metrics (GC pauses, heap growth, CPU utilization) to form a hypothesis. Differences between JDK versions, runtime frameworks, or GC tuning make reproducing and triaging regressions harder. This results in long incident cycles and risk of applying ineffective tuning changes that either fail to fix the problem or create new instability.

## Agentic solution — what this project provides

`jvm-perf-agent` automates the repetitive, first-cut diagnosis step with a transparent, rule-based agent. It parses JMeter CSVs into aggregated and time-series metrics, ingests a compact JVM JSON summary (GC events, heap samples, CPU), and applies deterministic heuristics to classify the dominant bottleneck (for example, CPU_BOUND, GC_HEAVY, LATENCY_OTHER, or INCONCLUSIVE). The output includes a structured `diagnosis` object (classification, findings, recommendations) and a concise human-readable `summary` suitable for an incident ticket. The approach prioritizes clear, actionable recommendations over black-box inference so teams can quickly validate and act on findings.

## Architecture — orchestrator, tools, memory, observability

The implementation follows a lightweight tool-oriented pattern: an orchestrator composes small focused tools and services to form the agent. Major components under `src/jvm_perf_agent/`:

- `agent.py`: the orchestrator and public entry points (`analyze_performance_run`, `run_http_like_handler`). It coordinates parsing, diagnosis, summarization, and session compare logic.
- `tools/jmeter_parser.py`: parses JMeter CSV files (pandas when available, csv fallback) and returns aggregate metrics and 10s time-series buckets.
- `tools/jvm_parser.py`: ingests compact JVM JSON (GC events, heap samples, CPU) and produces gc summaries, heap trends, and a simple CPU health flag.
- `diagnosis.py`: the deterministic rule engine that maps parsed metrics to classifications, findings, and tailored recommendations (framework/JDK-aware when context is provided).
- `sessions.py`: an in-memory session helper that stores a compact summary per `session_id`, enabling simple "compared to last run" comparisons useful for regression triage.
- `observability.py`: light-weight observability hooks (INFO-level logging and small in-memory metrics counters) to trace runs and collect counts/latency for demo or CI use.

This modular design keeps each piece small and testable and makes it straightforward to swap or extend tools (for example, adding richer JVM inputs or a persistent session store).

## Mapping to the 5‑Day AI Agents Intensive concepts

This project intentionally maps to key agent-design concepts taught in the intensive:

- Multi-agent & Tools: the orchestrator behaves like a coordinator that composes small, purpose-built tools (parsers, classifier). Each tool is simple and focused — a recommended pattern in agent design to reduce complexity and increase explainability.
- Sessions & Memory: the `sessions` component demonstrates short-term memory: storing a previous run summary and enabling the agent to produce comparative statements like "p95 improved by X ms compared to last run" — an important UX pattern for iterative tuning.
- Observability: lightweight telemetry and logs let you audit what the agent did and measure usage (runs, classification counts, avg analysis time). Observability is crucial for trust and debugging in automated agent workflows.
- A2A / Deployment: the `run_http_like_handler` and the suggested FastAPI wrapper illustrate how an agent can be composed into pipelines or called by other agents (A2A), enabling automation and CI integration without heavy infra.
- Deterministic, Explainable Reasoning: using explicit rules keeps recommendations reproducible and reviewable — a practical choice when a human operator must validate and act on suggestions.

## Getting Started (short)

Prerequisites: Python 3.10+. Recommended: create a venv and install requirements (if provided).

### Gemini Flash Integration (Optional)

To enable LLM-backed session analysis using Gemini Flash:

1. **Install the Gemini client:**
   ```bash
   pip install google-generativeai
   ```

2. **Configure your API key and model:**
   
   **Option A: Config file (recommended for security)**
   - Copy the template: `cp config/jvm_perf_agent.json.example config/jvm_perf_agent.json`
   - Edit `config/jvm_perf_agent.json` and add your API key:
     ```json
     {
       "gemini_api_key": "YOUR_API_KEY_HERE",
       "gemini_model": "gemini-2.5-flash-lite"
     }
     ```
   - The agent will automatically load this config on import.

   **Option B: Environment variables**
   ```bash
   export JVM_PERF_AGENT_GEMINI_API_KEY="your-key-here"
   export JVM_PERF_AGENT_GEMINI_MODEL="gemini-2.5-flash-lite"
   ```

   **Option C: User home directory (auto-loaded)**
   - Create `~/.jvm_perf_agent/config.json` with the same structure as the template.

3. **Enable Gemini usage:**
   - Set `USE_GEMINI_SESSION=1` to force Gemini; otherwise it auto-enables if a config file or API key is detected.

When enabled, the agent stores both the deterministic diagnosis and an LLM-produced analysis (key `"last_summary_llm"`) in each session for richer insights.

### Quick Usage

```python
from jvm_perf_agent.agent import analyze_performance_run
result = analyze_performance_run(jmeter_csv_text, jvm_json_text, context={"sla_ms":200, "framework":"Tomcat"})
print(result["summary"])
```

See `notebooks/kaggle_capstone.ipynb` for a ready-to-run Kaggle-style demo with three synthetic scenarios and an evaluation cell.

## A2A & Deployment (brief)

Two easy integration patterns: (1) a tiny FastAPI wrapper exposing `POST /analyze` that forwards payloads to `run_http_like_handler`, and (2) direct A2A invocation by importing the handler from another process. Both approaches are low-cost for POCs and integrate with CI pipelines or test orchestrators.

---

If you'd like, I can also add a minimal `requirements.txt` / `pyproject.toml`, a sample `app.py` (FastAPI) plus Dockerfile, and example data under `data/` to make local testing even simpler.