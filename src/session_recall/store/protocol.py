"""Shared store protocol for session backends."""

from __future__ import annotations

from typing import Protocol

from ..util.resolve_scope import Scope


class StoreSchemaError(Exception):
    """Raised when the selected store cannot satisfy the expected schema."""

    def __init__(self, problems: list[str]):
        super().__init__("schema validation failed")
        self.problems = problems


class SessionStore(Protocol):
    """Minimal protocol shared by supported session backends."""

    source: str

    def list_sessions(self, scope: Scope, *, days: int | None, limit: int) -> list[dict]:
        """Return recent sessions for the current store."""

    def recent_files(
        self,
        scope: Scope,
        *,
        days: int | None,
        limit: int,
    ) -> tuple[list[dict], str, str | None]:
        """Return recent file activity plus metadata about the selected source."""

    def resolve_session_id(self, raw_id: str) -> dict:
        """Resolve an exact or prefix session identifier."""

    def load_session_detail(
        self,
        session_id: str,
        *,
        turn_limit: int | None,
        truncate: int,
    ) -> dict:
        """Return show/export-style session detail."""

    def load_files(self, session_id: str) -> list[dict]:
        """Return session file metadata."""

    def load_checkpoints(self, session_id: str) -> list[dict]:
        """Return session checkpoint metadata."""

    def close(self) -> None:
        """Release any resources held by the store."""
