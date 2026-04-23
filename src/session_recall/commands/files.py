"""List recently touched files with session attribution."""
from __future__ import annotations

import sys

from ..db.connect import connect_ro
from ..db.schema_check import FEATURE_SUPPORT_SCHEMA, FILE_FALLBACK_SCHEMA, PATH_SCOPE_SCHEMA, schema_check
from ..config import DB_PATH
from ..util.file_activity import format_gap, latest_activity_timestamp, latest_file_timestamp
from ..util.format_output import output
from ..util.parse_important_files import parse_important_files
from ..util.resolve_scope import file_scope_sql, resolve_scope, session_scope_sql, time_filter_sql

_BASE = """SELECT sf.file_path, sf.tool_name, sf.first_seen_at,
             sf.session_id, s.summary FROM session_files sf
            JOIN sessions s ON s.id = sf.session_id"""

_CHECKPOINTS_BASE = """SELECT c.checkpoint_number, c.title, c.created_at, c.session_id,
                c.important_files, s.summary
           FROM checkpoints c JOIN sessions s ON s.id = c.session_id"""
_STALE_HOURS = 24


def _load_primary_files(conn, scope, days: int | None, limit: int) -> list[dict]:
    conditions = []
    params: list[str] = []
    scope_clause, scope_params = file_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("sf.first_seen_at", days)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _BASE
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY sf.first_seen_at DESC LIMIT ?"
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [{
        "file_path": r["file_path"],
        "tool_name": r["tool_name"],
        "source": "session_files",
        "date": (r["first_seen_at"] or "")[:10],
        "session_id": r["session_id"][:8],
        "session_summary": r["summary"],
    } for r in rows]


def _load_checkpoint_fallback(conn, scope, days: int | None, limit: int) -> list[dict]:
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
        for path in parse_important_files(row["important_files"]):
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
def _warning_for_fallback(latest_file, latest_activity) -> str:
    if latest_activity is None:
        return "Using checkpoint fallback for files"
    if latest_file is None:
        return "No session_files rows in scope, using checkpoint fallback"
    gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
    return f"session_files rows lag latest activity by {format_gap(gap_hours)}, using checkpoint fallback"


def run(args) -> int:
    scope = resolve_scope(getattr(args, 'repo', None))
    conn = connect_ro(DB_PATH)
    extra_schema = FEATURE_SUPPORT_SCHEMA if scope.mode == "path" else FILE_FALLBACK_SCHEMA
    problems = schema_check(conn, extra_schema)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
    if problems:
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    limit = getattr(args, 'limit', None) or 10
    days = getattr(args, 'days', None)
    primary_files = _load_primary_files(conn, scope, days, limit)
    fallback_files = _load_checkpoint_fallback(conn, scope, days, limit)
    latest_file = latest_file_timestamp(conn, scope)
    latest_activity = latest_activity_timestamp(conn, scope)
    file_rows_stale = latest_activity is not None and (
        latest_file is None or (latest_activity - latest_file).total_seconds() / 3600 > _STALE_HOURS
    )

    use_fallback = bool(fallback_files) and (not primary_files or file_rows_stale)
    files = fallback_files if use_fallback else primary_files
    data = {
        "repo": scope.display,
        "count": len(files),
        "files": files,
        "source": "checkpoint_fallback" if use_fallback else "session_files",
    }
    if use_fallback:
        data["warning"] = _warning_for_fallback(latest_file, latest_activity)
    elif file_rows_stale:
        if latest_file is None:
            data["warning"] = "No session_files rows in scope and no checkpoint fallback entries found"
        else:
            gap_hours = max(0.0, (latest_activity - latest_file).total_seconds() / 3600)
            data["warning"] = (
                f"session_files rows lag latest activity by {format_gap(gap_hours)} "
                "and no checkpoint fallback entries were found"
            )
    output(data, json_mode=getattr(args, 'json', False))
    conn.close()
    return 0
