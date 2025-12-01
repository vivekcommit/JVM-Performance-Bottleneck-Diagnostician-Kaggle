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
"""
from __future__ import annotations
from typing import Any, Dict, Optional

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
