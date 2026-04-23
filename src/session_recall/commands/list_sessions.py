"""List recent sessions for the current (or specified) repository."""
import os
import sys

from ..config import DB_PATH
from ..db.connect import connect_ro
from ..db.schema_check import FILE_FALLBACK_SCHEMA, PATH_SCOPE_SCHEMA, schema_check
from ..util.file_activity import latest_activity_timestamp, latest_file_timestamp
from ..util.file_hints import load_checkpoint_file_hints, load_turn_file_hints
from ..util.format_output import output
from ..util.resolve_scope import (
    file_scope_sql,
    resolve_scope,
    session_scope_sql,
    time_filter_sql,
)

_QUERY_BASE = """
    SELECT s.id, s.repository, s.branch, s.summary, s.created_at, s.updated_at,
           (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) as turns_count,
           (SELECT COUNT(*) FROM session_files f WHERE f.session_id = s.id) as files_count
    FROM sessions s"""
_STALE_HOURS = 24


def run(args) -> int:
    """Execute the list subcommand. Returns exit code."""
    scope = resolve_scope(args.repo)
    conn = connect_ro(DB_PATH)
    problems = schema_check(conn, PATH_SCOPE_SCHEMA if scope.mode == "path" else None)
    if problems:
        print("❌ Schema drift:", file=sys.stderr)
        for p in problems:
            print(f"   - {p}", file=sys.stderr)
        conn.close()
        return 2
    limit = args.limit or 10
    conditions = []
    params = []
    scope_clause, scope_params = session_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("s.created_at", args.days, default_days=30)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    sql = _QUERY_BASE + " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    sessions = [
        {
            "id_short": r["id"][:8], "id_full": r["id"],
            "repository": r["repository"], "branch": r["branch"],
            "summary": r["summary"],
            "date": r["created_at"][:10] if r["created_at"] else None,
            "created_at": r["created_at"],
            "turns_count": r["turns_count"], "files_count": r["files_count"],
        }
        for r in rows
    ]
    recent_files = _recent_files(conn, scope, days=args.days, limit=10)
    data = {"repo": scope.display, "count": len(sessions),
            "sessions": sessions, "recent_files": recent_files}
    output(data, json_mode=args.json)
    conn.close()
    return 0


_FILES_SQL = """SELECT sf.file_path, sf.tool_name, sf.first_seen_at, sf.session_id
FROM session_files sf JOIN sessions s ON s.id = sf.session_id
{where_clause}
ORDER BY sf.first_seen_at DESC LIMIT ?"""


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


def _recent_files(conn, scope, days=None, limit=10):
    conditions = []
    params = []
    scope_clause, scope_params = file_scope_sql(scope)
    if scope_clause:
        conditions.append(scope_clause)
        params.extend(scope_params)
    days_clause, days_params = time_filter_sql("sf.first_seen_at", days, default_days=30)
    if days_clause:
        conditions.append(days_clause)
        params.extend(days_params)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = _FILES_SQL.format(where_clause=where_clause)
    rows = conn.execute(sql, (*params, limit)).fetchall()
    cwd = os.getcwd()
    primary_files = [{
        "file_path": r["file_path"],
        "tool_name": r["tool_name"],
        "source": "session_files",
        "date": (r["first_seen_at"] or "")[:10],
        "session_id": r["session_id"][:8],
    } for r in rows]
    checkpoint_fallback_supported = not schema_check(conn, FILE_FALLBACK_SCHEMA)
    checkpoint_files = (
        load_checkpoint_file_hints(conn, scope, days, limit)
        if checkpoint_fallback_supported
        else []
    )
    turn_files = load_turn_file_hints(conn, scope, days, limit)
    fallback_files = checkpoint_files or turn_files
    latest_file = latest_file_timestamp(conn, scope)
    latest_activity = latest_activity_timestamp(conn, scope)
    file_rows_stale = latest_activity is not None and (
        latest_file is None or (latest_activity - latest_file).total_seconds() / 3600 > _STALE_HOURS
    )
    selected = fallback_files if fallback_files and (not primary_files or file_rows_stale) else primary_files
    return [_format_recent_file(row, cwd) for row in selected]
