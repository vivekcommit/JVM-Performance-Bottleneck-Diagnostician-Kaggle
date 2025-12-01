"""
Deterministic diagnosis rules for JVM performance runs.

Provides `diagnose_performance(jmeter_stats, jvm_stats, context)` which applies a
small explicit rule set to classify runs into: CPU_BOUND, GC_HEAVY, LATENCY_OTHER,
or INCONCLUSIVE. The function returns a dict with:
 - classification: one of the above
 - findings: list of human-readable observations
 - recommendations: list of 3-5 actionable recommendations (tailored by framework/jdk when possible)

Rules are intentionally simple and explainable to make the output easy to read
in a Kaggle notebook or short demo.
"""
from __future__ import annotations
from typing import Dict, Any, List


def _safe_get(d: Dict, *keys, default=None):
    v = d
    for k in keys:
        if not isinstance(v, dict):
            return default
        v = v.get(k, default)
    return v


def diagnose_performance(jmeter_stats: Dict[str, Any], jvm_stats: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Apply deterministic rules to classify performance issues.

    Inputs expected:
      - jmeter_stats: as returned by `parse_jmeter_csv` (overall_stats + time_series)
      - jvm_stats: as returned by `parse_jvm_stats` (gc_summary, heap_trend, cpu_flag)
      - context: optional, may contain `sla_ms`, `framework` (e.g., Vert.x, Tomcat), `jdk` (e.g., 8, 21)

    Returns: {classification, findings, recommendations}
    """
    sla_ms = float(context.get("sla_ms", 500.0))
    framework = (context.get("framework") or "").lower()
    jdk = str(context.get("jdk") or "").lower()

    overall = jmeter_stats.get("overall_stats") or {}
    time_series = jmeter_stats.get("time_series") or []
    gc = jvm_stats.get("gc_summary") or {}
    heap = jvm_stats.get("heap_trend") or {}
    cpu_flag = jvm_stats.get("cpu_flag") or "unknown"

    findings: List[str] = []
    recommendations: List[str] = []
    classification = "INCONCLUSIVE"

    # Extract useful signals
    p95 = float(overall.get("p95_ms", 0.0) or 0.0)
    error_rate = float(overall.get("error_rate_pct", 0.0) or 0.0)
    count = int(overall.get("count", 0) or 0)
    throughput = float(overall.get("throughput_tps", 0.0) or 0.0)

    gc_overhead = float(gc.get("gc_overhead_pct", 0.0) or 0.0)
    max_pause = float(gc.get("max_pause_ms", 0.0) or 0.0)

    start_heap = float(heap.get("start_heap_mb", 0.0) or 0.0)
    end_heap = float(heap.get("end_heap_mb", 0.0) or 0.0)
    max_heap = float(heap.get("max_heap_mb", 0.0) or 0.0)

    # Findings about errors and SLA
    if error_rate > 0.5:
        findings.append(f"Elevated error rate: {error_rate}%")
    if p95 > sla_ms:
        findings.append(f"p95 latency {p95} ms exceeds SLA {sla_ms} ms")
    else:
        findings.append(f"p95 latency {p95} ms within SLA {sla_ms} ms")

    # TPS plateau detection: find max tps and count of buckets near max
    plateau = False
    if time_series:
        tps_vals = [float(b.get("tps", 0.0)) for b in time_series]
        max_tps = max(tps_vals) if tps_vals else 0.0
        if max_tps > 0:
            near_max = [v for v in tps_vals if v >= 0.9 * max_tps]
            if len(near_max) >= 3:
                plateau = True
                findings.append(f"Throughput plateau detected: max_tps={round(max_tps,3)} tps, sustained across {len(near_max)} buckets")

    # GC signals
    if gc_overhead >= 10.0:
        findings.append(f"High GC overhead: {gc_overhead}% of test time spent in GC")
    if max_pause >= 200.0:
        findings.append(f"GC pause spikes observed: max pause {max_pause} ms")

    # Heap trend
    if max_heap and end_heap >= max_heap * 0.9 and end_heap > start_heap:
        findings.append(f"Heap trending upward: start={start_heap}MB end={end_heap}MB max={max_heap}MB")

    # CPU signal
    findings.append(f"CPU flag: {cpu_flag}")

    # Classification heuristics (ordered, explicit rules)
    # 1. GC heavy: significant GC overhead OR frequent long pauses
    if gc_overhead >= 12.0 or max_pause >= 300.0:
        classification = "GC_HEAVY"

    # 2. CPU bound: CPU very high or sustained TPS plateau with high CPU
    cpu_high = cpu_flag == "high"
    if cpu_high and (plateau or p95 > sla_ms):
        classification = "CPU_BOUND"

    # 3. Latency other: p95 exceeds SLA but not GC or CPU signals strongly
    if classification == "INCONCLUSIVE":
        if p95 > sla_ms or error_rate > 1.0:
            # if GC or CPU minor signals present, prefer those
            if gc_overhead >= 8.0 or max_pause >= 150.0:
                classification = "GC_HEAVY"
            elif cpu_high:
                classification = "CPU_BOUND"
            else:
                classification = "LATENCY_OTHER"

    # If still inconclusive but we saw errors and p95 within SLA, mark latency_other
    if classification == "INCONCLUSIVE" and error_rate > 1.0:
        classification = "LATENCY_OTHER"

    # Compose recommendations tailored by framework and JDK
    # Base recommendations per classification
    if classification == "GC_HEAVY":
        recommendations.extend([
            "Investigate allocation hotspots and reduce short-lived object churn.",
            "Consider tuning GC settings (collector choice, heap sizing, survivor ratios).",
            "Increase heap (if safe) to reduce GC frequency and monitor pause distribution.",
        ])
        if "vert" in framework:
            recommendations.append("For Vert.x, ensure worker threads and event-loop blocking operations are minimized.")
        if "tomcat" in framework:
            recommendations.append("For Tomcat, tune connector thread pools and check request queuing/backpressure.")
        if jdk in ("8", "8u"):
            recommendations.append("On JDK 8, prefer G1 tuning or consider CMS-to-G1 migration patterns.")
        elif jdk in ("21", "21u"):
            recommendations.append("On JDK 21, consider ZGC/CRaC options and review ergonomic defaults.")

    elif classification == "CPU_BOUND":
        recommendations.extend([
            "Profile the application to find CPU hotspots (async traces, flamegraphs).",
            "Offload expensive work to background workers or increase CPU cores/instances.",
            "Review native or JNI calls that may be consuming CPU.",
        ])
        if "vert" in framework:
            recommendations.append("For Vert.x: ensure event-loop handlers are non-blocking and use worker verticles for blocking tasks.")
        if "tomcat" in framework:
            recommendations.append("For Tomcat: tune maxThreads and ensure request handling is efficient.")

    elif classification == "LATENCY_OTHER":
        recommendations.extend([
            "Collect traces (distributed tracing) for slow transactions to find hotspots.",
            "Examine downstream dependencies (DB, HTTP calls) and network latencies.",
            "Add per-request timing to identify slow endpoints and payloads.",
        ])
        if error_rate > 1.0:
            recommendations.append("Correlate errors with slow requests — fix application-level exceptions first.")

    else:  # INCONCLUSIVE
        recommendations.extend([
            "Collect longer-duration runs with full metrics (heap profiles, CPU samples, traces).",
            "Increase sampling frequency for heap and GC events to provide signals.",
            "If possible, run a controlled load test gradually increasing load to observe saturation characteristics.",
        ])

    # Shorten recommendations to max 5
    if len(recommendations) > 5:
        recommendations = recommendations[:5]

    return {
        "classification": classification,
        "findings": findings,
        "recommendations": recommendations,
    }


__all__ = ["diagnose_performance"]
