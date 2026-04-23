"""Shared helpers for file-row freshness and fallback activity checks."""
from __future__ import annotations

from datetime import datetime, timezone

from .resolve_scope import file_scope_sql, session_scope_sql


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def format_gap(hours: float) -> str:
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def latest_file_timestamp(conn, scope) -> datetime | None:
    clause, params = file_scope_sql(scope)
    sql = "SELECT MAX(sf.first_seen_at) FROM session_files sf JOIN sessions s ON s.id = sf.session_id"
    if clause:
        sql += f" WHERE {clause}"
    return parse_timestamp(conn.execute(sql, params).fetchone()[0])


def latest_activity_timestamp(conn, scope) -> datetime | None:
    clause, params = session_scope_sql(scope)
    session_sql = "SELECT MAX(COALESCE(s.updated_at, s.created_at)) FROM sessions s"
    turn_sql = "SELECT MAX(t.timestamp) FROM turns t JOIN sessions s ON s.id = t.session_id"
    checkpoint_sql = "SELECT MAX(c.created_at) FROM checkpoints c JOIN sessions s ON s.id = c.session_id"
    if clause:
        session_sql += f" WHERE {clause}"
        turn_sql += f" WHERE {clause}"
        checkpoint_sql += f" WHERE {clause}"
    latest_candidates = (
        parse_timestamp(conn.execute(session_sql, params).fetchone()[0]),
        parse_timestamp(conn.execute(turn_sql, params).fetchone()[0]),
        parse_timestamp(conn.execute(checkpoint_sql, params).fetchone()[0]),
    )
    return max((ts for ts in latest_candidates if ts is not None), default=None)
