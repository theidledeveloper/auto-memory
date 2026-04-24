"""Store factory for supported session backends."""

from __future__ import annotations

from ..config import DEFAULT_SOURCE, get_db_path, normalize_source
from .claude import ClaudeStore
from .copilot import CopilotStore
from .protocol import SessionStore


def open_store(args, *, meta: dict | None = None, db_path: str | None = None) -> SessionStore:
    """Open the requested store backend for the current command."""
    source = normalize_source(getattr(args, "source", DEFAULT_SOURCE))
    if source == "claude":
        return ClaudeStore()
    return CopilotStore(db_path=db_path or get_db_path(), meta=meta)
