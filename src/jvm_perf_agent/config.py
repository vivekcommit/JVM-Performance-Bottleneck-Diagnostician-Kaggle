"""
Secure configuration handler for jvm_perf_agent.

Reads sensitive configuration (API keys, model names) from a user-controlled
config file. Supports both JSON config files and environment variables.

Exports:
- `get_gemini_api_key()` -> API key string or None
- `get_gemini_model()` -> model name string or default
- `load_config(config_path)` -> load config from a specific file path
"""
from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

_LOG = logging.getLogger(__name__)

_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CONFIG_PATHS = [
    Path.home() / ".jvm_perf_agent" / "config.json",  # User home
    Path(".") / "config" / "jvm_perf_agent.json",  # Project config/
    Path(".") / ".jvm_perf_agent.json",  # Repo root
]


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from a file or environment variables.

    Priority (highest to lowest):
    1. Explicit config_path parameter
    2. Environment variable JVM_PERF_AGENT_CONFIG
    3. Default search paths (~/.jvm_perf_agent/config.json, ./config/jvm_perf_agent.json, ./.jvm_perf_agent.json)
    4. Environment variables (JVM_PERF_AGENT_GEMINI_API_KEY, JVM_PERF_AGENT_GEMINI_MODEL)

    Returns:
        Dictionary with keys like 'gemini_api_key', 'gemini_model'.
        If no config found, returns empty dict.
    """
    global _CONFIG_CACHE

    config_path = config_path or os.getenv("JVM_PERF_AGENT_CONFIG")

    # If explicit config_path, try to load it
    if config_path:
        try:
            p = Path(config_path)
            if p.exists() and p.is_file():
                with open(p, "r", encoding="utf-8") as f:
                    _CONFIG_CACHE = json.load(f)
                _LOG.info(f"Loaded config from {config_path}")
                return _CONFIG_CACHE
            else:
                _LOG.warning(f"Config file not found: {config_path}")
        except Exception as e:
            _LOG.error(f"Failed to load config from {config_path}: {e}")

    # Try default search paths
    for default_path in _CONFIG_PATHS:
        try:
            if default_path.exists() and default_path.is_file():
                with open(default_path, "r", encoding="utf-8") as f:
                    _CONFIG_CACHE = json.load(f)
                _LOG.info(f"Loaded config from default path {default_path}")
                return _CONFIG_CACHE
        except Exception as e:
            _LOG.debug(f"Failed to load config from {default_path}: {e}")

    # Fall back to environment variables
    _CONFIG_CACHE = {
        "gemini_api_key": os.getenv("JVM_PERF_AGENT_GEMINI_API_KEY"),
        "gemini_model": os.getenv("JVM_PERF_AGENT_GEMINI_MODEL"),
    }
    _LOG.debug("Using configuration from environment variables")
    return _CONFIG_CACHE


def get_gemini_api_key() -> Optional[str]:
    """Get the Gemini API key from config or environment."""
    if _CONFIG_CACHE is None:
        load_config()
    key = (_CONFIG_CACHE or {}).get("gemini_api_key")
    if not key:
        key = os.getenv("JVM_PERF_AGENT_GEMINI_API_KEY")
    return key


def get_gemini_model() -> str:
    """Get the Gemini model name from config or environment.
    
    Defaults to 'gemini-2.5-flash-lite' if not configured.
    """
    if _CONFIG_CACHE is None:
        load_config()
    model = (_CONFIG_CACHE or {}).get("gemini_model")
    if not model:
        model = os.getenv("JVM_PERF_AGENT_GEMINI_MODEL")
    return model or "gemini-2.5-flash-lite"


def reload_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Reload configuration, clearing the cache."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None
    return load_config(config_path)


__all__ = ["get_gemini_api_key", "get_gemini_model", "load_config", "reload_config"]
