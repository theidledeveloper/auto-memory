"""Recent file-hint loaders for fallback paths."""
from __future__ import annotations

from datetime import datetime

from .file_activity import parse_timestamp
from .parse_important_files import parse_file_hints
from .resolve_scope import session_scope_sql, time_filter_sql

_CHECKPOINTS_BASE = """SELECT c.checkpoint_number, c.title, c.created_at, c.session_id,
                c.important_files, s.summary
           FROM checkpoints c JOIN sessions s ON s.id = c.session_id"""

_TURNS_BASE = """SELECT t.turn_index, t.timestamp, t.session_id, t.user_message,
            t.assistant_response, s.summary
       FROM turns t JOIN sessions s ON s.id = t.session_id"""


def load_checkpoint_file_hints(conn, scope, days: int | None, limit: int) -> list[dict]:
    conditions = ["c.important_files IS NOT NULL", "c.important_files != ''"]
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("c.created_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _CHECKPOINTS_BASE + " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    checkpoint_limit = max(limit * 5, 20)
    rows = conn.execute(sql, (*params, checkpoint_limit)).fetchall()

    files: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        for path in parse_file_hints(row["important_files"]):
            if path in seen:
                continue
            seen.add(path)
            files.append({
                "file_path": path,
                "tool_name": "checkpoint-fallback",
                "source": "checkpoint_fallback",
                "date": (row["created_at"] or "")[:10],
                "session_id": row["session_id"][:8],
                "session_summary": row["summary"],
                "checkpoint_number": row["checkpoint_number"],
                "checkpoint_title": row["title"],
            })
            if len(files) >= limit:
                return files
    return files


def load_turn_file_hints(conn, scope, days: int | None, limit: int) -> list[dict]:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("t.timestamp", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _TURNS_BASE
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.timestamp DESC LIMIT ?"
    turn_limit = max(limit * 10, 50)
    rows = conn.execute(sql, (*params, turn_limit)).fetchall()

    files: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        assistant_paths = parse_file_hints(row["assistant_response"])
        text_candidates = [("assistant", assistant_paths)]
        if not assistant_paths:
            text_candidates.append(("user", parse_file_hints(row["user_message"])))
        for text_source, paths in text_candidates:
            for path in paths:
                if path in seen:
                    continue
                seen.add(path)
                files.append({
                    "file_path": path,
                    "tool_name": "turn-fallback",
                    "source": "turn_fallback",
                    "date": (row["timestamp"] or "")[:10],
                    "session_id": row["session_id"][:8],
                    "session_summary": row["summary"],
                    "turn_index": row["turn_index"],
                    "turn_source": text_source,
                })
                if len(files) >= limit:
                    return files
    return files


def latest_checkpoint_hint_timestamp(conn, scope, cutoff_days: int | None = None) -> datetime | None:
    conditions = ["c.important_files IS NOT NULL", "c.important_files != ''"]
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("c.created_at", cutoff_days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = "SELECT MAX(c.created_at) FROM checkpoints c JOIN sessions s ON s.id = c.session_id"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return parse_timestamp(conn.execute(sql, params).fetchone()[0])


def latest_turn_hint_timestamp(
    conn,
    scope,
    cutoff_days: int | None = None,
    scan_limit: int = 200,
) -> datetime | None:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("t.timestamp", cutoff_days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _TURNS_BASE
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY t.timestamp DESC LIMIT ?"
    rows = conn.execute(sql, (*params, scan_limit)).fetchall()
    for row in rows:
        assistant_paths = parse_file_hints(row["assistant_response"])
        if assistant_paths or parse_file_hints(row["user_message"]):
            return parse_timestamp(row["timestamp"])
    return None
