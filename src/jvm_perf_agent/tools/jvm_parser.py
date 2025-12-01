"""
Simple JVM stats parser for textual 'key: value' dumps or JSON-like dictionaries.
Provides parse_jvm_stats(path_or_text_or_dict) -> dict with keys: heap_used_mb, heap_committed_mb, gc_count, gc_time_ms, threads, cpu_system_pct
Accepts either a file path, raw text, or a dict (already parsed JSON).
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import json
import re


def _read_text(path_or_text: str) -> str:
    p = Path(path_or_text)
    if p.exists():
        return p.read_text(encoding='utf-8')
    return str(path_or_text)


def parse_jvm_stats(obj) -> Dict[str, float]:
    # if a dict is passed, just extract
    if isinstance(obj, dict):
        data = obj
    else:
        text = _read_text(obj)
        # try JSON
        try:
            data = json.loads(text)
        except Exception:
            data = {}
            # parse simple key: value lines
            for line in text.splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    data[k.strip().lower()] = v.strip()

    # heuristics
    def _parse_mem(v) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).lower()
        m = re.match(r"([0-9\.]+)\s*(mb|kb|b|gb)?", s)
        if not m:
            try:
                return float(s)
            except Exception:
                return 0.0
        val = float(m.group(1))
        unit = m.group(2) or 'b'
        unit = unit.lower()
        if unit == 'kb':
            return val / 1024.0
        if unit == 'b':
            return val / (1024.0*1024.0)
        if unit == 'gb':
            return val * 1024.0
        return val

    heap_used = 0.0
    heap_committed = 0.0
    gc_count = 0
    gc_time_ms = 0.0
    threads = 0
    cpu_system = 0.0

    for k, v in data.items():
        key = str(k).lower()
        if 'heap' in key and 'used' in key:
            heap_used = _parse_mem(v)
        if 'heap' in key and 'committed' in key:
            heap_committed = _parse_mem(v)
        if 'gc' in key and 'count' in key:
            try:
                gc_count = int(v)
            except Exception:
                gc_count = gc_count
        if 'gc' in key and ('time' in key or 'ms' in key):
            try:
                gc_time_ms = float(v)
            except Exception:
                pass
        if 'thread' in key and ('count' in key or 'threads' in key):
            try:
                threads = int(v)
            except Exception:
                pass
        if 'cpu' in key and ('system' in key or 'process' in key):
            try:
                cpu_system = float(v)
            except Exception:
                pass

    return {
        'heap_used_mb': round(heap_used, 3),
        'heap_committed_mb': round(heap_committed, 3),
        'gc_count': int(gc_count),
        'gc_time_ms': float(gc_time_ms),
        'threads': int(threads),
        'cpu_system_pct': float(cpu_system),
    }
