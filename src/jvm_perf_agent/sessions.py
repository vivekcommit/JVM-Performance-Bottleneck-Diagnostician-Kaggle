"""
Small session helper with an in-memory session service.

Exports:
- `get_session_service()` -> singleton session service (attempts to use ADK's
  InMemorySessionService if available, otherwise a local fallback implementation)
- `save_run_summary(session_id, summary_dict)` -> store exactly one previous
  run summary per session in memory
- `load_previous_run_summary(session_id)` -> retrieve the stored summary or None

This module is intentionally tiny and defensive so it works without the ADK
installed. When ADK is available, its InMemorySessionService will be used.
For Gemini Flash integration, use a config file or environment variables.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
import os
import importlib
import importlib.util
import logging

from . import config as agent_config

_LOG = logging.getLogger(__name__)

_SESSION_SVC = None


class _FallbackInMemorySessionService:
    """A minimal in-memory session service compatible with required operations.

    Stores a single `last_summary` per session id. The public functions in this
    module interact with this service and do not depend on ADK APIs.
    """

    def __init__(self) -> None:
        # map: session_id -> {key: value}
        self._store: Dict[str, Dict[str, Any]] = {}

    def put(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._store:
            self._store[session_id] = {}
        self._store[session_id][key] = value

    def get(self, session_id: str, key: str) -> Optional[Any]:
        return self._store.get(session_id, {}).get(key)


class _GeminiBackedSessionService:
    """Session service that stores data in-memory but uses a Gemini
    (Gemini Flash) call to produce an LLM-based analysis/summary when
    saving a run summary. This class remains resilient if the Gemini
    client is not installed or configured; in that case it falls back
    to a deterministic local summary so behavior is predictable.

    The service exposes `put(session_id, key, value)` and
    `get(session_id, key)` to match the fallback service contract.
    When `put` is called with `key == 'last_summary'` the service will
    also store an LLM-produced analysis under key `'last_summary_llm'`.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        # detect whether a Gemini client looks available/configured
        self._has_gemini = False
        try:
            # prefer the lightweight `google.generativeai` if present
            self._genai = importlib.import_module("google.generativeai")
            self._has_gemini = True
        except Exception:
            self._genai = None
            self._has_gemini = False

    def _call_gemini(self, prompt: str) -> str:
        # Try to call a local Gemini client if available and configured.
        try:
            if self._genai is not None:
                api_key = agent_config.get_gemini_api_key()
                model = agent_config.get_gemini_model()
                if api_key:
                    try:
                        # runtime may require configure or set API key differently
                        if hasattr(self._genai, "configure"):
                            self._genai.configure(api_key=api_key)
                        else:
                            # set env for other client implementations
                            os.environ.setdefault("GEMINI_API_KEY", api_key)
                    except Exception:
                        _LOG.debug("Gemini client configure failed", exc_info=True)

                # Best-effort generate a short analysis/summary
                try:
                    # try a few known calling patterns defensively
                    if hasattr(self._genai, "generate_text"):
                        resp = self._genai.generate_text(model=model, prompt=prompt)
                        # extract text if response is structured
                        if isinstance(resp, dict) and "candidates" in resp:
                            return resp["candidates"][0].get("content", str(resp))
                        return str(resp)
                    if hasattr(self._genai, "generate"):
                        resp = self._genai.generate(model=model, input=prompt)
                        return str(resp)
                except Exception:
                    _LOG.debug("Gemini call failed", exc_info=True)

        except Exception:
            _LOG.debug("Gemini client not available", exc_info=True)

        # Fallback deterministic summarization (no external call)
        # Keep short and stable so tests and offline runs behave predictably.
        snippet = (prompt or "").strip().replace("\n", " ")[:200]
        return f"LLM_MOCK_SUMMARY: {snippet}"

    def put(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._store:
            self._store[session_id] = {}
        self._store[session_id][key] = value

        # On saving the run summary, produce an LLM analysis in background
        try:
            if key == "last_summary":
                prompt = (
                    "Create a concise analysis of the following JVM performance "
                    "run summary (one sentence):\n" + repr(value)
                )
                analysis = self._call_gemini(prompt)
                self._store[session_id]["last_summary_llm"] = analysis
        except Exception:
            _LOG.debug("Failed generating LLM-backed analysis", exc_info=True)

    def get(self, session_id: str, key: str) -> Optional[Any]:
        return self._store.get(session_id, {}).get(key)


def get_session_service():
    """Return a singleton session service.

    If an ADK `InMemorySessionService` is importable, instantiate and return it.
    Otherwise return a lightweight fallback implemented above.
    """
    global _SESSION_SVC
    if _SESSION_SVC is not None:
        return _SESSION_SVC

    # Try to import ADK's InMemorySessionService (best-effort)
    try:
        # Known ADK package names vary; try common candidates defensively.
        try:
            from adk.sessions import InMemorySessionService as _AdkInMem  # type: ignore
        except Exception:
            try:
                from google_adk.sessions import InMemorySessionService as _AdkInMem  # type: ignore
            except Exception:
                _AdkInMem = None

        if _AdkInMem is not None:
            _SESSION_SVC = _AdkInMem()
            return _SESSION_SVC
    except Exception:
        # fall through to fallback
        pass

    # If user explicitly requested Gemini-backed sessions or a Gemini
    # client appears available, prefer a Gemini-backed service. This is
    # optional and will gracefully fallback to the local service if
    # Gemini isn't configured.
    try:
        use_gemini = os.getenv("USE_GEMINI_SESSION") in ("1", "true", "True")
        gemini_api_key = agent_config.get_gemini_api_key()
        gemini_configured = bool(gemini_api_key)
        genai_available = importlib.util.find_spec("google.generativeai") is not None
        if use_gemini or gemini_configured or genai_available:
            try:
                _SESSION_SVC = _GeminiBackedSessionService()
                return _SESSION_SVC
            except Exception:
                _LOG.debug("Failed to initialise Gemini-backed session service", exc_info=True)
                # fall through to fallback
                pass
    except Exception:
        # defensive: any problem deciding Gemini usage should not break
        _LOG.debug("Error deciding Gemini session service usage", exc_info=True)

    _SESSION_SVC = _FallbackInMemorySessionService()
    return _SESSION_SVC


def save_run_summary(session_id: str, summary_dict: Dict[str, Any]) -> None:
    """Save `summary_dict` as the most recent run summary for `session_id`.

    Exactly one summary is kept per session; subsequent calls overwrite the
    previous value.
    """
    svc = get_session_service()
    # Prefer a generic put/get API if present, else try common method names
    if hasattr(svc, "put"):
        svc.put(session_id, "last_summary", summary_dict)
        return
    if hasattr(svc, "save"):
        try:
            svc.save(session_id, "last_summary", summary_dict)
            return
        except Exception:
            pass
    # Last-resort: set attribute on service
    try:
        svc._store = getattr(svc, "_store", {})
        svc._store[session_id] = {"last_summary": summary_dict}
    except Exception:
        # not much else we can do
        raise RuntimeError("Unable to save run summary to session service")


def load_previous_run_summary(session_id: str) -> Optional[Dict[str, Any]]:
    """Load the previous run summary for `session_id`, or None if missing."""
    svc = get_session_service()
    if hasattr(svc, "get"):
        return svc.get(session_id, "last_summary")
    if hasattr(svc, "load"):
        try:
            return svc.load(session_id, "last_summary")
        except Exception:
            pass
    # Fallback to direct store attribute
    try:
        store = getattr(svc, "_store", {})
        return store.get(session_id, {}).get("last_summary")
    except Exception:
        return None


__all__ = ["get_session_service", "save_run_summary", "load_previous_run_summary"]
