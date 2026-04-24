"""Copilot SQLite-backed store implementation."""

from __future__ import annotations

import os

from ..db.connect import connect_ro
from ..db.queries import (
    load_checkpoints as db_load_checkpoints,
    load_files as db_load_files,
    load_session_detail as db_load_session_detail,
    resolve_session_id as db_resolve_session_id,
)
from ..db.schema_check import FILE_FALLBACK_SCHEMA, PATH_SCOPE_SCHEMA, schema_check
from ..util.file_activity import format_gap, latest_activity_timestamp, latest_file_timestamp
from ..util.file_hints import load_checkpoint_file_hints, load_turn_file_hints
from ..util.resolve_scope import Scope, file_scope_sql, session_scope_sql, time_filter_sql
from .protocol import StoreSchemaError

_LIST_QUERY_BASE = """
    SELECT s.id, s.repository, s.branch, s.summary, s.created_at, s.updated_at,
           (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) as turns_count,
           (SELECT COUNT(*) FROM session_files f WHERE f.session_id = s.id) as files_count
    FROM sessions s"""
_FILES_SQL = """SELECT sf.file_path, sf.tool_name, sf.first_seen_at, sf.session_id
FROM session_files sf JOIN sessions s ON s.id = sf.session_id
{where_clause}
ORDER BY sf.first_seen_at DESC LIMIT ?"""
_STALE_HOURS = 24


class CopilotStore:
    """SQLite-backed store that preserves the existing Copilot behavior."""

    source = "copilot"

    def __init__(self, *, db_path: str, meta: dict | None = None):
        self.conn = connect_ro(db_path, meta=meta)

    def close(self) -> None:
        self.conn.close()

    def _ensure(self, *extra_requirements) -> None:
        problems: list[str] = []
        for requirement in (None, *extra_requirements):
            if requirement is None:
                current = schema_check(self.conn)
            else:
                current = schema_check(self.conn, requirement)
            for item in current:
                if item not in problems:
                    problems.append(item)
        if problems:
            raise StoreSchemaError(problems)

    def list_sessions(self, scope: Scope, *, days: int | None, limit: int) -> list[dict]:
        self._ensure(PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        conditions: list[str] = []
        params: list[str | int] = []
        scope_clause, scope_params = session_scope_sql(scope)
        if scope_clause:
            conditions.append(scope_clause)
            params.extend(scope_params)
        days_clause, days_params = time_filter_sql("s.created_at", days)
        if days_clause:
            conditions.append(days_clause)
            params.extend(days_params)
        sql = _LIST_QUERY_BASE + (" WHERE " + " AND ".join(conditions) if conditions else "")
        sql += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "id_short": row["id"][:8],
                "id_full": row["id"],
                "repository": row["repository"],
                "branch": row["branch"],
                "summary": row["summary"],
                "date": row["created_at"][:10] if row["created_at"] else None,
                "created_at": row["created_at"],
                "turns_count": row["turns_count"],
                "files_count": row["files_count"],
            }
            for row in rows
        ]

    def recent_files(
        self,
        scope: Scope,
        *,
        days: int | None,
        limit: int,
    ) -> tuple[list[dict], str, str | None]:
        self._ensure(PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
        conditions: list[str] = []
        params: list[str | int] = []
        scope_clause, scope_params = file_scope_sql(scope)
        if scope_clause:
            conditions.append(scope_clause)
            params.extend(scope_params)
        days_clause, days_params = time_filter_sql("sf.first_seen_at", days)
        if days_clause:
            conditions.append(days_clause)
            params.extend(days_params)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = _FILES_SQL.format(where_clause=where_clause)
        rows = self.conn.execute(sql, (*params, limit)).fetchall()
        cwd = os.getcwd()
        primary_files = [
            _format_recent_file(
                {
                    "file_path": row["file_path"],
                    "tool_name": row["tool_name"],
                    "source": "session_files",
                    "date": (row["first_seen_at"] or "")[:10],
                    "session_id": row["session_id"][:8],
                },
                cwd,
            )
            for row in rows
        ]
        checkpoint_fallback_supported = not schema_check(self.conn, FILE_FALLBACK_SCHEMA)
        checkpoint_files = (
            load_checkpoint_file_hints(self.conn, scope, days, limit)
            if checkpoint_fallback_supported
            else []
        )
        turn_files = load_turn_file_hints(self.conn, scope, days, limit)
        fallback_files = checkpoint_files or turn_files
        fallback_source = "checkpoint_fallback" if checkpoint_files else "turn_fallback"
        fallback_label = "checkpoint fallback" if checkpoint_files else "turn fallback"
        latest_file = latest_file_timestamp(self.conn, scope)
        latest_activity = latest_activity_timestamp(self.conn, scope)
        file_rows_stale = latest_activity is not None and (
            latest_file is None or (latest_activity - latest_file).total_seconds() / 3600 > _STALE_HOURS
        )
        use_fallback = bool(fallback_files) and (not primary_files or file_rows_stale)
        selected = fallback_files if use_fallback else primary_files
        warning = None
        if use_fallback:
            warning = _warning_for_fallback(latest_file, latest_activity, fallback_label)
        elif file_rows_stale:
            if latest_file is None:
                warning = "No session_files rows in scope and no checkpoint or turn fallback entries found"
            else:
                gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
                warning = (
                    f"session_files rows lag latest activity by {format_gap(gap_hours)} "
                    "and no checkpoint or turn fallback entries were found"
                )
        files = selected if use_fallback else primary_files
        if use_fallback:
            files = [_format_recent_file(item, cwd) for item in selected]
        return files, fallback_source if use_fallback else "session_files", warning

    def resolve_session_id(self, raw_id: str) -> dict:
        self._ensure()
        return dict(db_resolve_session_id(self.conn, raw_id))

    def load_session_detail(
        self,
        session_id: str,
        *,
        turn_limit: int | None,
        truncate: int,
    ) -> dict:
        self._ensure()
        return db_load_session_detail(self.conn, session_id, turn_limit=turn_limit, truncate=truncate)

    def load_files(self, session_id: str) -> list[dict]:
        self._ensure()
        return [dict(row) for row in db_load_files(self.conn, session_id)]

    def load_checkpoints(self, session_id: str) -> list[dict]:
        self._ensure()
        return [dict(row) for row in db_load_checkpoints(self.conn, session_id)]


def _warning_for_fallback(latest_file, latest_activity, fallback_label: str) -> str:
    if latest_activity is None:
        return f"Using {fallback_label} for files"
    if latest_file is None:
        return f"No session_files rows in scope, using {fallback_label}"
    gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
    return f"session_files rows lag latest activity by {format_gap(gap_hours)}, using {fallback_label}"


def _format_recent_file(row: dict, cwd: str) -> dict:
    path = row["file_path"]
    return {
        "file_path": os.path.relpath(path, cwd) if os.path.isabs(path) and path.startswith(cwd) else path,
        "full_path": path,
        "tool_name": row["tool_name"],
        "date": row["date"],
        "session_id": row["session_id"],
        "source": row.get("source", "session_files"),
    }
